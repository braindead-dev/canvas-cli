"""Opt-in page-body revalidation. Listings and authorization are always fresh."""

import copy
import hashlib
import json
from urllib.parse import quote

from .client import CanvasError, valid_etag
from .pages import visible
from .snapshot import redact


def _page_id(page):
    value = page.get('page_id')
    return value if type(value) is int and value > 0 else None


def _digest(page):
    encoded = json.dumps(page, sort_keys=True, ensure_ascii=False,
                         allow_nan=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _candidates(previous):
    """Invalid/edited cache hints fall back to full reads, never stale bodies."""
    if not isinstance(previous, dict):
        return {}
    metadata = previous.get('page_revalidation')
    pages = previous.get('pages')
    if (not isinstance(metadata, dict) or type(metadata.get('schema_version')) is not int or
            metadata['schema_version'] != 1 or not isinstance(metadata.get('entries'), list) or
            not isinstance(pages, list)):
        return {}
    indexed = {}
    for page in pages:
        if not isinstance(page, dict) or not _page_id(page) or _page_id(page) in indexed:
            return {}
        indexed[_page_id(page)] = page
    found = {}
    for entry in metadata['entries']:
        if not isinstance(entry, dict) or not _page_id(entry) or _page_id(entry) in found:
            return {}
        page = indexed.get(_page_id(entry))
        if (not page or not visible(page) or not isinstance(page.get('body'), str) or
                not isinstance(page.get('url'), str) or not page['url'] or
                entry.get('url') != page['url'] or not valid_etag(entry.get('etag'))):
            continue
        try:
            if entry.get('sha256') != _digest(page):
                continue
        except (TypeError, ValueError, UnicodeError):
            continue
        found[_page_id(entry)] = (page, entry['etag'])
    return found


class PageRevalidation:
    """Sync owns viewer/origin/course binding and verifies identity after capture."""

    def __init__(self, previous):
        self.candidates = _candidates(previous)
        self.entries = []
        self.stats = {'pages_fetched': 0, 'pages_revalidated': 0, 'conditional_requests': 0}

    def read(self, client, course_id, item):
        slug = item['url']
        identifier = _page_id(item)
        candidate = self.candidates.get(identifier)
        if candidate and candidate[0]['url'] != slug:
            candidate = None
        route = f'/api/v1/courses/{course_id}/pages/' + (
            f'page_id:{identifier}' if identifier else quote(slug, safe=''))
        tag = candidate[1] if candidate else None
        self.stats['conditional_requests'] += int(tag is not None)
        response = client.conditional_get(route, tag)
        if response['not_modified']:
            if candidate is None:
                raise CanvasError('No matching saved page for revalidation; refusing snapshot')
            page = copy.deepcopy(candidate[0])
            self.stats['pages_revalidated'] += 1
        else:
            page = response['data']
            self.stats['pages_fetched'] += 1
        if (not isinstance(page, dict) or page.get('url') != slug or
                identifier is not None and _page_id(page) != identifier or
                'course_id' in page and (type(page['course_id']) is not int or
                                        str(page['course_id']) != course_id)):
            raise CanvasError('Canvas returned a different page; refusing snapshot')
        page = redact(page)
        if visible(page) and _page_id(page) and isinstance(page.get('body'), str) and response['etag']:
            self.entries.append({'page_id': page['page_id'], 'url': slug,
                                 'etag': response['etag'], 'sha256': _digest(page)})
        return page

    def metadata(self):
        return {'schema_version': 1, 'entries': self.entries}
