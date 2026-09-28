import os
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from canvas_pocket.cli import brief, parser, run
from canvas_pocket.client import CanvasError


class CLITests(unittest.TestCase):
    def test_global_options_work_before_or_after_command(self):
        self.assertEqual(parser().parse_args(['--format', 'brief', 'courses']).format, 'brief')
        self.assertEqual(parser().parse_args(['courses', '--format', 'brief']).format, 'brief')
        self.assertEqual(parser().parse_args(['--max-pages', '3', 'courses']).max_pages, 3)
        self.assertEqual(parser().parse_args(['courses', '--max-pages', '3']).max_pages, 3)
        self.assertEqual(parser().parse_args(['--format', 'brief', 'courses']).max_pages, 100)
        self.assertEqual(parser().parse_args(['auth', 'status', '--format', 'brief']).format,
                         'brief')

    @patch.dict(os.environ, {'CANVAS_ORIGIN': 'https://canvas.example.edu', 'CANVAS_TOKEN': 'synthetic'})
    @patch('canvas_pocket.cli.Client')
    def test_post_defaults_to_preview(self, client):
        client.return_value.request.return_value = (
            {'id': 456, 'context_id': 123, 'title': 'Synthetic topic', 'published': True}, '')
        with tempfile.TemporaryDirectory() as folder:
            f = Path(folder) / 'message.txt'
            f.write_text('<script>not HTML</script>\nhello')
            result = run(parser().parse_args(['post', '123', '456', '--message-file', str(f)]))
            self.assertTrue(result['dry_run'])
            self.assertIn('&lt;script&gt;', result['body']['message'])
            client.return_value.request.assert_called_once_with(
                '/api/v1/courses/123/discussion_topics/456')

    @patch.dict(os.environ, {'CANVAS_ORIGIN': 'https://canvas.example.edu', 'CANVAS_TOKEN': 'synthetic'})
    @patch('canvas_pocket.cli.Client')
    def test_explicit_reply_posts_once(self, client):
        topic = {'id': 456, 'context_id': 123, 'title': 'Synthetic topic', 'published': True}
        client.return_value.request.return_value = (topic, '')
        with tempfile.TemporaryDirectory() as folder:
            f = Path(folder) / 'message.txt'
            f.write_text('Synthetic test only')
            command = ['post', '123', '456', '--reply-to', '789', '--message-file', str(f)]
            preview = run(parser().parse_args(command))
            client.return_value.request.reset_mock()
            client.return_value.request.side_effect = [(topic, ''), ({'id': 999}, '')]
            run(parser().parse_args(command + ['--yes', '--confirm', preview['confirm']]))
            client.return_value.request.assert_any_call(
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
    def test_work_validates_window_and_routes_to_caller_submissions(self, client):
        client.return_value.list.return_value = [
            {'id': 7, 'name': 'Synthetic task', 'due_at': None,
             'submission': {'workflow_state': 'submitted'}}]
        result = run(parser().parse_args(['work', '--course', '8', '--status', 'submitted']))
        self.assertEqual(result['assignments'][0]['status'], 'submitted')
        client.return_value.list.assert_called_once_with(
            '/api/v1/courses/8/assignments?include%5B%5D=submission&per_page=100', 100)
        with self.assertRaises(CanvasError):
            run(parser().parse_args(['work', '--days', '0']))

    @patch.dict(os.environ, {'CANVAS_ORIGIN': 'https://canvas.example.edu', 'CANVAS_TOKEN': 'synthetic'})
    @patch('canvas_pocket.cli.Client')
    def test_agenda_routes_read_only_and_brief_shows_local_time(self, client):
        due = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        client.return_value.list.side_effect = [
            [{'id': 8, 'name': 'Example course'}],
            [{'id': 7, 'name': 'Synthetic task', 'due_at': due,
              'submission': {'workflow_state': 'unsubmitted'}}]]
        result = run(parser().parse_args(['agenda', '--course', '8', '--days', '7',
                                          '--timezone', 'UTC']))
        self.assertEqual(result['items'][0]['assignment_id'], 7)
        self.assertEqual(result['items'][0]['course_name'], 'Example course')
        self.assertEqual(result['time_zone'], 'UTC')
        self.assertIn('Synthetic task', brief(result))
        self.assertEqual(client.return_value.list.call_args.args,
                         ('/api/v1/courses/8/assignments?include%5B%5D=submission&per_page=100', 100))
        with self.assertRaises(CanvasError):
            run(parser().parse_args(['agenda', '--days', '0']))

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
    def test_tabs_and_front_page_are_read_only_and_filtered(self, client):
        client.return_value.list.return_value = [
            {'id': 'home', 'label': 'Home', 'html_url': '/courses/8',
             'visibility': 'public', 'position': 1, 'secret': 'not returned'},
            {'id': 'hidden', 'label': 'Hidden', 'hidden': True},
        ]
        tabs = run(parser().parse_args(['tabs', '8']))
        self.assertEqual(tabs, [{'id': 'home', 'label': 'Home',
                                 'html_url': '/courses/8', 'position': 1,
                                 'visibility': 'public'}])
        self.assertEqual(brief(tabs), 'Home  /courses/8')
        client.return_value.list.assert_called_once_with('/api/v1/courses/8/tabs?per_page=100', 100)
        client.return_value.request.return_value = ({'url': 'welcome', 'published': True}, '')
        self.assertEqual(run(parser().parse_args(['front-page', '8']))['url'], 'welcome')
        client.return_value.request.assert_called_once_with('/api/v1/courses/8/front_page')
        client.return_value.request.return_value = ({'url': 'draft', 'published': False}, '')
        with self.assertRaises(CanvasError):
            run(parser().parse_args(['front-page', '8']))

    @patch.dict(os.environ, {'CANVAS_ORIGIN': 'https://canvas.example.edu', 'CANVAS_TOKEN': 'synthetic'})
    @patch('canvas_pocket.cli.Client')
    def test_grading_and_quiz_metadata_routes_are_get_only(self, client):
        client.return_value.list.return_value = [{'id': 3}]
        client.return_value.request.return_value = ({'id': 3}, '')
        for name, route in (
            ('assignment-groups', 'assignment_groups'), ('rubrics', 'rubrics'),
            ('quizzes', 'quizzes')):
            with self.subTest(name=name):
                self.assertEqual(run(parser().parse_args([name, '8'])), [{'id': 3}])
                self.assertEqual(client.return_value.list.call_args.args,
                                 (f'/api/v1/courses/8/{route}?per_page=100', 100))
        for name, route in (
            ('assignment-group', 'assignment_groups'), ('rubric', 'rubrics'),
            ('quiz', 'quizzes')):
            with self.subTest(name=name):
                self.assertEqual(run(parser().parse_args([name, '8', '3'])), {'id': 3})
                client.return_value.request.assert_called_with(f'/api/v1/courses/8/{route}/3')
        self.assertEqual(run(parser().parse_args(['new-quizzes', '8'])), [{'id': 3}])
        client.return_value.list.assert_called_with(
            '/api/quiz/v1/courses/8/quizzes?per_page=100', 100)
        self.assertEqual(run(parser().parse_args(['new-quiz', '8', '3'])), {'id': 3})
        client.return_value.request.assert_called_with('/api/quiz/v1/courses/8/quizzes/3')

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

    @patch.dict(os.environ, {'CANVAS_ORIGIN': 'https://canvas.example.edu', 'CANVAS_TOKEN': 'synthetic'})
    @patch('canvas_pocket.cli.Client')
    def test_inbox_reply_requires_preview_digest_and_stable_audience(self, client):
        thread = {'id': 9, 'subject': 'Synthetic thread',
                  'participants': [{'id': 7, 'name': 'Recipient'}], 'audience': [7]}
        client.return_value.request.return_value = (thread, '')
        with tempfile.TemporaryDirectory() as folder:
            message = Path(folder) / 'reply.txt'
            message.write_text('Synthetic response')
            command = ['inbox-reply', '9', '--message-file', str(message)]
            preview = run(parser().parse_args(command))
            self.assertTrue(preview['dry_run'])
            self.assertEqual(preview['body'], {'body': 'Synthetic response'})
            client.return_value.request.assert_called_once_with(
                '/api/v1/conversations/9?auto_mark_as_read=false')
            with self.assertRaisesRegex(CanvasError, 'both --yes and --confirm'):
                run(parser().parse_args(command + ['--yes']))
            client.return_value.request.reset_mock()
            changed = {**thread, 'audience': [7, 8]}
            client.return_value.request.return_value = (changed, '')
            with self.assertRaisesRegex(CanvasError, 'Preview changed'):
                run(parser().parse_args(command + ['--yes', '--confirm', preview['confirm']]))
            client.return_value.request.assert_called_once_with(
                '/api/v1/conversations/9?auto_mark_as_read=false')
            client.return_value.request.side_effect = [(thread, ''), ({'id': 9}, '')]
            sent = run(parser().parse_args(command + ['--yes', '--confirm', preview['confirm']]))
            self.assertEqual(sent['id'], 9)
            self.assertEqual(client.return_value.request.call_args.args,
                             ('/api/v1/conversations/9/add_message', 'POST',
                              {'body': 'Synthetic response'}))


if __name__ == '__main__': unittest.main()
