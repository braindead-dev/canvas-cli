"""Private, read-only course snapshots. Never write raw Canvas data into Git."""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from .client import CanvasError

SECRET_FIELDS = {'secure_params', 'access_token', 'refresh_token', 'client_secret',
                 'api_key', 'authorization', 'auth_token'}
SECRET_QUERY = {'access_token', 'token', 'auth_token', 'verifier', 'signature',
                'key-pair-id', 'policy'}


def redact(value):
    """Remove token-shaped fields and URL query secrets before disk export."""
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()
                if key.lower() not in SECRET_FIELDS}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        if value.startswith(('https://', 'http://')) and not any(c.isspace() for c in value):
            parsed = urlsplit(value)
            if parsed.query:
                pairs = parse_qsl(parsed.query, keep_blank_values=True)
                if any(key.lower() in SECRET_QUERY or key.lower().startswith(('x-amz-', 'x-goog-'))
                       for key, _ in pairs):
                    safe = [(key, item) for key, item in pairs
                            if key.lower() not in SECRET_QUERY and
                            not key.lower().startswith(('x-amz-', 'x-goog-'))]
                    return urlunsplit(parsed._replace(query=urlencode(safe)))
            return value
        # HTML attributes and prose can contain signed URLs too. Unlike a standalone
        # URL, an embedded query may be HTML-escaped or use an unknown signature key.
        # Drop its entire query and fragment rather than trying to parse a secret list.
        def strip_embedded_url(match):
            url = urlsplit(match.group())
            return urlunsplit(url._replace(query='', fragment=''))
        return re.sub(r"https?://[^\s\"'<>()]+", strip_embedded_url, value)
    return value


def capture(client, course_id, max_pages):
    base = f'/api/v1/courses/{course_id}'
    course, _ = client.request(base + '?include[]=syllabus_body')
    if not isinstance(course, dict) or str(course.get('id')) != course_id:
        raise CanvasError('Canvas returned a different course; refusing snapshot')
    unavailable = {}

    def listing(name, route):
        try:
            return client.list(route, max_pages)
        except CanvasError as error:
            unavailable[name] = str(error)
            return []

    assignments = listing('assignments', base + '/assignments?per_page=100')
    modules = listing('modules', base + '/modules?per_page=100')
    for module in modules:
        module['items'] = listing(f"module {module['id']} items",
                                  base + f"/modules/{module['id']}/items?per_page=100")
    listed_pages = listing('pages', base + '/pages?per_page=100')
    if 'pages' in unavailable:
        listed_pages = [
            {'url': item['page_url'], 'title': item.get('title')}
            for module in modules for item in module.get('items', [])
            if item.get('type') == 'Page' and item.get('page_url') and
            item.get('published') is not False and not item.get('locked_for_user')
        ]
    pages = []
    excluded_pages = 0
    seen_pages = set()
    for item in listed_pages:
        if item.get('published') is False or item.get('locked_for_user'):
            excluded_pages += 1
            continue
        slug = item.get('url')
        if not slug:
            unavailable[f"page {item.get('page_id', 'without-url')}"] = 'No page URL returned'
            continue
        if slug in seen_pages:
            continue
        seen_pages.add(slug)
        try:
            page, _ = client.request(base + '/pages/' + quote(slug, safe=''))
            if page.get('published') is False or page.get('locked_for_user'):
                excluded_pages += 1
            else:
                pages.append(page)
        except CanvasError as error:
            unavailable[f'page {slug}'] = str(error)
    announcements = listing('announcements', base + '/discussion_topics?per_page=100&only_announcements=true')
    return redact({
        'schema_version': 1,
        'captured_at': datetime.now(timezone.utc).isoformat(),
        'origin': client.host,
        'course_id': int(course_id),
        'complete': not unavailable,
        'unavailable': unavailable,
        'excluded_unpublished_or_locked_pages': excluded_pages,
        'course': course,
        'assignments': assignments,
        'modules': modules,
        'pages': pages,
        'announcements': announcements,
    })


def validate_destination(path):
    path = Path(path).expanduser().resolve(strict=False)
    if not path.parent.is_dir():
        raise CanvasError('Snapshot parent directory does not exist')
    if any((parent / '.git').exists() for parent in (path.parent, *path.parent.parents)):
        raise CanvasError('Raw course snapshots cannot be saved inside a Git checkout')
    if path.exists():
        raise CanvasError('Snapshot path already exists; choose a new filename')
    return path


def save_private(path, data):
    path = validate_destination(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        raise CanvasError('Snapshot path already exists; choose a new filename') from None
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write('\n')
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {'saved': str(path), 'complete': data['complete'],
            'counts': {name: len(data[name]) for name in ('assignments', 'modules', 'pages', 'announcements')},
            'unavailable': list(data['unavailable'])}
