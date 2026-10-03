"""Exact native ungraded-topic edits/deletion, not replies or assignment administration."""

from .client import CanvasError
from .discussion import _message
from .events import timestamp
from .group_content import _context, _id, _number, base
from .writes import account, check_flags, confirmed, digest

FIELDS = ('id', 'title', 'published', 'locked', 'pinned', 'position', 'created_at', 'posted_at',
          'last_reply_at', 'delayed_post_at', 'lock_at', 'todo_date', 'discussion_type',
          'discussion_subentry_count', 'require_initial_post', 'is_section_specific',
          'allow_rating', 'only_graders_can_rate', 'sort_order', 'sort_order_locked', 'expanded', 'expanded_locked')
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
            ('allow_rating', 'only_graders_can_rate', 'sort_order_locked', 'expanded', 'expanded_locked')) or
            any(row.get(key) is not None and not isinstance(row[key], str) for key in ('discussion_type', 'sort_order'))):
        raise CanvasError('Canvas returned malformed topic options')
    return {**{key: row.get(key) for key in FIELDS}, 'author_id': author_id,
            'message_digest': digest(row['message'] or ''), 'attachments': sorted(attached, key=lambda row: row['id']),
            'section_ids': sorted(section_ids), 'audience_digest': digest(row.get('ungraded_discussion_overrides')),
            'permissions': {key: permissions[key] for key in ('update', 'delete')}}


def _scope(client, item, context_type):
    route, row = _context(client, item, context_type)
    if row.get('workflow_state') == 'deleted':
        raise CanvasError('The discussion context is deleted')
    if (any(row.get(key) is not None and not isinstance(row[key], str) for key in ('name', 'workflow_state')) or
            any(row.get(key) is not None and type(row[key]) is not bool for key in ('concluded', 'non_collaborative'))):
        raise CanvasError('Canvas returned malformed discussion context metadata')
    return route, {key: row.get(key) for key in ('id', 'name', 'workflow_state', 'concluded', 'non_collaborative')}


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


def change(client, item, topic_id, *, context_type='course', title=None, message=None, delete=False,
           acknowledge_shared=False, acknowledge_removal=False, max_pages=100, yes=False, confirm=None):
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
    if delete and (title is not None or message is not None):
        raise CanvasError('Topic deletion cannot include content edits')
    changes = None if delete else _changes(title, message)
    identity = account(client)
    route, context = _scope(client, item, context_type)
    before = _read(client, route, item, topic_id, context_type)
    permission = 'delete' if delete else 'update'
    if before['permissions'][permission] is not True:
        raise CanvasError('Canvas does not permit this exact discussion-topic ' + permission)
    if not delete and all(before['message_digest'] == digest(value) if key == 'message' else before[key] == value
                          for key, value in changes.items()):
        raise CanvasError('The selected topic text already matches; no edit needed')
    inventory = _inventory(client, route, item, context_type, max_pages)
    listed = {key: before[key] for key in ('id', 'title', 'published', 'locked', 'pinned', 'position')}
    if listed not in inventory or _read(client, route, item, topic_id, context_type) != before or account(client) != identity:
        raise CanvasError('Discussion/account changed during preflight; review a fresh preview')
    preview = {**identity, 'context_type': context_type, f'{context_type}_id': int(item), 'context': context,
               'topic': before, 'inventory_digest': digest(inventory), 'acknowledge_shared_topic': True,
               'acknowledge_topic_removal': acknowledge_removal, 'method': 'DELETE' if delete else 'PUT',
               'route': route + '/discussion_topics/' + topic_id + '?no_verifiers=true', 'body': changes, 'warning': WARNING}
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
              after['permissions']['update'] is not True):
            raise CanvasError('Stored topic acknowledgement and readback do not agree')
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
    matched = {key: after['message_digest'] == digest(value) if key == 'message' else after[key] == value
               for key, value in changes.items()}
    changed = [key for key in before if before[key] != after[key]]
    requested = {'message_digest' if key == 'message' else key for key in changes}
    return {'edited_topic': {**after, 'html_url': client.host + f'/{context_type}s/{item}/discussion_topics/{topic_id}'},
            'context_type': context_type, f'{context_type}_id': int(item), 'acknowledgement_matches_readback': True,
            'stored_text_matches_request': matched, 'changed_fields': changed,
            'unrequested_changed_fields': [key for key in changed if key not in requested],
            'note': 'One native PUT and independent exact-topic readback with stable account/context verified. '
                    'Requested-text equality and other observed field changes are labeled; native HTML rewriting is not hidden. '
                    'No private prompt, attachment URLs or raw response emitted, no reply/read-marker write, retry or rollback.'}
