import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from canvas_pocket.client import CanvasError
from canvas_pocket.planning import deadlines


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
        client.list.side_effect = [[{'id': 1}, {'id': 2}], CanvasError('Not accessible'),
                                   [{'id': 22, 'due_at': soon}]]
        result = deadlines(client, 100)
        self.assertEqual(result['unavailable_courses'][0]['course_id'], 1)
        self.assertEqual(result['assignments'][0]['course_id'], 2)
