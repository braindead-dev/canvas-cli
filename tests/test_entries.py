import unittest
from unittest.mock import Mock

from canvas_cli.client import CanvasError
from canvas_cli.discussion import change_entry, entry, post, state


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.profile = {'id': 7}
        self.topic = {'id': 9, 'context_id': 8, 'title': 'Synthetic topic', 'published': True}
        self.current = {'id': 31, 'user_id': 7, 'discussion_topic_id': 9,
                        'message': '<p>Original synthetic entry</p>', 'updated_at': '2026-10-02T12:00:00Z'}
        self.rows = [self.current]
        self.write_result = self.current
        def request(route, method='GET', body=None, **kwargs):
            if method == 'GET':
                return (self.profile if route == '/api/v1/users/self/profile' else self.topic), ''
            return self.write_result, ''
        self.client.request.side_effect = request
        self.client.list.side_effect = lambda *args: self.rows

    def test_exact_entry_read_uses_paginated_id_lookup_without_mutations(self):
        result = entry(self.client, '8', '9', '31', 3, 'group')
        self.assertEqual(result, self.current)
        self.client.list.assert_called_once_with('/api/v1/groups/8/discussion_topics/9/entry_list?ids%5B%5D=31&per_page=100', 3)
        self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))

    def test_missing_duplicate_malformed_or_wrong_topic_entry_is_refused(self):
        for rows in ([], [self.current, self.current], [None], [{'id': True}],
                     [{**self.current, 'id': 32}], [{**self.current, 'discussion_topic_id': 10}]):
            self.rows = rows
            with self.subTest(rows=rows), self.assertRaisesRegex(CanvasError, 'exact requested'):
                entry(self.client, '8', '9', '31')

    def test_invalid_id_and_post_first_visibility_do_not_reach_entry_list(self):
        with self.assertRaises(CanvasError):
            entry(self.client, '8', '9', '../31')
        self.client.list.assert_not_called()
        self.topic.update(require_initial_post=True, user_can_see_posts=False)
        with self.assertRaisesRegex(CanvasError, 'initial post'):
            entry(self.client, '8', '9', '31')
        self.client.list.assert_not_called()

    def test_edit_preview_escapes_plain_text_and_sends_exact_body_once(self):
        preview = change_entry(self.client, '8', '9', '31', '<hello>\nworld')
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['before']['message'], self.current['message'])
        self.assertEqual(preview['body'], {'message': '<p>&lt;hello&gt;<br>world</p>'})
        self.write_result = {**self.current, **preview['body']}
        result = change_entry(self.client, '8', '9', '31', '<hello>\nworld', yes=True, confirm=preview['confirm'])
        self.assertEqual(result['entry']['id'], 31)
        self.client.request.assert_called_with('/api/v1/courses/8/discussion_topics/9/entries/31', 'PUT', preview['body'])

    def test_each_identity_destination_and_entry_revision_change_invalidates_confirmation(self):
        for change in ('account', 'origin', 'context', 'message', 'timestamp', 'title'):
            self.setUp()
            preview = change_entry(self.client, '8', '9', '31', 'New entry', context_type='group')
            if change == 'account': self.profile['id'] = 99; self.current['user_id'] = 99
            if change == 'origin': self.client.host = 'https://other.example.edu'
            if change == 'message': self.current['message'] = 'Changed current entry'
            if change == 'timestamp': self.current['updated_at'] = '2026-10-02T13:00:00Z'
            if change == 'title': self.topic['title'] = 'Changed topic'
            self.client.request.reset_mock()
            with self.subTest(change=change), self.assertRaisesRegex(CanvasError, 'Preview changed'):
                change_entry(self.client, '8', '9', '31', 'New entry',
                             context_type='course' if change == 'context' else 'group',
                             yes=True, confirm=preview['confirm'])
            self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))

    def test_other_owners_deleted_entries_and_explicit_permissions_are_refused(self):
        for fields in ({'user_id': 99}, {'user_id': True}, {'user_id': '7'}, {'deleted': True},
                       {'hidden_for_user': True}, {'locked_for_user': True}, {'permissions': {'update': False}}):
            self.setUp(); self.current.update(fields)
            with self.subTest(fields=fields), self.assertRaises(CanvasError):
                change_entry(self.client, '8', '9', '31', 'New entry')
        self.setUp(); self.current['permissions'] = {'delete': False}
        with self.assertRaises(CanvasError):
            change_entry(self.client, '8', '9', '31', delete=True)

    def test_attached_entry_requires_explicit_loss_acknowledgement(self):
        self.current['attachment'] = {'id': 81, 'display_name': 'synthetic.txt', 'url': 'https://storage.example/private'}
        with self.assertRaisesRegex(CanvasError, 'remove existing attachments'):
            change_entry(self.client, '8', '9', '31', 'New entry')
        preview = change_entry(self.client, '8', '9', '31', 'New entry', remove_attachment=True)
        self.assertTrue(preview['removes_attachment'])
        self.assertNotIn('url', preview['before']['attachment'])
        self.assertEqual(preview['body']['remove_attachment'], '1')
        self.current['attachment']['id'] = 82
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            change_entry(self.client, '8', '9', '31', 'New entry', remove_attachment=True,
                         yes=True, confirm=preview['confirm'])

    def test_delete_requires_empty_response_contract_and_only_targets_entry(self):
        preview = change_entry(self.client, '8', '9', '31', delete=True, context_type='group')
        self.assertEqual(preview['expected_response'], 'no_content')
        self.assertIsNone(preview['body'])
        self.write_result = None
        result = change_entry(self.client, '8', '9', '31', delete=True, context_type='group',
                              yes=True, confirm=preview['confirm'])
        self.assertTrue(result['deleted'])
        self.client.request.assert_called_with('/api/v1/groups/8/discussion_topics/9/entries/31',
                                               'DELETE', None, expect_no_content=True)

    def test_empty_changes_unpaired_confirmation_and_mixed_delete_fail_before_requests(self):
        for kwargs in ({'message': '  '}, {'message': 'New', 'yes': True},
                       {'delete': True, 'message': 'New'}, {'delete': True, 'remove_attachment': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                change_entry(self.client, '8', '9', '31', **kwargs)
        self.client.request.assert_not_called()

    def test_wrong_write_response_is_uncertain_and_never_retried(self):
        preview = change_entry(self.client, '8', '9', '31', 'New')
        for result in (None, {'id': True}, {**self.current, 'id': 32}, {**self.current, 'user_id': 99}):
            self.write_result = result; self.client.request.reset_mock()
            with self.subTest(result=result), self.assertRaisesRegex(CanvasError, 'Verify in Canvas'):
                change_entry(self.client, '8', '9', '31', 'New', yes=True, confirm=preview['confirm'])
            self.assertEqual(sum(len(call.args) > 1 for call in self.client.request.call_args_list), 1)

    def test_reply_target_is_read_and_bound_to_post_confirmation(self):
        preview = post(self.client, '8', '9', '31', 'A reply')
        self.assertEqual(preview['reply_target']['id'], 31)
        self.current['message'] = 'Edited target'
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            post(self.client, '8', '9', '31', 'A reply', yes=True, confirm=preview['confirm'])
        self.current['deleted'] = True
        with self.assertRaisesRegex(CanvasError, 'deleted'):
            post(self.client, '8', '9', '31', 'A reply')

    def test_subscription_and_topic_read_markers_only_touch_the_requested_state(self):
        for action, method, suffix in [('subscribe', 'PUT', 'subscribed'), ('unsubscribe', 'DELETE', 'subscribed'),
                                       ('read', 'PUT', 'read'), ('unread', 'DELETE', 'read')]:
            with self.subTest(action=action):
                self.client.request.reset_mock()
                preview = state(self.client, '8', '9', action, context_type='group')
                self.assertTrue(preview['dry_run'])
                self.assertIsNone(preview['entry_id'])
                self.assertIsNone(preview['body'])
                self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))
                state(self.client, '8', '9', action, context_type='group', yes=True, confirm=preview['confirm'])
                self.client.request.assert_called_with(f'/api/v1/groups/8/discussion_topics/9/{suffix}',
                                                       method, None, expect_no_content=True)
                self.client.list.assert_not_called()

    def test_read_marker_on_another_authors_entry_is_allowed_and_forced_flag_preserved(self):
        self.current['user_id'] = 99
        for forced in (None, False, True):
            with self.subTest(forced=forced):
                preview = state(self.client, '8', '9', 'unread', entry_id='31', forced=forced)
                body = {'forced_read_state': forced} if forced is not None else None
                self.assertEqual(preview['body'], body)
                result = state(self.client, '8', '9', 'unread', entry_id='31', forced=forced,
                               yes=True, confirm=preview['confirm'])
                self.assertEqual(result['discussion_state']['forced_read_state'], forced)
                self.client.request.assert_called_with('/api/v1/courses/8/discussion_topics/9/entries/31/read',
                                                       'DELETE', body, expect_no_content=True)

    def test_read_or_subscription_state_changes_invalidate_confirmation(self):
        for change in ('subscribed', 'read_state', 'forced_read_state', 'entry_message', 'origin', 'account'):
            self.setUp()
            preview = state(self.client, '8', '9', 'read', entry_id='31')
            if change == 'subscribed': self.topic['subscribed'] = True
            if change == 'read_state': self.current['read_state'] = 'read'
            if change == 'forced_read_state': self.current['forced_read_state'] = True
            if change == 'entry_message': self.current['message'] = 'Changed content'
            if change == 'origin': self.client.host = 'https://other.example.edu'
            if change == 'account': self.profile['id'] = 99
            self.client.request.reset_mock()
            with self.subTest(change=change), self.assertRaisesRegex(CanvasError, 'Preview changed'):
                state(self.client, '8', '9', 'read', entry_id='31', yes=True, confirm=preview['confirm'])
            self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))

    def test_state_controls_do_not_bypass_post_first_or_hidden_deleted_content(self):
        self.topic.update(require_initial_post=True, user_can_see_posts=False)
        # Topic text/subscription controls don't fetch entries; reading somebody's entry still requires visibility.
        self.assertTrue(state(self.client, '8', '9', 'subscribe')['dry_run'])
        with self.assertRaisesRegex(CanvasError, 'initial post'):
            state(self.client, '8', '9', 'read', entry_id='31')
        self.client.list.assert_not_called()
        self.setUp(); self.topic['locked'] = True
        self.assertTrue(state(self.client, '8', '9', 'unsubscribe')['dry_run'])
        for fields in ({'deleted': True}, {'hidden_for_user': True}):
            self.setUp(); self.current.update(fields)
            with self.subTest(fields=fields), self.assertRaises(CanvasError):
                state(self.client, '8', '9', 'read', entry_id='31')

    def test_invalid_state_combinations_are_refused_before_network(self):
        for action, kwargs in [('delete', {}), ('subscribe', {'entry_id': '31'}),
                               ('read', {'forced': True}), ('read', {'entry_id': '31', 'forced': 'false'}),
                               ('read', {'yes': True})]:
            with self.subTest(action=action, kwargs=kwargs), self.assertRaises(CanvasError):
                state(self.client, '8', '9', action, **kwargs)
        self.client.request.assert_not_called()


if __name__ == '__main__': unittest.main()
