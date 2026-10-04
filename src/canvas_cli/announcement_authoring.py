"""Native announcement authoring, distinct from discussion drafts and replies."""

from datetime import datetime, timedelta, timezone

from .client import CanvasError
from .events import timestamp
from .group_content import _id, _number, base
from .topic_dates import instant, matches
from .topic_management import (
    _changes,
    _inventory,
    _inventory_delta,
    _matches,
    _parent,
    _read,
    _scope,
    _topic,
)
from .writes import account, check_flags, confirmed, digest

WARNING = ('Changes a shared announcement, not a private draft, reply or note. Native announcements '
           'are always published; future posting is scheduling, not draft privacy. Creation/updates '
           'can notify participants and observers and update activity/participant records. Delivery '
           'and future execution are not verified. Native permissions, HTML processing, course comment '
           'locks and blueprint restrictions remain authoritative. Deletion does not recall notifications '
           'or prove permanent erasure. No peer replies, grading, attachments, audience/settings changes, '
           'automatic retry, cleanup or rollback are requested. Preflight is not an atomic lock.')
UNCERTAIN = ('Could not verify the announcement operation. It may already have succeeded; check Canvas '
             'before repeating. No automatic retry, cleanup, rollback or private response-body logging.')


def _local(item, context_type, max_pages, acknowledge_shared):
    if context_type not in ('course', 'group'):
        raise CanvasError('Announcement authoring requires a course or group context')
    base(item, context_type)
    if acknowledge_shared is not True or type(max_pages) is not int or max_pages < 1:
        raise CanvasError('Use --acknowledge-shared-announcement and a positive inventory limit, including previews')


def _posting(value, context_type):
    if value is None:
        return None
    if context_type != 'course':
        raise CanvasError('Native group announcement creation does not accept posting dates')
    value = instant(value)
    if timestamp(value) <= datetime.now(timezone.utc) + timedelta(seconds=60):
        raise CanvasError('Scheduled announcement posting must remain at least 60 seconds in the future')
    return value


def _published(parsed):
    if parsed['published'] is not True or parsed['can_unpublish'] is not False:
        raise CanvasError('Canvas did not report native always-published, non-draft announcement semantics')
    return {**parsed, 'is_announcement': True}


def _metadata(row, item, identifier, context_type):
    return _published(_topic(row, item, identifier, context_type, announcement=True))


def _current(client, route, item, identifier, context_type):
    return _published(_read(client, route, item, identifier, context_type, announcement=True))


def _listed(row):
    return {key: row[key] for key in ('id', 'title', 'published', 'locked', 'pinned', 'position')}


def _creation_rights(client, item, context_type):
    route, context = _scope(client, item, context_type)
    row, _ = client.request(route + '?include%5B%5D=permissions')
    if _id(row) != int(item) or {key: row.get(key) for key in context} != context:
        raise CanvasError('Announcement context changed while reading native creation permission')
    rights = row.get('permissions')
    if not isinstance(rights, dict) or rights.get('create_announcement') is not True:
        raise CanvasError('Canvas did not grant dynamic native announcement creation in this context')
    return route, context


def create(client, item, *, title, message, context_type='course', post_at=None, comments=False,
           acknowledge_shared=False, acknowledge_broadcast=False, max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    _local(item, context_type, max_pages, acknowledge_shared)
    if acknowledge_broadcast is not True or type(comments) is not bool or title is None or message is None:
        raise CanvasError('Announcement creation needs a title, message, boolean comment choice and --acknowledge-broadcast')
    body = {**_changes(title, message), 'is_announcement': True, 'lock_comment': not comments}
    posting = _posting(post_at, context_type)
    if posting is not None:
        body['delayed_post_at'] = posting
    identity = account(client)
    route, context = _creation_rights(client, item, context_type)
    inventory = _inventory(client, route, item, context_type, max_pages, announcement=True)
    if (_creation_rights(client, item, context_type) != (route, context) or
            _inventory(client, route, item, context_type, max_pages, announcement=True) != inventory or
            account(client) != identity):
        raise CanvasError('Announcement context, permission, inventory or account changed during preflight')
    _posting(posting, context_type)
    preview = {**identity, 'context_type': context_type, f'{context_type}_id': int(item), 'context': context,
               'permissions': {'create_announcement': True}, 'inventory_digest': digest(inventory),
               'acknowledge_shared_announcement': True, 'acknowledge_broadcast': True,
               'posting_choice': 'scheduled' if posting else 'post_now',
               'method': 'POST', 'route': route + '/discussion_topics?no_verifiers=true', 'body': body, 'warning': WARNING}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        identifier = _id(response)
        if identifier in {row['id'] for row in inventory}:
            raise CanvasError('Canvas acknowledged an existing announcement')
        after = _metadata(response, item, str(identifier), context_type)
        if (after['author_id'] != identity['user_id'] or after['locked'] is not (not comments) or
                not matches(after, 'delayed_post_at', posting)):
            raise CanvasError('Canvas did not store the requested announcement author/comment state/posting instant')
        if (_creation_rights(client, item, context_type) != (route, context) or account(client) != identity or
                _current(client, route, item, str(identifier), context_type) != after):
            raise CanvasError('Announcement acknowledgement and independent readback do not agree')
        remaining = _inventory(client, route, item, context_type, max_pages, announcement=True)
        if _listed(after) not in remaining or account(client) != identity:
            raise CanvasError('The new announcement was not verified in the complete accessible inventory')
    except CanvasError:
        raise CanvasError(UNCERTAIN) from None
    return {'created_announcement': {**after, 'html_url': client.host + f'/{context_type}s/{item}/discussion_topics/{identifier}'},
            'context_type': context_type, f'{context_type}_id': int(item), 'new_id_verified': True,
            'acknowledgement_matches_readback': True,
            'stored_text_matches_request': {key: _matches(after, key, body[key]) for key in ('title', 'message')},
            'comments_locked': after['locked'], 'stored_posting_at': after['delayed_post_at'],
            'future_execution_verified': False, 'notification_delivery_verified': False,
            'observed_inventory_changes': _inventory_delta(inventory, remaining),
            'note': 'One native POST, own author/new announcement ID, exact comment/date state and independent '
                    'topic/inventory readback verified with stable identity/context/creation permission. '
                    'Text normalization and other inventory changes are labeled. Published is not delivery or '
                    'availability proof; no private prompt, peer replies, retry or cleanup.'}


def change(client, item, identifier, *, context_type='course', title=None, message=None, delete=False,
           acknowledge_shared=False, acknowledge_broadcast=False, acknowledge_removal=False,
           max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    _local(item, context_type, max_pages, acknowledge_shared)
    _number(identifier)
    if (type(delete) is not bool or type(acknowledge_removal) is not bool or delete != acknowledge_removal or
            type(acknowledge_broadcast) is not bool or acknowledge_broadcast != (not delete)):
        raise CanvasError('Editing requires --acknowledge-broadcast; deletion instead needs --acknowledge-announcement-removal')
    if delete and (title is not None or message is not None):
        raise CanvasError('Announcement deletion cannot include text edits')
    changes = None if delete else _changes(title, message)
    identity = account(client)
    route, context = _scope(client, item, context_type)
    before = _current(client, route, item, identifier, context_type)
    if before['permissions']['delete' if delete else 'update'] is not True:
        raise CanvasError('Canvas does not permit this exact announcement operation')
    if not delete and all(_matches(before, key, value) for key, value in changes.items()):
        raise CanvasError('The announcement text already matches; no update needed')
    inventory = _inventory(client, route, item, context_type, max_pages, announcement=True)
    if (_listed(before) not in inventory or _current(client, route, item, identifier, context_type) != before or
            _scope(client, item, context_type) != (route, context) or
            _inventory(client, route, item, context_type, max_pages, announcement=True) != inventory or account(client) != identity):
        raise CanvasError('Announcement/context/inventory/account changed during preflight')
    # Native text updates otherwise default locked=false. lock_comment preserves
    # the current state without sending locked or changing the creator preference.
    body = None if delete else {**changes, 'is_announcement': True, 'lock_comment': before['locked']}
    preview = {**identity, 'context_type': context_type, f'{context_type}_id': int(item), 'context': context,
               'announcement': before, 'inventory_digest': digest(inventory),
               'acknowledge_shared_announcement': True, 'acknowledge_broadcast': acknowledge_broadcast,
               'acknowledge_announcement_removal': acknowledge_removal, 'method': 'DELETE' if delete else 'PUT',
               'route': route + '/discussion_topics/' + identifier + '?no_verifiers=true', 'body': body, 'warning': WARNING}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        if _scope(client, item, context_type) != (route, context) or account(client) != identity:
            raise CanvasError('Announcement context/account changed during verification')
        if delete:
            if _id(response) != int(identifier) or response.get('workflow_state') != 'deleted' or response.get('type') != 'Announcement':
                raise CanvasError('Canvas did not acknowledge the exact native announcement soft deletion')
            _parent(response, item, context_type)
            remaining = _inventory(client, route, item, context_type, max_pages, announcement=True)
            if any(row['id'] == int(identifier) for row in remaining):
                raise CanvasError('Deleted announcement remains in the active inventory')
            try:
                _current(client, route, item, identifier, context_type)
            except CanvasError as error:
                if error.status not in (404, 410):
                    raise
                missing_status = error.status
            else:
                raise CanvasError('Deleted announcement remains readable')
        else:
            after = _metadata(response, item, identifier, context_type)
            if (_current(client, route, item, identifier, context_type) != after or after['locked'] is not before['locked']):
                raise CanvasError('Announcement readback or preserved comment lock did not agree')
            remaining = _inventory(client, route, item, context_type, max_pages, announcement=True)
            if _listed(after) not in remaining:
                raise CanvasError('Edited announcement is absent from its accessible inventory')
        if account(client) != identity:
            raise CanvasError('Account changed during announcement verification')
    except CanvasError:
        raise CanvasError(UNCERTAIN) from None
    shared = {'context_type': context_type, f'{context_type}_id': int(item),
              'observed_inventory_changes': _inventory_delta(inventory, remaining),
              'notification_delivery_verified': False}
    if delete:
        return {**shared, 'deleted_announcement': {'id': int(identifier), 'title': before['title']},
                'removed_from_active_inventory': True, 'exact_id_read_status': missing_status,
                'note': 'Native announcement soft deletion, active-inventory absence and exact-ID not-found '
                        'verified with stable context/account. No permanent-erasure, attachment cleanup or '
                        'notification-recall proof; no retry or rollback.'}
    requested = {'message_digest' if key == 'message' else key for key in changes}
    changed = [key for key in before if before[key] != after[key]]
    return {**shared, 'edited_announcement': {**after, 'html_url': client.host + f'/{context_type}s/{item}/discussion_topics/{identifier}'},
            'acknowledgement_matches_readback': True, 'comment_lock_preserved': True,
            'stored_text_matches_request': {key: _matches(after, key, value) for key, value in changes.items()},
            'changed_fields': changed, 'unrequested_changed_fields': [key for key in changed if key not in requested],
            'note': 'One native PUT, independent announcement/inventory readback and preserved comment lock '
                    'verified with stable context/account. HTML normalization and other observed changes are '
                    'labeled, not causal proof. No private prompt, peer replies, explicit preference write, retry or rollback.'}
