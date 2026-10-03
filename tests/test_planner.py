import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from canvas_cli.client import CanvasError
from canvas_cli.planner import change_note, create_note, items, notes, own_id, window


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.profile = {'id': 7}
        self.course = {'id': 8, 'name': 'Synthetic course', 'course_code': 'TEST'}
        self.client.list.return_value = []
        self.client.request.return_value = (self.profile, '')

    def test_canonical_dates_and_inclusive_default_window(self):
        self.assertEqual(window('2026-09-25'), ('2026-09-25', '2026-10-08'))
        self.assertEqual(window('2026-10-02', '2026-10-02'),
                         ('2026-10-02', '2026-10-02'))
        for start, end in [('20260925', None), ('2026-02-30', None),
                           ('9999-12-31', None), ('2026-10-02', '2026-10-01')]:
            with self.subTest(start=start, end=end), self.assertRaises(CanvasError):
                window(start, end)

    def test_item_filters_and_contexts_are_paginated_gets(self):
        row = {'plannable_id': 9, 'plannable_type': 'assignment',
               'plannable': {'title': 'Synthetic task'},
               'planner_override': {'marked_complete': True},
               'submissions': {'missing': True}}
        self.client.list.return_value = [row]
        result = items(self.client, 4, '2026-10-01', '2026-10-02',
                       courses=['8', '8'], groups=['9'], filter_by='incomplete_items')
        query = parse_qs(urlsplit(self.client.list.call_args.args[0]).query)
        self.assertEqual(query['context_codes[]'], ['course_8', 'group_9'])
        self.assertEqual(query['filter'], ['incomplete_items'])
        self.assertEqual(self.client.list.call_args.args[1], 4)
        self.assertEqual(result['items'], [row])
        self.assertIn('not proof', result['note'])
        self.client.request.assert_not_called()

    def test_malformed_item_details_are_not_treated_as_empty(self):
        for rows in [[None], [{'plannable': 'bad'}], [{'planner_override': []}]]:
            self.client.list.return_value = rows
            with self.subTest(rows=rows), self.assertRaises(CanvasError):
                items(self.client, 3)

    def test_personal_notes_use_signed_in_user_not_arbitrary_id(self):
        notes(self.client, 2, courses=['8'], personal=True)
        self.client.request.assert_called_once_with('/api/v1/users/self/profile')
        query = parse_qs(urlsplit(self.client.list.call_args.args[0]).query)
        self.assertEqual(query['context_codes[]'], ['course_8', 'user_7'])
        for profile in ({'id': True}, {'id': 0}, {'id': '7'}, None):
            with self.subTest(profile=profile), self.assertRaises(CanvasError):
                own_id(profile)
        with self.assertRaises(CanvasError):
            notes(self.client, 2, start='20261002')

    def test_task_preview_binds_account_origin_course_and_body_without_writing(self):
        self.client.request.side_effect = [(self.profile, ''), (self.course, '')]
        preview = create_note(self.client, '  Read chapter  ', '2026-10-02',
                              details='Synthetic notes', course_id='8')
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['origin'], self.client.host)
        self.assertEqual(preview['user_id'], 7)
        self.assertEqual(preview['body'], {'title': 'Read chapter', 'todo_date': '2026-10-02',
                                          'details': 'Synthetic notes', 'course_id': 8})
        self.assertEqual([c.args for c in self.client.request.call_args_list],
                         [('/api/v1/users/self/profile',), ('/api/v1/courses/8',)])

    def test_task_confirmation_posts_once_and_changed_account_refuses(self):
        preview = create_note(self.client, 'Synthetic task', '2026-10-02')
        self.client.request.side_effect = [(self.profile, ''), ({'id': 41}, '')]
        self.assertEqual(create_note(self.client, 'Synthetic task', '2026-10-02',
                                     yes=True, confirm=preview['confirm']), {'id': 41})
        self.client.request.assert_called_with('/api/v1/planner_notes', 'POST', preview['body'])
        for changed in ({'id': 9},):
            self.client.request.reset_mock()
            self.client.request.side_effect = [(changed, '')]
            with self.assertRaisesRegex(CanvasError, 'Preview changed'):
                create_note(self.client, 'Synthetic task', '2026-10-02',
                            yes=True, confirm=preview['confirm'])
            self.client.request.assert_called_once_with('/api/v1/users/self/profile')
        self.client.host = 'https://different.example.edu'
        self.client.request.side_effect = [(self.profile, '')]
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            create_note(self.client, 'Synthetic task', '2026-10-02',
                        yes=True, confirm=preview['confirm'])

    def test_invalid_task_and_incomplete_confirmation_do_not_contact_canvas(self):
        for kwargs in ({'yes': True}, {'confirm': 'digest'}, {'details': []}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                create_note(self.client, 'Synthetic', '2026-10-02', **kwargs)
        with self.assertRaises(CanvasError):
            create_note(self.client, ' ', '2026-10-02')
        self.client.request.assert_not_called()

    def test_task_course_identity_and_network_errors_are_not_suppressed(self):
        self.client.request.side_effect = [(self.profile, ''), ({'id': 99}, '')]
        with self.assertRaisesRegex(CanvasError, 'different course'):
            create_note(self.client, 'Synthetic', '2026-10-02', course_id='8')
        self.client.list.side_effect = CanvasError('limited', status=429)
        with self.assertRaises(CanvasError) as error:
            items(self.client, 2)
        self.assertEqual(error.exception.status, 429)

    def test_edit_sends_only_selected_fields_and_preserves_other_details(self):
        note = {'id': 41, 'user_id': 7, 'title': 'Before', 'details': 'Keep this',
                'todo_date': '2026-10-01', 'course_id': 8, 'updated_at': 'version1'}
        reads = [(self.profile, ''), (note, '')]
        self.client.request.side_effect = reads
        preview = change_note(self.client, '41', title='After')
        self.assertEqual(preview['body'], {'title': 'After'})
        self.assertEqual(preview['before']['details'], 'Keep this')
        self.client.request.side_effect = reads + [({**note, 'title': 'After'}, '')]
        change_note(self.client, '41', title='After', yes=True, confirm=preview['confirm'])
        self.client.request.assert_called_with('/api/v1/planner_notes/41', 'PUT', {'title': 'After'})

    def test_changed_task_or_other_owner_prevents_mutation(self):
        note = {'id': 41, 'user_id': 7, 'title': 'Before', 'updated_at': 'version1'}
        self.client.request.side_effect = [(self.profile, ''), (note, '')]
        preview = change_note(self.client, '41', title='After')
        for changed in ({**note, 'updated_at': 'version2'}, {**note, 'user_id': 99},
                        {**note, 'id': 99}, {**note, 'workflow_state': 'deleted'}):
            self.client.request.reset_mock()
            self.client.request.side_effect = [(self.profile, ''), (changed, '')]
            with self.subTest(changed=changed), self.assertRaises(CanvasError):
                change_note(self.client, '41', title='After', yes=True, confirm=preview['confirm'])
            self.assertTrue(all(len(c.args) == 1 for c in self.client.request.call_args_list))

    def test_course_clear_is_explicit_and_linked_notes_cannot_reassociate(self):
        note = {'id': 41, 'user_id': 7, 'title': 'Task', 'course_id': 8}
        self.client.request.side_effect = [(self.profile, ''), (note, '')]
        preview = change_note(self.client, '41', clear_course=True, details='')
        self.assertEqual(preview['body'], {'course_id': None, 'details': ''})
        self.client.request.side_effect = [(self.profile, ''),
                                           ({**note, 'linked_object_type': 'assignment'}, '')]
        with self.assertRaisesRegex(CanvasError, 'linked task'):
            change_note(self.client, '41', clear_course=True)

    def test_delete_requires_fresh_preview_and_never_deletes_an_assignment(self):
        note = {'id': 41, 'user_id': 7, 'title': 'Synthetic task'}
        self.client.request.side_effect = [(self.profile, ''), (note, '')]
        preview = change_note(self.client, '41', delete=True)
        self.assertEqual(preview['method'], 'DELETE')
        self.assertIsNone(preview['body'])
        self.assertIn('no assignment is deleted', preview['effect'])
        self.client.request.side_effect = [(self.profile, ''), (note, ''),
                                           ({**note, 'workflow_state': 'deleted'}, '')]
        change_note(self.client, '41', delete=True, yes=True, confirm=preview['confirm'])
        self.client.request.assert_called_with('/api/v1/planner_notes/41', 'DELETE', None)

    def test_invalid_edit_or_delete_flags_fail_before_read(self):
        for kwargs in ({}, {'title': ' '}, {'delete': True, 'title': 'No'},
                       {'course_id': '8', 'clear_course': True}, {'details': []}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                change_note(self.client, '41', **kwargs)
        self.client.request.assert_not_called()


if __name__ == '__main__': unittest.main()
