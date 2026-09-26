import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from canvas_pocket.client import CanvasError
from canvas_pocket.cli import parser, run
from canvas_pocket.markdown import render, save


class MarkdownTests(unittest.TestCase):
    def fixture(self):
        return {
            'schema_version': 1, 'origin': 'https://canvas.example.edu',
            'course_id': 12, 'captured_at': '2026-09-25T00:00:00Z',
            'complete': False, 'unavailable': {'pages': 'Not available'},
            'course': {'name': 'Synthetic # Course',
                       'syllabus_body': '<p>Read the outline.</p><script>do_not_render()</script>'},
            'assignments': [{'id': 3, 'name': 'Paper [draft]',
                             'description': '<p>Write ![image](https://evil.example/pixel)</p>',
                             'due_at': '2026-10-01T00:00:00Z',
                             'html_url': 'https://canvas.example.edu/courses/12/assignments/3'}],
            'announcements': [{'id': 4, 'title': 'Welcome',
                               'posted_at': '2026-09-25T00:00:00Z',
                               'message': '<p>Hello &amp; welcome.</p>'}],
            'modules': [{'id': 5, 'name': 'Week 1', 'items': [{'title': 'Introduction'}]}],
            'pages': [{'url': 'intro', 'title': 'Start',
                       'body': '<style>.hidden{}</style><p>First page.</p>'}],
        }

    def test_render_is_readable_and_inert(self):
        text = render(self.fixture())
        self.assertIn('# Synthetic \\# Course', text)
        self.assertIn('Due: 2026-10-01T00:00:00Z', text)
        self.assertIn('[Open in Canvas](https://canvas.example.edu/courses/12/assignments/3)', text)
        self.assertIn('Hello & welcome', text)
        self.assertIn('Some content could not be read', text)
        self.assertNotIn('do_not_render', text)
        self.assertNotIn('.hidden', text)
        self.assertNotIn('![image]', text)
        self.assertIn('\\!\\[image\\]', text)
        self.assertIn('- Introduction', text)

    def test_malicious_or_signed_links_are_omitted(self):
        source = self.fixture()
        for url in ('https://canvas.example.edu/courses/12/assignments/3?token=secret',
                    'https://evil.example/courses/12/assignments/3',
                    'https://canvas.example.edu/courses/12/x)![image](https://evil.example)'):
            with self.subTest(url=url):
                source['assignments'][0]['html_url'] = url
                self.assertNotIn('[Open in Canvas]', render(source))

    def test_save_private_and_offline_cli(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'snapshot.json'
            source.write_text(json.dumps(self.fixture()))
            destination = root / 'course.md'
            with patch.dict(os.environ, {'CANVAS_ORIGIN': '', 'CANVAS_TOKEN': ''}), \
                 patch('canvas_pocket.cli.Client') as client:
                result = run(parser().parse_args(
                    ['snapshot-markdown', str(source), '--output', str(destination)]))
                client.assert_not_called()
            self.assertEqual(result['saved'], str(destination.resolve()))
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertIn('## Assignments', destination.read_text())
            with self.assertRaises(CanvasError):
                save(destination, 'Cannot overwrite')
            (root / '.git').mkdir()
            with self.assertRaises(CanvasError):
                save(root / 'another.md', 'No Git export')


if __name__ == '__main__': unittest.main()
