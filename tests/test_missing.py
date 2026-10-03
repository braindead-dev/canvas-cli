import unittest
from unittest.mock import Mock

from canvas_pocket.cli import brief
from canvas_pocket.client import CanvasError
from canvas_pocket.missing import read


class MissingTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.client.request.return_value = ({'id': 7}, '')
        self.assignment = {'id': 88, 'course_id': 101, 'name': 'Synthetic missing paper',
                           'published': True, 'due_at': '2026-10-01T06:59:00Z', 'locked_for_user': True,
                           'course': {'id': 101, 'name': 'Synthetic course', 'private_field': 'No echo'},
                           'description': 'Private prompt not requested',
                           'html_url': 'https://canvas.example.edu/courses/101/assignments/88?verifier=secret'}
        self.override = {'id': 51, 'user_id': 7, 'plannable_type': 'assignment', 'plannable_id': 88,
                         'marked_complete': True, 'dismissed': False, 'private_field': 'No echo'}
        self.client.list.return_value = [self.assignment]

    def test_own_native_feed_paginates_and_projects_only_metadata_with_local_dates(self):
        result = read(self.client, 3, time_zone='America/Los_Angeles')
        self.client.list.assert_called_once_with(
            '/api/v1/users/self/missing_submissions?per_page=100&include%5B%5D=course', 3)
        self.client.request.assert_called_once_with('/api/v1/users/self/profile')
        self.assertEqual(result['user_id'], 7)
        item = result['missing_assignments'][0]
        self.assertEqual(item['due_local'], '2026-09-30T23:59:00-07:00')
        self.assertIn('11:59 PM PDT', item['due_display'])
        self.assertEqual(item['course_name'], 'Synthetic course')
        self.assertTrue(item['locked_for_user'])
        self.assertNotIn('Private prompt', str(result))
        self.assertNotIn('No echo', str(result))
        self.assertNotIn('secret', str(result))
        self.assertFalse(result['complete_coursework_inventory'])
        self.assertIn('Synthetic missing paper', brief(result))

    def test_repeatable_course_and_native_filters_do_not_infer_completion(self):
        result = read(self.client, course_ids=['101', '102', '101'], submittable=True,
                      current_grading_period=True, include_planner=True)
        self.client.list.assert_called_once_with(
            '/api/v1/users/self/missing_submissions?per_page=100&include%5B%5D=course&'
            'include%5B%5D=planner_overrides&course_ids%5B%5D=101&course_ids%5B%5D=102&'
            'filter%5B%5D=submittable&filter%5B%5D=current_grading_period', 100)
        self.assertEqual(result['course_ids'], [101, 102])
        self.assertIsNone(result['missing_assignments'][0]['planner_override'])
        self.client.list.return_value = [{**self.assignment, 'planner_override': self.override}]
        item = read(self.client, include_planner=True)['missing_assignments'][0]
        self.assertTrue(item['planner_override']['marked_complete'])
        self.assertEqual(item['status_source'], 'canvas_missing_submissions')
        self.assertNotIn('private_field', str(item))

    def test_unknown_dates_remain_unknown_without_synthesizing_a_deadline(self):
        for value in (None, '', 'bad', '2026-10-01T06:59:00', 3):
            self.client.list.return_value = [{**self.assignment, 'due_at': value}]
            item = read(self.client)['missing_assignments'][0]
            self.assertIsNone(item['due_local'])
            self.assertEqual(item['due_display'], 'Unknown due time')

    def test_malformed_duplicate_and_unselected_records_are_rejected(self):
        for rows in ([None], [{**self.assignment, 'id': True}], [{**self.assignment, 'course_id': True}],
                     [{**self.assignment, 'published': False}], [self.assignment, self.assignment],
                     [{**self.assignment, 'course_id': 102}],
                     [{**self.assignment, 'course': {'id': 102}}]):
            self.client.list.return_value = rows
            with self.subTest(rows=rows), self.assertRaises(CanvasError):
                read(self.client, course_ids=['101'])

    def test_planner_override_must_be_own_and_match_assignment_without_string_bool_coercion(self):
        for override in ([], {**self.override, 'user_id': 8}, {**self.override, 'user_id': True},
                         {**self.override, 'plannable_id': 89}, {**self.override, 'plannable_type': 'quiz'},
                         {**self.override, 'marked_complete': 1}):
            self.client.list.return_value = [{**self.assignment, 'planner_override': override}]
            with self.subTest(override=override), self.assertRaises(CanvasError):
                read(self.client, include_planner=True)

    def test_bad_options_fail_before_any_network_and_native_errors_are_not_empty_success(self):
        for options in ({'course_ids': '101'}, {'course_ids': ['01']}, {'course_ids': ['١']},
                        {'course_ids': ['0']}, {'submittable': 1}, {'current_grading_period': 'true'},
                        {'include_planner': 1}, {'time_zone': 'No/Such_Zone'}):
            with self.subTest(options=options), self.assertRaises(CanvasError):
                read(self.client, **options)
        self.client.request.assert_not_called()
        self.client.list.assert_not_called()
        for status in (401, 403, 404, 429):
            self.client.list.side_effect = CanvasError('Unavailable', status=status)
            with self.assertRaises(CanvasError):
                read(self.client)

    def test_empty_native_feed_is_not_proof_that_nothing_else_is_due(self):
        self.client.list.return_value = []
        result = read(self.client)
        self.assertEqual(result['missing_assignments'], [])
        self.assertTrue(result['complete_for_endpoint'])
        self.assertFalse(result['complete_coursework_inventory'])
        self.assertIn('not every unfinished', result['note'])
