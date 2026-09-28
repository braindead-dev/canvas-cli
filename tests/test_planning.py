import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from canvas_pocket.client import CanvasError
from canvas_pocket.planning import agenda, deadlines, work


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

    def test_agenda_keeps_undated_separate_and_uses_dst_at_due_time(self):
        now = datetime(2026, 10, 31, 17, tzinfo=timezone.utc)
        client = Mock()
        client.list.side_effect = [
            [{'id': 8, 'name': 'Synthetic course'}],
            [{'id': 1, 'name': 'Due after DST shift', 'due_at': '2026-11-01T09:00:00Z',
              'html_url': 'https://canvas.example.edu/courses/8/assignments/1',
              'submission': {'workflow_state': 'unsubmitted'}},
             {'id': 2, 'name': 'Submitted', 'due_at': '2026-11-01T08:00:00Z',
              'submission': {'workflow_state': 'submitted'}},
             {'id': 3, 'name': 'Undated'},
             {'id': 4, 'name': 'Future', 'due_at': '2026-12-01T00:00:00Z',
              'submission': {'workflow_state': 'unsubmitted'}}],
        ]
        result = agenda(client, 100, days=14, time_zone='America/Los_Angeles',
                        include_undated=True, now=now)
        self.assertEqual([item['assignment_id'] for item in result['items']], [1])
        self.assertEqual(result['items'][0]['due_local'], '2026-11-01T01:00:00-08:00')
        self.assertEqual(result['items'][0]['urgency'], 'next_72h')
        self.assertEqual(result['undated_count'], 1)
        self.assertEqual(result['undated'][0]['assignment_id'], 3)

    def test_agenda_marks_overdue_closed_and_unknown_without_claiming_submission(self):
        now = datetime(2026, 9, 27, 20, tzinfo=timezone.utc)
        client = Mock()
        client.list.side_effect = [
            [{'id': 8}],
            [{'id': 1, 'name': 'Late', 'due_at': '2026-09-26T20:00:00Z',
              'lock_at': '2026-09-27T19:00:00Z'},
             {'id': 2, 'name': 'Next', 'due_at': '2026-09-28T20:00:00Z',
              'unlock_at': '2026-09-29T00:00:00Z',
              'submission': {'workflow_state': 'unsubmitted'}}],
        ]
        result = agenda(client, 100, now=now, time_zone='UTC')
        self.assertEqual([item['urgency'] for item in result['items']], ['overdue', 'next_72h'])
        self.assertEqual(result['items'][0]['status'], 'unknown')
        self.assertEqual(result['items'][0]['availability'], 'closed')
        self.assertEqual(result['items'][1]['availability'], 'not_yet_open')
        self.assertIsNone(result['undated'])
        with self.assertRaisesRegex(CanvasError, 'Unknown IANA time zone'):
            agenda(Mock(), 100, time_zone='No/Such_Zone', now=now)

    def test_agenda_selects_multiple_courses_once_each(self):
        now = datetime(2026, 9, 27, 20, tzinfo=timezone.utc)
        client = Mock()
        client.list.side_effect = [
            [{'id': 8, 'name': 'First course'}, {'id': 9, 'name': 'Second course'}],
            [{'id': 1, 'name': 'First', 'due_at': '2026-09-29T20:00:00Z',
              'submission': {'workflow_state': 'unsubmitted'}}],
            [{'id': 2, 'name': 'Second', 'due_at': '2026-09-28T20:00:00Z',
              'submission': {'workflow_state': 'unsubmitted'}}],
        ]
        result = agenda(client, 100, now=now, time_zone='UTC',
                        course_ids=['8', '9', '8'])
        self.assertEqual([item['course_id'] for item in result['items']], ['9', '8'])
        self.assertEqual([item['course_name'] for item in result['items']],
                         ['Second course', 'First course'])
        self.assertEqual(client.list.call_count, 3)
