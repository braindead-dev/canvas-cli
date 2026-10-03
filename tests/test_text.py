"""Shared bounded UTF-8 inputs, not implicit credential or browser imports."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from canvas_cli.client import CanvasError
from canvas_cli.text import read_utf8


class TextInputTests(unittest.TestCase):
    def test_text_is_reread_and_empty_is_an_explicit_value(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'input.txt'
            for value in ('Synthetic text', '', 'Changed synthetic text \u2603'):
                path.write_text(value, encoding='utf-8')
                self.assertEqual(read_utf8(path, label='Test'), value)

    def test_byte_limit_bounds_the_read_before_decoding_and_does_not_print_input(self):
        source = io.BytesIO(b'Synthetic private content')
        path = Mock()
        path.open.return_value = source
        with self.assertRaisesRegex(CanvasError, 'Test file exceeds') as caught:
            read_utf8(path, label='Test', max_bytes=5)
        self.assertNotIn('private', str(caught.exception))
        self.assertTrue(source.closed)
        source = io.BytesIO(b'abcde')
        path.open.return_value = source
        self.assertEqual(read_utf8(path, label='Test', max_bytes=5), 'abcde')

    def test_invalid_utf8_has_only_a_safe_field_label(self):
        path = Mock()
        path.open.return_value = io.BytesIO(b'\xffSynthetic private content')
        with self.assertRaisesRegex(CanvasError, 'Test file must be UTF-8 text') as caught:
            read_utf8(path, label='Test')
        self.assertNotIn('private', str(caught.exception))
