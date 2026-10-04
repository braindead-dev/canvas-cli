"""Synthetic native announcement behavior, independent of CLI validators."""

import copy
from urllib.parse import parse_qs, urlencode, urlsplit

from .appointments import _send


def _announcement(identifier):
    return {'id': identifier, 'title': 'Synthetic announcement',
            'message': '<p>synthetic-private-original-announcement</p>', 'is_announcement': True,
            'published': True, 'can_unpublish': False, 'can_lock': True, 'comments_disabled': False,
            'locked': True, 'pinned': False,
            'position': identifier - 8, 'require_initial_post': False, 'is_section_specific': False,
            'sections': [], 'discussion_subentry_count': 0, 'assignment_id': None, 'root_topic_id': None,
            'group_category_id': None, 'topic_children': [], 'group_topic_children': [], 'anonymous_state': None,
            'created_at': '2026-10-01T12:00:00Z', 'posted_at': '2026-10-01T12:00:00Z',
            'last_reply_at': None, 'delayed_post_at': None, 'lock_at': None, 'todo_date': None,
            'author': {'id': 7, 'email': 'synthetic-private-author@example.edu'},
            'permissions': {'update': True, 'delete': True, 'reply': False},
            'attachments': [{'id': 51, 'filename': 'synthetic.txt', 'display_name': 'Synthetic', 'size': 20,
                             'url': 'https://storage.example.edu/?token=synthetic-private-attachment'}],
            'ungraded_discussion_overrides': [], 'private': 'synthetic-private-opaque-metadata'}


def initialize(state, *, enabled=False):
    state.announcement_enabled = enabled
    if not enabled:
        return
    state.announcements = {identifier: _announcement(identifier) for identifier in (9, 10)}
    state.announcement_context = {'name': 'Synthetic announcement context', 'workflow_state': 'available'}
    state.announcement_viewer = 7
    state.announcement_next_id = 11
    state.announcement_creation = True
    state.announcement_written = state.announcement_denied = False
    state.announcement_read_denied = state.announcement_inventory_denied = False
    state.announcement_force_lock = state.announcement_ignore_date = state.announcement_ignore_delete = False
    state.announcement_ignore_comment_lock = state.announcement_keep_closing_date = False
    state.announcement_account_changed = state.announcement_context_changed = state.announcement_sanitize = False
    state.announcement_ack_patch = state.announcement_read_patch = None
    state.announcement_hide_after = False
    state.announcement_missing_status = 404
    state.announcement_mutations = []
    state.announcement_notifications = []
    state.announcement_preference_writes = 0
    state.announcement_entries = [{'id': 301, 'message': 'synthetic-private-peer-comment'}]


def _route(state, handler):
    if not state.announcement_enabled:
        return None
    url = urlsplit(handler.path)
    prefix = next((prefix for prefix in ('/api/v1/courses/123', '/api/v1/groups/123')
                   if url.path == prefix or url.path.startswith(prefix + '/')), None)
    return url, prefix


def _scoped(row, prefix):
    return {**copy.deepcopy(row), 'context_id': 123,
            'context_type': 'Course' if '/courses/' in prefix else 'Group'}


def read(state, handler):
    parsed = _route(state, handler)
    if parsed is None:
        return False
    url, prefix = parsed
    query = parse_qs(url.query)
    if url.path == '/api/v1/users/self/profile':
        _send(handler, {'id': 8 if state.announcement_written and state.announcement_account_changed
                       else state.announcement_viewer})
    elif prefix is None:
        return False
    elif url.path == prefix:
        row = {'id': 123, **state.announcement_context}
        if state.announcement_written and state.announcement_context_changed:
            row['name'] = 'Changed context'
        if query.get('include[]') == ['permissions']:
            row['permissions'] = {'create_announcement': state.announcement_creation,
                                  'create_discussion_topic': True}
        _send(handler, row)
    elif url.path == prefix + '/discussion_topics':
        if query.get('only_announcements') != ['true']:
            _send(handler, {'private': 'synthetic-private-unfiltered-announcements'}, 400)
        elif state.announcement_written and state.announcement_inventory_denied:
            _send(handler, {'private': 'synthetic-private-inventory-denial'}, 403)
        else:
            rows = [_scoped(row, prefix) for row in state.announcements.values()]
            if state.announcement_written and state.announcement_hide_after:
                rows = [row for row in rows if row['id'] < 11]
            page = int(query.get('page', ['1'])[0])
            query['page'] = [str(page + 1)]
            link = f'<{url.path}?{urlencode(query, doseq=True)}>; rel="next"' if page < len(rows) else None
            _send(handler, rows[page - 1:page], link=link)
    elif url.path.startswith(prefix + '/discussion_topics/'):
        if query != {'include[]': ['sections'], 'no_verifiers': ['true']}:
            _send(handler, {'private': 'synthetic-private-invalid-announcement-read'}, 400)
        elif state.announcement_written and state.announcement_read_denied:
            _send(handler, {'private': 'synthetic-private-read-denial'}, 403)
        else:
            identifier = int(url.path.rsplit('/', 1)[1])
            if identifier not in state.announcements:
                _send(handler, {'private': 'synthetic-private-missing-announcement'}, state.announcement_missing_status)
            else:
                row = _scoped(state.announcements[identifier], prefix)
                if state.announcement_written and state.announcement_read_patch:
                    row.update(state.announcement_read_patch)
                _send(handler, row)
    else:
        _send(handler, {'private': 'synthetic-private-unexpected-announcement-route'}, 404)
    return True


def write(state, handler, body):
    parsed = _route(state, handler)
    if parsed is None or parsed[1] is None:
        return False
    url, prefix = parsed
    query = parse_qs(url.query)
    creating = handler.command == 'POST' and url.path == prefix + '/discussion_topics'
    deleting = handler.command == 'DELETE'
    identifier = state.announcement_next_id if creating else int(url.path.rsplit('/', 1)[1])
    row = _announcement(identifier) if creating else state.announcements.get(identifier)
    allowed = {'title', 'message', 'is_announcement', 'lock_comment'} | ({'delayed_post_at'} if creating and '/courses/' in prefix else set())
    if (handler.command not in ('POST', 'PUT', 'DELETE') or query != {'no_verifiers': ['true']} or
            deleting and body or not deleting and (set(body) - allowed or body.get('is_announcement') is not True)):
        _send(handler, {'private': 'synthetic-private-invalid-announcement-write'}, 400)
        return True
    if (state.announcement_denied or row is None or creating and not state.announcement_creation or
            not creating and row['permissions']['delete' if deleting else 'update'] is not True):
        _send(handler, {'private': 'synthetic-private-native-announcement-denial'}, 403)
        return True
    state.announcement_mutations.append((handler.command, handler.path, copy.deepcopy(body)))
    state.announcement_written = True
    if deleting:
        response = {**_scoped(row, prefix), 'type': 'Announcement', 'workflow_state': 'deleted'}
        if not state.announcement_ignore_delete:
            state.announcements.pop(identifier)
    else:
        if creating:
            row.update(author={'id': state.announcement_viewer}, attachments=None, position=len(state.announcements) + 1)
            state.announcements[identifier] = row
            state.announcement_next_id += 1
        row.update({key: body[key] for key in ('title', 'message') if key in body})
        # Canvas's announcement update path defaults to unlocked when omitted.
        # A course-level lock can override a requested open comment state.
        requested_lock = body.get('lock_comment', False)
        if row['locked'] and not requested_lock and not state.announcement_keep_closing_date:
            row['lock_at'] = None
        if not state.announcement_ignore_comment_lock:
            row['locked'] = state.announcement_force_lock and '/courses/' in prefix or requested_lock
        if 'delayed_post_at' in body and not state.announcement_ignore_date:
            row['delayed_post_at'] = body['delayed_post_at']
        if state.announcement_sanitize:
            row['message'] = row['message'].replace('<br>', '<br />')
        state.announcement_notifications.append(identifier)
        response = _scoped(row, prefix)
    if state.announcement_ack_patch is not None:
        response = (response | state.announcement_ack_patch if isinstance(state.announcement_ack_patch, dict)
                    else state.announcement_ack_patch)
    _send(handler, response)
    return True
