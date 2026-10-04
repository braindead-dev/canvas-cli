"""Independent synthetic native discussion prompt updates and soft-deletion state."""

import copy
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

from . import podcasts, topic_duplication, topic_sections
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
              'delayed_post_at': None, 'lock_at': None, 'todo_date': None,
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
    state.topic_config_enabled = state.topic_granular_options_enabled = False
    state.topic_edit_options = state.topic_edit_views = True
    state.topic_order_enabled = state.topic_order_ignore = state.topic_order_read_denied = False
    state.topic_order_ack = None
    state.topic_read_forum = True
    state.topic_schedule_enabled = state.topic_schedule_midnight_rewrite = False
    state.topic_schedule_time_zone_after = None
    state.topic_todo_enabled = False
    state.topic_content_add = True
    state.topic_content_add_report = None
    state.topic_todo_offset_storage = state.topic_todo_shift = False
    state.topic_podcast_enabled = state.topic_podcast_drop_moderation = state.topic_podcast_error = False
    state.topic_podcast_permission_report = state.topic_podcast_permission_after = None
    topic_duplication.initialize(state)
    topic_sections.initialize(state)


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
    elif topic_sections.read(state, handler, url, prefix):
        return True
    elif url.path == prefix:
        row = {'id': int(prefix.rsplit('/', 1)[1]), **state.topic_context}
        if state.topic_written and state.topic_schedule_time_zone_after:
            row['time_zone'] = state.topic_schedule_time_zone_after
        if parse_qs(url.query).get('include[]') == ['permissions']:
            row['permissions'] = {'create_discussion_topic': state.topic_create_permission, 'create_announcement': False}
        _send(handler, row)
    elif url.path == prefix + '/permissions':
        rights = {'moderate_forum': state.topic_moderator}
        if 'read_forum' in parse_qs(url.query).get('permissions[]', []):
            rights['read_forum'] = state.topic_read_forum
        if 'read_as_admin' in parse_qs(url.query).get('permissions[]', []):
            rights['read_as_admin'] = state.topic_context_admin
        if 'manage_course_content_add' in parse_qs(url.query).get('permissions[]', []):
            rights = ({'manage_course_content_add': state.topic_content_add} if state.topic_content_add_report is None
                      else state.topic_content_add_report)
        if state.topic_podcast_enabled:
            if state.topic_podcast_permission_report is not None:
                rights = state.topic_podcast_permission_report
            if state.topic_written and state.topic_podcast_permission_after is not None:
                rights = state.topic_podcast_permission_after
        _send(handler, rights)
    elif url.path == prefix + '/discussion_topics':
        if state.topic_order_enabled and state.topic_written and state.topic_order_read_denied:
            _send(handler, {'private': 'synthetic-private-order-read-denial'}, 403)
            return True
        parameters = parse_qs(url.query)
        if parameters.get('only_announcements') != ['false']:
            _send(handler, {'private': 'synthetic-private-unfiltered-inventory'}, 400)
            return True
        page = int(parameters.get('page', ['1'])[0])
        rows = list(state.managed_topics.values())
        if state.topic_written and state.topic_duplicate_inventory_patch:
            rows = [row | state.topic_duplicate_inventory_patch.get(row['id'], {}) for row in rows]
        if state.topic_duplicate_hidden_id is not None:
            rows = [row for row in rows if row['id'] != state.topic_duplicate_hidden_id]
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
        if state.topic_written and state.topic_readback_denied or identifier == state.topic_duplicate_hidden_id:
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
    if topic_duplication.write(state, handler, body, url, prefix):
        return True
    if prefix is not None and handler.command == 'POST' and url.path == prefix + '/discussion_topics/reorder':
        if not state.topic_order_enabled or state.topic_denied or not state.topic_moderator or not state.topic_read_forum:
            _send(handler, {'private': 'synthetic-private-native-order-denial'}, 403)
            return True
        order = body.get('order')
        pinned = [row for row in state.managed_topics.values() if row['pinned']]
        if (url.query or set(body) != {'order'} or not isinstance(order, list) or not order or
                any(type(identifier) is not int for identifier in order) or len(order) != len(set(order)) or
                set(order) != {row['id'] for row in pinned}):
            _send(handler, {'private': 'synthetic-private-native-invalid-order'}, 400)
            return True
        state.topic_written = True
        if not state.topic_order_ignore:
            for position, identifier in enumerate(order, 1):
                state.managed_topics[identifier]['position'] = position
        result = {'reorder': True, 'order': [str(row['id']) for row in sorted(pinned, key=lambda row: row['position'])],
                  'private': 'synthetic-private-native-order-response'}
        if state.topic_order_ack is not None:
            result = state.topic_order_ack
        _send(handler, result)
        return True
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
        if topic_sections.write(state, handler, body, url, prefix, row):
            return True
        if (state.topic_podcast_enabled and handler.command == 'PUT' and body and
                set(body) <= {'podcast_enabled', 'podcast_has_student_posts'} and
                parse_qs(url.query) == {'no_verifiers': ['true']}):
            state.topic_written = True
            if state.topic_podcast_drop_moderation:
                state.topic_moderator = False
            if not state.topic_ignore:
                podcasts.apply(row, body, group='/groups/' in prefix, moderator=state.topic_moderator,
                               edit_options=not state.topic_granular_options_enabled or state.topic_edit_options)
            if state.topic_state_lose_edit:
                row['permissions']['update'] = False
            state.topic_notifications.append(identifier)
            if state.topic_podcast_error:
                _send(handler, {'private': 'synthetic-private-error-after-feed-setting'}, 500)
                return True
            response = copy.deepcopy(row)
            if state.topic_ack_patch is not None:
                response = response | state.topic_ack_patch if isinstance(state.topic_ack_patch, dict) else state.topic_ack_patch
            _send(handler, response)
            return True
        if (state.topic_todo_enabled and handler.command == 'PUT' and set(body) == {'todo_date'} and
                parse_qs(url.query) == {'no_verifiers': ['true']}):
            # Native permission asymmetry is independent of the CLI's preflight checks.
            if body['todo_date'] is not None and (state.topic_content_add is not True or row.get('assignment_id') is not None):
                _send(handler, {'private': 'synthetic-private-native-todo-denial'}, 403)
                return True
            state.topic_written = True
            if not state.topic_ignore and 'todo_date' not in state.topic_ignored_fields:
                row.update(body)
                if state.topic_todo_offset_storage and row['todo_date']:
                    row['todo_date'] = row['todo_date'].replace('Z', '+00:00')
                if state.topic_todo_shift:
                    row['todo_date'] = '2040-10-02T19:00:01Z'
                if state.topic_state_lose_edit:
                    row['permissions']['update'] = False
                state.topic_notifications.append(identifier)
            response = copy.deepcopy(row)
            if state.topic_ack_patch is not None:
                response = {**response, **state.topic_ack_patch} if isinstance(state.topic_ack_patch, dict) else state.topic_ack_patch
            _send(handler, response)
            return True
        if (state.topic_schedule_enabled and handler.command == 'PUT' and body and
                set(body) <= {'delayed_post_at', 'lock_at'} and parse_qs(url.query) == {'no_verifiers': ['true']}):
            # Native date callbacks are modeled independently, not by importing CLI validators.
            selected = dict(body) if prefix.startswith('/api/v1/courses/') else {}
            state.topic_written = True
            if not state.topic_ignore:
                old = {key: row[key] for key in ('delayed_post_at', 'lock_at')}
                row.update({key: value for key, value in selected.items() if key not in state.topic_ignored_fields})
                if old != {key: row[key] for key in old}:
                    row['published'] = True  # post_delayed is published for ordinary discussions too
                    closing = datetime.fromisoformat(row['lock_at'].replace('Z', '+00:00')) if row['lock_at'] else None
                    row['locked'] = closing is not None and closing < datetime.now(timezone.utc)
                if state.topic_schedule_midnight_rewrite and row['lock_at']:
                    local = datetime.fromisoformat(row['lock_at'].replace('Z', '+00:00')).astimezone(ZoneInfo(state.topic_context['time_zone']))
                    if (local.hour, local.minute, local.second, local.microsecond) == (0, 0, 0, 0):
                        row['lock_at'] = (local + timedelta(days=1) - timedelta(seconds=1)).isoformat()
                if state.topic_state_lose_edit:
                    row['permissions']['update'] = False
                state.topic_notifications.append(identifier)
            response = copy.deepcopy(row)
            if state.topic_ack_patch is not None:
                response = {**response, **state.topic_ack_patch} if isinstance(state.topic_ack_patch, dict) else state.topic_ack_patch
            _send(handler, response)
            return True
        option_keys = {'discussion_type', 'require_initial_post', 'allow_rating', 'only_graders_can_rate',
                       'sort_order', 'sort_order_locked', 'expanded', 'expanded_locked'}
        if (state.topic_config_enabled and handler.command == 'PUT' and body and set(body) <= option_keys and
                parse_qs(url.query) == {'no_verifiers': ['true']}):
            # Independent native option filtering and validation, not production validators.
            options = dict(body)
            if prefix.startswith('/api/v1/groups/'):
                options.pop('require_initial_post', None)
            elif state.topic_granular_options_enabled:
                if not state.topic_edit_options:
                    for key in ('discussion_type', 'require_initial_post', 'allow_rating', 'only_graders_can_rate',
                                'expanded', 'expanded_locked'):
                        options.pop(key, None)
                if not state.topic_edit_views:
                    for key in ('sort_order', 'sort_order_locked'):
                        options.pop(key, None)
            selected = row | options
            if (any(type(value) is not bool for key, value in options.items() if key not in ('discussion_type', 'sort_order')) or
                    selected['discussion_type'] not in ('side_comment', 'not_threaded', 'threaded', 'flat') or
                    selected['sort_order'] not in ('asc', 'desc') or selected['expanded_locked'] and not selected['expanded']):
                _send(handler, {'private': 'synthetic-private-native-invalid-options'}, 400)
                return True
            state.topic_written = True
            if not state.topic_ignore:
                row.update({key: value for key, value in options.items() if key not in state.topic_ignored_fields})
                if state.topic_state_lose_edit:
                    row['permissions']['update'] = False
                state.topic_notifications.append(identifier)
            response = copy.deepcopy(row)
            if state.topic_ack_patch is not None:
                response = {**response, **state.topic_ack_patch} if isinstance(state.topic_ack_patch, dict) else state.topic_ack_patch
            _send(handler, response)
            return True
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
