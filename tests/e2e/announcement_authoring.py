"""Synthetic native announcement behavior, independent of CLI validators."""

import copy
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlsplit

from .appointments import _send


def apply_date_lock(row, body, *, ignored_dates=(), ignore_comments=False, keep_closing=False):
    """Synthetic native date processing followed by comment-lock precedence."""
    def instant(value):
        return datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None

    before = {key: instant(row[key]) for key in ('delayed_post_at', 'lock_at')}
    row.update({key: body[key] for key in before if key in body and key not in ignored_dates})
    after = {key: instant(row[key]) for key in before}
    if after != before:
        now = datetime.now(timezone.utc)
        row['workflow_state'] = 'post_delayed' if after['delayed_post_at'] and after['delayed_post_at'] > now else 'active'
        row['locked'] = after['lock_at'] is not None and after['lock_at'] < now
    # A changed closing date owns the resulting lock state. With an unchanged
    # closing date, the explicit/default comment choice can close or reopen it.
    requested = body.get('lock_comment', False)
    if after['lock_at'] == before['lock_at'] and not ignore_comments and row['locked'] != requested:
        if not requested and not keep_closing:
            row['lock_at'] = None
        row['locked'] = requested


def apply_section_filter(row, value, catalog, *, visible=None, fail=False, ignore=False):
    """Independent native association-before-error and stored flag semantics."""
    selected = [] if value == 'all' else [int(part) for part in value.split(',')]
    active = {section['id'] for section in catalog}
    if value != 'all' and (not selected or set(selected) - active):
        raise ValueError('Unknown synthetic section')
    old = {section['id'] for section in row['sections']} if row['is_section_specific'] else set()
    denied = fail or visible is not None and ((old & active) - set(visible) or set(selected) - set(visible))
    if not ignore:
        # Selected associations can persist before a later authorization/validation
        # failure. All-sections clearing is deferred to the successful save path.
        if not denied or value != 'all':
            row['sections'] = [copy.deepcopy(section) for section in catalog if section['id'] in selected]
        if not denied:
            row['is_section_specific'] = value != 'all'
    return not denied


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
            'ungraded_discussion_overrides': None, 'private': 'synthetic-private-opaque-metadata'}


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
    state.announcement_ignored_dates = set()
    state.announcement_store_date_offset = state.announcement_shift_date = state.announcement_lose_update = False
    state.announcement_account_changed = state.announcement_context_changed = state.announcement_sanitize = False
    state.announcement_ack_patch = state.announcement_read_patch = None
    state.announcement_hide_after = False
    state.announcement_missing_status = 404
    state.announcement_mutations = []
    state.announcement_notifications = []
    state.announcement_preference_writes = 0
    state.announcement_entries = [{'id': 301, 'message': 'synthetic-private-peer-comment'}]
    state.announcement_sections = [{'id': value, 'course_id': 123, 'name': 'synthetic-private-section',
                                    'nonxlist_course_id': 99, 'start_at': None, 'end_at': None,
                                    'restrict_enrollments_to_section_dates': False} for value in (33, 34)]
    state.announcement_section_visible_ids = None
    state.announcement_sections_denied = state.announcement_sections_denied_after = False
    state.announcement_sections_after = None
    state.announcement_sections_error_after_apply = state.announcement_ignore_sections = False


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
    elif url.path == prefix + '/sections' and '/courses/' in prefix:
        if state.announcement_sections_denied or state.announcement_written and state.announcement_sections_denied_after:
            _send(handler, {'private': 'synthetic-private-section-list-denial'}, 403)
        else:
            rows = (state.announcement_sections_after if state.announcement_written and state.announcement_sections_after is not None
                    else state.announcement_sections)
            page = int(query.get('page', ['1'])[0])
            query['page'] = [str(page + 1)]
            link = f'<{url.path}?{urlencode(query, doseq=True)}>; rel="next"' if page < len(rows) else None
            _send(handler, rows[page - 1:page], link=link)
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
    allowed = {'title', 'message', 'is_announcement', 'lock_comment'} | ({'delayed_post_at', 'lock_at', 'specific_sections'} if '/courses/' in prefix else set())
    if (handler.command not in ('POST', 'PUT', 'DELETE') or query != {'no_verifiers': ['true']} or
            deleting and body or not deleting and (set(body) - allowed or body.get('is_announcement') is not True)):
        _send(handler, {'private': 'synthetic-private-invalid-announcement-write'}, 400)
        return True
    if (row is None or creating and not state.announcement_creation or
            not creating and row['permissions']['delete' if deleting else 'update'] is not True):
        _send(handler, {'private': 'synthetic-private-native-announcement-denial'}, 403)
        return True
    if 'specific_sections' in body:
        try:
            accepted = apply_section_filter(row, body['specific_sections'], state.announcement_sections,
                                            visible=state.announcement_section_visible_ids,
                                            fail=state.announcement_denied or state.announcement_sections_error_after_apply,
                                            ignore=state.announcement_ignore_sections)
        except (ValueError, AttributeError):
            accepted = False
        if not accepted:
            _send(handler, {'private': 'synthetic-private-native-section-error-after-association'},
                  403 if state.announcement_denied else 400)
            return True
    elif state.announcement_denied:
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
        ignored = state.announcement_ignored_dates | ({'delayed_post_at', 'lock_at'} if state.announcement_ignore_date else set())
        apply_date_lock(row, body, ignored_dates=ignored, ignore_comments=state.announcement_ignore_comment_lock,
                        keep_closing=state.announcement_keep_closing_date)
        if state.announcement_force_lock and '/courses/' in prefix:
            row['locked'] = True
        if state.announcement_store_date_offset:
            row.update({key: datetime.fromisoformat(row[key].replace('Z', '+00:00')).isoformat()
                        for key in ('delayed_post_at', 'lock_at') if row[key] is not None})
        if state.announcement_shift_date:
            row['lock_at'] = '2099-10-03T19:00:00Z'
        if state.announcement_lose_update:
            row['permissions']['update'] = False
        if state.announcement_sanitize:
            row['message'] = row['message'].replace('<br>', '<br />')
        state.announcement_notifications.append(identifier)
        response = _scoped(row, prefix)
    if state.announcement_ack_patch is not None:
        response = (response | state.announcement_ack_patch if isinstance(state.announcement_ack_patch, dict)
                    else state.announcement_ack_patch)
    _send(handler, response)
    return True
