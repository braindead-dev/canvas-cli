"""Native Scheduler discovery and own individual reservations, never allocation."""

import re
from datetime import datetime, timezone
from urllib.parse import urlencode

from .client import CanvasError
from .events import read as read_event
from .events import timestamp
from .writes import account, check_flags, confirmed, digest

GROUP_FIELDS = ('id', 'title', 'start_at', 'end_at', 'location_name', 'location_address',
                'context_codes', 'sub_context_codes', 'workflow_state', 'participant_type',
                'participant_visibility', 'requiring_action', 'appointments_count',
                'min_appointments_per_participant', 'max_appointments_per_participant',
                'participants_per_appointment', 'html_url', 'created_at', 'updated_at')
EVENT_FIELDS = ('id', 'appointment_group_id', 'parent_event_id', 'context_code',
                'title', 'start_at', 'end_at', 'workflow_state', 'participant_type',
                'location_name', 'location_address', 'reserved', 'available_slots',
                'participants_per_appointment', 'updated_at', 'html_url')
NOTE = ('Native Scheduler metadata, not external advising appointments. Availability can change; '
        'empty results do not prove no office hours. Other participants and their comments are omitted.')


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]*', value):
        raise CanvasError('Expected a positive appointment group, slot or reservation ID')
    return value


def _numeric(value):
    return type(value) is int and value > 0


def _project(record, fields):
    # Even whitelisted scalar fields must not carry unexpected nested private data.
    result = {}
    for key in fields:
        if key in record:
            value = record[key]
            if key in ('context_codes', 'sub_context_codes'):
                valid = isinstance(value, list) and all(isinstance(item, str) for item in value)
            else:
                valid = value is None or type(value) in (str, int, bool)
            if not valid:
                raise CanvasError('Canvas returned malformed appointment metadata; no record was printed')
            result[key] = value
    return result


def _slot(record, group):
    if (not isinstance(record, dict) or not _numeric(record.get('id')) or
            type(record.get('appointment_group_id')) is not int or record['appointment_group_id'] != group['id'] or
            record.get('context_code') != f"appointment_group_{group['id']}" or
            record.get('participant_type') != group['participant_type'] or
            record.get('parent_event_id') is not None or record.get('hidden') or record.get('locked_for_user') or
            record.get('workflow_state') not in ('active', 'locked')):
        raise CanvasError('Canvas returned a different, inaccessible or malformed appointment slot')
    for key in ('available_slots', 'participants_per_appointment'):
        if record.get(key) is not None and (type(record[key]) is not int or record[key] < 0):
            raise CanvasError('Canvas returned malformed slot capacity metadata')
    if 'reserved' in record and type(record['reserved']) is not bool:
        raise CanvasError('Canvas returned malformed own-reservation status')
    result = _project(record, EVENT_FIELDS)
    if group['participant_type'] == 'Group':
        result.pop('reserved', None)
    return result


def _group(record, *, include_details=False, slots=False):
    if (not isinstance(record, dict) or not _numeric(record.get('id')) or
            record.get('workflow_state') != 'active' or record.get('participant_type') not in ('User', 'Group') or
            not isinstance(record.get('context_codes'), list) or not record['context_codes'] or
            any(not isinstance(code, str) or not re.fullmatch(r'course_[1-9][0-9]*', code)
                for code in record['context_codes'])):
        raise CanvasError('Canvas returned an unpublished, foreign or malformed appointment group')
    result = _project(record, GROUP_FIELDS)
    for key in ('min_appointments_per_participant', 'max_appointments_per_participant', 'participants_per_appointment'):
        if record.get(key) is not None and (type(record[key]) is not int or record[key] < 0):
            raise CanvasError('Canvas returned malformed appointment limits')
    times = record.get('reserved_times')
    if not isinstance(times, list):
        raise CanvasError('Canvas did not report the own reservation inventory')
    seen, reservations = set(), []
    for item in times:
        if not isinstance(item, dict) or not _numeric(item.get('id')) or item['id'] in seen:
            raise CanvasError('Canvas returned malformed or duplicate own reservations')
        seen.add(item['id'])
        reservations.append(_project(item, ('id', 'start_at', 'end_at')))
    # Native reserved_times is a user-only association; it is not an inventory of a candidate group's bookings.
    result['reserved_times'] = sorted(reservations, key=lambda item: item['id']) if record['participant_type'] == 'User' else None
    if include_details:
        result.update(_project(record, ('description',)))
    if slots:
        if not isinstance(record.get('appointments'), list):
            raise CanvasError('Canvas did not report the appointment slot inventory')
        result['appointments'] = [_slot(item, result) for item in record['appointments']]
        ids = [item['id'] for item in result['appointments']]
        if len(ids) != len(set(ids)):
            raise CanvasError('Canvas returned duplicate appointment slots')
    return result


def _groups(client, max_pages, courses=(), include_past=False, include_details=False):
    for course in courses:
        _id(course)
    query = [('scope', 'reservable'), ('per_page', '100'), ('include[]', 'reserved_times'),
             ('include_past_appointments', 'true' if include_past else 'false')]
    query.extend(('context_codes[]', f'course_{course}') for course in dict.fromkeys(courses))
    rows = client.list('/api/v1/appointment_groups?' + urlencode(query), max_pages)
    groups = [_group(row, include_details=include_details) for row in rows]
    ids = [row['id'] for row in groups]
    if len(ids) != len(set(ids)):
        raise CanvasError('Canvas returned duplicate appointment groups')
    if courses and any(not set(row['context_codes']) & {f'course_{course}' for course in courses} for row in groups):
        raise CanvasError('Canvas returned appointment groups outside the selected courses')
    return groups


def listing(client, max_pages=100, *, courses=(), include_past=False, include_details=False):
    return {'appointment_groups': _groups(client, max_pages, courses, include_past, include_details),
            'scope': 'reservable', 'include_past': include_past, 'note': NOTE}


def _read_group(client, group_id, include_details=False):
    record, _ = client.request(f'/api/v1/appointment_groups/{_id(group_id)}?include%5B%5D=reserved_times')
    group = _group(record, include_details=include_details, slots=True)
    if str(group['id']) != group_id:
        raise CanvasError('Canvas returned a different appointment group')
    return group


def read(client, group_id, *, include_details=False):
    return {'appointment_group': _read_group(client, group_id, include_details), 'note': NOTE}


def _future(record):
    first, last = timestamp(record.get('start_at')), timestamp(record.get('end_at'))
    if last <= first or last <= datetime.now(timezone.utc):
        raise CanvasError('Only a current or future slot with valid start/end times can change reservations')


def _individual(group):
    if group['participant_type'] != 'User':
        raise CanvasError('This appointment requires a group booking; individual reservation commands cannot change it')


def _own(record, identity, group_id, slot_id, *, reservation_id=None, deleted=False):
    if (not isinstance(record, dict) or not _numeric(record.get('id')) or
            reservation_id is not None and str(record['id']) != reservation_id or
            record.get('context_code') != f"user_{identity['user_id']}" or record.get('participant_type') != 'User' or
            type(record.get('appointment_group_id')) is not int or str(record['appointment_group_id']) != group_id or
            type(record.get('parent_event_id')) is not int or str(record['parent_event_id']) != slot_id or
            record.get('workflow_state') not in (('deleted',) if deleted else ('active', 'locked')) or
            record.get('group') is not None or record.get('series_uuid') or record.get('rrule') or
            record.get('user') is not None and (not isinstance(record['user'], dict) or
                type(record['user'].get('id')) is not int or record['user']['id'] != identity['user_id']) or
            record.get('hidden') or record.get('locked_for_user')):
        raise CanvasError('Canvas did not confirm the exact own individual appointment reservation')
    return _project(record, EVENT_FIELDS)


def _ack(result, group_id, slot_id, *, reservation_id=None, deleted=False):
    # Native acknowledgements may display a course context, not the underlying User.
    # Validate the relation here; a separate GET without child events proves own ownership/state.
    if (not isinstance(result, dict) or not _numeric(result.get('id')) or
            reservation_id is not None and str(result['id']) != reservation_id or
            type(result.get('appointment_group_id')) is not int or str(result['appointment_group_id']) != group_id or
            type(result.get('parent_event_id')) is not int or str(result['parent_event_id']) != slot_id or
            result.get('participant_type') != 'User' or
            result.get('workflow_state') not in (('deleted',) if deleted else ('active', 'locked'))):
        raise CanvasError('Appointment write outcome uncertain; check Canvas before repeating. No automatic retries.')
    return str(result['id'])


def _verify(client, result, identity, group_id, slot_id, *, reservation_id=None, deleted=False,
            expected=None, comments=None):
    new_id = _ack(result, group_id, slot_id, reservation_id=reservation_id, deleted=deleted)
    try:
        record = read_event(client, new_id, exclude_children=True)
        reservation = _own(record, identity, group_id, slot_id, reservation_id=new_id, deleted=deleted)
        if expected and any(timestamp(record.get(key)) != timestamp(expected.get(key)) for key in ('start_at', 'end_at')):
            raise CanvasError('Reservation time changed')
        if comments is not None and record.get('comments') != comments:
            raise CanvasError('Reservation comments changed')
    except CanvasError:
        raise CanvasError('Appointment write was acknowledged, but own state could not be verified. '
                          'Check Canvas before repeating; no automatic retries.') from None
    return {'appointment_reservation': reservation, 'cancelled': deleted,
            'note': 'Exact own individual reservation state verified by a separate read. '
                    'The organizer may receive native notifications; no other reservation was intentionally changed.'}


def reserve(client, group_id, slot_id, *, comments=None, max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    _id(group_id); _id(slot_id)
    if comments is not None and (not isinstance(comments, str) or len(comments) > 10000):
        raise CanvasError('Reservation comments must be text of at most 10000 characters')
    identity = account(client)
    groups = _groups(client, max_pages)
    group = next((row for row in groups if str(row['id']) == group_id), None)
    if group is None:
        raise CanvasError('This appointment group is not in the current own reservable inventory')
    _individual(group)
    slot = _slot(read_event(client, slot_id, exclude_children=True), group)
    _future(slot)
    if slot.get('reserved') is not False:
        raise CanvasError('Canvas must report this slot as not already reserved by you')
    if slot.get('available_slots') == 0:
        raise CanvasError('This appointment slot is full')
    limit = group.get('max_appointments_per_participant')
    if limit is not None and len(group['reserved_times']) >= limit:
        raise CanvasError('The reported per-participant reservation limit is already met; existing bookings are not replaced')
    body = {'participant_id': identity['user_id'], 'cancel_existing': False}
    if comments is not None:
        body['comments'] = comments
    preview = {**identity, 'appointment_group': group, 'slot': slot, 'method': 'POST',
               'route': f'/api/v1/calendar_events/{slot_id}/reservations', 'body': body,
               'effect': 'Reserves this one slot for you, never another user/group. Existing bookings are not cancelled. '
                         'Comments are shared with the organizer; native notifications can be sent. '
                         'Availability and authorization can change after this preview.'}
    result = confirmed(client, preview, yes, confirm)
    return _verify(client, result, identity, group_id, slot_id, expected=slot, comments=comments) if yes else result


def cancel(client, group_id, reservation_id, *, reason=None, yes=False, confirm=None):
    check_flags(yes, confirm)
    _id(group_id); _id(reservation_id)
    if reason is not None and (not isinstance(reason, str) or len(reason) > 10000):
        raise CanvasError('Cancellation reason must be text of at most 10000 characters')
    identity = account(client)
    group = _read_group(client, group_id)
    _individual(group)
    record = read_event(client, reservation_id, exclude_children=True)
    slot_id = str(record.get('parent_event_id'))
    reservation = _own(record, identity, group_id, slot_id, reservation_id=reservation_id)
    _future(reservation)
    if int(reservation_id) not in {item['id'] for item in group['reserved_times']}:
        raise CanvasError('This reservation is not in the reported own reservation inventory')
    if int(slot_id) not in {item['id'] for item in group['appointments']}:
        raise CanvasError('The parent slot is not in the selected appointment group')
    body = {'which': 'one'}
    if reason is not None:
        body['cancel_reason'] = reason
    preview = {**identity, 'appointment_group': {key: value for key, value in group.items() if key != 'appointments'},
               'reservation': reservation, 'content_revision': digest({key: record.get(key) for key in ('comments', 'description')}),
               'method': 'DELETE', 'route': f'/api/v1/calendar_events/{reservation_id}', 'body': body,
               'effect': 'Cancels only your exact individual reservation, not the parent slot or appointment group. '
                         'The organizer may be notified and can see the cancellation reason. '
                         'Rebooking is not guaranteed; no automatic replacement or retry.'}
    result = confirmed(client, preview, yes, confirm)
    return _verify(client, result, identity, group_id, slot_id, reservation_id=reservation_id, deleted=True) if yes else result
