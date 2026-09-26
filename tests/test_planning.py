import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from canvas_pocket.client import CanvasError
from canvas_pocket.planning import deadlines, work


class PlanningTests(unittest.TestCase):
    def test_sorts_by_instant_not_lexical_timezone(self):
        soon = datetime.now(timezone.utc) + timedelta(days=1)
        client = Mock()
        client.list.side_effect = [
            [{'id': 1, 'name': 'Example'}],
            [{'id': 11, 'name': 'Earlier', 'due_at': soon.isoformat(timespec='seconds')},
             {'id': 12, 'name': 'Later', 'due_at': (soon + timedelta(hours=1)).astimezone(
                 timezone(timedelta(hours=-7))).isoformat(timespec='seconds')}],
        ]
        result = deadlines(client, 100)
        self.assertEqual([a['assignment_id'] for a in result['assignments']], [11, 12])

    def test_reports_unavailable_course_and_keeps_other_deadlines(self):
        soon = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        client = Mock()
        client.list.side_effect = [[{'id': 1}, {'id': 2}], CanvasError('Not accessible', status=403),
                                   [{'id': 22, 'due_at': soon}]]
        result = deadlines(client, 100)
        self.assertEqual(result['unavailable_courses'][0]['course_id'], 1)
        self.assertEqual(result['assignments'][0]['course_id'], 2)

    def test_rate_limit_stops_cross_course_planning(self):
        for command in (deadlines, work):
            with self.subTest(command=command.__name__):
                client = Mock()
                client.list.side_effect = [[{'id': 1}, {'id': 2}],
                                           CanvasError('rate limited', status=429)]
                with self.assertRaises(CanvasError):
                    command(client, 100)
                self.assertEqual(client.list.call_count, 2)

    def test_work_uses_caller_due_date_and_distinguishes_unknown(self):
        soon = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        later = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        client = Mock()
        client.list.side_effect = [
            [{'id': 1, 'name': 'Synthetic course'}],
            [{'id': 11, 'name': 'Paper', 'due_at': later,
              'submission': {'workflow_state': 'graded', 'grade': 'A'}},
             {'id': 12, 'name': 'Discussion', 'due_at': soon,
              'submission': {'workflow_state': 'unsubmitted', 'missing': True}},
             {'id': 13, 'name': 'Lab', 'due_at': None}],
        ]
        result = work(client, 100)
        self.assertEqual([a['assignment_id'] for a in result['assignments']], [12, 11, 13])
        self.assertEqual([a['status'] for a in result['assignments']], ['missing', 'graded', 'unknown'])
        self.assertEqual(client.list.call_args_list[1].args[0],
                         '/api/v1/courses/1/assignments?include%5B%5D=submission&per_page=100')

    def test_work_filters_window_and_status_without_inventing_missing(self):
        soon = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        client = Mock()
        client.list.return_value = [
            {'id': 11, 'due_at': old, 'submission': {'workflow_state': 'unsubmitted'}},
            {'id': 12, 'due_at': soon, 'submission': {'workflow_state': 'unsubmitted'}},
            {'id': 13, 'due_at': soon, 'submission': {'workflow_state': 'submitted'}},
            {'id': 14, 'due_at': None, 'submission': {'workflow_state': 'unsubmitted'}},
        ]
        result = work(client, 100, course_id='5', days=2, status='unsubmitted')
        self.assertEqual([a['assignment_id'] for a in result['assignments']], [12])
        self.assertEqual(result['assignments'][0]['status'], 'unsubmitted')
