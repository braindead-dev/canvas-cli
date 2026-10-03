"""Own contact-channel metadata and exact, preview-first notification frequencies."""

import re

from .client import CanvasError
from .writes import account, check_flags, confirmed, digest

FREQUENCIES = ('immediately', 'daily', 'weekly', 'never')
READ_NOTE = ('GET only; no selected frequencies are changed. Canvas may create default notification-policy '
             'records when reading preferences. Delivery is not guaranteed, and course-specific overrides '
             'or institution settings may also apply.')


def _number(value):
    if (not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]*', value)):
        raise CanvasError('Expected a positive numeric channel ID')
    return value


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', value):
        raise CanvasError('Use an exact notification/category key from notification-preferences')
    return value


def pairs(values):
    changes = {}
    for value in values:
        if not isinstance(value, str) or value.count('=') != 1:
            raise CanvasError('Use --set NOTIFICATION=immediately|daily|weekly|never')
        name, frequency = value.split('=')
        _name(name)
        if frequency not in FREQUENCIES or name in changes:
            raise CanvasError('Notification keys must be distinct and frequencies must be immediately, daily, weekly or never')
        changes[name] = frequency
    if not changes:
        raise CanvasError('Select at least one notification preference')
    return changes


def _channels(client, user_id, max_pages):
    rows = client.list('/api/v1/users/self/communication_channels?per_page=100', max_pages)
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] < 1 or
                type(row.get('user_id')) is not int or row['user_id'] != user_id or
                not isinstance(row.get('type'), str) or not row['type'] or
                not isinstance(row.get('workflow_state'), str) or not row['workflow_state'] or
                row['workflow_state'] == 'retired'):
            raise CanvasError('Canvas returned an invalid or non-own communication channel')
        if row['id'] in seen:
            raise CanvasError('Canvas returned duplicate communication channel IDs')
        seen.add(row['id'])
    return rows


def _metadata(row, include_address=False):
    fields = ('id', 'user_id', 'type', 'position', 'workflow_state', 'created_at', 'bounce_count',
              'last_bounce_at', 'last_transient_bounce_at', 'last_suppression_bounce_at')
    result = {key: row[key] for key in fields if key in row}
    # Native push addresses can be provider-specific; never dump tokens or bounce summaries.
    if include_address and row['type'] in ('email', 'sms'):
        address = row.get('address')
        if address is not None and not isinstance(address, str):
            raise CanvasError('Canvas returned an invalid communication address')
        result['address'] = address
    return result


def channels(client, max_pages=100, *, include_addresses=False):
    identity = account(client)
    rows = _channels(client, identity['user_id'], max_pages)
    return {**identity, 'communication_channels': [_metadata(row, include_addresses) for row in rows],
            'complete_for_endpoint': True, 'addresses_included': include_addresses,
            'note': 'Own channels only. Email/SMS addresses require --include-addresses; push/provider addresses, '
                    'tokens and bounce summaries are never printed. Channel state does not prove delivery.'}


def _channel(client, channel_id, identity, max_pages):
    rows = _channels(client, identity['user_id'], max_pages)
    row = next((row for row in rows if row['id'] == int(channel_id)), None)
    if row is None:
        raise CanvasError('Channel was not found in your complete own-channel inventory')
    return row


def _preferences(response):
    # Canvas's controller returns this wrapper even though API docs say "list".
    if not isinstance(response, dict) or not isinstance(response.get('notification_preferences'), list):
        raise CanvasError('Canvas returned an invalid notification-preference response')
    result = {}
    for row in response['notification_preferences']:
        if (not isinstance(row, dict) or not isinstance(row.get('notification'), str) or
                not re.fullmatch(r'[a-z][a-z0-9_]*', row['notification']) or
                row.get('frequency') not in FREQUENCIES or
                row.get('category') is not None and not isinstance(row['category'], str)):
            raise CanvasError('Canvas returned invalid notification-preference metadata')
        name = row['notification']
        if name in result:
            raise CanvasError('Canvas returned duplicate notification-preference keys')
        result[name] = {'notification': name, 'frequency': row['frequency'], 'category': row.get('category')}
    return result


def _read(client, channel_id):
    route = f'/api/v1/users/self/communication_channels/{channel_id}/notification_preferences'
    response, links = client.request(route)
    if re.search(r'<[^>]+>;\s*rel="next"', links):
        raise CanvasError('Unexpected preference pagination; refusing an incomplete inventory')
    return _preferences(response)


def preferences(client, channel_id, max_pages=100, *, category=None):
    _number(channel_id)
    if category is not None:
        _name(category)
    identity = account(client)
    channel = _channel(client, channel_id, identity, max_pages)
    inventory = _read(client, channel_id)
    categories = sorted({row['category'] for row in inventory.values() if row['category'] is not None})
    if category is not None and category not in categories:
        raise CanvasError('Category is not reported for this channel; use notification-preferences to see its keys')
    return {**identity, 'channel': _metadata(channel), 'category_filter': category,
            'categories': categories,
            'notification_preferences': [row for _, row in sorted(inventory.items())
                                         if category is None or row['category'] == category],
            'complete_for_endpoint': True, 'note': READ_NOTE}


def change(client, channel_id, changes=None, *, category=None, frequency=None, max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    _number(channel_id)
    if category is not None:
        _name(category)
        if changes is not None or frequency not in FREQUENCIES:
            raise CanvasError('Select one exact category and supported frequency, not mixed explicit notification keys')
    else:
        if frequency is not None or not isinstance(changes, dict) or not changes:
            raise CanvasError('Select at least one notification preference, or a category with frequency')
        for name, value in changes.items():
            _name(name)
            if value not in FREQUENCIES:
                raise CanvasError('Frequency must be immediately, daily, weekly or never')
    identity = account(client)
    channel = _channel(client, channel_id, identity, max_pages)
    inventory = _read(client, channel_id)
    if category is not None:
        changes = {name: frequency for name, row in inventory.items() if row['category'] == category}
        if not changes:
            raise CanvasError('Category is not reported for this channel; no change requested')
    if any(name not in inventory for name in changes):
        raise CanvasError('A requested notification is not reported for this channel; no change requested')
    current = {name: inventory[name] for name in sorted(changes)}
    revision = {key: channel.get(key) for key in ('id', 'user_id', 'type', 'address', 'workflow_state', 'created_at')}
    preview = {**identity, 'channel': _metadata(channel), 'channel_revision': digest(revision),
               'current_preferences': current, 'requested_frequencies': dict(sorted(changes.items())),
               'method': 'PUT', 'route': f'/api/v1/users/self/communication_channels/{channel_id}/notification_preferences',
               'body': {'notification_preferences': {name: {'frequency': frequency}
                                                     for name, frequency in sorted(changes.items())}},
               'effect': 'Set only the named notification frequencies on this own channel, across its notifications. '
                         'Does not add/delete a channel, alter enrollment or mark Inbox messages read.',
               'warning': 'Use channels --include-addresses to identify email/SMS destinations before confirming. '
                          'Disabling notifications can hide deadline emails. Native batch updates may partially apply '
                          'before an error; verify in Canvas before repeating. ' + READ_NOTE}
    selection = {'category': category, 'notification_count': len(changes),
                 'scope': 'Only exact notification keys currently reported in this category; no future or unreported keys.'}
    if category is not None:
        preview['category_selection'] = selection
        preview['warning'] += (' Category selection expands to the exact listed keys in the batch, not a broad category '
                               'mutation. Added/removed/recategorized keys before confirmation require a fresh preview.')
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        accepted = _preferences(response)
        if set(accepted) != set(changes) or any(accepted[name]['frequency'] != frequency or
                accepted[name]['category'] != current[name]['category'] for name, frequency in changes.items()):
            raise CanvasError('Preference acknowledgement mismatch')
    except CanvasError:
        raise CanvasError('Could not verify Canvas notification changes. The batch may have partially applied; '
                          'check Canvas before repeating. No automatic retries or response-body logging.') from None
    result = {**identity, 'channel': _metadata(channel),
            'notification_changes': [row for _, row in sorted(accepted.items())], 'acknowledged': True,
            'note': 'Canvas acknowledged the selected frequencies only. Unselected preferences were not sent. '
                    'Delivery and course overrides are not verified; no read-marker or channel changes were requested.'}
    if category is not None:
        result['category_selection'] = selection
    return result
