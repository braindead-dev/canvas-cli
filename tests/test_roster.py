import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from canvas_cli.client import CanvasError
from canvas_cli.roster import listing


class RosterTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.client.request.return_value = ({'id': 101, 'name': 'Synthetic course'}, '')
        self.enrollment = {'id': 21, 'course_id': 101, 'user_id': 7, 'course_section_id': 31,
                           'type': 'StudentEnrollment', 'role': 'StudentEnrollment', 'enrollment_state': 'active',
                           'grades': {'current_score': 100}, 'sis_section_id': 'synthetic-private-section'}
        self.user = {'id': 7, 'name': 'Synthetic person', 'short_name': 'Synthetic',
                     'email': 'synthetic-contact@example.edu', 'sis_user_id': 'synthetic-private-sis',
                     'login_id': 'synthetic-private-login', 'uuid': 'synthetic-private-uuid',
                     'bio': 'synthetic-private-bio', 'enrollments': [self.enrollment],
                     'avatar_url': 'https://storage.example.edu/portrait?token=synthetic-private-token'}
        self.client.list.return_value = [self.user]

    def test_default_roster_is_metadata_first_and_has_qualified_completeness(self):
        result = listing(self.client, '101', max_pages=2)
        self.assertEqual(result['users'], [{'id': 7, 'name': 'Synthetic person', 'short_name': 'Synthetic'}])
        self.assertTrue(result['complete_for_endpoint'])
        self.assertEqual(result['returned_user_count'], 1)
        self.assertIn('not a total membership count', result['note'])
        self.assertNotIn('synthetic-private', str(result))
        self.assertNotIn('synthetic-contact', str(result))
        self.client.request.assert_called_once_with('/api/v1/courses/101')
        self.client.list.assert_called_once_with('/api/v1/courses/101/users?per_page=100', 2)

    def test_native_course_filters_encode_repeated_values_and_opt_in_enrollments(self):
        result = listing(self.client, '101', search='  Example & Name  ', enrollment_types=['ta', 'teacher'],
                         enrollment_states=['active', 'invited'], sections=['32', '31'],
                         include_enrollments=True, include_email=True)
        query = parse_qs(urlsplit(self.client.list.call_args.args[0]).query)
        self.assertEqual(query, {'per_page': ['100'], 'search_term': ['Example & Name'],
                                 'enrollment_type[]': ['ta', 'teacher'], 'enrollment_state[]': ['active', 'invited'],
                                 'section_ids[]': ['31', '32'], 'include[]': ['enrollments']})
        self.assertEqual(result['filters']['section_ids'], [31, 32])
        self.assertEqual(result['users'][0]['email'], 'synthetic-contact@example.edu')
        self.assertEqual(result['users'][0]['enrollments'][0]['course_section_id'], 31)
        self.assertNotIn('grades', str(result))
        self.assertNotIn('synthetic-private', str(result))

    def test_enrollment_ids_are_exact_user_and_course_scoped_never_unchecked_associations(self):
        for change in ({'course_id': 102}, {'user_id': 8}, {'course_id': '101'}, {'user_id': True},
                       {'id': True}, {'role_id': False}, {'course_section_id': '31'}, {'role': {}}):
            self.client.list.return_value = [{**self.user, 'enrollments': [{**self.enrollment, **change}]}]
            with self.subTest(change=change), self.assertRaises(CanvasError):
                listing(self.client, '101', include_enrollments=True)
        for enrollments in (None, {}, [self.enrollment, self.enrollment]):
            self.client.list.return_value = [{**self.user, 'enrollments': enrollments}]
            with self.subTest(enrollments=enrollments), self.assertRaises(CanvasError):
                listing(self.client, '101', include_enrollments=True)

    def test_group_roster_keeps_native_count_and_full_flag_separate_from_returned_users(self):
        self.client.request.return_value = ({'id': 11, 'name': 'Synthetic group', 'members_count': 10, 'is_full': True}, '')
        result = listing(self.client, '11', 'group', search='Example', exclude_inactive=False)
        self.assertEqual(result['reported_members_count'], 10)
        self.assertTrue(result['native_is_full'])
        self.assertEqual(result['returned_user_count'], 1)
        query = parse_qs(urlsplit(self.client.list.call_args.args[0]).query)
        self.assertEqual(query, {'per_page': ['100'], 'search_term': ['Example'], 'exclude_inactive': ['false']})
        self.client.request.assert_called_once_with('/api/v1/groups/11')
        self.assertNotIn('/users/self/groups', str(self.client.mock_calls))

    def test_omitted_group_filters_do_not_override_native_defaults_or_invent_capacity(self):
        self.client.request.return_value = ({'id': 11, 'name': 'Synthetic group'}, '')
        result = listing(self.client, '11', 'group')
        self.client.list.assert_called_once_with('/api/v1/groups/11/users?per_page=100', 100)
        self.assertNotIn('native_is_full', result)
        self.assertNotIn('reported_members_count', result)
        self.assertIsNone(result['filters']['exclude_inactive'])

    def test_invalid_filters_and_contexts_fail_before_any_network(self):
        for context in ('0', '01', '١', '../101', None, True):
            with self.subTest(context=context), self.assertRaises(CanvasError):
                listing(self.client, context)
        for kwargs in ({'context_type': 'account'}, {'max_pages': 0}, {'max_pages': True}, {'search': 'x'},
                       {'search': 'a\nb'}, {'enrollment_types': ['admin']}, {'enrollment_types': ['ta', 'ta']},
                       {'enrollment_states': ['deleted']}, {'sections': ['31', '31']}, {'sections': ['031']},
                       {'sections': '31'}, {'exclude_inactive': False},
                       {'context_type': 'group', 'include_enrollments': True},
                       {'context_type': 'group', 'sections': ['31']},
                       {'context_type': 'group', 'exclude_inactive': 'false'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                listing(self.client, '101', **kwargs)
        self.client.request.assert_not_called()
        self.client.list.assert_not_called()

    def test_malformed_duplicate_and_foreign_context_rows_fail_closed(self):
        for users in ([self.user, self.user], [None], [{'id': True}], [{'id': '7'}],
                      [{**self.user, 'name': {}}], [{**self.user, 'email': []}]):
            self.client.list.return_value = users
            with self.subTest(users=users), self.assertRaises(CanvasError):
                listing(self.client, '101', include_email=True)
        self.client.request.return_value = ({'id': 102}, '')
        self.client.list.reset_mock()
        with self.assertRaisesRegex(CanvasError, 'different content context'):
            listing(self.client, '101')
        self.client.list.assert_not_called()

    def test_denied_truncated_and_bad_capacity_rosters_are_not_empty_success(self):
        for status in (401, 403, 404, 429):
            self.client.list.side_effect = CanvasError('Synthetic error', status)
            with self.subTest(status=status), self.assertRaises(CanvasError) as error:
                listing(self.client, '101')
            self.assertEqual(error.exception.status, status)
        self.client.list.side_effect = CanvasError('Page limit reached')
        with self.assertRaisesRegex(CanvasError, 'Page limit'):
            listing(self.client, '101', max_pages=1)
        self.client.list.side_effect = None
        self.client.list.return_value = []
        for change in ({'members_count': True}, {'members_count': -1}, {'is_full': 'false'}):
            self.client.request.return_value = ({'id': 11, **change}, '')
            with self.subTest(change=change), self.assertRaises(CanvasError):
                listing(self.client, '11', 'group')


if __name__ == '__main__':
    unittest.main()
