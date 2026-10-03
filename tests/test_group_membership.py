import unittest
from unittest.mock import Mock

from canvas_pocket.client import CanvasError
from canvas_pocket.group_membership import change, read


class GroupMembershipTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.group = {'id': 11, 'name': 'Synthetic group', 'role': 'student_organized', 'group_category_id': 3,
                      'non_collaborative': False, 'concluded': False, 'join_level': 'parent_context_auto_join',
                      'sis_group_id': 'synthetic-private-group-sis'}
        self.member = {'id': 71, 'group_id': 11, 'user_id': 7, 'workflow_state': 'accepted', 'moderator': False,
                       'sis_import_id': 'synthetic-private-import', 'created_at': '2026-10-01T12:00:00Z'}
        self.others = [{**self.member, 'id': 72, 'user_id': 8, 'private': 'synthetic-private-other'}]
        self.client.list.return_value = self.others

        def request(route, method='GET', body=None):
            if route == '/api/v1/users/self/profile':
                return {'id': 7}, ''
            if route == '/api/v1/groups/11':
                return self.group.copy(), ''
            if '/permissions?' in route:
                return {'join': True, 'leave': True}, ''
            if method == 'POST' and route.endswith('/memberships'):
                return self.member.copy(), ''
            if method == 'DELETE' and route.endswith('/users/self'):
                return {'ok': True}, ''
            raise AssertionError((route, method, body))
        self.client.request.side_effect = request

    def test_read_returns_only_own_active_record_not_other_people_or_sis_data(self):
        self.client.list.return_value = [self.member, *self.others]
        result = read(self.client, '11', 3)
        self.assertEqual(result['membership']['user_id'], 7)
        self.assertEqual(result['membership']['workflow_state'], 'accepted')
        self.assertTrue(result['complete_for_endpoint'])
        self.assertNotIn('synthetic-private', str(result))
        self.assertNotIn('user_id\': 8', str(result))
        self.client.list.assert_called_once_with('/api/v1/groups/11/memberships?per_page=100', 3)
        self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))

    def test_absent_active_record_is_not_a_claim_that_deleted_records_do_not_exist(self):
        result = read(self.client, '11')
        self.assertIsNone(result['membership'])
        self.assertIn('deleted/rejected', result['note'])
        for state in ('requested', 'invited'):
            self.client.list.return_value = [{**self.member, 'workflow_state': state}]
            self.assertEqual(read(self.client, '11')['membership']['workflow_state'], state)

    def test_join_has_account_group_current_state_bound_preview_and_exact_self_body(self):
        preview = change(self.client, '11', 'join')
        self.assertTrue(preview['dry_run'])
        self.assertIsNone(preview['current_membership'])
        self.assertEqual(preview['body'], {'user_id': 'self'})
        self.assertEqual(preview['route'], '/api/v1/groups/11/memberships')
        self.assertNotIn('synthetic-private', str(preview))
        self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))
        result = change(self.client, '11', 'join', yes=True, confirm=preview['confirm'])
        self.assertEqual(result['membership']['workflow_state'], 'accepted')
        self.assertTrue(result['acknowledged'])
        self.client.request.assert_called_with('/api/v1/groups/11/memberships', 'POST', {'user_id': 'self'})

    def test_leave_uses_only_self_route_and_native_boolean_ok_ack(self):
        self.client.list.return_value = [self.member]
        preview = change(self.client, '11', 'leave')
        self.assertEqual(preview['current_membership']['id'], 71)
        self.assertEqual(preview['route'], '/api/v1/groups/11/users/self')
        self.assertIsNone(preview['body'])
        result = change(self.client, '11', 'leave', yes=True, confirm=preview['confirm'])
        self.assertTrue(result['acknowledged'])
        self.assertIsNone(result['membership'])
        self.assertIn('not an independent readback', result['note'])
        self.client.request.assert_called_with('/api/v1/groups/11/users/self', 'DELETE', None)

    def test_role_lifecycle_and_differentiation_tag_restrictions_do_not_assume_admin_privileges(self):
        for field, value in (('role', None), ('role', 'imported'), ('role', 'uncategorized'),
                             ('non_collaborative', True), ('non_collaborative', None),
                             ('concluded', True), ('concluded', None), ('group_category_id', True),
                             ('group_category_id', '3'), ('group_category_id', 0)):
            original = self.group.copy()
            self.group[field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(CanvasError, 'project groups'):
                change(self.client, '11', 'join')
            self.group = original
        self.client.list.assert_not_called()
        self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))

    def test_permission_is_explicit_not_inferred_from_membership_or_role(self):
        original = self.client.request.side_effect
        for permissions in ({}, {'join': False}, {'join': 'true'}, {'join': 1}, []):
            def request(route, *args):
                return (permissions, '') if '/permissions?' in route else original(route, *args)
            self.client.request.side_effect = request
            with self.subTest(permissions=permissions), self.assertRaisesRegex(CanvasError, 'explicit'):
                change(self.client, '11', 'join')
        self.client.list.assert_not_called()

    def test_duplicate_join_invitation_only_and_absent_leave_are_not_writes(self):
        for state in ('accepted', 'requested'):
            self.client.list.return_value = [{**self.member, 'workflow_state': state}]
            with self.subTest(state=state), self.assertRaisesRegex(CanvasError, 'already have'):
                change(self.client, '11', 'join')
        self.client.list.return_value = []
        with self.assertRaisesRegex(CanvasError, 'No active own'):
            change(self.client, '11', 'leave')
        self.group['join_level'] = 'invitation_only'
        with self.assertRaisesRegex(CanvasError, 'invitation acceptance'):
            change(self.client, '11', 'join')
        self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))

    def test_account_group_and_membership_changes_invalidate_confirmation(self):
        preview = change(self.client, '11', 'join')
        self.group['name'] = 'Renamed synthetic group'
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            change(self.client, '11', 'join', yes=True, confirm=preview['confirm'])
        self.group['name'] = 'Synthetic group'
        self.client.list.return_value = [{**self.member, 'workflow_state': 'invited'}]
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            change(self.client, '11', 'join', yes=True, confirm=preview['confirm'])
        self.client.list.return_value = []
        original = self.client.request.side_effect
        self.client.request.side_effect = lambda route, *args: ({'id': 9}, '') if route.endswith('/profile') else original(route, *args)
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            change(self.client, '11', 'join', yes=True, confirm=preview['confirm'])
        self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))

    def test_malformed_foreign_or_duplicate_active_records_are_never_absent_success(self):
        for rows in ([self.member, self.member], [self.member, {**self.member, 'id': 72}],
                     [{**self.member, 'group_id': 12}], [{**self.member, 'group_id': '11'}],
                     [{**self.member, 'workflow_state': 'deleted'}], [{**self.member, 'moderator': 'false'}],
                     [{**self.member, 'id': True}], [{**self.member, 'user_id': False}],
                     [{**self.member, 'created_at': {}}]):
            self.client.list.return_value = rows
            with self.subTest(rows=rows), self.assertRaises(CanvasError):
                read(self.client, '11')

    def test_ambiguous_acknowledgements_are_sanitized_never_retried(self):
        original = self.client.request.side_effect
        for action, replies in (('join', ({**self.member, 'user_id': 8}, {**self.member, 'group_id': 12},
                                          {'private': 'synthetic-private-error'})),
                                ('leave', ({'ok': 'true'}, {'ok': 1}, {}))):
            self.client.list.return_value = [] if action == 'join' else [self.member]
            preview = change(self.client, '11', action)
            for reply in replies:
                def request(route, method='GET', body=None):
                    return (reply, '') if method != 'GET' else original(route)
                self.client.request.side_effect = request
                self.client.request.reset_mock()
                with self.subTest(action=action, reply=reply), self.assertRaisesRegex(CanvasError, 'may have succeeded') as error:
                    change(self.client, '11', action, yes=True, confirm=preview['confirm'])
                self.assertNotIn('synthetic-private', str(error.exception))
                self.assertEqual(len([call for call in self.client.request.call_args_list if len(call.args) > 1]), 1)
            self.client.request.side_effect = original

    def test_denial_truncation_and_confirmation_flag_errors_never_write(self):
        for status in (401, 403, 404, 429):
            self.client.list.side_effect = CanvasError('Synthetic error', status)
            with self.subTest(status=status), self.assertRaises(CanvasError) as error:
                change(self.client, '11', 'join')
            self.assertEqual(error.exception.status, status)
        self.client.list.side_effect = CanvasError('Page limit reached')
        with self.assertRaisesRegex(CanvasError, 'Page limit'):
            change(self.client, '11', 'join')
        self.client.request.reset_mock()
        for kwargs in ({'yes': True}, {'confirm': 'abc'}, {'action': 'accept'}, {'max_pages': 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                change(self.client, '11', **({'action': 'join'} | kwargs))
        self.client.request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
