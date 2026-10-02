import unittest
from unittest.mock import Mock, patch

from canvas_pocket.client import CanvasError
from canvas_pocket.overrides import TYPE_NAMES, change, create, read


class OverrideTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.profile = {'id': 7}
        self.override = {'id': 42, 'user_id': 7, 'plannable_type': 'planner_note', 'plannable_id': 41,
                         'marked_complete': True, 'dismissed': False, 'workflow_state': 'active',
                         'updated_at': '2026-10-02T12:00:00Z', 'deleted_at': None}
        self.item = {'plannable_type': 'planner_note', 'plannable_id': 41,
                     'plannable': {'title': 'Synthetic task'}, 'planner_override': None}
        self.feed = {'planner_window': {'start': '2026-10-01', 'end': '2026-10-14'}, 'items': [self.item]}
        self.client.request.return_value = (self.profile, '')
        self.client.list.return_value = []

    @patch('canvas_pocket.overrides.items')
    def test_creation_uses_own_paginated_feed_and_exact_confirmed_body(self, feed):
        feed.return_value = self.feed
        preview = create(self.client, 'planner_note', '41', 3, marked_complete=True)
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['body'], {'plannable_type': 'planner_note', 'plannable_id': 41,
                                          'marked_complete': True, 'dismissed': False})
        feed.assert_called_once_with(self.client, 3, None, None)
        self.client.list.assert_called_once_with('/api/v1/planner/overrides?per_page=100', 3)
        self.client.request.assert_called_once_with('/api/v1/users/self/profile')
        self.client.request.side_effect = [(self.profile, ''), (self.override, '')]
        result = create(self.client, 'planner_note', '41', 3, marked_complete=True,
                        yes=True, confirm=preview['confirm'])
        self.assertEqual(result['planner_override']['id'], 42)
        self.client.request.assert_called_with('/api/v1/planner/overrides', 'POST', preview['body'])

    @patch('canvas_pocket.overrides.items')
    def test_all_documented_types_are_selectable_without_reading_assessment_content(self, feed):
        for item_type in TYPE_NAMES:
            feed.return_value = {**self.feed, 'items': [{**self.item, 'plannable_type': item_type}]}
            with self.subTest(item_type=item_type):
                preview = create(self.client, item_type, '41', 3, dismissed=True, allow_module_progress=True)
                self.assertEqual(preview['body']['plannable_type'], item_type)
                self.assertIn('not an assignment submission', preview['effect'])
        self.assertTrue(all(call.args == ('/api/v1/users/self/profile',)
                            for call in self.client.request.call_args_list))

    @patch('canvas_pocket.overrides.items')
    def test_assignment_normalization_accepts_only_its_linked_planner_object(self, feed):
        feed.return_value = {**self.feed, 'items': [{**self.item, 'plannable_type': 'assignment'}]}
        preview = create(self.client, 'assignment', '41', 3, marked_complete=True, allow_module_progress=True)
        linked = {**self.override, 'plannable_type': 'quiz', 'plannable_id': 99, 'assignment_id': 41}
        self.client.request.side_effect = [(self.profile, ''), (linked, '')]
        result = create(self.client, 'assignment', '41', 3, marked_complete=True, allow_module_progress=True,
                        yes=True, confirm=preview['confirm'])
        self.assertEqual(result['planner_override']['plannable_id'], 99)
        self.client.request.reset_mock()
        self.client.request.side_effect = [(self.profile, ''), ({**linked, 'assignment_id': 43}, '')]
        with self.assertRaisesRegex(CanvasError, 'outcome uncertain'):
            create(self.client, 'assignment', '41', 3, marked_complete=True, allow_module_progress=True,
                   yes=True, confirm=preview['confirm'])
        self.assertEqual(self.client.request.call_count, 2)

    @patch('canvas_pocket.overrides.items')
    def test_existing_override_is_not_duplicated_including_assignment_aliases(self, feed):
        for item_type, override in [('planner_note', self.override),
                                    ('assignment', {**self.override, 'plannable_type': 'quiz',
                                                    'plannable_id': 99, 'assignment_id': 41})]:
            self.client.list.return_value = [override]
            with self.subTest(item_type=item_type), self.assertRaisesRegex(CanvasError, 'already exists'):
                create(self.client, item_type, '41', 3, marked_complete=True, allow_module_progress=True)
        feed.assert_not_called()

    @patch('canvas_pocket.overrides.items')
    def test_missing_duplicate_hidden_locked_or_already_overridden_feed_item_is_not_written(self, feed):
        for rows in ([], [self.item, self.item], [{**self.item, 'planner_override': self.override}],
                     [{**self.item, 'published': False}], [{**self.item, 'hidden_for_user': True}],
                     [{**self.item, 'plannable': {'locked_for_user': True}}]):
            feed.return_value = {**self.feed, 'items': rows}
            self.client.request.reset_mock()
            with self.subTest(rows=rows), self.assertRaises(CanvasError):
                create(self.client, 'planner_note', '41', 3, marked_complete=True)
            self.client.request.assert_called_once_with('/api/v1/users/self/profile')

    def test_edit_preserves_unspecified_checkbox_even_when_true(self):
        self.client.request.side_effect = [(self.profile, ''), (self.override, '')]
        preview = change(self.client, '42', dismissed=True)
        self.assertEqual(preview['body'], {'marked_complete': True, 'dismissed': True})
        self.client.request.side_effect = [(self.profile, ''), (self.override, ''),
                                           ({**self.override, 'dismissed': True}, '')]
        result = change(self.client, '42', dismissed=True, yes=True, confirm=preview['confirm'])
        self.assertEqual(result['planner_override']['marked_complete'], True)
        self.client.request.assert_called_with('/api/v1/planner/overrides/42', 'PUT', preview['body'])
        self.client.request.side_effect = [(self.profile, ''), ({**self.override, 'dismissed': True}, '')]
        preview = change(self.client, '42', marked_complete=False)
        self.assertEqual(preview['body'], {'marked_complete': False, 'dismissed': True})

    def test_course_content_requires_explicit_module_progress_acknowledgement(self):
        course = {**self.override, 'plannable_type': 'WikiPage'}
        self.client.request.side_effect = [(self.profile, ''), (course, '')]
        with self.assertRaisesRegex(CanvasError, 'allow-module-progress'):
            change(self.client, '42', dismissed=True)
        self.client.request.side_effect = [(self.profile, ''), (course, '')]
        preview = change(self.client, '42', dismissed=True, allow_module_progress=True)
        self.assertTrue(preview['module_progress_acknowledged'])
        self.assertIn('module mark-done', preview['effect'])

    def test_delete_removes_only_the_override_and_does_not_claim_to_undo_module_progress(self):
        course = {**self.override, 'plannable_type': 'assignment'}
        self.client.request.side_effect = [(self.profile, ''), (course, '')]
        preview = change(self.client, '42', delete=True)
        self.assertIsNone(preview['body'])
        self.client.request.side_effect = [(self.profile, ''), (course, ''),
                                           ({**course, 'workflow_state': 'deleted', 'deleted_at': '2026-10-02T14:00:00Z'}, '')]
        result = change(self.client, '42', delete=True, yes=True, confirm=preview['confirm'])
        self.assertIn('does not undo', result['note'])
        self.client.request.assert_called_with('/api/v1/planner/overrides/42', 'DELETE', None)

    def test_changed_account_checkbox_or_target_invalidates_confirmation(self):
        self.client.request.side_effect = [(self.profile, ''), (self.override, '')]
        preview = change(self.client, '42', dismissed=True)
        for profile, override in [({'id': 8}, {**self.override, 'user_id': 8}),
                                  (self.profile, {**self.override, 'marked_complete': False}),
                                  (self.profile, {**self.override, 'plannable_id': 43})]:
            self.client.request.reset_mock()
            self.client.request.side_effect = [(profile, ''), (override, '')]
            with self.subTest(profile=profile, override=override), self.assertRaisesRegex(CanvasError, 'Preview changed'):
                change(self.client, '42', dismissed=True, yes=True, confirm=preview['confirm'])
            self.assertEqual(self.client.request.call_count, 2)

    def test_malformed_wrong_user_deleted_and_unpublished_overrides_fail_closed(self):
        for row in (None, {**self.override, 'id': True}, {**self.override, 'id': 43},
                    {**self.override, 'user_id': 8}, {**self.override, 'marked_complete': 'true'},
                    {**self.override, 'plannable_type': []}, {**self.override, 'plannable_id': True},
                    {**self.override, 'workflow_state': 'deleted'}, {**self.override, 'workflow_state': 'unpublished'}):
            self.client.request.reset_mock()
            self.client.request.side_effect = [(self.profile, ''), (row, '')]
            with self.subTest(row=row), self.assertRaises(CanvasError):
                change(self.client, '42', dismissed=True)
            self.assertEqual(self.client.request.call_count, 2)

    def test_read_is_current_user_only_and_not_a_checkbox_mutation(self):
        self.client.request.side_effect = [(self.profile, ''), (self.override, '')]
        data = read(self.client, '42')
        self.assertTrue(data['marked_complete'])
        self.client.request.assert_called_with('/api/v1/planner/overrides/42')
        self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))

    def test_invalid_flags_and_course_create_acknowledgement_fail_before_reads(self):
        for kwargs in ({}, {'marked_complete': 'true'}, {'dismissed': 1}, {'marked_complete': True, 'yes': True},
                       {'marked_complete': True, 'confirm': 'unused'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                create(self.client, 'planner_note', '41', 3, **kwargs)
        with self.assertRaisesRegex(CanvasError, 'allow-module-progress'):
            create(self.client, 'assignment', '41', 3, marked_complete=True)
        for item_type in ('made_up', []):
            with self.subTest(item_type=item_type), self.assertRaises(CanvasError):
                create(self.client, item_type, '41', 3, marked_complete=True)
        with self.assertRaises(CanvasError):
            change(self.client, '42', delete=True, marked_complete=True)
        self.client.request.assert_not_called()
        self.client.list.assert_not_called()


if __name__ == '__main__': unittest.main()
