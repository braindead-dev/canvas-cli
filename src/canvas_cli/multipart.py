"""Bounded native attachment forms; no caller-supplied headers or credentials."""

import re
import secrets

from .client import CanvasError

MAX_BYTES = 25 * 1024 * 1024


def inspect_file(source, max_bytes):
    """Shared private byte capture for native prompt and entry attachment commands."""
    from .upload import file_info, staged_file
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_BYTES:
        raise CanvasError('Native multipart files must fit a positive byte limit within 25 MiB')
    info = file_info(source, max_bytes)
    filename(info['name'], info['content_type'])
    with staged_file(info, max_bytes) as staged:
        content = staged.read(max_bytes + 1)
    return info, content


def filename(name, content_type):
    try:
        valid = (isinstance(name, str) and name not in ('', '.', '..') and len(name.encode('utf-8')) <= 255 and
                 not any(char in name for char in '/\\"') and
                 not any(ord(char) < 32 or 127 <= ord(char) < 160 for char in name) and
                 isinstance(content_type, str) and len(content_type) <= 255 and
                 re.fullmatch(r'[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+', content_type))
    except UnicodeError:
        valid = False
    if not valid:
        raise CanvasError('Attachment needs a bounded UTF-8 basename and plain media type; no private filename logged')


def encode(fields, name, content_type, content):
    filename(name, content_type)
    if not isinstance(fields, dict) or len(fields) > 16 or type(content) is not bytes or not 0 < len(content) <= MAX_BYTES:
        raise CanvasError('Attachment form must contain bounded fields and nonempty bytes within 25 MiB')
    values = []
    try:
        for key, value in fields.items():
            if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', key) or key == 'attachment':
                raise ValueError
            if type(value) is bool:
                value = str(value).lower()
            if not isinstance(value, str) or '\x00' in value or len(value.encode('utf-8')) > 40000:
                raise ValueError
            values.append((key, value.encode('utf-8')))
    except (ValueError, UnicodeError):
        raise CanvasError('Attachment form has unsupported fields; no private content logged') from None
    boundary = 'canvas-' + secrets.token_hex(24)
    marker = boundary.encode('ascii')
    # Random framing is not part of confirmation. Refuse a collision rather than
    # interpreting file bytes as another part or retrying an ambiguous request.
    if marker in content or any(marker in value for _, value in values):
        raise CanvasError('Attachment form boundary collision; no request was sent')
    parts = [b'--' + marker + b'\r\nContent-Disposition: form-data; name="' + key.encode('ascii') +
             b'"\r\n\r\n' + value + b'\r\n' for key, value in values]
    parts.append(b'--' + marker + b'\r\nContent-Disposition: form-data; name="attachment"; filename="' +
                 name.encode('utf-8') + b'"\r\nContent-Type: ' + content_type.encode('ascii') + b'\r\n\r\n' +
                 content + b'\r\n--' + marker + b'--\r\n')
    return b''.join(parts), 'multipart/form-data; boundary=' + boundary
