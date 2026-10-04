"""Bounded explicit UTF-8 inputs and inert human-facing terminal text."""

import html

from .client import CanvasError

TERMINAL_ESCAPES = {
    code: f'\\u{code:04x}' for code in (
        *range(32), *range(0x7f, 0xa0), *range(0xd800, 0xe000),
        0x061c, 0x200e, 0x200f, *range(0x202a, 0x202f), *range(0x2066, 0x206a)
    ) if code not in (9, 10)
}


def html_body(text):
    """Plain text becomes inert rich text; an empty input stays explicitly empty."""
    return '<p>' + html.escape(text).replace('\n', '<br>') + '</p>' if text else ''


def terminal_safe(value):
    """Expose controls/bidi overrides/surrogates, preserving ordinary Unicode, tabs and lines."""
    return value.translate(TERMINAL_ESCAPES)


def read_utf8(path, *, label, max_bytes=40000):
    with path.open('rb') as source:
        content = source.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise CanvasError(f'{label} file exceeds local UTF-8 size bounds')
    try:
        return content.decode('utf-8')
    except UnicodeError:
        raise CanvasError(f'{label} file must be UTF-8 text') from None
