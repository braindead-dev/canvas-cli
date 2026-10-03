import unittest
from unittest.mock import Mock

from canvas_pocket.client import CanvasError
from canvas_pocket.group_categories import groups, listing, read


class GroupCategoryTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.course = {'id': 101, 'name': 'Synthetic course'}
        self.category = {'id': 3, 'context_type': 'Course', 'course_id': 101, 'name': 'Synthetic project groups',
                         'role': None, 'self_signup': 'restricted', 'self_signup_end_at': '2026-10-08T07:00:00Z',
                         'group_limit': 5, 'non_collaborative': False, 'allows_multiple_memberships': False,
                         'sis_group_category_id': 'synthetic-private-category-sis',
                         'progress': {'message': 'synthetic-private-progress-message'}}
        self.group = {'id': 11, 'context_type': 'Course', 'course_id': 101, 'group_category_id': 3,
                      'name': 'Synthetic project team', 'members_count': 3, 'max_membership': 5,
                      'leader': {'id': 8, 'name': 'synthetic-private-leader'},
                      'users': [{'id': 8, 'email': 'synthetic-private-member@example.edu'}]}
        self.client.request.side_effect = [(self.course, ''), (self.category, '')]
        self.client.list.return_value = [self.category]

    def test_course_category_listing_is_paginated_filtered_metadata_without_progress_or_sis(self):
        self.client.request.side_effect = None
        self.client.request.return_value = (self.course, '')
        result = listing(self.client, '101', 2, collaboration_state='all')
        self.client.list.assert_called_once_with('/api/v1/courses/101/group_categories?per_page=100&collaboration_state=all', 2)
        self.assertEqual(result['group_categories'][0]['group_limit'], 5)
        self.assertTrue(result['complete_for_endpoint'])
        self.assertNotIn('synthetic-private', str(result))
        self.assertIn('not proof', result['note'])

    def test_single_category_is_exact_course_scoped_even_on_global_numeric_route(self):
        result = read(self.client, '101', '3')
        self.assertEqual(result['group_category']['id'], 3)
        self.assertEqual(result['group_category']['self_signup'], 'restricted')
        self.assertNotIn('synthetic-private', str(result))
        self.assertEqual([call.args[0] for call in self.client.request.call_args_list],
                         ['/api/v1/courses/101', '/api/v1/group_categories/3'])

    def test_category_groups_verify_exact_category_and_course_and_omit_member_associations(self):
        self.client.list.return_value = [self.group]
        result = groups(self.client, '101', '3', 3)
        self.assertEqual(result['category_groups'][0]['group_category_id'], 3)
        self.assertEqual(result['category_groups'][0]['members_count'], 3)
        self.assertNotIn('leader', str(result['category_groups']))
        self.assertNotIn('synthetic-private', str(result))
        self.client.list.assert_called_once_with('/api/v1/group_categories/3/groups?per_page=100', 3)

    def test_account_foreign_course_wrong_id_and_missing_context_are_refused(self):
        for change in ({'context_type': 'Account'}, {'course_id': 102}, {'course_id': '101'},
                       {'course_id': True}, {'id': 4}, {'id': False}, {'context_type': None}):
            self.client.request.side_effect = [(self.course, ''), ({**self.category, **change}, '')]
            self.client.list.reset_mock()
            with self.subTest(change=change), self.assertRaises(CanvasError):
                groups(self.client, '101', '3')
            self.client.list.assert_not_called()

    def test_foreign_and_duplicate_category_groups_are_never_partial_success(self):
        for change in ({'course_id': 102}, {'group_category_id': 4}, {'group_category_id': '3'},
                       {'context_type': 'Account'}, {'members_count': True}, {'max_membership': -1}, {'is_full': 'false'}):
            self.client.request.side_effect = [(self.course, ''), (self.category, '')]
            self.client.list.return_value = [{**self.group, **change}]
            with self.subTest(change=change), self.assertRaises(CanvasError):
                groups(self.client, '101', '3')
        self.client.request.side_effect = [(self.course, ''), (self.category, '')]
        self.client.list.return_value = [self.group, self.group]
        with self.assertRaisesRegex(CanvasError, 'duplicate'):
            groups(self.client, '101', '3')

    def test_native_unknown_fields_are_not_invented_and_bad_reported_fields_fail_closed(self):
        self.client.request.side_effect = [(self.course, ''), ({'id': 3, 'context_type': 'Course', 'course_id': 101}, '')]
        result = read(self.client, '101', '3')
        self.assertNotIn('allows_multiple_memberships', result['group_category'])
        self.assertNotIn('self_signup', result['group_category'])
        for change in ({'group_limit': True}, {'allows_multiple_memberships': 1}, {'self_signup': {}}):
            self.client.request.side_effect = [(self.course, ''), ({**self.category, **change}, '')]
            with self.subTest(change=change), self.assertRaises(CanvasError):
                read(self.client, '101', '3')

    def test_bad_inputs_fail_before_network_and_collaboration_mismatches_are_not_silently_removed(self):
        for function, args, kwargs in ((listing, ('../101',), {}), (listing, ('101',), {'max_pages': 0}),
                                       (listing, ('101',), {'collaboration_state': 'unknown'}),
                                       (read, ('101', '03'), {}), (groups, ('101', '3'), {'max_pages': True})):
            with self.subTest(function=function), self.assertRaises(CanvasError):
                function(self.client, *args, **kwargs)
        self.client.request.assert_not_called()
        self.client.list.assert_not_called()
        self.client.request.side_effect = None
        self.client.request.return_value = (self.course, '')
        for rows, state in (([self.category, self.category], 'collaborative'), ([self.category], 'non_collaborative'),
                            ([{**self.category, 'non_collaborative': True}], 'collaborative')):
            self.client.list.return_value = rows
            with self.subTest(state=state), self.assertRaises(CanvasError):
                listing(self.client, '101', collaboration_state=state)

    def test_denied_truncated_and_unexpected_category_pagination_are_not_empty_success(self):
        self.client.request.side_effect = None
        self.client.request.return_value = (self.course, '')
        for status in (401, 403, 404, 429):
            self.client.list.side_effect = CanvasError('Synthetic denied', status)
            with self.subTest(status=status), self.assertRaises(CanvasError) as error:
                listing(self.client, '101')
            self.assertEqual(error.exception.status, status)
        self.client.list.side_effect = CanvasError('Page limit reached')
        with self.assertRaisesRegex(CanvasError, 'Page limit'):
            listing(self.client, '101')
        self.client.request.side_effect = [(self.course, ''), (self.category, '</api/v1/group_categories/3?page=2>; rel="next"')]
        with self.assertRaisesRegex(CanvasError, 'Unexpected'):
            read(self.client, '101', '3')


if __name__ == '__main__':
    unittest.main()
