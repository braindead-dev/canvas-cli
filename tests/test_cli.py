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


if __name__ == '__main__': unittest.main()
