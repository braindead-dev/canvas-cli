"""Shared bounded UTF-8 inputs, not implicit credential or browser imports."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from canvas_cli.client import CanvasError
from canvas_cli.text import read_utf8, terminal_safe


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


class TextOutputTests(unittest.TestCase):
    def test_every_c0_del_and_c1_control_is_visible_except_tabs_and_newlines(self):
        for code in (*range(32), *range(0x7f, 0xa0)):
            character = chr(code)
            expected = character if code in (9, 10) else f'\\u{code:04x}'
            with self.subTest(code=code):
                self.assertEqual(terminal_safe(character), expected)

    def test_ansi_color_cursor_clear_title_hyperlink_and_clipboard_controls_are_inert(self):
        sequences = ('\x1b[31mRed\x1b[0m', '\x1b[2J\x1b[H', '\x1b]0;Synthetic title\x07',
                     '\x1b]8;;https://example.org\x1b\\Link\x1b]8;;\x1b\\',
                     '\x1b]52;c;U3ludGhldGlj\x07', '\x9b2J\x9d52;c;U3ludGhldGlj\x9c')
        for sequence in sequences:
            result = terminal_safe(sequence)
            with self.subTest(sequence=sequence):
                self.assertFalse(any(ord(char) < 32 and char not in '\t\n' or 0x7f <= ord(char) <= 0x9f for char in result))
                self.assertIn('\\u', result)

    def test_bidi_controls_and_isolates_are_visible_not_silently_reordered(self):
        for code in (0x061c, 0x200e, 0x200f, *range(0x202a, 0x202f), *range(0x2066, 0x206a)):
            with self.subTest(code=code):
                self.assertEqual(terminal_safe('Left' + chr(code) + 'Right'), f'Left\\u{code:04x}Right')

    def test_multilingual_text_combining_characters_emoji_joiners_and_layout_are_preserved(self):
        text = 'English\t中文 العربية עברית\nCafe\u0301 👩\u200d💻 ❤️\ufe0f\n'
        self.assertEqual(terminal_safe(text), text)
        self.assertEqual(terminal_safe(''), '')

    def test_surrogate_codepoints_render_as_visible_escapes_and_output_is_utf8(self):
        for code in range(0xd800, 0xe000):
            result = terminal_safe(chr(code))
            self.assertEqual(result, f'\\u{code:04x}')
            self.assertEqual(result.encode('utf-8').decode('utf-8'), result)

    def test_visible_literal_escapes_are_preserved_and_sanitization_is_idempotent(self):
        text = 'Literal \\u001b; control \x1b; backslash \\; carriage return \r'
        result = terminal_safe(text)
        self.assertEqual(terminal_safe(result), result)
        self.assertEqual(result.count('\\u001b'), 2)
        self.assertIn('carriage return \\u000d', result)
