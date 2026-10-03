import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from canvas_cli.client import CanvasError
from canvas_cli.news import announcement_feed


class NewsTests(unittest.TestCase):
    def test_cross_course_feed_sorts_and_preserves_full_body(self):
        client = Mock()
        client.list.side_effect = [
            [{'id': 1, 'name': 'Course A'}, {'id': 2, 'name': 'Course B'}],
            [{'id': 11, 'title': 'Older', 'message': '<p>Example</p>',
              'posted_at': '2026-09-24T10:00:00-07:00'}],
            [{'id': 12, 'title': 'Newer', 'message': '<p>Second</p>',
              'posted_at': '2026-09-24T18:00:00Z'}],
        ]
        result = announcement_feed(client, 100, 7)
        self.assertEqual([a['id'] for a in result['announcements']], [12, 11])
        self.assertEqual(result['announcements'][0]['course_name'], 'Course B')
        self.assertEqual(result['announcements'][1]['message'], '<p>Example</p>')
        url = client.list.call_args_list[1].args[0]
        parsed = parse_qs(urlsplit(url).query)
        self.assertEqual(parsed['context_codes[]'], ['course_1'])
        self.assertEqual(parsed['active_only'], ['true'])
        self.assertEqual(parsed['per_page'], ['100'])
        self.assertLessEqual(datetime.fromisoformat(parsed['end_date'][0]) -
                             datetime.fromisoformat(parsed['start_date'][0]), timedelta(days=7))

    def test_unavailable_course_is_reported_without_hiding_others(self):
        client = Mock()
        client.list.side_effect = [[{'id': 1}, {'id': 2}], CanvasError('Not accessible', status=403),
                                   [{'id': 22, 'posted_at': '2026-09-24T00:00:00Z'}]]
        result = announcement_feed(client, 100)
        self.assertEqual(result['unavailable_courses'][0]['course_id'], 1)
        self.assertEqual(result['announcements'][0]['id'], 22)

    def test_rate_limit_is_not_reported_as_unavailable_course(self):
        client = Mock()
        client.list.side_effect = [[{'id': 1}, {'id': 2}],
                                   CanvasError('rate limited', status=429)]
        with self.assertRaises(CanvasError):
            announcement_feed(client, 100)
        self.assertEqual(client.list.call_count, 2)

    def test_selected_courses_are_deduplicated(self):
        client = Mock()
        client.list.return_value = []
        announcement_feed(client, 100, course_ids=['3', '3', '4'])
        self.assertEqual(client.list.call_count, 2)


if __name__ == '__main__': unittest.main()
