import unittest
from unittest.mock import Mock

from canvas_pocket.cli import brief
from canvas_pocket.client import CanvasError
from canvas_pocket.submissions import read


class SubmissionReadTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.client.request.return_value = ({'id': 7}, '')
        self.row = {'id': 31, 'assignment_id': 88, 'user_id': 7, 'attempt': 2, 'workflow_state': 'submitted',
                    'grade_matches_current_submission': False, 'body': 'Private submitted work',
                    'assignment': {'id': 88, 'course_id': 101, 'name': 'Synthetic paper', 'published': True,
                                   'description': 'Private prompt'},
                    'submission_history': [{'attempt': 1, 'body': 'Private first attempt',
                                            'assignment_id': 88, 'user_id': 7}],
                    'submission_comments': [{'id': 41, 'author_id': 8, 'comment': 'Private feedback',
                                             'access_token': 'never echo'}]}
        self.client.list.return_value = [self.row]

    def test_metadata_first_paginated_own_records_do_not_echo_private_work_or_feedback(self):
        result = read(self.client, '101', 3)
        self.client.list.assert_called_once_with('/api/v1/courses/101/students/submissions?'
                                                'student_ids%5B%5D=7&include%5B%5D=assignment&per_page=100', 3)
        self.assertNotIn('Private', str(result))
        self.assertNotIn('submission_history', result['submissions'][0])
        self.assertIn('earlier attempt', result['note'])
        self.assertIn('Synthetic paper', brief(result))
        self.assertFalse(result['complete_coursework_inventory'])

    def test_native_filters_opt_in_history_and_comment_metadata_without_body_disclosure(self):
        result = read(self.client, '101', assignment_ids=['88', '89', '88'], state='submitted',
                      include_history=True, include_comments=True)
        self.client.list.assert_called_once_with('/api/v1/courses/101/students/submissions?'
            'student_ids%5B%5D=7&include%5B%5D=assignment&per_page=100&assignment_ids%5B%5D=88&'
            'assignment_ids%5B%5D=89&workflow_state=submitted&include%5B%5D=submission_history&'
            'include%5B%5D=submission_comments', 100)
        item = result['submissions'][0]
        self.assertEqual(item['submission_history'][0]['attempt'], 1)
        self.assertEqual(item['submission_comments'], [{'id': 41, 'author_id': 8}])
        self.assertNotIn('Private', str(result))
        content = read(self.client, '101', include_history=True, include_comments=True, include_content=True)
        self.assertIn('Private submitted work', str(content))
        self.assertIn('Private first attempt', str(content))
        self.assertIn('Private feedback', str(content))
        self.assertNotIn('never echo', str(content))
        self.row['submission_history'].append(None)
        self.assertIsNone(read(self.client, '101', include_history=True)['submissions'][0]['submission_history'][-1])

    def test_unknown_associations_stay_unknown_and_hidden_assignment_content_is_withheld(self):
        self.client.list.return_value = [{**self.row, 'submission_history': None, 'submission_comments': None}]
        item = read(self.client, '101', include_history=True, include_comments=True)['submissions'][0]
        self.assertIsNone(item['submission_history'])
        self.assertIsNone(item['submission_comments'])
        for flags in ({'assignment_visible': False}, {'assignment': {**self.row['assignment'], 'published': False}}):
            self.client.list.return_value = [{**self.row, **flags}]
            item = read(self.client, '101', include_history=True, include_comments=True,
                        include_content=True)['submissions'][0]
            self.assertIn('content_withheld', item)
            self.assertNotIn('Private', str(item))

    def test_foreign_owner_assignment_course_history_and_bad_associations_fail_closed(self):
        for flags in ({'user_id': 8}, {'user_id': True}, {'assignment_id': True}, {'assignment_id': 89},
                      {'course_id': 102}, {'assignment': {'id': 89}}, {'assignment': {'id': 88, 'course_id': 102}},
                      {'workflow_state': 'graded'}, {'submission_history': [{} , {'user_id': 8}]},
                      {'submission_history': [{'assignment_id': 89}]}, {'submission_comments': [None]}):
            self.client.list.return_value = [{**self.row, **flags}]
            with self.subTest(flags=flags), self.assertRaises(CanvasError):
                read(self.client, '101', assignment_ids=['88'], state='submitted',
                     include_history=True, include_comments=True)
        self.client.list.return_value = [self.row, self.row]
        with self.assertRaisesRegex(CanvasError, 'duplicate'):
            read(self.client, '101')

    def test_invalid_options_fail_before_network(self):
        for course, options in (('0', {}), ('١', {}), ('101', {'assignment_ids': '88'}),
                                ('101', {'assignment_ids': ['01']}), ('101', {'state': 'missing'}),
                                ('101', {'include_history': 1}), ('101', {'include_comments': 'true'}),
                                ('101', {'include_content': 1})):
            with self.subTest(options=options), self.assertRaises(CanvasError):
                read(self.client, course, **options)
        self.client.request.assert_not_called()
        self.client.list.assert_not_called()

    def test_pagination_access_failure_is_not_an_empty_complete_inventory(self):
        self.client.list.side_effect = CanvasError('Page limit reached')
        with self.assertRaisesRegex(CanvasError, 'Page limit'):
            read(self.client, '101')
        self.client.list.side_effect = CanvasError('Denied', status=403)
        with self.assertRaises(CanvasError):
            read(self.client, '101')
