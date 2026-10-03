"""Bounded explicit text-file inputs, with no private data in diagnostics."""

from .client import CanvasError


def read_utf8(path, *, label, max_bytes=40000):
    with path.open('rb') as source:
        content = source.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise CanvasError(f'{label} file exceeds local UTF-8 size bounds')
    try:
        return content.decode('utf-8')
    except UnicodeError:
        raise CanvasError(f'{label} file must be UTF-8 text') from None
