"""Independent native-shaped wiki page routes for subprocess HTTPS tests."""

import copy
from urllib.parse import parse_qs, urlencode, urlsplit

from .appointments import _send


def initialize(state, *, enabled=False):
    state.page_authoring_enabled = enabled
    state.page_viewer = 7
    state.page_context = {'name': 'Synthetic wiki context'}
    state.page_permissions = {'manage_wiki_create': True, 'manage_wiki_update': True, 'participate_as_student': False}
    state.page_student_wiki = False
    state.page_records = {1001: {'page_id': 1001, 'url': 'welcome', 'title': 'Welcome', 'editing_roles': 'teachers,students',
                                 'published': True, 'front_page': False, 'publish_at': None,
                                 'updated_at': '2026-10-01T12:00:00Z', 'body': '<p>Synthetic private old wiki content</p>',
                                 'last_edited_by': {'email': 'synthetic-private-wiki-peer@example.edu'},
                                 'secure_params': 'synthetic-private-wiki-token'},
                          1002: {'page_id': 1002, 'url': '1001', 'title': 'Numeric slug', 'editing_roles': 'teachers',
                                 'published': True, 'front_page': True, 'publish_at': None,
                                 'updated_at': '2026-10-01T12:00:00Z', 'body': '<p>Synthetic private other page</p>'}}
    state.page_revision_id = 3
    state.page_history_allowed = True
    state.page_write = None
    state.page_write_denied = state.page_readback_denied = state.page_delete_race = False
    state.page_sanitize = False
    state.page_ack_patch = {}
    state.page_readback_patch = {}
    state.page_ignored_fields = set()
    state.page_permissions_lost = False


def read(state, handler):
    if not state.page_authoring_enabled:
        return False
    url = urlsplit(handler.path)
    query = parse_qs(url.query)
    if url.path == '/api/v1/users/self/profile':
        _send(handler, {'id': state.page_viewer})
        return True
    prefix = next((prefix for prefix in ('/api/v1/courses/107', '/api/v1/groups/17')
                   if url.path == prefix or url.path.startswith(prefix + '/')), None)
    if prefix is None:
        return False
    suffix = url.path[len(prefix):]
    if not suffix:
        context = {'id': int(prefix.rsplit('/', 1)[1]), **state.page_context}
        if query.get('include[]') == ['allow_student_wiki_edits']:
            context['allow_student_wiki_edits'] = state.page_student_wiki
        _send(handler, context)
    elif suffix == '/permissions':
        permissions = copy.deepcopy(state.page_permissions)
        if state.page_write is not None and state.page_permissions_lost:
            permissions['manage_wiki_update'] = False
        _send(handler, permissions)
    elif suffix == '/pages':
        rows = list(state.page_records.values())
        page = int(query.get('page', ['1'])[0])
        query['page'] = [str(page + 1)]
        link = f'<{url.path}?{urlencode(query, doseq=True)}>; rel="next"' if page < len(rows) else None
        _send(handler, rows[page - 1:page], link=link)
    elif suffix.startswith('/pages/page_id:'):
        identifier = int(suffix.split(':')[1].split('/')[0])
        record = state.page_records.get(identifier)
        if record is None:
            _send(handler, {'private': 'synthetic-private-missing-wiki'}, 404)
        elif state.page_write is not None and state.page_readback_denied:
            _send(handler, {'private': 'synthetic-private-wiki-readback-denial'}, 403)
        elif suffix.endswith('/revisions'):
            if state.page_history_allowed:
                _send(handler, [{'revision_id': state.page_revision_id, 'updated_at': record['updated_at'], 'latest': True,
                                 'edited_by': {'email': 'synthetic-private-history-peer@example.edu'}}])
            else:
                _send(handler, {'private': 'synthetic-private-no-edit-history'}, 403)
        elif suffix.endswith('/revisions/latest'):
            _send(handler, {'revision_id': state.page_revision_id, 'updated_at': record['updated_at'], 'latest': True})
        else:
            _send(handler, {**record, **(state.page_readback_patch if state.page_write is not None else {})})
    else:
        _send(handler, {'private': 'synthetic-private-ambiguous-page-route'}, 400)
    return True


def write(state, handler, body):
    if not state.page_authoring_enabled:
        return False
    prefix = next((prefix for prefix in ('/api/v1/courses/107/pages', '/api/v1/groups/17/pages')
                   if handler.path == prefix or handler.path.startswith(prefix + '/page_id:')), None)
    if prefix is None:
        return False
    state.page_write = copy.deepcopy(body)
    if state.page_write_denied:
        _send(handler, {'private': 'synthetic-private-blueprint-restriction'}, 403)
        return True
    if handler.command == 'POST' and handler.path == prefix or state.page_delete_race:
        identifier = max(state.page_records) + 1
        record = {'page_id': identifier, 'url': 'new-page', 'title': 'New page', 'body': '',
                  'editing_roles': 'members' if '/groups/' in prefix else 'teachers',
                  'published': '/groups/' in prefix or not state.page_permissions['manage_wiki_update'],
                  'front_page': False, 'publish_at': None}
    elif handler.command == 'PUT' and '/page_id:' in handler.path:
        identifier = int(handler.path.rsplit(':', 1)[1])
        record = state.page_records[identifier]
    else:
        _send(handler, {'private': 'synthetic-private-invalid-page-write'}, 400)
        return True
    changes = body['wiki_page']
    for key, value in changes.items():
        if key != 'notify_of_update' and key not in state.page_ignored_fields:
            record[key] = value
    if 'title' in changes and 'title' not in state.page_ignored_fields:
        record['url'] = changes['title'].lower().replace(' ', '-')
    if record['front_page']:
        for row in state.page_records.values():
            row['front_page'] = False
        record['front_page'] = True
    elif changes.get('title') == 'Front Page' and not any(row['front_page'] for row in state.page_records.values()):
        record['front_page'] = True  # Native default wiki front-page locator can select a new page implicitly.
    if state.page_sanitize:
        record['body'] = record['body'].replace('<script>bad()</script>', '')
    record['updated_at'] = '2026-10-03T12:00:00Z'
    state.page_records[identifier] = record
    state.page_revision_id += 1
    _send(handler, {**record, **state.page_ack_patch})
    return True
