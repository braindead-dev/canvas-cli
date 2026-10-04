"""Exact native ungraded-topic text/state/deletion, not assignment administration."""

from . import topic_dates
from .client import CanvasError
from .discussion import _message
from .events import timestamp
from .group_content import _context, _id, _number, base
from .topic_options import validate, validate_current
from .writes import account, check_flags, confirmed, digest

FIELDS = ('id', 'title', 'published', 'locked', 'pinned', 'position', 'created_at', 'posted_at',
          'last_reply_at', 'delayed_post_at', 'lock_at', 'todo_date', 'discussion_type',
          'discussion_subentry_count', 'require_initial_post', 'is_section_specific', 'user_can_see_posts', 'subscription_hold',
          'allow_rating', 'only_graders_can_rate', 'sort_order', 'sort_order_locked', 'expanded', 'expanded_locked',
          'can_unpublish', 'can_lock', 'comments_disabled')
ACTIONS = {'publish': ('published', True), 'unpublish': ('published', False),
           'close': ('locked', True), 'open': ('locked', False), 'pin': ('pinned', True), 'unpin': ('pinned', False)}
WARNING = ('Changes a shared discussion prompt, not your reply or a private note. Native updates can '
           'sanitize/rewrite HTML, notify people, update activity/module/pacing/blueprint associations and '
           'record access. Deletion soft-deletes the topic and removes module tags/section visibility; '
           'existing replies can become inaccessible. Attachments are not explicitly changed or deleted. '
           'Only ungraded, non-anonymous topics without root/child/group-set associations are supported here; '
           'announcements and linked assignments require separate workflows. Native permissions and editing '
           'restrictions remain authoritative. Preflight is not an atomic lock; concurrent changes can be '
           'overwritten. No read-marker, reply, grade or submission write; no automatic retry or rollback.')
UNCERTAIN = ('Could not verify the discussion-topic change. It may already have succeeded; check Canvas '
             'before repeating. No automatic retry, cleanup, rollback or private response-body logging.')
STATE_WARNING = ('Native state controls affect the shared topic and its audience. Published does not mean '
                 'available now: opening dates, course/module access and future jobs still apply. Draft eligibility '
                 'is the reported can_unpublish flag, not a guessed role or total reply count. Closing affects replies, '
                 'not topic deletion. Reopening a closed topic can clear lock_at. Pin/unpin moves the topic to the '
                 'bottom of its native ordering scope and can shift other positions. Only accessible inventory '
                 'changes are observed, not all hidden topics or causal proof. No retry, cleanup or rollback.')
OPTIONS_WARNING = ('Changes shared reply structure, likes or default views, not your personal display preferences. '
                   'Changing require_initial_post can reveal or hide existing replies for other participants; '
                   'no peer entries or cached replies are read here. Course granular permissions and blueprint '
                   'restrictions can reject or discard options; exact stored values must independently read back. '
                   'Expansion cannot be both collapsed and locked. Existing entries are not rewritten or deleted. '
                   'Observed inventory changes are not exclusive causal proof; no retry, cleanup or rollback.')


def _parent(row, item, context_type):
    for key in ('context_id', context_type + '_id'):
        if key in row and (type(row[key]) is not int or row[key] != int(item)):
            raise CanvasError('Canvas returned a topic outside the requested context')
    if row.get('context_type') is not None and (not isinstance(row['context_type'], str) or
                                               row['context_type'].lower() != context_type):
        raise CanvasError('Canvas returned a topic outside the requested context')


def _topic(row, item, topic_id, context_type):
    if _id(row) != int(topic_id):
        raise CanvasError('Canvas returned a different discussion topic')
    _parent(row, item, context_type)
    if (row.get('workflow_state') == 'deleted' or row.get('hidden_for_user') or
            row.get('anonymous_state') is not None or row.get('is_announcement') is not False):
        raise CanvasError('Topic management requires a readable non-anonymous discussion, not an announcement')
    if (any(key not in row or row[key] is not None for key in ('assignment_id', 'root_topic_id', 'group_category_id')) or
            row.get('assignment') is not None or any(row.get(key) != [] for key in ('topic_children', 'group_topic_children'))):
        raise CanvasError('Linked assignments, root/child topics and group-set discussions need separate management workflows')
    if (not isinstance(row.get('title'), str) or not row['title'] or 'message' not in row or
            row['message'] is not None and not isinstance(row['message'], str) or
            any(key not in row for key in topic_dates.FIELDS) or
            any(type(row.get(key)) is not bool for key in ('published', 'locked', 'pinned', 'require_initial_post', 'is_section_specific')) or
            type(row.get('discussion_subentry_count')) is not int or row['discussion_subentry_count'] < 0):
        raise CanvasError('Canvas returned incomplete discussion-topic metadata')
    lock = row.get('lock_info')
    if lock is not None and (not isinstance(lock, dict) or lock.get('can_view') is False or
                             'can_view' in lock and type(lock['can_view']) is not bool):
        raise CanvasError('The actual discussion prompt is not readable; lock explanations cannot be edited as content')
    permissions = row.get('permissions')
    if not isinstance(permissions, dict) or any(type(permissions.get(key)) is not bool for key in ('update', 'delete')):
        raise CanvasError('Canvas did not report exact native topic update/delete permissions')
    author = row.get('author')
    author_id = _id(author) if author is not None else None
    attachments = [] if row.get('attachments') is None else row['attachments']
    if 'attachments' not in row or not isinstance(attachments, list):
        raise CanvasError('Canvas did not report the discussion-topic attachment inventory')
    attached = []
    for attachment in attachments:
        identifier = _id(attachment)
        if (any(attachment.get(key) is not None and not isinstance(attachment[key], str)
                for key in ('filename', 'display_name', 'updated_at')) or
                attachment.get('size') is not None and (type(attachment['size']) is not int or attachment['size'] < 0)):
            raise CanvasError('Canvas returned malformed topic attachment metadata')
        if attachment.get('updated_at') is not None:
            timestamp(attachment['updated_at'])
        attached.append({'id': identifier, **{key: attachment.get(key) for key in
                         ('filename', 'display_name', 'size', 'updated_at')}})
    if len({row['id'] for row in attached}) != len(attached):
        raise CanvasError('Canvas returned duplicate discussion-topic attachments')
    sections = row.get('sections', [])
    if (not isinstance(sections, list) or row['is_section_specific'] and not sections or
            context_type == 'group' and row['is_section_specific']):
        raise CanvasError('Canvas did not report the section-specific topic audience')
    section_ids = [_id(section) for section in sections]
    if len(set(section_ids)) != len(section_ids):
        raise CanvasError('Canvas returned duplicate topic audience sections')
    for key in ('created_at', 'posted_at', 'last_reply_at', 'delayed_post_at', 'lock_at', 'todo_date'):
        if row.get(key) is not None:
            timestamp(row[key])
    if row.get('position') is not None and (type(row['position']) is not int or row['position'] < 0):
        raise CanvasError('Canvas returned malformed topic ordering')
    if (any(row.get(key) is not None and type(row[key]) is not bool for key in
            ('allow_rating', 'only_graders_can_rate', 'sort_order_locked', 'expanded', 'expanded_locked',
             'can_unpublish', 'can_lock', 'comments_disabled', 'user_can_see_posts')) or
            any(row.get(key) is not None and not isinstance(row[key], str) for key in ('discussion_type', 'sort_order', 'subscription_hold'))):
        raise CanvasError('Canvas returned malformed topic options')
    return {**{key: row.get(key) for key in FIELDS}, 'author_id': author_id,
            'message_digest': digest(row['message'] or ''), 'attachments': sorted(attached, key=lambda row: row['id']),
            'section_ids': sorted(section_ids), 'audience_digest': digest(row.get('ungraded_discussion_overrides')),
            'permissions': {key: permissions[key] for key in ('update', 'delete')}}


def _scope(client, item, context_type):
    route, row = _context(client, item, context_type)
    if row.get('workflow_state') == 'deleted':
        raise CanvasError('The discussion context is deleted')
    if (any(row.get(key) is not None and not isinstance(row[key], str) for key in ('name', 'workflow_state', 'time_zone')) or
            any(row.get(key) is not None and type(row[key]) is not bool for key in ('concluded', 'non_collaborative'))):
        raise CanvasError('Canvas returned malformed discussion context metadata')
    return route, {key: row.get(key) for key in ('id', 'name', 'workflow_state', 'concluded', 'non_collaborative', 'time_zone')}


def _read(client, route, item, topic_id, context_type):
    row, _ = client.request(route + '/discussion_topics/' + topic_id + '?include%5B%5D=sections&no_verifiers=true')
    return _topic(row, item, topic_id, context_type)


def _inventory(client, route, item, context_type, max_pages):
    output = []
    for row in client.list(route + '/discussion_topics?per_page=100&only_announcements=false', max_pages):
        _id(row)
        _parent(row, item, context_type)
        if row.get('is_announcement') is not False or row.get('workflow_state') == 'deleted':
            raise CanvasError('Canvas returned a foreign/deleted topic in the discussion inventory')
        output.append({key: row.get(key) for key in ('id', 'title', 'published', 'locked', 'pinned', 'position')})
    if len({row['id'] for row in output}) != len(output):
        raise CanvasError('Canvas returned duplicate discussion-topic identifiers')
    return sorted(output, key=lambda row: row['id'])


def _changes(title, message):
    changes = {}
    if title is not None:
        if (not isinstance(title, str) or not title.strip() or len(title.strip()) > 255 or
                any(ord(char) < 32 or 0x7f <= ord(char) < 0xa0 for char in title)):
            raise CanvasError('Topic title must be nonempty, within 255 characters and contain no controls')
        changes['title'] = title.strip()
    if message is not None:
        changes['message'] = _message(message)
    if not changes:
        raise CanvasError('Select --title or --message-file for a discussion-topic edit')
    try:
        if any(len(value.encode('utf-8')) > 40000 or '\x00' in value for value in changes.values()):
            raise UnicodeError
    except UnicodeError:
        raise CanvasError('Discussion-topic changes must be bounded UTF-8 text without NUL characters') from None
    return changes


def _inventory_delta(before, after):
    old = {row['id']: row for row in before}
    new = {row['id']: row for row in after}
    return {'added_ids': sorted(new.keys() - old.keys()), 'removed_ids': sorted(old.keys() - new.keys()),
            'changed': [{'id': identifier, 'fields': [key for key in old[identifier] if old[identifier][key] != new[identifier][key]]}
                        for identifier in sorted(old.keys() & new.keys()) if old[identifier] != new[identifier]]}


def _matches(row, key, value):
    if key == 'message':
        return row['message_digest'] == digest(value)
    if key in topic_dates.FIELDS:
        return topic_dates.matches(row, key, value)
    return row[key] == value


def change(client, item, topic_id, *, context_type='course', title=None, message=None, delete=False,
           action=None, acknowledge_shared=False, acknowledge_removal=False, acknowledge_ordering=False,
           acknowledge_schedule_removal=False, options=None, acknowledge_reply_visibility=False,
           schedule=None, acknowledge_availability=False,
           max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    if context_type not in ('course', 'group'):
        raise CanvasError('Topic management requires a course or group context')
    base(item, context_type)
    _number(topic_id)
    if (acknowledge_shared is not True or type(delete) is not bool or type(acknowledge_removal) is not bool or
            delete != acknowledge_removal):
        raise CanvasError('Use --acknowledge-shared-topic; deletion also requires --acknowledge-topic-removal, including previews')
    if type(max_pages) is not int or max_pages < 1:
        raise CanvasError('Topic inventory limit must be a positive integer')
    if (type(acknowledge_ordering) is not bool or type(acknowledge_schedule_removal) is not bool or
            action is not None and (not isinstance(action, str) or action not in ACTIONS)):
        raise CanvasError('Select a known topic state action and explicit boolean acknowledgements')
    if sum((delete, action is not None, options is not None, schedule is not None,
            title is not None or message is not None)) > 1:
        raise CanvasError('Topic deletion and state controls cannot include other operations or content edits')
    if ((action in ('pin', 'unpin')) != acknowledge_ordering or
            acknowledge_schedule_removal and action != 'open'):
        raise CanvasError('Pin/unpin requires --acknowledge-topic-ordering-change; schedule-removal acknowledgement is only for opening')
    if options is not None:
        options = validate(options, context_type)
    if type(acknowledge_availability) is not bool or acknowledge_availability != (schedule is not None):
        raise CanvasError('Scheduling requires --acknowledge-availability-change, including previews; not for other operations')
    if schedule is not None:
        schedule = topic_dates.validate(schedule, context_type)
    if (type(acknowledge_reply_visibility) is not bool or
            acknowledge_reply_visibility != (options is not None and 'require_initial_post' in options)):
        raise CanvasError('Changing require_initial_post requires --acknowledge-reply-visibility-change, including previews; not for other operations')
    changes = (schedule if schedule is not None else options if options is not None else
               dict([ACTIONS[action]]) if action is not None else None if delete else _changes(title, message))
    controlled = action is not None or options is not None or schedule is not None
    identity = account(client)
    route, context = _scope(client, item, context_type)
    before = _read(client, route, item, topic_id, context_type)
    permission = 'delete' if delete else 'update'
    if before['permissions'][permission] is not True:
        raise CanvasError('Canvas does not permit this exact discussion-topic ' + permission)
    if action == 'unpublish' and before['can_unpublish'] is not True:
        raise CanvasError('Canvas did not report native eligibility to move this exact topic to draft')
    if action == 'close' and before['can_lock'] is not True:
        raise CanvasError('Canvas did not report native eligibility to close this exact topic')
    clears_schedule = action == 'open' and before['locked'] and before['lock_at'] is not None
    if clears_schedule and not acknowledge_schedule_removal:
        raise CanvasError('Opening this closed topic clears its closing date; use --acknowledge-closing-schedule-removal, including previews')
    if options is not None:
        validate_current(options, before)
    if schedule is not None:
        topic_dates.validate_current(schedule, before, context)
    if not delete and all(_matches(before, key, value) for key, value in changes.items()):
        if schedule is not None:
            raise CanvasError('The selected topic dates already match; no schedule update needed')
        raise CanvasError('The selected topic settings already match; no update needed' if options is not None else
                          'The selected topic state already matches; no state update needed' if action is not None else
                          'The selected topic text already matches; no edit needed')
    inventory = _inventory(client, route, item, context_type, max_pages)
    listed = {key: before[key] for key in ('id', 'title', 'published', 'locked', 'pinned', 'position')}
    if listed not in inventory or _read(client, route, item, topic_id, context_type) != before or account(client) != identity:
        raise CanvasError('Discussion/account changed during preflight; review a fresh preview')
    if controlled and (_scope(client, item, context_type) != (route, context) or
                       _inventory(client, route, item, context_type, max_pages) != inventory or account(client) != identity):
        raise CanvasError('Discussion context/inventory changed during state preflight')
    preview = {**identity, 'context_type': context_type, f'{context_type}_id': int(item), 'context': context,
               'topic': before, 'inventory_digest': digest(inventory), 'acknowledge_shared_topic': True,
               'acknowledge_topic_removal': acknowledge_removal, 'method': 'DELETE' if delete else 'PUT',
               'route': route + '/discussion_topics/' + topic_id + '?no_verifiers=true', 'body': changes, 'warning': WARNING}
    if action is not None:
        preview.update(topic_state_action=action, acknowledge_topic_ordering_change=acknowledge_ordering,
                       acknowledge_closing_schedule_removal=acknowledge_schedule_removal,
                       clears_closing_schedule=clears_schedule, warning=WARNING + ' ' + STATE_WARNING)
    if options is not None:
        preview.update(acknowledge_reply_visibility_change=acknowledge_reply_visibility,
                       warning=WARNING + ' ' + OPTIONS_WARNING)
    if schedule is not None:
        preview.update(acknowledge_availability_change=True, warning=WARNING + ' ' + topic_dates.WARNING)
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        if delete:
            if _id(response) != int(topic_id) or response.get('workflow_state') != 'deleted':
                raise CanvasError('Canvas did not acknowledge the exact native soft deletion')
            _parent(response, item, context_type)
            after = None
        else:
            after = _topic(response, item, topic_id, context_type)
        next_route, next_context = _scope(client, item, context_type)
        if next_context != context or account(client) != identity:
            raise CanvasError('Discussion context/account changed during verification')
        if delete:
            remaining = _inventory(client, next_route, item, context_type, max_pages)
            if any(row['id'] == int(topic_id) for row in remaining):
                raise CanvasError('The deleted discussion remains in the active inventory')
            try:
                _read(client, next_route, item, topic_id, context_type)
            except CanvasError as error:
                if error.status not in (404, 410):
                    raise
                missing_status = error.status
            else:
                raise CanvasError('The deleted discussion is still readable')
        elif (_read(client, next_route, item, topic_id, context_type) != after or
              not controlled and after['permissions']['update'] is not True):
            raise CanvasError('Stored topic acknowledgement and readback do not agree')
        if options is not None and any(after[key] != value for key, value in options.items()):
            raise CanvasError('Canvas did not store every selected native discussion option')
        if schedule is not None and not all(_matches(after, key, value) for key, value in schedule.items()):
            raise CanvasError('Canvas did not store every selected discussion date as the exact instant or explicit clearing')
        if action is not None:
            field, value = ACTIONS[action]
            if after[field] is not value or clears_schedule and after['lock_at'] is not None:
                raise CanvasError('Canvas did not store the requested native state or clear its closing date')
        if controlled:
            remaining = _inventory(client, next_route, item, context_type, max_pages)
            if {key: after[key] for key in listed} not in remaining:
                raise CanvasError('The updated topic is not verified in the accessible inventory')
        if account(client) != identity:
            raise CanvasError('Account changed during topic verification')
    except CanvasError:
        raise CanvasError(UNCERTAIN) from None
    if delete:
        return {'deleted_topic': {'id': int(topic_id), 'title': before['title']}, 'context_type': context_type,
                f'{context_type}_id': int(item), 'removed_from_active_inventory': True, 'exact_id_read_status': missing_status,
                'note': 'One native soft DELETE acknowledged, absent from the complete active-topic inventory and exact ID not found. '
                        'Stable account/context verified. No assertion of permanent erasure, module/notification cleanup or attachment deletion; '
                        'no CLI restore, automatic retry or rollback.'}
    matched = {key: _matches(after, key, value) for key, value in changes.items()}
    changed = [key for key in before if before[key] != after[key]]
    requested = {'message_digest' if key == 'message' else key for key in changes}
    result = {'edited_topic': {**after, 'html_url': client.host + f'/{context_type}s/{item}/discussion_topics/{topic_id}'},
            'context_type': context_type, f'{context_type}_id': int(item), 'acknowledgement_matches_readback': True,
            'stored_text_matches_request': matched, 'changed_fields': changed,
            'unrequested_changed_fields': [key for key in changed if key not in requested],
            'note': 'One native PUT and independent exact-topic readback with stable account/context verified. '
                    'Requested-text equality and other observed field changes are labeled; native HTML rewriting is not hidden. '
                    'No private prompt, attachment URLs or raw response emitted, no reply/read-marker write, retry or rollback.'}
    if controlled:
        result.update(stored_text_matches_request={},
                      observed_inventory_changes=_inventory_delta(inventory, remaining),
                      note='One native PUT, exact selected settings and independent topic/inventory readback with stable account/context verified. '
                           'Other observed field/inventory changes are labeled, not attributed exclusively to this write. '
                           'Opening/availability/future jobs and notification/module/pacing effects remain unverified. '
                           'No private prompt, signed URLs, peer reply reads, retries or rollback.')
    if action is not None:
        result['topic_state'] = {'action': action, 'field': field, 'value': value, 'verified': True,
                                'closing_schedule_cleared': True if clears_schedule else None}
    if options is not None:
        result['configured_topic_settings'] = {'values': options, 'verified': True,
                                               'reply_visibility_change_acknowledged': acknowledge_reply_visibility}
    if schedule is not None:
        result['scheduled_topic_dates'] = {'requested': schedule, 'stored': {key: after[key] for key in schedule},
                                           'verified': True, 'availability_change_acknowledged': True,
                                           'observed_states': {key: {'before': before[key], 'after': after[key]}
                                                               for key in ('published', 'locked')},
                                           'future_execution_verified': False}
    return result
