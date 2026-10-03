import unittest
from unittest.mock import Mock

from canvas_pocket.client import CanvasError
from canvas_pocket.favorites import change, listing


class FavoritesTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.target = {'id': 101, 'name': 'Synthetic course', 'workflow_state': 'available'}
        self.client.request.return_value = ({'id': 7}, '')
        self.client.list.return_value = [self.target]

    def preview(self, action='add', item_id='101', context_type='course'):
        self.client.request.side_effect = [({'id': 7}, ''), (self.target, '')] if item_id else [({'id': 7}, '')]
        return change(self.client, action, item_id, context_type=context_type)

    def test_course_and_group_reads_keep_pagination_and_never_write(self):
        for context in ('course', 'group'):
            self.assertEqual(listing(self.client, 3, context), [self.target])
            self.client.list.assert_called_with(f'/api/v1/users/self/favorites/{context}s?per_page=100', 3)
        self.client.request.assert_not_called()

    def test_preview_binds_account_target_displayed_defaults_and_exact_route(self):
        result = self.preview()
        self.assertTrue(result['dry_run'])
        self.assertEqual(result['user_id'], 7)
        self.assertEqual(result['target']['id'], 101)
        self.assertFalse(result['manual_selection_known'])
        self.assertIn('automatically generated', result['warning'])
        self.assertEqual(result['route'], '/api/v1/users/self/favorites/courses/101')
        self.assertEqual(result['method'], 'POST')
        self.assertIsNone(result['body'])
        self.assertEqual(self.client.request.call_count, 2)

    def test_add_and_remove_validate_exact_namespace_and_single_write(self):
        for context in ('course', 'group'):
            for action in ('add', 'remove'):
                with self.subTest(context=context, action=action):
                    preview = self.preview(action, context_type=context)
                    response = {'context_id': 101, 'context_type': context.title()}
                    self.client.request.side_effect = [({'id': 7}, ''), (self.target, ''), (response, '')]
                    result = change(self.client, action, '101', context_type=context, yes=True, confirm=preview['confirm'])
                    self.assertTrue(result['acknowledged'])
                    self.client.request.assert_called_with(f'/api/v1/users/self/favorites/{context}s/101',
                                                          'POST' if action == 'add' else 'DELETE', None)

    def test_remove_accepts_native_empty_ack_but_add_does_not(self):
        for action in ('add', 'remove'):
            preview = self.preview(action)
            self.client.request.side_effect = [({'id': 7}, ''), (self.target, ''), ({}, '')]
            if action == 'remove':
                self.assertTrue(change(self.client, action, '101', yes=True, confirm=preview['confirm'])['acknowledged'])
            else:
                with self.assertRaisesRegex(CanvasError, 'verify Canvas'):
                    change(self.client, action, '101', yes=True, confirm=preview['confirm'])

    def test_reset_previews_all_displayed_items_and_native_status_ack(self):
        for context in ('course', 'group'):
            preview = self.preview('reset', None, context)
            self.assertIn('ALL custom', preview['effect'])
            self.assertIsNone(preview['target'])
            self.client.request.side_effect = [({'id': 7}, ''), ({'status': 'ok'}, '')]
            result = change(self.client, 'reset', context_type=context, yes=True, confirm=preview['confirm'])
            self.assertEqual(result['favorite_change']['action'], 'reset')
            self.client.request.assert_called_with(f'/api/v1/users/self/favorites/{context}s', 'DELETE', None)

    def test_changed_account_site_selection_or_target_invalidates_preview(self):
        preview = self.preview()
        cases = [({'id': 8}, self.target, [self.target], self.client.host),
                 ({'id': 7}, {**self.target, 'name': 'Changed'}, [self.target], self.client.host),
                 ({'id': 7}, self.target, [], self.client.host),
                 ({'id': 7}, self.target, [self.target], 'https://other.example.edu')]
        for profile, target, selection, host in cases:
            with self.subTest(host=host, profile=profile, selection=selection):
                self.client.host = host
                self.client.list.return_value = selection
                self.client.request.reset_mock()
                self.client.request.side_effect = [(profile, ''), (target, '')]
                with self.assertRaisesRegex(CanvasError, 'Preview changed'):
                    change(self.client, 'add', '101', yes=True, confirm=preview['confirm'])
                self.assertEqual(self.client.request.call_count, 2)

    def test_unknown_response_never_gets_retried_or_dumped(self):
        preview = self.preview()
        for response in (None, [], {}, {'context_id': 102, 'context_type': 'Course'},
                         {'context_id': '101', 'context_type': 'Course'},
                         {'context_id': 101, 'context_type': 'Group', 'private': 'not printed'}):
            with self.subTest(response=response):
                self.client.request.reset_mock()
                self.client.request.side_effect = [({'id': 7}, ''), (self.target, ''), (response, '')]
                with self.assertRaisesRegex(CanvasError, 'verify Canvas') as error:
                    change(self.client, 'add', '101', yes=True, confirm=preview['confirm'])
                self.assertNotIn('not printed', str(error.exception))
                self.assertEqual(self.client.request.call_count, 3)
        reset = self.preview('reset', None)
        self.client.request.side_effect = [({'id': 7}, ''), ({'status': 'failed'}, '')]
        with self.assertRaises(CanvasError):
            change(self.client, 'reset', yes=True, confirm=reset['confirm'])

    def test_bad_identity_or_duplicate_selection_prevents_write(self):
        for target, selection in (({'id': 102}, []), ({'id': True}, []), ([], []),
                                  (self.target, [{'id': '101'}]), (self.target, [self.target, self.target])):
            with self.subTest(target=target, selection=selection):
                self.client.request.side_effect = [({'id': 7}, ''), (target, '')]
                self.client.list.return_value = selection
                with self.assertRaises(CanvasError):
                    change(self.client, 'add', '101')

    def test_invalid_options_fail_before_any_network(self):
        options = [{'action': 'bad'}, {'action': 'add'}, {'action': 'add', 'item_id': '0'},
                   {'action': 'add', 'item_id': '01'}, {'action': 'add', 'item_id': '١'},
                   {'action': 'add', 'item_id': '1', 'context_type': 'user'},
                   {'action': 'reset', 'item_id': '101'}, {'action': 'reset', 'yes': True}]
        for kwargs in options:
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                change(self.client, **kwargs)
        self.client.request.assert_not_called()
        self.client.list.assert_not_called()
