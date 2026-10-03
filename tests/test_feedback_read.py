import unittest
from unittest.mock import Mock

from canvas_pocket.cli import brief
from canvas_pocket.client import CanvasError
from canvas_pocket.feedback_read import read


class FeedbackReadTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.client.request.return_value = ({'id': 7}, '')
        self.row = {'id': 31, 'assignment_id': 88, 'user_id': 7, 'attempt': 2,
                    'workflow_state': 'submitted', 'grade_matches_current_submission': False,
                    'grade': 'B', 'score': 0, 'graded_at': '2026-10-01T19:00:00Z', 'posted_at': '2026-10-01T20:00:00Z',
                    'body': 'Never print submitted answer', 'url': 'https://example.edu/private-submitted-answer',
                    'assignment': {'id': 88, 'course_id': 101, 'name': 'Synthetic paper', 'published': True,
                                   'points_possible': 0, 'description': 'Never print prompt'},
                    'submission_history': [{'body': 'Never print old answer'}],
                    'submission_comments': [{'id': 41, 'author_id': 8, 'comment': 'Private feedback text',
                                             'created_at': '2026-10-01T18:00:00Z', 'edited_at': '2026-10-03T09:00:00+02:00',
                                             'media_comment': {'url': 'Never print media'},
                                             'attachments': [{'url': 'Never print attachment'}], 'private': 'Never print unknown'}],
                    'rubric_assessment': {'_criterion1': {'rating_id': 'rating1', 'points': 0,
                                                        'comments': 'Private rubric feedback', 'private': 'Never print rubric unknown'}}}
        self.client.list.return_value = [self.row]

    def test_metadata_first_feedback_is_paginated_owned_and_never_includes_submitted_answers(self):
        result = read(self.client, '101', 3, time_zone='America/Los_Angeles')
        item = result['feedback'][0]
        self.assertEqual(item['score'], 0)
        self.assertEqual(item['points_possible'], 0)
        self.assertEqual(item['comment_count'], 1)
        self.assertEqual(item['grade_applicability'], 'earlier_attempt')
        self.assertEqual(item['rubric_assessment'], {'_criterion1': {'rating_id': 'rating1', 'points': 0}})
        self.assertEqual(item['latest_reported_feedback_at'], '2026-10-03T07:00:00+00:00')
        self.assertIn('12:00 AM PDT', item['latest_feedback_display'])
        self.assertNotIn('Private feedback', str(result))
        self.assertNotIn('Private rubric', str(result))
        self.assertNotIn('Never print', str(result))
        self.assertNotIn('private-submitted-answer', str(result))
        self.assertIn('Grade does not match', brief(result))
        self.assertIn('score 0 / 0', brief(result))
        self.client.list.assert_called_once_with('/api/v1/courses/101/students/submissions?'
            'student_ids%5B%5D=7&include%5B%5D=assignment&per_page=100&'
            'include%5B%5D=submission_comments&include%5B%5D=rubric_assessment', 3)
        self.assertTrue(result['complete_for_endpoint'])
        self.assertFalse(result['complete_coursework_inventory'])

    def test_text_opt_in_is_feedback_only_not_history_answers_media_or_attachment_links(self):
        result = read(self.client, '101', include_text=True)
        self.assertIn('Private feedback text', str(result))
        self.assertIn('Private rubric feedback', str(result))
        self.assertNotIn('Never print', str(result))
        self.assertNotIn('private-submitted-answer', str(result))
        self.assertIn('Private rubric feedback', brief(result))
        self.assertIn('may be your own or from peers', result['note'])

    def test_native_reassignment_then_earlier_attempt_then_recent_dates_is_not_work_completion(self):
        base = {**self.row, 'submission_comments': [], 'rubric_assessment': {}}
        self.client.list.return_value = [
            {**base, 'assignment_id': 91, 'assignment': {'id': 91}, 'grade_matches_current_submission': True,
             'graded_at': '2026-10-05T00:00:00Z'},
            {**base, 'assignment_id': 90, 'assignment': {'id': 90}, 'redo_request': True,
             'grade_matches_current_submission': True, 'graded_at': '2026-10-01T00:00:00Z'},
            base,
            {'assignment_id': 92, 'user_id': 7, 'assignment': {'id': 92}, 'score': None,
             'submission_comments': [], 'rubric_assessment': {}},
        ]
        result = read(self.client, '101')
        self.assertEqual([row['assignment_id'] for row in result['feedback']], [90, 88, 91])
        self.assertEqual(result['endpoint_submission_count'], 4)
        self.assertEqual(result['excluded_no_reported_feedback'], 1)
        self.assertIn('reassignment flag', brief(result))
        self.assertFalse(result['complete_coursework_inventory'])

    def test_since_filters_reported_instants_inclusively_and_preserves_uncertain_dates(self):
        self.client.list.return_value = [
            {**self.row, 'submission_comments': [], 'rubric_assessment': {},
             'graded_at': '2026-10-01T00:00:00Z', 'posted_at': None},
            {**self.row, 'assignment_id': 89, 'assignment': {'id': 89}, 'submission_comments': [], 'rubric_assessment': {},
             'graded_at': '2026-10-03T09:00:00+02:00', 'posted_at': None},
            {**self.row, 'assignment_id': 90, 'assignment': {'id': 90}, 'submission_comments': [], 'rubric_assessment': {},
             'graded_at': None, 'posted_at': None},
            {**self.row, 'assignment_id': 91, 'assignment': {'id': 91},
             'graded_at': '2026-10-01T00:00:00Z', 'posted_at': None,
             'submission_comments': [{'id': 44, 'author_id': None, 'created_at': None}]},
        ]
        result = read(self.client, '101', since='2026-10-03T07:00:00Z')
        self.assertEqual({row['assignment_id'] for row in result['feedback']}, {89, 90, 91})
        self.assertEqual(result['excluded_before_since'], 1)
        self.assertEqual(result['included_uncertain_dates'], 2)
        self.assertEqual(result['since'], '2026-10-03T07:00:00+00:00')
        # Latest comment edit can include an otherwise old grade.
        self.client.list.return_value = [self.row]
        self.assertEqual(len(read(self.client, '101', since='2026-10-03T07:00:00Z')['feedback']), 1)

    def test_missing_associations_are_unknown_not_zero_reviews_or_known_empty_rubric(self):
        row = {key: value for key, value in self.row.items() if key not in ('submission_comments', 'rubric_assessment')}
        self.client.list.return_value = [row]
        result = read(self.client, '101')
        item = result['feedback'][0]
        self.assertIsNone(item['comment_count'])
        self.assertFalse(item['comments_reported'])
        self.assertFalse(item['rubric_reported'])
        self.assertIsNone(item['rubric_assessment'])
        self.assertIn('Comments: unknown; rubric criteria: unknown', brief(result))

    def test_hidden_assignments_never_expose_feedback_text_or_rubric_points(self):
        for patch in ({'assignment_visible': False}, {'assignment': {**self.row['assignment'], 'published': False}}):
            self.client.list.return_value = [{**self.row, **patch}]
            item = read(self.client, '101', include_text=True)['feedback'][0]
            self.assertIn('feedback_text_withheld', item)
            self.assertIn('rubric_assessment_withheld', item)
            self.assertIsNone(item['rubric_assessment'])
            self.assertNotIn('Private', str(item))
            self.assertNotIn('Never print', str(item))

    def test_invalid_options_fail_before_any_account_or_submission_requests(self):
        for options in ({'include_text': 1}, {'time_zone': 'invalid/synthetic'}, {'time_zone': None},
                        {'since': ''}, {'since': '2026-10-02'}, {'since': '2026-10-02T12:00:00'},
                        {'since': '2026-02-30T12:00:00Z'}, {'since': True},
                        {'since': '0001-01-01T00:00:00+23:59'}):
            with self.subTest(options=options), self.assertRaises(CanvasError):
                read(self.client, '101', **options)
        self.client.request.assert_not_called()
        self.client.list.assert_not_called()

    def test_malformed_grades_flags_timestamps_and_comments_fail_without_partial_output(self):
        for patch in ({'grade': False}, {'score': True}, {'score': float('inf')},
                      {'grade_matches_current_submission': 0}, {'redo_request': 'true'},
                      {'assignment': {**self.row['assignment'], 'points_possible': True}},
                      {'graded_at': 'not a timestamp'}, {'posted_at': '2026-10-02T12:00:00'},
                      {'submission_comments': [{'id': True}]}, {'submission_comments': [{'id': 0}]},
                      {'submission_comments': [{'id': 41, 'author_id': -1}]},
                      {'submission_comments': [self.row['submission_comments'][0], self.row['submission_comments'][0]]},
                      {'submission_comments': [{'id': 41, 'created_at': 'invalid'}]},
                      {'submission_comments': [{'id': 41, 'comment': {'private': 'never print malformed'}}]}):
            self.client.list.return_value = [self.row, {**self.row, 'assignment_id': 89, 'assignment': {'id': 89}, **patch}]
            with self.subTest(patch=patch), self.assertRaises(CanvasError) as error:
                read(self.client, '101', include_text=True)
            self.assertNotIn('never print malformed', str(error.exception))

    def test_empty_native_inventory_and_access_pagination_failure_never_claim_all_work_done(self):
        self.client.list.return_value = []
        result = read(self.client, '101')
        self.assertEqual(result['feedback'], [])
        self.assertIn('not proof of completed coursework', brief(result))
        for error in (CanvasError('Page limit reached'), CanvasError('Permission denied', status=403)):
            self.client.list.side_effect = error
            with self.assertRaises(CanvasError):
                read(self.client, '101')
