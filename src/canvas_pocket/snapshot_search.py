"""Offline full-text search over an already-exported private course snapshot."""

import re

from .client import CanvasError
from .markdown import plain


def _documents(snapshot):
    course = snapshot.get('course') or {}
    if isinstance(course, dict):
        yield 'syllabus', snapshot.get('course_id'), 'Syllabus', course.get('syllabus_body')
    for kind, title_key, body_key, id_key in (
            ('assignment', 'name', 'description', 'id'),
            ('announcement', 'title', 'message', 'id'),
            ('page', 'title', 'body', 'url')):
        for item in snapshot.get(kind + 's', []):
            if isinstance(item, dict):
                yield kind, item.get(id_key), item.get(title_key) or '', item.get(body_key)
    for module in snapshot.get('modules', []):
        if not isinstance(module, dict):
            continue
        yield 'module', module.get('id'), module.get('name') or '', ''
        for item in module.get('items') or []:
            if isinstance(item, dict):
                yield 'module_item', item.get('id'), item.get('title') or '', ''


def search(snapshot, query, limit=20):
    if limit < 1 or limit > 100:
        raise CanvasError('--limit must be between 1 and 100')
    terms = query.casefold().split()
    if not terms or len(query) > 200:
        raise CanvasError('Use a nonempty query of at most 200 characters')
    if snapshot.get('schema_version') != 1:
        raise CanvasError('Unsupported snapshot schema')
    for name in ('assignments', 'announcements', 'pages', 'modules'):
        if not isinstance(snapshot.get(name), list):
            raise CanvasError('Malformed snapshot content')
    hits = []
    for kind, identity, title, body in _documents(snapshot):
        title = str(title)
        text = re.sub(r'\s+', ' ', plain(body)).strip()
        combined = (title + ' ' + text).casefold()
        if not all(term in combined for term in terms):
            continue
        positions = [text.casefold().find(term) for term in terms]
        first = min((position for position in positions if position >= 0), default=0)
        start = max(0, first - 60)
        snippet = text[start:start + 180]
        if start:
            snippet = '…' + snippet
        if start + 180 < len(text):
            snippet += '…'
        hits.append({'kind': kind, 'id': identity, 'title': title,
                     'snippet': snippet, 'title_matches': sum(term in title.casefold() for term in terms)})
    hits.sort(key=lambda item: (-item['title_matches'], item['kind'], str(item['id'])))
    for item in hits:
        del item['title_matches']
    return {'query': query, 'course_id': snapshot.get('course_id'),
            'snapshot_captured_at': snapshot.get('captured_at'),
            'snapshot_complete': bool(snapshot.get('complete')),
            'total_matches': len(hits), 'shown': hits[:limit],
            'note': ('Snapshot is incomplete; missing results are possible.'
                     if not snapshot.get('complete') else 'Offline search only; newer Canvas content is not included.')}
