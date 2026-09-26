"""Offline, private Markdown projection of a Canvas course snapshot."""

import os
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .client import CanvasError
from .snapshot import validate_destination


class PlainText(HTMLParser):
    BLOCKS = frozenset({'address', 'article', 'blockquote', 'br', 'div', 'h1', 'h2', 'h3',
                        'h4', 'h5', 'h6', 'hr', 'li', 'ol', 'p', 'section', 'table', 'tr', 'ul'})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skipped = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'template'):
            self.skipped += 1
        elif tag in self.BLOCKS and not self.skipped:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'template'):
            self.skipped = max(0, self.skipped - 1)
        elif tag in self.BLOCKS and not self.skipped:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.skipped:
            self.parts.append(data)

    def text(self):
        return '\n'.join(line.strip() for line in ''.join(self.parts).splitlines()
                         if line.strip())


def plain(value):
    if not isinstance(value, str) or not value:
        return ''
    parser = PlainText()
    parser.feed(value)
    return parser.text()


def escaped(value):
    """Keep source text inert in Markdown, including headings, links and images."""
    text = re.sub(r'([\\`*_{}\[\]()#+!>|])', r'\\\1', str(value))
    text = re.sub(r'(?m)^([ \t]*)([-+])(?=\s)', r'\1\\\2', text)
    return re.sub(r'(?m)^([ \t]*\d+)\.(?=\s)', r'\1\\.', text)


def trusted_canvas_link(snapshot, value):
    if not isinstance(value, str):
        return None
    target = urlsplit(value)
    source = urlsplit(snapshot.get('origin', ''))
    if (target.scheme == 'https' and target.netloc == source.netloc and
            not target.username and not target.password and not target.query and
            not target.fragment and target.path.startswith('/courses/') and
            re.fullmatch(r'[A-Za-z0-9/%_.-]+', target.path)):
        return value
    return None


def render(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get('schema_version') != 1:
        raise CanvasError('Unsupported snapshot schema')
    course = snapshot.get('course') or {}
    if not isinstance(course, dict) or any(not isinstance(snapshot.get(kind), list)
                                          for kind in ('assignments', 'modules', 'pages', 'announcements')):
        raise CanvasError('Malformed snapshot content')
    title = escaped(course.get('name') or course.get('course_code') or f"Course {snapshot.get('course_id', '')}")
    lines = [f'# {title}', '', f"Captured: {escaped(snapshot.get('captured_at') or 'unknown')}",
             f"Snapshot complete: {'yes' if snapshot.get('complete') else 'no'}", '']
    unavailable = snapshot.get('unavailable') or {}
    if unavailable:
        lines += ['Some content could not be read from Canvas; this is not a complete course export.',
                  'Unavailable: ' + ', '.join(escaped(k) for k in sorted(unavailable)), '']

    def add_body(value):
        content = plain(value)
        if content:
            lines.extend(escaped(content).split('\n'))
            lines.append('')

    lines += ['## Syllabus', '']
    add_body(course.get('syllabus_body'))
    lines += ['## Assignments', '']
    for item in snapshot['assignments']:
        if not isinstance(item, dict):
            continue
        lines += [f"### {escaped(item.get('name') or item.get('id') or 'Untitled assignment')}", '']
        for label, key in (('Due', 'due_at'), ('Unlocks', 'unlock_at'), ('Locks', 'lock_at'),
                           ('Points', 'points_possible')):
            if item.get(key) is not None:
                lines.append(f'{label}: {escaped(item[key])}')
        link = trusted_canvas_link(snapshot, item.get('html_url'))
        if link:
            lines.append(f'[Open in Canvas]({link})')
        lines.append('')
        add_body(item.get('description'))

    lines += ['## Announcements', '']
    for item in snapshot['announcements']:
        if not isinstance(item, dict):
            continue
        lines += [f"### {escaped(item.get('title') or item.get('id') or 'Untitled announcement')}", '']
        if item.get('posted_at'):
            lines += [f"Posted: {escaped(item['posted_at'])}", '']
        add_body(item.get('message'))

    lines += ['## Modules', '']
    for module in snapshot['modules']:
        if not isinstance(module, dict):
            continue
        lines += [f"### {escaped(module.get('name') or module.get('id') or 'Untitled module')}", '']
        for item in module.get('items') or []:
            if isinstance(item, dict):
                lines.append(f"- {escaped(item.get('title') or item.get('type') or 'Item')}")
        lines.append('')

    lines += ['## Pages', '']
    for page in snapshot['pages']:
        if not isinstance(page, dict):
            continue
        lines += [f"### {escaped(page.get('title') or page.get('url') or 'Untitled page')}", '']
        add_body(page.get('body'))
    return '\n'.join(lines).rstrip() + '\n'


def save(path, markdown):
    target = validate_destination(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(target, flags, 0o600)
    except FileExistsError:
        raise CanvasError('Markdown path already exists; choose a new filename') from None
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(markdown)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return {'saved': str(target), 'bytes': len(markdown.encode('utf-8')),
            'note': 'Private course content; review before sharing.'}
