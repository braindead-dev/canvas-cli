"""Independent synthetic native discussion prompt updates and soft-deletion state."""

import copy
from urllib.parse import parse_qs, urlencode, urlsplit

from .appointments import _send


def initialize(state, *, enabled=False):
    state.topic_management_enabled = enabled
    if not enabled:
        return
    state.topic_viewer = 7
    state.topic_context = {'name': 'Synthetic discussion context', 'workflow_state': 'available'}
    state.managed_topics = {
        901: {'id': 901, 'title': 'Synthetic prompt', 'message': '<p>synthetic-private-prior-prompt</p>',
              'is_announcement': False, 'assignment_id': None, 'root_topic_id': None, 'group_category_id': None,
              'topic_children': [], 'group_topic_children': [], 'anonymous_state': None,
              'published': True, 'locked': False, 'pinned': True, 'position': 1, 'require_initial_post': False,
              'is_section_specific': False, 'sections': [], 'discussion_subentry_count': 0,
              'created_at': '2026-10-01T12:00:00Z', 'posted_at': '2026-10-01T12:00:00Z', 'last_reply_at': None,
              'author': {'id': 7, 'email': 'synthetic-private-author@example.edu'},
              'permissions': {'update': True, 'delete': True, 'reply': True},
              'attachments': [{'id': 881, 'filename': 'synthetic.txt', 'display_name': 'Synthetic', 'size': 20,
                               'url': 'https://storage.example.edu/?token=synthetic-private-signed-attachment'}],
              'ungraded_discussion_overrides': [{'student_ids': [7], 'secret': 'synthetic-private-audience'}],
              'podcast_url': 'https://example.edu/feed/synthetic-private-feed'},
        902: {'id': 902, 'title': 'Synthetic other topic', 'is_announcement': False,
              'published': True, 'locked': False, 'pinned': False, 'position': 2}}
    state.topic_written = state.topic_denied = state.topic_readback_denied = False
    state.topic_sanitize = state.topic_account_changed = state.topic_ignore = False
    state.topic_ack_patch = state.topic_readback_patch = None
    state.topic_missing_status = 404
    state.topic_ignored_fields = set()
    state.topic_entries = [{'id': 991, 'message': 'synthetic-private-peer-reply'}]
    state.topic_attachment_deleted = False
    state.topic_notifications = []
    state.topic_deleted = set()
    state.topic_create_permission = True
    state.topic_moderator = state.topic_own_edit = False
    state.topic_publication_override = None
    state.topic_state_enabled = state.topic_state_lose_edit = state.topic_state_keep_schedule = False
    state.topic_state_hide_after = state.topic_state_inventory_denied = False


def _route(state, handler):
    if not state.topic_management_enabled:
        return None
    url = urlsplit(handler.path)
    prefixes = ('/api/v1/courses/111', '/api/v1/groups/119')
    return url, next((prefix for prefix in prefixes if url.path == prefix or url.path.startswith(prefix + '/')), None)


def read(state, handler):
    parsed = _route(state, handler)
    if parsed is None:
        return False
    url, prefix = parsed
    if url.path == '/api/v1/users/self/profile':
        _send(handler, {'id': 8 if state.topic_written and state.topic_account_changed else state.topic_viewer})
    elif prefix is None:
        return False
    elif url.path == prefix:
        row = {'id': int(prefix.rsplit('/', 1)[1]), **state.topic_context}
        if parse_qs(url.query).get('include[]') == ['permissions']:
            row['permissions'] = {'create_discussion_topic': state.topic_create_permission, 'create_announcement': False}
        _send(handler, row)
    elif url.path == prefix + '/permissions':
        _send(handler, {'moderate_forum': state.topic_moderator})
    elif url.path == prefix + '/discussion_topics':
        parameters = parse_qs(url.query)
        if parameters.get('only_announcements') != ['false']:
            _send(handler, {'private': 'synthetic-private-unfiltered-inventory'}, 400)
            return True
        page = int(parameters.get('page', ['1'])[0])
        rows = list(state.managed_topics.values())
        if state.topic_written and state.topic_state_enabled:
            if state.topic_state_inventory_denied:
                _send(handler, {'private': 'synthetic-private-inventory-denial'}, 403)
                return True
            if state.topic_state_hide_after:
                rows = [row for row in rows if row['id'] != 901]
        parameters['page'] = [str(page + 1)]
        link = f'<{url.path}?{urlencode(parameters, doseq=True)}>; rel="next"' if page < len(rows) else None
        _send(handler, rows[page - 1:page], link=link)
    elif url.path.startswith(prefix + '/discussion_topics/'):
        if parse_qs(url.query) != {'include[]': ['sections'], 'no_verifiers': ['true']}:
            _send(handler, {'private': 'synthetic-private-unscoped-topic-read'}, 400)
            return True
        identifier = int(url.path.rsplit('/', 1)[1])
        if state.topic_written and state.topic_readback_denied:
            _send(handler, {'private': 'synthetic-private-readback-denial'}, 403)
        elif identifier not in state.managed_topics:
            _send(handler, {'private': 'synthetic-private-missing-topic'}, state.topic_missing_status)
        else:
            row = copy.deepcopy(state.managed_topics[identifier])
            if state.topic_written and state.topic_readback_patch:
                row.update(state.topic_readback_patch)
            _send(handler, row)
    else:
        return False
    return True


def write(state, handler, body):
    parsed = _route(state, handler)
    if parsed is None:
        return False
    url, prefix = parsed
    if prefix is not None and handler.command == 'POST' and url.path == prefix + '/discussion_topics':
        if (state.topic_denied or state.topic_create_permission is not True or
                body.get('published') is False and not state.topic_moderator):
            _send(handler, {'private': 'synthetic-private-native-creation-denial'}, 403)
            return True
        if (set(body) - {'title', 'message', 'published'} or type(body.get('published')) is not bool or
                parse_qs(url.query) != {'no_verifiers': ['true']}):
            _send(handler, {'private': 'synthetic-private-native-invalid-creation'}, 400)
            return True
        identifier = max(state.managed_topics) + 1
        row = copy.deepcopy(state.managed_topics[901])
        row.update(id=identifier, title=body['title'], message=body.get('message'), published=body['published'],
                   pinned=False, locked=False, position=len(state.managed_topics) + 1, attachments=None,
                   author={'id': state.topic_viewer}, ungraded_discussion_overrides=[],
                   permissions={'update': state.topic_own_edit, 'delete': state.topic_own_edit})
        if state.topic_sanitize and row['message'] is not None:
            row['message'] = row['message'].replace('<br>', '<br />')
        if state.topic_publication_override is not None:
            row['published'] = state.topic_publication_override
        state.managed_topics[identifier] = row
        state.topic_written = True
        state.topic_notifications.append(identifier)
        response = copy.deepcopy(row)
        if state.topic_ack_patch is not None:
            response = {**response, **state.topic_ack_patch} if isinstance(state.topic_ack_patch, dict) else state.topic_ack_patch
        _send(handler, response)
        return True
    if prefix is None or not url.path.startswith(prefix + '/discussion_topics/'):
        return False
    identifier = int(url.path.rsplit('/', 1)[1])
    permission = 'delete' if handler.command == 'DELETE' else 'update'
    row = state.managed_topics.get(identifier)
    if (handler.command not in ('PUT', 'DELETE') or row is None or state.topic_denied or
            row.get('permissions', {}).get(permission) is not True):
        _send(handler, {'private': 'synthetic-private-native-topic-permission-denial'}, 403)
        return True
    if set(body) - {'title', 'message'} or parse_qs(url.query) != {'no_verifiers': ['true']}:
        if (state.topic_state_enabled and handler.command == 'PUT' and len(body) == 1 and
                set(body) <= {'published', 'locked', 'pinned'} and all(type(value) is bool for value in body.values()) and
                parse_qs(url.query) == {'no_verifiers': ['true']}):
            if (body.get('published') is False and row.get('can_unpublish') is not True or
                    body.get('locked') is True and row.get('can_lock') is not True):
                _send(handler, {'private': 'synthetic-private-native-state-ineligible'}, 403)
                return True
            state.topic_written = True
            if not state.topic_ignore:
                if body.get('locked') is False and row['locked'] and not state.topic_state_keep_schedule:
                    row['lock_at'] = None
                if 'pinned' in body and row['pinned'] != body['pinned']:
                    siblings = [topic for topic in state.managed_topics.values() if topic['id'] != identifier]
                    for sibling in siblings:
                        if sibling['pinned'] == row['pinned'] and sibling['position'] > row['position']:
                            sibling['position'] -= 1
                    row['position'] = max((topic['position'] for topic in siblings if topic['pinned'] == body['pinned']), default=0) + 1
                row.update(body)
                if state.topic_state_lose_edit:
                    row['permissions']['update'] = False
                state.topic_notifications.append(identifier)
            response = copy.deepcopy(row)
            if state.topic_ack_patch is not None:
                response = {**response, **state.topic_ack_patch} if isinstance(state.topic_ack_patch, dict) else state.topic_ack_patch
            _send(handler, response)
            return True
        _send(handler, {'private': 'synthetic-private-native-invalid-topic-changes'}, 400)
        return True
    state.topic_written = True
    if handler.command == 'DELETE':
        # Native destroy returns database-shaped JSON, unlike the topic API serializer.
        response = {'id': identifier, 'context_type': prefix.split('/')[3][:-1].title(),
                    'context_id': int(prefix.rsplit('/', 1)[1]), 'workflow_state': 'deleted',
                    'message': row['message'], 'user': {'name': 'synthetic-private-author'}}
        if not state.topic_ignore:
            state.topic_deleted.add(identifier)
            state.managed_topics.pop(identifier)
    else:
        if not state.topic_ignore:
            row.update({key: value for key, value in body.items() if key not in state.topic_ignored_fields})
            if state.topic_sanitize:
                row['message'] = row['message'].replace('<br>', '<br />')
            state.topic_notifications.append(identifier)
        response = copy.deepcopy(row)
    if state.topic_ack_patch is not None:
        response = {**response, **state.topic_ack_patch} if isinstance(state.topic_ack_patch, dict) else state.topic_ack_patch
    _send(handler, response)
    return True
