"""Own contact methods, with native confirmation and independently verified removal."""

import re

from .client import CanvasError
from .writes import account, check_flags, confirmed, digest

FIELDS = ('id', 'user_id', 'type', 'position', 'workflow_state', 'created_at', 'bounce_count',
          'last_bounce_at', 'last_transient_bounce_at', 'last_suppression_bounce_at')
WRITE_NOTE = ('Native confirmation/delivery, login recovery, institution restrictions and concurrent changes '
              'are not verified. No automatic retries; no enrollment or Inbox changes were requested.')


def number(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]*', value):
        raise CanvasError('Expected a positive numeric channel ID')
    return value


def _record(row, user_id, *, retired=False):
    if (not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] < 1 or
            type(row.get('user_id')) is not int or row['user_id'] != user_id or
            not isinstance(row.get('type'), str) or not row['type'] or
            not isinstance(row.get('workflow_state'), str) or not row['workflow_state'] or
            (row['workflow_state'] == 'retired') != retired):
        raise CanvasError('Canvas returned an invalid or non-own communication channel')
    metadata(row)
    return row


def metadata(row, include_address=False):
    result = {}
    for key in FIELDS:
        if key not in row:
            continue
        value = row[key]
        if key in ('id', 'user_id', 'position', 'bounce_count'):
            valid = value is None or type(value) is int
        else:
            valid = value is None or isinstance(value, str)
        if not valid:
            raise CanvasError('Canvas returned malformed communication-channel metadata; no record was printed')
        result[key] = value
    # Native push/provider addresses are not contact addresses and can contain tokens.
    if include_address and row['type'] in ('email', 'sms'):
        address = row.get('address')
        if address is not None and not isinstance(address, str):
            raise CanvasError('Canvas returned an invalid communication address')
        result['address'] = address
    return result


def inventory(client, user_id, max_pages):
    rows = client.list('/api/v1/users/self/communication_channels?per_page=100', max_pages)
    seen = set()
    for row in rows:
        _record(row, user_id)
        if row['id'] in seen:
            raise CanvasError('Canvas returned duplicate communication channel IDs')
        seen.add(row['id'])
    return rows


def select(client, channel_id, identity, max_pages):
    number(channel_id)
    rows = inventory(client, identity['user_id'], max_pages)
    row = next((row for row in rows if row['id'] == int(channel_id)), None)
    if row is None:
        raise CanvasError('Channel was not found in your complete own-channel inventory')
    return row


def listing(client, max_pages=100, *, include_addresses=False):
    identity = account(client)
    rows = inventory(client, identity['user_id'], max_pages)
    return {**identity, 'communication_channels': [metadata(row, include_addresses) for row in rows],
            'complete_for_endpoint': True, 'addresses_included': include_addresses,
            'note': 'Own channels only. Email/SMS addresses require --include-addresses; push/provider addresses, '
                    'tokens and bounce summaries are never printed. Channel state does not prove delivery.'}


def _address(value):
    if (not isinstance(value, str) or not value or len(value) > 1024 or value != value.strip() or
            any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)):
        raise CanvasError('A contact address must be one trimmed, control-free line of at most 1024 characters')
    return value


def _revision(rows):
    # Bind every reported channel, including ordering and addresses, without displaying private destinations.
    fields = ('id', 'user_id', 'type', 'address', 'position', 'workflow_state', 'created_at')
    return digest([{key: row.get(key) for key in fields} for row in sorted(rows, key=lambda item: item['id'])])


def _ack(response, identity, channel_type, address, *, channel_id=None, retired=False):
    try:
        row = _record(response, identity['user_id'], retired=retired)
        if (row['type'] != channel_type or row.get('address') != address or
                channel_id is not None and str(row['id']) != channel_id or
                not retired and row['workflow_state'] not in ('active', 'unconfirmed')):
            raise CanvasError('Contact acknowledgement mismatch')
    except CanvasError:
        raise CanvasError('Contact write outcome uncertain. Check Canvas before repeating; '
                          'no automatic retries or response-body logging.') from None
    return row


def _verify(client, identity, expected, max_pages, *, deleted=False):
    try:
        rows = inventory(client, identity['user_id'], max_pages)
        row = next((row for row in rows if row['id'] == expected['id']), None)
        if deleted:
            if row is not None:
                raise CanvasError('Contact is still listed')
        elif (row is None or row.get('address') != expected['address'] or row['type'] != expected['type'] or
              row['workflow_state'] not in ('active', 'unconfirmed')):
            raise CanvasError('Contact read-back mismatch')
        if account(client) != identity:
            raise CanvasError('Account changed during verification')
    except CanvasError:
        raise CanvasError('Contact write was acknowledged, but the full own-channel inventory could not verify it. '
                          'Check Canvas before repeating; no automatic retries.') from None
    return metadata(expected if deleted else row)


def create(client, channel_type, address, *, acknowledge_message=False, max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    if channel_type not in ('email', 'sms'):
        raise CanvasError('Contact creation supports email or SMS; push registration requires a separate developer-key/provider workflow')
    _address(address)
    if not acknowledge_message:
        raise CanvasError('Use --acknowledge-contact-message to acknowledge a native confirmation message to this contact')
    identity = account(client)
    rows = inventory(client, identity['user_id'], max_pages)
    for row in rows:
        if row['type'] == channel_type:
            existing = _address(row.get('address'))
            if existing.lower() == address.lower():
                raise CanvasError('This contact is already in your own inventory; creation is not a confirmation-resend command')
    preview = {**identity, 'current_channels_revision': _revision(rows), 'method': 'POST',
               'route': '/api/v1/users/self/communication_channels',
               'body': {'communication_channel': {'type': channel_type, 'address': address}, 'skip_confirmation': False},
               'acknowledge_contact_message': True,
               'effect': 'Adds or reactivates this one own contact. Canvas can send it an email/SMS confirmation; '
                         'you must complete native confirmation yourself. No push token, confirmation bypass or login creation is requested. '
                         'Retired contacts are not listed, so a new ID is not guaranteed. '
                         'Native address validation, institution restrictions and capacity limits still apply.'}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    accepted = _ack(response, identity, channel_type, address)
    if accepted['id'] in {row['id'] for row in rows}:
        raise CanvasError('Contact write outcome uncertain: an already-visible channel was returned. '
                          'Check Canvas before repeating; no automatic retries.')
    result = _verify(client, identity, accepted, max_pages)
    return {**identity, 'channel_change': result, 'deleted': False, 'verified': True,
            'confirmation_required': result['workflow_state'] == 'unconfirmed',
            'note': 'Exact own contact and reported state verified by a separate full inventory. '
                    'Addresses are omitted from this result. Complete native confirmation if unconfirmed. ' + WRITE_NOTE}


def delete(client, channel_id, *, acknowledge_removal=False, max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    number(channel_id)
    if not acknowledge_removal:
        raise CanvasError('Use --acknowledge-contact-removal; removing a contact can stop alerts and change the primary/recovery email')
    identity = account(client)
    rows = inventory(client, identity['user_id'], max_pages)
    row = next((row for row in rows if str(row['id']) == channel_id), None)
    if row is None:
        raise CanvasError('Channel was not found in your complete own-channel inventory')
    address = row.get('address')
    if not isinstance(address, str) or not address:
        raise CanvasError('Canvas did not identify the exact contact destination')
    preview = {**identity, 'channel': metadata(row), 'current_channels_revision': _revision(rows),
               'method': 'DELETE', 'route': f'/api/v1/users/self/communication_channels/{channel_id}',
               'acknowledge_contact_removal': True,
               'effect': 'Retires only this exact own channel. It can stop notification delivery, change the primary email '
                         'or disrupt account recovery/integrations, including when it is your last contact. '
                         'Removing a push channel can disable notifications for all its devices; this is not individual token revocation. '
                         'Institution-managed contacts and OTP-linked SMS may be refused by Canvas. '
                         'Use channels --include-addresses to identify email/SMS destinations first; provider addresses stay private.'}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    accepted = _ack(response, identity, row['type'], address, channel_id=channel_id, retired=True)
    result = _verify(client, identity, accepted, max_pages, deleted=True)
    return {**identity, 'channel_change': result, 'deleted': True, 'verified': True,
            'note': 'Exact own retired-channel acknowledgement and absence from a separate full inventory verified. '
                    'Primary-email, login recovery and integration behavior are not independently verified. ' + WRITE_NOTE}
