import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from canvas_pocket.client import CanvasError
from canvas_pocket.enrollments import read, respond


class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.row = {'id': 77, 'course_id': 101, 'user_id': 7, 'course_section_id': 31,
                    'type': 'StudentEnrollment', 'role': 'StudentEnrollment', 'enrollment_state': 'active',
                    'updated_at': '2026-10-02T12:00:00Z', 'grades': {'current_score': 100},
                    'sis_user_id': 'synthetic-private-enrollment-sis',
                    'user': {'email': 'synthetic-private-enrollment-contact@example.edu'},
                    'last_activity_at': 'synthetic-private-analytics'}
        self.invitation = {**self.row, 'id': 99, 'course_id': 102, 'enrollment_state': 'invited'}
        self.client.list.return_value = [self.row, {**self.row, 'id': 78, 'course_section_id': 32}, self.invitation]
        self.client.request.side_effect = lambda route, method='GET', body=None: (
            {'id': 7} if method == 'GET' and route == '/api/v1/users/self/profile' else {'success': True}, '')

    def test_default_own_inventory_preserves_separate_sections_without_grades_or_private_fields(self):
        result = read(self.client, 2)
        self.assertEqual([row['id'] for row in result['enrollments']], [77, 78, 99])
        self.assertEqual([row['course_section_id'] for row in result['enrollments'][:2]], [31, 32])
        self.assertTrue(result['complete_for_endpoint'])
        self.assertFalse(result['course_filter_applied_locally'])
        self.assertNotIn('synthetic-private', str(result))
        self.assertNotIn('grades', str(result['enrollments']))
        self.assertIn('not prove official registration', result['note'])
        self.client.list.assert_called_once_with('/api/v1/users/self/enrollments?per_page=100', 2)
        self.client.request.assert_called_once_with('/api/v1/users/self/profile')

    def test_filters_use_native_user_scoped_states_types_term_and_local_course_filter(self):
        result = read(self.client, types=['TaEnrollment', 'StudentEnrollment'],
                      states=['current_and_future', 'invited'], courses=['102'], term='12')
        self.assertEqual([row['id'] for row in result['enrollments']], [99])
        self.assertTrue(result['course_filter_applied_locally'])
        query = parse_qs(urlsplit(self.client.list.call_args.args[0]).query)
        self.assertEqual(query, {'per_page': ['100'], 'type[]': ['StudentEnrollment', 'TaEnrollment'],
                                 'state[]': ['current_and_future', 'invited'], 'enrollment_term_id': ['12']})
        self.assertNotIn('user_id', query)
        self.assertNotIn('sis_course_id[]', query)

    def test_foreign_user_and_bad_ids_are_not_filtered_away_or_emitted(self):
        for change in ({'user_id': 8}, {'user_id': True}, {'course_id': '101'}, {'course_id': True},
                       {'id': False}, {'enrollment_state': {}}, {'role_id': '3'}):
            self.client.list.return_value = [{**self.row, **change}, self.invitation]
            with self.subTest(change=change), self.assertRaises(CanvasError):
                read(self.client, courses=['102'])
        self.client.list.return_value = [self.row, self.row]
        with self.assertRaisesRegex(CanvasError, 'duplicate'):
            read(self.client)

    def test_invalid_filter_inputs_are_rejected_before_credentials_or_network(self):
        for kwargs in ({'max_pages': 0}, {'max_pages': True}, {'types': ['admin']}, {'states': ['unknown']},
                       {'types': ['StudentEnrollment', 'StudentEnrollment']}, {'courses': '101'},
                       {'courses': ['101', '101']}, {'courses': ['../101']}, {'term': 'sis_term_id:12'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                read(self.client, **kwargs)
        for kwargs in ({'action': 'delete'}, {'acknowledge': False}, {'yes': True}, {'confirm': 'abc'}, {'max_pages': 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                respond(self.client, '102', '99', **({'action': 'accept', 'acknowledge': True} | kwargs))
        self.client.request.assert_not_called()
        self.client.list.assert_not_called()

    def test_accept_and_reject_only_exact_pending_own_invitation_preview_then_one_post(self):
        self.client.list.return_value = [self.invitation]
        for action in ('accept', 'reject'):
            preview = respond(self.client, '102', '99', action, acknowledge=True)
            self.assertTrue(preview['dry_run'])
            self.assertEqual(preview['invitation']['user_id'], 7)
            self.assertEqual(preview['route'], '/api/v1/courses/102/enrollments/99/' + action)
            self.assertIsNone(preview['body'])
            self.assertIn('not official', preview['warning'])
            self.assertNotIn('synthetic-private', str(preview))
            self.client.list.assert_called_with('/api/v1/users/self/enrollments?per_page=100&state%5B%5D=invited', 100)
            with self.assertRaisesRegex(CanvasError, 'Preview changed'):
                respond(self.client, '102', '99', action, acknowledge=True, yes=True, confirm='wrong')
            self.client.request.reset_mock()
            result = respond(self.client, '102', '99', action, acknowledge=True, yes=True, confirm=preview['confirm'])
            self.assertTrue(result['acknowledged'])
            self.assertEqual(result['invitation_response'], action)
            self.assertIn('not an independent readback', result['note'])
            self.assertEqual(len([call for call in self.client.request.call_args_list if len(call.args) > 1]), 1)
            self.client.request.assert_called_with(preview['route'], 'POST', None)

    def test_active_rejected_foreign_course_and_missing_invites_are_refused(self):
        for rows in ([], [self.row], [{**self.invitation, 'course_id': 103}],
                     [{**self.invitation, 'enrollment_state': 'active'}],
                     [{**self.invitation, 'enrollment_state': 'rejected'}], [{**self.invitation, 'user_id': 8}]):
            self.client.list.return_value = rows
            with self.subTest(rows=rows), self.assertRaises(CanvasError):
                respond(self.client, '102', '99', 'accept', acknowledge=True)
        self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))

    def test_account_and_invitation_metadata_changes_invalidate_confirmation(self):
        self.client.list.return_value = [self.invitation]
        preview = respond(self.client, '102', '99', 'accept', acknowledge=True)
        for change in ({'updated_at': '2026-10-02T13:00:00Z'}, {'course_section_id': 32}, {'role': 'New role'}):
            self.client.list.return_value = [{**self.invitation, **change}]
            with self.subTest(change=change), self.assertRaisesRegex(CanvasError, 'Preview changed'):
                respond(self.client, '102', '99', 'accept', acknowledge=True, yes=True, confirm=preview['confirm'])
        self.client.list.return_value = [{**self.invitation, 'user_id': 9}]
        self.client.request.side_effect = lambda route, *args: ({'id': 9}, '')
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            respond(self.client, '102', '99', 'accept', acknowledge=True, yes=True, confirm=preview['confirm'])
        self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))

    def test_ambiguous_ack_is_sanitized_never_retried_or_claimed_as_success(self):
        self.client.list.return_value = [self.invitation]
        preview = respond(self.client, '102', '99', 'reject', acknowledge=True)
        for reply in ({'success': 'true'}, {'success': 1}, {'private': 'synthetic-private-response'}, []):
            self.client.request.side_effect = lambda route, method='GET', body=None: ({'id': 7} if method == 'GET' else reply, '')
            self.client.request.reset_mock()
            with self.subTest(reply=reply), self.assertRaisesRegex(CanvasError, 'may have succeeded') as error:
                respond(self.client, '102', '99', 'reject', acknowledge=True, yes=True, confirm=preview['confirm'])
            self.assertNotIn('synthetic-private', str(error.exception))
            self.assertEqual(len([call for call in self.client.request.call_args_list if len(call.args) > 1]), 1)

    def test_denied_or_truncated_inventories_do_not_authorize_a_write(self):
        for status in (401, 403, 404, 429):
            self.client.list.side_effect = CanvasError('Synthetic error', status)
            with self.subTest(status=status), self.assertRaises(CanvasError) as error:
                respond(self.client, '102', '99', 'accept', acknowledge=True)
            self.assertEqual(error.exception.status, status)
        self.client.list.side_effect = CanvasError('Page limit reached')
        with self.assertRaisesRegex(CanvasError, 'Page limit'):
            read(self.client, 1)
        self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))


if __name__ == '__main__':
    unittest.main()
