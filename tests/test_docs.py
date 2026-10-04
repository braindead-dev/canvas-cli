"""Keep public docs navigable and examples aligned with the real parser."""

import io
import re
import shlex
import unittest
from contextlib import redirect_stdout
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

from canvas_cli.arguments import parser

ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    def documents(self):
        return [ROOT / 'README.md', ROOT / 'CAPABILITIES.md', *sorted((ROOT / 'docs').glob('*.md'))]

    def test_readme_stays_a_short_entry_point(self):
        readme = (ROOT / 'README.md').read_text()
        self.assertLessEqual(len(readme.splitlines()), 90)
        self.assertLessEqual(len(readme.split()), 700)
        self.assertIn('docs/getting-started.md', readme)
        self.assertIn('docs/safety.md', readme)
        self.assertIn('docs/development.md', readme)
        self.assertEqual(readme.splitlines()[0], '# Canvas CLI')
        for document in self.documents():
            self.assertNotRegex(document.read_text(), r'(?:^|`)canvas-cli(?:\s|`)', document.name)

    def test_local_markdown_links_and_heading_fragments_resolve(self):
        for document in self.documents():
            text = document.read_text()
            for target in re.findall(r'(?<!!)\[[^\]\n]+\]\(([^\s)]+)\)', text):
                if '://' in target or target.startswith('mailto:'):
                    continue
                path, _, fragment = target.partition('#')
                destination = (document.parent / path).resolve() if path else document
                with self.subTest(document=document.name, link=target):
                    self.assertTrue(destination.is_file(), target)
                    self.assertTrue(destination.is_relative_to(ROOT), target)
                    if fragment:
                        headings = re.findall(r'^#+\s+(.+)$', destination.read_text(), re.MULTILINE)
                        anchors = {re.sub(r'[^\w\- ]', '', heading.lower()).replace(' ', '-')
                                   for heading in headings}
                        self.assertIn(fragment, anchors)

    def test_documents_have_one_title_balanced_fences_and_spaced_headings(self):
        for document in self.documents():
            lines = document.read_text().splitlines()
            with self.subTest(document=document.name):
                self.assertEqual(sum(line.startswith('# ') for line in lines), 1)
                self.assertEqual(sum(line.startswith('```') for line in lines) % 2, 0)
                in_code = False
                for index, line in enumerate(lines):
                    if line.startswith('```'):
                        in_code = not in_code
                    elif not in_code and re.match(r'^#+ ', line):
                        if index:
                            self.assertEqual(lines[index - 1], '')
                        self.assertEqual(lines[index + 1], '')

    @patch('canvas_cli.auth.connect')
    def test_shell_examples_parse_offline_without_authentication(self, connect):
        root = parser()
        examples = 0
        for document in self.documents():
            for block in re.findall(r'```sh\n(.*?)\n```', document.read_text(), re.DOTALL):
                for line in block.splitlines():
                    words = shlex.split(line, comments=True)
                    if not words or words[0] != 'canvas':
                        continue
                    with self.subTest(document=document.name, example=line):
                        if words[1:] == ['--version']:
                            output = io.StringIO()
                            with redirect_stdout(output), self.assertRaises(SystemExit) as result:
                                root.parse_args(words[1:])
                            self.assertEqual(result.exception.code, 0)
                            self.assertEqual(output.getvalue(), 'canvas ' + version('canvas-cli') + '\n')
                        else:
                            root.parse_args(words[1:])
                    examples += 1
        self.assertGreater(examples, 30)
        connect.assert_not_called()
