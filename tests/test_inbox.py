import unittest
from unittest.mock import Mock

from canvas_cli.client import CanvasError
from canvas_cli.inbox import change


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.thread = {'id': 12, 'subject': 'Synthetic thread', 'workflow_state': 'unread',
                       'message_count': 1, 'starred': False, 'subscribed': True, 'private': False,
                       'messages': [{'id': 31, 'author_id': 7, 'body': 'Synthetic private text'}]}

    def preview(self, **kwargs):
        self.client.request.side_effect = [({'id': 7}, ''), (self.thread, '')]
        return change(self.client, '12', **kwargs)

    def test_preview_is_read_only_binds_revision_and_does_not_echo_message_text(self):
        preview = self.preview(starred=True)
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['body'], {'conversation': {'starred': True}})
        self.assertNotIn('Synthetic private text', str(preview))
        self.assertEqual(len(preview['message_revision']), 64)
        self.client.request.assert_called_with('/api/v1/conversations/12?auto_mark_as_read=false')
        self.assertEqual(self.client.request.call_count, 2)

    def test_state_and_explicit_false_values_send_only_requested_fields(self):
        options = [{'state': 'archived'}, {'state': 'read'}, {'state': 'unread'},
                   {'starred': False, 'subscribed': False}, {'starred': True, 'subscribed': True}]
        for kwargs in options:
            with self.subTest(kwargs=kwargs):
                preview = self.preview(**kwargs)
                updated = {**self.thread, **preview['body']['conversation']}
                self.client.request.side_effect = [({'id': 7}, ''), (self.thread, ''), (updated, '')]
                result = change(self.client, '12', **kwargs, yes=True, confirm=preview['confirm'])
                self.assertFalse(result['deleted_from_own_view'])
                self.client.request.assert_called_with('/api/v1/conversations/12', 'PUT', preview['body'])

    def test_subscription_requires_confirmed_nonprivate_thread(self):
        for private in (None, True, 'false'):
            with self.subTest(private=private):
                self.thread['private'] = private
                with self.assertRaisesRegex(CanvasError, 'group conversation'):
                    self.preview(subscribed=False)
        self.thread['private'] = True
        self.assertTrue(self.preview(starred=True)['dry_run'])

    def test_delete_requires_permanent_ack_and_confirms_empty_own_view(self):
        preview = self.preview(delete=True, permanent=True)
        self.assertIn('does not unsend', preview['effect'])
        self.assertIsNone(preview['body'])
        self.client.request.side_effect = [({'id': 7}, ''), (self.thread, ''),
                                           ({**self.thread, 'message_count': 0, 'messages': []}, '')]
        result = change(self.client, '12', delete=True, permanent=True, yes=True, confirm=preview['confirm'])
        self.assertTrue(result['deleted_from_own_view'])
        self.client.request.assert_called_with('/api/v1/conversations/12', 'DELETE', None)

    def test_changed_identity_site_message_or_state_invalidates_preview(self):
        preview = self.preview(starred=True)
        cases = [({'id': 8}, self.thread, self.client.host),
                 ({'id': 7}, {**self.thread, 'workflow_state': 'read'}, self.client.host),
                 ({'id': 7}, {**self.thread, 'messages': [{'id': 31, 'body': 'Changed'}]}, self.client.host),
                 ({'id': 7}, self.thread, 'https://other.example.edu')]
        for profile, thread, host in cases:
            with self.subTest(profile=profile, host=host):
                self.client.request.reset_mock()
                self.client.host = host
                self.client.request.side_effect = [(profile, ''), (thread, '')]
                with self.assertRaisesRegex(CanvasError, 'Preview changed'):
                    change(self.client, '12', starred=True, yes=True, confirm=preview['confirm'])
                self.assertEqual(self.client.request.call_count, 2)

    def test_wrong_id_or_malformed_revision_prevents_preview(self):
        cases = [{**self.thread, 'id': 13}, {**self.thread, 'id': '12'},
                 {**self.thread, 'workflow_state': 'deleted'}, {**self.thread, 'message_count': True},
                 {**self.thread, 'messages': None}, {**self.thread, 'messages': [1]}]
        for thread in cases:
            with self.subTest(thread=thread):
                self.client.request.side_effect = [({'id': 7}, ''), (thread, '')]
                with self.assertRaises(CanvasError):
                    change(self.client, '12', starred=True)

    def test_unconfirmed_write_outcomes_are_not_retried_or_dumped(self):
        preview = self.preview(starred=False)
        for response in (None, {}, [], {**self.thread, 'id': 13}, {**self.thread, 'starred': 'false'},
                         {**self.thread, 'starred': True, 'private_data': 'Do not print'}):
            with self.subTest(response=response):
                self.client.request.reset_mock()
                self.client.request.side_effect = [({'id': 7}, ''), (self.thread, ''), (response, '')]
                with self.assertRaisesRegex(CanvasError, 'verify Canvas') as error:
                    change(self.client, '12', starred=False, yes=True, confirm=preview['confirm'])
                self.assertNotIn('Do not print', str(error.exception))
                self.assertEqual(self.client.request.call_count, 3)
        preview = self.preview(delete=True, permanent=True)
        self.client.request.side_effect = [({'id': 7}, ''), (self.thread, ''), (self.thread, '')]
        with self.assertRaisesRegex(CanvasError, 'verify Canvas'):
            change(self.client, '12', delete=True, permanent=True, yes=True, confirm=preview['confirm'])

    def test_invalid_options_fail_before_network(self):
        options = [{}, {'state': 'deleted'}, {'starred': 1}, {'subscribed': 'true'},
                   {'delete': True}, {'delete': True, 'permanent': True, 'starred': False},
                   {'permanent': True, 'state': 'read'}, {'starred': True, 'yes': True}]
        for kwargs in options:
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                change(self.client, '12', **kwargs)
        for number in ('0', '01', '١', '12/restore', 12, None):
            with self.subTest(number=number), self.assertRaises(CanvasError):
                change(self.client, number, starred=True)
        self.client.request.assert_not_called()
