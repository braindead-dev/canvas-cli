from contextlib import redirect_stderr
from io import StringIO
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from canvas_pocket.cli import parser, run
from canvas_pocket.client import CanvasError


class CLITests(unittest.TestCase):
    @patch.dict(os.environ, {'CANVAS_ORIGIN': 'https://canvas.example.edu', 'CANVAS_TOKEN': 'synthetic'})
    @patch('canvas_pocket.cli.Client')
    def test_post_defaults_to_preview(self, client):
        with tempfile.TemporaryDirectory() as folder:
            f = Path(folder) / 'message.txt'
            f.write_text('<script>not HTML</script>\nhello')
            result = run(parser().parse_args(['post', '123', '456', '--message-file', str(f)]))
            self.assertTrue(result['dry_run'])
            self.assertIn('&lt;script&gt;', result['body']['message'])
            client.return_value.request.assert_not_called()

    @patch.dict(os.environ, {'CANVAS_ORIGIN': 'https://canvas.example.edu', 'CANVAS_TOKEN': 'synthetic'})
    @patch('canvas_pocket.cli.Client')
    def test_explicit_reply_posts_once(self, client):
        client.return_value.request.return_value = ({'id': 999}, '')
        with tempfile.TemporaryDirectory() as folder:
            f = Path(folder) / 'message.txt'
            f.write_text('Synthetic test only')
            run(parser().parse_args(['post', '123', '456', '--reply-to', '789', '--message-file', str(f), '--yes']))
            client.return_value.request.assert_called_once_with(
                '/api/v1/courses/123/discussion_topics/456/entries/789/replies',
                'POST', {'message': '<p>Synthetic test only</p>'})

    @patch.dict(os.environ, {'CANVAS_ORIGIN': 'https://canvas.example.edu', 'CANVAS_TOKEN': 'synthetic'})
    @patch('canvas_pocket.cli.Client')
    def test_overview_uses_active_courses_and_preserves_upcoming(self, client):
        due = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        client.return_value.list.side_effect = [
            [{'id': 123, 'name': 'Example', 'course_code': 'EX 1', 'workflow_state': 'available', 'private_field': 'omit'}],
            [{'id': 55, 'title': 'Upcoming synthetic assignment'}],
            [{'id': 77}],
            [{'id': 88, 'name': 'Paper', 'due_at': due}],
        ]
        result = run(parser().parse_args(['overview']))
        self.assertEqual(result['courses'], [{'id': 123, 'name': 'Example', 'course_code': 'EX 1', 'workflow_state': 'available'}])
        self.assertEqual(result['upcoming'][0]['id'], 55)
        self.assertEqual(result['todo'][0]['id'], 77)
        self.assertEqual(result['deadlines']['assignments'][0]['assignment_id'], 88)
        self.assertEqual(client.return_value.list.call_args_list[0].args[0],
                         '/api/v1/courses?enrollment_state=active&per_page=100')

    @patch.dict(os.environ, {'CANVAS_ORIGIN': 'https://canvas.example.edu', 'CANVAS_TOKEN': 'synthetic'})
    @patch('canvas_pocket.cli.Client')
    def test_calendar_contexts_and_dates_are_explicit(self, client):
        client.return_value.list.side_effect = [
            [{'id': 8}, {'id': 9}], [{'id': 44, 'title': 'Synthetic event'}]]
        client.return_value.request.return_value = ({'id': 7}, '')
        result = run(parser().parse_args(['calendar', '--start', '2026-09-25', '--end', '2026-09-30',
                                          '--active', '--course', '8', '--personal']))
        self.assertEqual(result[0]['id'], 44)
        self.assertEqual(client.return_value.list.call_args_list[-1].args[0],
                         '/api/v1/calendar_events?type=event&start_date=2026-09-25&end_date=2026-09-30&per_page=100&context_codes%5B%5D=course_8&context_codes%5B%5D=course_9&context_codes%5B%5D=user_7')
        with self.assertRaises(CanvasError):
            run(parser().parse_args(['calendar', '--start', '2026-09-30', '--end', '2026-09-25']))
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser().parse_args(['calendar', '--start', '20260925'])

    @patch.dict(os.environ, {'CANVAS_ORIGIN': 'https://canvas.example.edu', 'CANVAS_TOKEN': 'synthetic'})
    @patch('canvas_pocket.cli.Client')
    def test_grades_only_returns_own_course_enrollment(self, client):
        client.return_value.request.return_value = ({'id': 7}, '')
        client.return_value.list.return_value = [{'user_id': 7, 'course_id': 8, 'grades': {'current_score': 90}}]
        result = run(parser().parse_args(['grades', '8']))
        self.assertEqual(result[0]['grades']['current_score'], 90)
        client.return_value.list.assert_called_once_with('/api/v1/courses/8/enrollments?user_id=7&per_page=100', 100)
        client.return_value.list.return_value = [{'user_id': 99, 'course_id': 8}]
        with self.assertRaises(CanvasError):
            run(parser().parse_args(['grades', '8']))

    @patch.dict(os.environ, {'CANVAS_ORIGIN': 'https://canvas.example.edu', 'CANVAS_TOKEN': 'synthetic'})
    @patch('canvas_pocket.cli.Client')
    def test_folder_and_outline_routes_are_read_only(self, client):
        client.return_value.list.side_effect = [
            [{'id': 4, 'name': 'Week 1'}], [{'id': 5, 'title': 'Page'}], [{'id': 2, 'name': 'Docs'}]]
        result = run(parser().parse_args(['outline', '8']))
        self.assertEqual(result[0]['items'][0]['title'], 'Page')
        self.assertEqual(client.return_value.list.call_args_list[1].args[0],
                         '/api/v1/courses/8/modules/4/items?per_page=100')
        run(parser().parse_args(['folder-files', '2']))
        self.assertEqual(client.return_value.list.call_args_list[2].args[0],
                         '/api/v1/folders/2/files?per_page=100')
        client.return_value.request.assert_not_called()

    @patch.dict(os.environ, {'CANVAS_ORIGIN': 'https://canvas.example.edu', 'CANVAS_TOKEN': 'synthetic'})
    @patch('canvas_pocket.cli.Client')
    def test_inbox_and_group_routes(self, client):
        client.return_value.list.return_value = []
        client.return_value.request.return_value = ({'id': 9}, '')
        run(parser().parse_args(['inbox', '--scope', 'unread', '--course', '8']))
        self.assertEqual(client.return_value.list.call_args.args[0],
                         '/api/v1/conversations?per_page=100&scope=unread&filter%5B%5D=course_8')
        run(parser().parse_args(['conversation', '9']))
        client.return_value.request.assert_called_with(
            '/api/v1/conversations/9?auto_mark_as_read=false')
        run(parser().parse_args(['groups']))
        self.assertEqual(client.return_value.list.call_args.args[0],
                         '/api/v1/users/self/groups?per_page=100')
        run(parser().parse_args(['favorites']))
        self.assertEqual(client.return_value.list.call_args.args[0],
                         '/api/v1/users/self/favorites/courses?per_page=100')


if __name__ == '__main__': unittest.main()
