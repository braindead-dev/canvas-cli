import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from canvas_pocket.cli import parser, run


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
        client.return_value.list.side_effect = [
            [{'id': 123, 'name': 'Example', 'course_code': 'EX 1', 'workflow_state': 'available', 'private_field': 'omit'}],
            [{'id': 55, 'title': 'Upcoming synthetic assignment'}],
            [{'id': 77}],
        ]
        result = run(parser().parse_args(['overview']))
        self.assertEqual(result['courses'], [{'id': 123, 'name': 'Example', 'course_code': 'EX 1', 'workflow_state': 'available'}])
        self.assertEqual(result['upcoming'][0]['id'], 55)
        self.assertEqual(result['todo'][0]['id'], 77)
        self.assertEqual(client.return_value.list.call_args_list[0].args[0],
                         '/api/v1/courses?enrollment_state=active&per_page=100')


if __name__ == '__main__': unittest.main()
