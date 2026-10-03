"""Native wiki soft deletion and assignment cascade in a synthetic HTTPS server."""

import copy
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

from .appointments import _send


def initialize(state, *, enabled=False):
    state.page_deletion_enabled = enabled
    state.deletion_viewer = 7
    state.deletion_context = {'name': 'Synthetic deletion context', 'workflow_state': 'available'}
    state.deletion_permission = True
    state.deletion_pages = {
        3001: {'page_id': 3001, 'title': 'Target', 'url': 'current', 'published': True, 'front_page': False,
               'editing_roles': 'teachers', 'body': '<p>synthetic-private-page</p>', 'publish_at': None,
               'updated_at': '2026-10-01T12:00:00Z'},
        3002: {'page_id': 3002, 'title': 'Numeric slug', 'url': '3001', 'published': True, 'front_page': True,
               'editing_roles': 'teachers', 'body': '<p>synthetic-private-front</p>', 'publish_at': None,
               'updated_at': '2026-10-01T12:00:00Z'}}
    state.deletion_revision = {'revision_id': 3, 'updated_at': '2026-10-01T12:00:00Z', 'latest': True}
    state.deletion_assignment = {'id': 82, 'course_id': 109, 'name': 'Synthetic linked assignment',
                                 'submission_types': ['wiki_page'], 'published': True, 'workflow_state': 'published',
                                 'updated_at': '2026-10-01T12:00:00Z', 'secure_params': 'synthetic-private-assignment-token',
                                 'submission': {'body': 'synthetic-private-submission'}}
    state.deletion_written = state.deletion_deny = state.deletion_ignore = state.deletion_keep_assignment = False
    state.deletion_changed_account = state.deletion_permission_lost = state.deletion_front_changed = False
    state.deletion_inventory_denied = False
    state.deletion_ack_patch = {}
    state.deletion_ack_response = None
    state.deletion_exact_status = 403
    state.deletion_exact_readable = False
    state.deletion_slug_status = state.deletion_cascade_status = None
    state.deletion_old_page = None


def _route(state, handler):
    if not state.page_deletion_enabled:
        return None
    url = urlsplit(handler.path)
    prefix = next((prefix for prefix in ('/api/v1/courses/109', '/api/v1/groups/19')
                   if url.path == prefix or url.path.startswith(prefix + '/')), None)
    return url, prefix, url.path[len(prefix):] if prefix else None, parse_qs(url.query)


def read(state, handler):
    parsed = _route(state, handler)
    if parsed is None:
        return False
    url, prefix, suffix, query = parsed
    if url.path == '/api/v1/users/self/profile':
        _send(handler, {'id': 8 if state.deletion_written and state.deletion_changed_account else state.deletion_viewer})
        return True
    if prefix is None:
        return False
    if not suffix:
        _send(handler, {'id': int(prefix.rsplit('/', 1)[1]), **state.deletion_context})
    elif suffix == '/permissions':
        if query.get('permissions[]') != ['manage_wiki_delete']:
            _send(handler, {'private': 'synthetic-private-edit-permission-is-not-delete'}, 403)
        else:
            _send(handler, {'manage_wiki_delete': False if state.deletion_written and state.deletion_permission_lost else state.deletion_permission})
    elif suffix == '/pages':
        if state.deletion_written and state.deletion_inventory_denied:
            _send(handler, {'private': 'synthetic-private-page-index-denial'}, 403)
        else:
            rows = [{key: value for key, value in row.items() if key not in ('body', 'assignment')}
                    for row in state.deletion_pages.values()]
            page = int(query.get('page', ['1'])[0])
            query['page'] = [str(page + 1)]
            link = f'<{url.path}?{urlencode(query, doseq=True)}>; rel="next"' if page < len(rows) else None
            _send(handler, rows[page - 1:page], link=link)
    elif suffix == '/assignments/82':
        if state.deletion_written and not state.deletion_keep_assignment:
            _send(handler, {'private': 'synthetic-private-cascade-result'}, state.deletion_cascade_status or 404)
        else:
            _send(handler, state.deletion_assignment)
    elif suffix.startswith('/pages/page_id:'):
        identifier = int(suffix.split(':')[1].split('/')[0])
        if identifier not in state.deletion_pages:
            if state.deletion_exact_readable:
                _send(handler, state.deletion_old_page)
            else:
                _send(handler, {'private': 'synthetic-private-deleted-exact-id'}, state.deletion_exact_status)
        elif suffix.endswith('/revisions/latest'):
            _send(handler, {**state.deletion_revision, 'edited_by': {'email': 'synthetic-private-editor@example.edu'}})
        elif '/revisions' in suffix:
            _send(handler, {'private': 'synthetic-private-no-history-permission'}, 403)
        else:
            _send(handler, state.deletion_pages[identifier])
    elif suffix.startswith('/pages/'):
        if state.deletion_slug_status:
            _send(handler, {'private': 'synthetic-private-old-slug-access'}, state.deletion_slug_status)
        else:
            slug = unquote(suffix.removeprefix('/pages/'))
            row = next((row for row in state.deletion_pages.values() if row['url'] == slug), None)
            if row is None and slug.isascii() and slug.isdecimal():
                row = state.deletion_pages.get(int(slug))
            _send(handler, row if row is not None else {'private': 'synthetic-private-missing-slug'}, 200 if row is not None else 404)
    else:
        _send(handler, {'private': 'synthetic-private-unknown-delete-route'}, 400)
    return True


def write(state, handler, body):
    parsed = _route(state, handler)
    if parsed is None:
        return False
    _, prefix, suffix, query = parsed
    if prefix is None:
        return False
    if (suffix != '/pages/page_id:3001' or handler.command != 'DELETE' or body != {} or
            query.get('no_verifiers') != ['true'] or state.deletion_deny or not state.deletion_permission):
        _send(handler, {'private': 'synthetic-private-native-delete-restriction'}, 403)
        return True
    row = state.deletion_pages[3001]
    if row['front_page']:
        _send(handler, {'private': 'synthetic-private-front-delete-refused'}, 400)
        return True
    state.deletion_written = True
    state.deletion_old_page = copy.deepcopy(row)
    response = {**copy.deepcopy(row), 'published': False, 'front_page': False, 'workflow_state': 'deleted',
                'updated_at': '2026-10-03T12:00:00Z', 'locked_for_user': True,
                'secure_params': 'synthetic-private-delete-ack-token', **state.deletion_ack_patch}
    if not state.deletion_ignore:
        state.deletion_pages.pop(3001)
    if state.deletion_front_changed:
        state.deletion_pages[3002]['front_page'] = False
    _send(handler, state.deletion_ack_response if state.deletion_ack_response is not None else response)
    return True
