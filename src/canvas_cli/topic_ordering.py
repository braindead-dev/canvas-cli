"""Native full pinned-topic ordering, not a pin toggle or personal preference."""

from .client import CanvasError
from .group_content import _number, base
from .topic_management import _inventory, _inventory_delta, _scope
from .writes import account, check_flags, confirmed, digest

WARNING = ('Changes shared pinned-topic order, including graded or section-specific pinned topics, '
           'not your personal dashboard. Every accessible pinned topic must be explicitly included. '
           'Native authorization on a new temporary topic requires read_forum and moderate_forum; '
           'permission on one authored topic is insufficient. Accessible inventory is not proof that '
           'no hidden topics exist; unexpected native IDs/order fail verification. No prompts, entries, '
           'grades, attachments or pin flags are requested changed. Preflight is not atomic; '
           'concurrent ordering can be overwritten. No automatic retry, cleanup or rollback.')
UNCERTAIN = ('Could not verify pinned-topic ordering. It may already have succeeded; check Canvas '
             'before repeating. No automatic retry, rollback or private response-body logging.')


def _authority(client, item, context_type):
    route, context = _scope(client, item, context_type)
    rights, _ = client.request(route + '/permissions?permissions%5B%5D=read_forum&permissions%5B%5D=moderate_forum')
    if not isinstance(rights, dict) or any(rights.get(key) is not True for key in ('read_forum', 'moderate_forum')):
        raise CanvasError('Canvas did not report the native context read/moderation rights for pinned-topic ordering')
    return route, context, {'read_forum': True, 'moderate_forum': True}


def _ordered(rows):
    if any(type(row['pinned']) is not bool for row in rows):
        raise CanvasError('Canvas did not report every accessible topic pin flag')
    pinned = [row for row in rows if row['pinned']]
    if (any(type(row['position']) is not int or row['position'] < 0 for row in pinned) or
            len({row['position'] for row in pinned}) != len(pinned)):
        raise CanvasError('Canvas returned ambiguous pinned-topic positions')
    return [row['id'] for row in sorted(pinned, key=lambda row: row['position'])]


def reorder(client, item, order, *, context_type='course', acknowledge=False, max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    base(item, context_type)
    if context_type not in ('course', 'group') or acknowledge is not True:
        raise CanvasError('Use a course/group context and --acknowledge-all-pinned-topics, including previews')
    if (type(max_pages) is not int or max_pages < 1 or not isinstance(order, (list, tuple)) or not order):
        raise CanvasError('Provide a nonempty full order and positive inventory page limit')
    for identifier in order:
        _number(identifier)
    selected = [int(identifier) for identifier in order]
    if len(set(selected)) != len(selected):
        raise CanvasError('Pinned-topic ordering cannot contain duplicate identifiers')
    identity = account(client)
    route, context, rights = _authority(client, item, context_type)
    before = _inventory(client, route, item, context_type, max_pages)
    previous = _ordered(before)
    if set(selected) != set(previous):
        raise CanvasError('Include every accessible pinned topic exactly once, and no unpinned or foreign topic')
    if selected == previous:
        raise CanvasError('Pinned topics already have the requested order; no write needed')
    if (_authority(client, item, context_type) != (route, context, rights) or
            _inventory(client, route, item, context_type, max_pages) != before or account(client) != identity):
        raise CanvasError('Pinned inventory/context/permissions/account changed during preflight')
    preview = {**identity, 'context_type': context_type, f'{context_type}_id': int(item), 'context': context,
               'permissions': rights, 'previous_order': previous, 'inventory_digest': digest(before),
               'acknowledge_all_pinned_topics': True, 'method': 'POST',
               'route': route + '/discussion_topics/reorder', 'body': {'order': selected}, 'warning': WARNING}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        if (not isinstance(response, dict) or response.get('reorder') is not True or
                response.get('order') != [str(identifier) for identifier in selected]):
            raise CanvasError('Canvas did not acknowledge the exact complete native pinned-topic order')
        if _authority(client, item, context_type) != (route, context, rights) or account(client) != identity:
            raise CanvasError('Pinned-topic context/permissions/account changed during verification')
        after = _inventory(client, route, item, context_type, max_pages)
        if _ordered(after) != selected or account(client) != identity:
            raise CanvasError('Independent pinned inventory does not match the requested order')
    except CanvasError:
        raise CanvasError(UNCERTAIN) from None
    positions = {row['id']: row['position'] for row in after if row['pinned']}
    return {'pinned_topic_order': selected, 'positions': [{'id': identifier, 'position': positions[identifier]} for identifier in selected],
            'context_type': context_type, f'{context_type}_id': int(item), 'order_verified': True,
            'html_url': client.host + f'/{context_type}s/{item}/discussion_topics',
            'observed_inventory_changes': _inventory_delta(before, after),
            'note': 'One native POST and exact native order acknowledgement plus independent paginated position readback verified. '
                    'Account/context/moderation rights remained stable. Observed inventory changes are not exclusive causal proof; '
                    'unseen topics, notifications and other downstream effects are not verified. No private prompt, signed URLs, '
                    'peer replies or raw response emitted; no automatic retry or rollback.'}
