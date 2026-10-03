import unittest
from unittest.mock import Mock

from canvas_pocket.cli import brief
from canvas_pocket.client import CanvasError
from canvas_pocket.peer_reviews import read


class PeerReviewTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.assignment = {'id': 88, 'course_id': 101, 'name': 'Synthetic assignment', 'published': True}
        self.received = {'id': 61, 'asset_id': 41, 'asset_type': 'Submission', 'user_id': 7,
                         'assessor_id': 9, 'workflow_state': 'assigned'}
        self.outgoing = {**self.received, 'id': 62, 'user_id': 9, 'assessor_id': 7}
        self.client.request.side_effect = [({'id': 7}, ''), (self.assignment, '')]
        self.client.list.return_value = [self.received, self.outgoing]

    def test_default_scope_reports_reviews_of_own_work_not_complete_owed_tasks(self):
        data = read(self.client, '101', '88', 3)
        self.assertEqual([row['id'] for row in data['peer_reviews']], [61])
        self.assertTrue(data['peer_reviews'][0]['about_own_submission'])
        self.assertFalse(data['peer_reviews'][0]['assigned_to_self'])
        self.assertEqual(data['excluded_by_scope'], 1)
        self.assertFalse(data['owed_review_inventory_complete'])
        self.assertIn('reviews OF your work', data['note'])
        self.client.list.assert_called_once_with('/api/v1/courses/101/assignments/88/peer_reviews?per_page=100', 3)
        self.assertEqual(self.client.request.call_count, 2)

    def test_visible_scope_and_associations_are_explicit_without_read_status(self):
        self.received.update({'submission_comments': [{'comment': 'Synthetic feedback'}],
                              'user': {'id': 7}, 'assessor': {'id': 9}})
        data = read(self.client, '101', '88', scope='visible', comments=True, users=True)
        self.assertEqual(len(data['peer_reviews']), 2)
        self.assertTrue(data['peer_reviews'][1]['assigned_to_self'])
        self.assertEqual(data['peer_reviews'][0]['submission_comments'][0]['comment'], 'Synthetic feedback')
        self.client.list.assert_called_with('/api/v1/courses/101/assignments/88/peer_reviews?per_page=100&include%5B%5D=submission_comments&include%5B%5D=user', 100)
        self.assertIn('assessor 9', brief(data))
        self.assertNotIn('Synthetic feedback', brief(data))

    def test_anonymous_assessor_is_never_inferred_or_recovered(self):
        anonymous = {key: value for key, value in self.received.items() if key != 'assessor_id'}
        anonymous['assessor'] = {'id': 9, 'name': 'Not to disclose without assessor identity'}
        self.client.list.return_value = [anonymous]
        data = read(self.client, '101', '88', users=True)
        self.assertNotIn('assessor_id', data['peer_reviews'][0])
        self.assertNotIn('assessor', data['peer_reviews'][0])
        self.assertIsNone(data['peer_reviews'][0]['assigned_to_self'])
        self.assertIn('hidden/unknown', brief(data))
        self.assertNotIn('Not to disclose', str(data))
        self.assertEqual(self.client.request.call_count, 2)

    def test_optional_associations_are_not_echoed_when_not_requested(self):
        self.received.update({'submission_comments': [{'comment': 'Not requested'}],
                              'assessor': {'id': 9}, 'user': {'id': 7}})
        data = read(self.client, '101', '88')
        self.assertNotIn('submission_comments', data['peer_reviews'][0])
        self.assertNotIn('assessor', data['peer_reviews'][0])
        self.assertNotIn('user', data['peer_reviews'][0])

    def test_unpublished_locked_or_wrong_assignment_stops_before_review_read(self):
        for assignment in ({**self.assignment, 'published': False}, {**self.assignment, 'locked_for_user': True},
                           {**self.assignment, 'id': 89}, {**self.assignment, 'id': '88'},
                           {**self.assignment, 'course_id': 102}):
            with self.subTest(assignment=assignment):
                self.client.request.side_effect = [({'id': 7}, ''), (assignment, '')]
                self.client.list.reset_mock()
                with self.assertRaises(CanvasError):
                    read(self.client, '101', '88')
                self.client.list.assert_not_called()

    def test_duplicate_or_malformed_review_ids_refuse_output(self):
        for rows in ([self.received, self.received], [None], [{**self.received, 'id': True}],
                     [{**self.received, 'user_id': '7'}], [{**self.received, 'asset_id': 0}],
                     [{**self.received, 'assessor_id': True}]):
            with self.subTest(rows=rows):
                self.client.request.side_effect = [({'id': 7}, ''), (self.assignment, '')]
                self.client.list.return_value = rows
                with self.assertRaises(CanvasError):
                    read(self.client, '101', '88')

    def test_empty_scope_does_not_claim_no_owed_reviews(self):
        self.client.list.return_value = []
        data = read(self.client, '101', '88')
        self.assertTrue(data['complete_for_endpoint'])
        self.assertFalse(data['owed_review_inventory_complete'])
        self.assertIn('does not prove', brief(data))

    def test_invalid_options_fail_before_network(self):
        self.client.request.reset_mock()
        for kwargs in ({'scope': 'owed'}, {'comments': 1}, {'users': 'true'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                read(self.client, '101', '88', **kwargs)
        for number in ('0', '01', '١', '1/../2', None, True):
            with self.subTest(number=number), self.assertRaises(CanvasError):
                read(self.client, number, '88')
        self.client.request.assert_not_called()
