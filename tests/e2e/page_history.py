"""Synthetic native revision endpoints, independent of the production client."""

import copy
from urllib.parse import parse_qs, urlencode, urlsplit

from .appointments import _send


def initialize(state, *, enabled=False):
    state.page_history_enabled = enabled
    state.history_viewer = 7
    state.history_context = {'name': 'Synthetic history context'}
    state.history_permissions = {'manage_wiki_create': True, 'manage_wiki_update': True, 'participate_as_student': False}
    state.history_student_wiki = False
    state.history_front_url = '2001'
    state.history_pages = {2001: {'page_id': 2001, 'title': 'Current', 'url': 'current', 'body': '<p>Synthetic current private HTML</p>',
                                 'published': True, 'editing_roles': 'teachers', 'publish_at': None,
                                 'updated_at': '2026-10-01T12:00:00Z'},
                           2002: {'page_id': 2002, 'title': 'Numeric slug', 'url': '2001', 'body': '<p>Private other HTML</p>',
                                  'published': True, 'editing_roles': 'teachers', 'publish_at': None,
                                  'updated_at': '2026-10-01T12:00:00Z'}}
    state.history_records = {1: {'revision_id': 1, 'title': 'Earlier', 'url': 'earlier', 'body': '<p>Synthetic historical private HTML</p>',
                                'updated_at': '2026-09-01T12:00:00Z'},
                            2: {'revision_id': 2, 'title': 'Current', 'url': 'current', 'body': '<p>Previous private HTML</p>',
                                'updated_at': '2026-09-15T12:00:00Z'},
                            3: {'revision_id': 3, **{key: state.history_pages[2001][key] for key in ('title', 'url', 'body', 'updated_at')}}}
    state.history_edit_allowed = state.history_read_allowed = True
    state.history_written = state.history_write_denied = state.history_ignore_restore = False
    state.history_readback_denied = state.history_sanitize = state.history_url_suffix = False
    state.history_permissions_lost = state.history_account_changed = False
    state.history_ack_patch = {}
    state.history_readback_patch = {}
    state.history_list_patch = None


def _page(state, identifier):
    row = {**copy.deepcopy(state.history_pages[identifier]), 'front_page': state.history_pages[identifier]['url'] == state.history_front_url,
           'last_edited_by': {'email': 'synthetic-private-page-editor@example.edu'}, 'secure_params': 'synthetic-private-page-token'}
    return {**row, **(state.history_readback_patch if state.history_written else {})}


def _revision(state, number, *, summary=False):
    row = {**copy.deepcopy(state.history_records[number]), 'latest': number == max(state.history_records),
           'edited_by': {'id': 8, 'display_name': 'Synthetic editor', 'name': 'Synthetic name',
                         'email': 'synthetic-private-history-editor@example.edu', 'login_id': 'synthetic-private-login',
                         'avatar_url': 'synthetic-private-avatar', 'secure_params': 'synthetic-private-history-token'}}
    if summary:
        for key in ('title', 'url', 'body'):
            row.pop(key)
    return row


def _route(state, handler):
    if not state.page_history_enabled:
        return None
    url = urlsplit(handler.path)
    prefix = next((prefix for prefix in ('/api/v1/courses/108', '/api/v1/groups/18')
                   if url.path == prefix or url.path.startswith(prefix + '/')), None)
    return (url, prefix, url.path[len(prefix):] if prefix else None, parse_qs(url.query))


def read(state, handler):
    parsed = _route(state, handler)
    if parsed is None:
        return False
    url, prefix, suffix, query = parsed
    if url.path == '/api/v1/users/self/profile':
        _send(handler, {'id': 8 if state.history_written and state.history_account_changed else state.history_viewer})
        return True
    if prefix is None:
        return False
    if not suffix:
        row = {'id': int(prefix.rsplit('/', 1)[1]), **state.history_context}
        if query.get('include[]') == ['allow_student_wiki_edits']:
            row['allow_student_wiki_edits'] = state.history_student_wiki
        _send(handler, row)
    elif suffix == '/permissions':
        row = {**state.history_permissions}
        if state.history_written and state.history_permissions_lost:
            row['manage_wiki_update'] = False
        _send(handler, row)
    elif suffix == '/pages':
        _paged(handler, url, query, [_page(state, identifier) for identifier in state.history_pages])
    elif suffix.startswith('/pages/page_id:'):
        identifier = int(suffix.split(':')[1].split('/')[0])
        if identifier not in state.history_pages or not state.history_read_allowed or state.history_written and state.history_readback_denied:
            _send(handler, {'private': 'synthetic-private-native-history-access-denial'}, 403)
        elif suffix.endswith('/revisions'):
            if not state.history_edit_allowed:
                _send(handler, {'private': 'synthetic-private-native-revisions-denial'}, 403)
            else:
                rows = state.history_list_patch if state.history_list_patch is not None else [_revision(state, n, summary=True) for n in state.history_records]
                _paged(handler, url, query, rows)
        elif '/revisions/' in suffix:
            key = suffix.rsplit('/', 1)[1]
            number = max(state.history_records) if key == 'latest' else int(key)
            if key != 'latest' and not state.history_edit_allowed:
                _send(handler, {'private': 'synthetic-private-native-numeric-revision-denial'}, 403)
            elif number not in state.history_records:
                _send(handler, {'private': 'synthetic-private-missing-revision'}, 404)
            else:
                _send(handler, _revision(state, number, summary=query.get('summary') == ['true']))
        else:
            _send(handler, _page(state, identifier))
    else:
        _send(handler, {'private': 'synthetic-private-ambiguous-history-route'}, 400)
    return True


def _paged(handler, url, query, rows):
    page = int(query.get('page', ['1'])[0])
    query['page'] = [str(page + 1)]
    link = f'<{url.path}?{urlencode(query, doseq=True)}>; rel="next"' if page < len(rows) else None
    _send(handler, rows[page - 1:page], link=link)


def write(state, handler, body):
    parsed = _route(state, handler)
    if parsed is None:
        return False
    url, prefix, suffix, _ = parsed
    if prefix is None or not suffix.startswith('/pages/page_id:') or '/revisions/' not in suffix:
        return False
    identifier = int(suffix.split(':')[1].split('/')[0])
    number = int(suffix.rsplit('/', 1)[1])
    manager = state.history_permissions['manage_wiki_update'] or '/courses/' in prefix and state.history_student_wiki
    if handler.command != 'POST' or body != {} or state.history_write_denied or not manager or not state.history_edit_allowed:
        _send(handler, {'private': 'synthetic-private-native-restore-denial'}, 403)
        return True
    if identifier not in state.history_pages or number not in state.history_records:
        _send(handler, {'private': 'synthetic-private-native-restore-missing'}, 404)
        return True
    state.history_written = True
    if not state.history_ignore_restore:
        page = state.history_pages[identifier]
        selected = state.history_records[number]
        changes = {key: selected[key] for key in ('title', 'url', 'body')}
        if state.history_sanitize:
            changes['body'] = changes['body'].replace('<script>bad()</script>', '')
        if state.history_url_suffix:
            changes['url'] += '-2'  # Native permanent lookup collision without changing the title.
        if any(page[key] != value for key, value in changes.items()):
            page.update(changes, updated_at='2026-10-03T12:00:00Z')
            number = max(state.history_records) + 1
            state.history_records[number] = {'revision_id': number, **{key: page[key] for key in ('title', 'url', 'body', 'updated_at')}}
    _send(handler, {**_revision(state, max(state.history_records)), **state.history_ack_patch})
    return True
