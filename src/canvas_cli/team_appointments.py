"""Native Scheduler reservations for one explicitly selected, joined course team."""

from urllib.parse import urlencode

from . import appointments
from .access import query
from .client import CanvasError
from .events import read as read_event
from .group_content import _context
from .group_membership import _metadata
from .writes import account, check_flags, confirmed, digest

NOTE = ('Reservations belong to the selected team, including bookings made by teammates, not your individual user. '
        'Only this appointment group is shown from the fully paginated team calendar; '
        'other teams, roster identities and comments are omitted. Native access and availability can change.')


def _team(client, team_id, group, identity):
    route, raw = _context(client, team_id, 'group')
    if (group['participant_type'] != 'Group' or raw.get('concluded') is not False or
            raw.get('non_collaborative') is not False or
            not appointments._numeric(raw.get('course_id')) or not appointments._numeric(raw.get('group_category_id')) or
            group['context_codes'] != [f"course_{raw['course_id']}"] or
            group.get('sub_context_codes') != [f"group_category_{raw['group_category_id']}"] or
            raw.get('workflow_state', 'active') != 'active'):
        raise CanvasError('Select a current collaborative course team in the exact Scheduler group set')
    team = appointments._project(raw, ('id', 'name', 'course_id', 'group_category_id', 'concluded', 'non_collaborative'))
    # Native self lookup avoids downloading a peer roster just to prove own membership.
    raw_membership, _ = client.request(route + '/memberships/self')
    membership = _metadata(raw_membership, team_id)
    if membership['user_id'] != identity['user_id'] or membership['workflow_state'] != 'accepted':
        raise CanvasError('Accepted own membership in the selected team is required; invitations are not membership')
    permissions = query(client, route, ['manage_calendar'])
    if permissions['manage_calendar'] is not True:
        raise CanvasError('Canvas did not grant the selected team calendar permission')
    return {'team': team, 'own_membership': membership, 'permissions': permissions}


def _reservations(client, team_id, group, max_pages):
    query = [('type', 'event'), ('all_events', 'true'), ('per_page', '100'),
             ('context_codes[]', f'group_{team_id}'), ('excludes[]', 'child_events'), ('excludes[]', 'description')]
    rows = client.list('/api/v1/calendar_events?' + urlencode(query), max_pages)
    result, seen = [], set()
    slots = {slot['id'] for slot in group['appointments']}
    for row in rows:
        if (not isinstance(row, dict) or not appointments._numeric(row.get('id')) or row['id'] in seen or
                row.get('context_code') != f'group_{team_id}'):
            raise CanvasError('Canvas returned duplicate, malformed or foreign team calendar records')
        seen.add(row['id'])
        appointment_id = row.get('appointment_group_id')
        if appointment_id is None:
            continue  # Ordinary team calendar events are not Scheduler reservations.
        if not appointments._numeric(appointment_id):
            raise CanvasError('Canvas returned malformed team appointment identifiers')
        if appointment_id != group['id']:
            continue
        item = appointments._reservation(row, 'Group', int(team_id), str(group['id']), str(row.get('parent_event_id')))
        if item['parent_event_id'] not in slots:
            raise CanvasError('A team reservation has no parent slot in the selected Scheduler group')
        result.append(item)
    return sorted(result, key=lambda row: row['id'])


def _state(client, group_id, team_id, max_pages):
    appointments._id(group_id); appointments._id(team_id)
    if type(max_pages) is not int or max_pages < 1:
        raise CanvasError('Team appointment page limit must be a positive integer')
    identity = account(client)
    # Past reservations count toward native per-participant limits, so don't use a date window.
    group = appointments._read_group(client, group_id, include_past=True)
    member = _team(client, team_id, group, identity)
    reservations = _reservations(client, team_id, group, max_pages)
    if account(client) != identity:
        raise CanvasError('Canvas account changed while reading team appointments; no write was sent')
    return identity, group, member, reservations


def read(client, group_id, team_id, *, max_pages=100):
    identity, group, member, reservations = _state(client, group_id, team_id, max_pages)
    return {**identity, **member, 'appointment_group': group, 'team_reservations': reservations,
            'complete_for_endpoint': True, 'note': NOTE}


def _flags(group_id, team_id, target_id, acknowledge_team_change, yes, confirm, text):
    check_flags(yes, confirm)
    appointments._id(group_id); appointments._id(team_id); appointments._id(target_id)
    if not acknowledge_team_change:
        raise CanvasError('Use --acknowledge-team-change: this booking change affects every member of the selected team')
    if text is not None and (not isinstance(text, str) or len(text) > 10000):
        raise CanvasError('Appointment comments/reason must be text of at most 10000 characters')


def _preview(identity, group, member, reservations):
    return {**identity, **member, 'appointment_group': {key: value for key, value in group.items() if key != 'appointments'},
            'team_reservations': reservations}


def _verify(client, result, identity, group_id, team_id, slot_id, member, max_pages, *, deleted=False,
            reservation_id=None, expected=None, comments=None):
    verified = appointments._verify(client, result, identity, group_id, slot_id, participant_type='Group',
                                    participant_id=int(team_id), reservation_id=reservation_id,
                                    deleted=deleted, expected=expected, comments=comments)
    try:
        fresh_identity, _, fresh_member, reservations = _state(client, group_id, team_id, max_pages)
        item = verified['appointment_reservation']
        matches = [row for row in reservations if row['id'] == item['id']]
        if (fresh_identity != identity or fresh_member != member or
                deleted and matches or not deleted and matches != [item]):
            raise CanvasError('Team reservation read-back mismatch')
    except CanvasError:
        raise CanvasError('Appointment write was acknowledged, but current team membership/inventory could not be verified. '
                          'Check Canvas before repeating; no automatic retries.') from None
    return {**verified, 'team': member['team'],
            'note': 'Exact selected team reservation and current own membership verified by separate reads. '
                    'The change affects the whole team; native notifications may be sent. '
                    'No other reservation was intentionally changed.'}


def reserve(client, group_id, team_id, slot_id, *, comments=None, acknowledge_team_change=False,
            max_pages=100, yes=False, confirm=None):
    _flags(group_id, team_id, slot_id, acknowledge_team_change, yes, confirm, comments)
    identity, group, member, reservations = _state(client, group_id, team_id, max_pages)
    reservable = appointments._groups(client, max_pages)
    if int(group_id) not in {row['id'] for row in reservable}:
        raise CanvasError('This appointment group is not in the current own reservable inventory')
    slot = appointments._slot(read_event(client, slot_id, exclude_children=True), group)
    if slot['id'] != int(slot_id) or slot['id'] not in {row['id'] for row in group['appointments']}:
        raise CanvasError('The selected slot is not in this Scheduler group')
    appointments._future(slot)
    if any(row['parent_event_id'] == slot['id'] for row in reservations):
        raise CanvasError('The selected team already reserved this slot, possibly through a teammate')
    if slot.get('available_slots') == 0:
        raise CanvasError('This appointment slot is full')
    limit = group.get('max_appointments_per_participant')
    if limit is not None and len(reservations) >= limit:
        raise CanvasError('The team per-participant reservation limit is already met; existing bookings are not replaced')
    body = {'participant_id': int(team_id), 'cancel_existing': False}
    if comments is not None:
        body['comments'] = comments
    preview = {**_preview(identity, group, member, reservations), 'slot': slot,
               'method': 'POST', 'route': f'/api/v1/calendar_events/{slot_id}/reservations', 'body': body,
               'effect': 'Reserves this one slot for the selected team, not your individual user. '
                         'Every member is affected; comments are shared with the organizer and native notifications may be sent. '
                         'Existing bookings are never cancelled or replaced. Availability/authorization can change.'}
    result = confirmed(client, preview, yes, confirm)
    return (_verify(client, result, identity, group_id, team_id, slot_id, member, max_pages,
                    expected=slot, comments=comments) if yes else result)


def cancel(client, group_id, team_id, reservation_id, *, reason=None, acknowledge_team_change=False,
           max_pages=100, yes=False, confirm=None):
    _flags(group_id, team_id, reservation_id, acknowledge_team_change, yes, confirm, reason)
    identity, group, member, reservations = _state(client, group_id, team_id, max_pages)
    if int(reservation_id) not in {row['id'] for row in reservations}:
        raise CanvasError('This reservation is not in the selected team appointment inventory')
    record = read_event(client, reservation_id, exclude_children=True)
    slot_id = str(record.get('parent_event_id'))
    reservation = appointments._reservation(record, 'Group', int(team_id), group_id, slot_id, reservation_id=reservation_id)
    if reservation not in reservations:
        raise CanvasError('The team reservation changed while reading; review fresh state')
    appointments._future(reservation)
    body = {'which': 'one'}
    if reason is not None:
        body['cancel_reason'] = reason
    preview = {**_preview(identity, group, member, reservations), 'reservation': reservation,
               'content_revision': digest({key: record.get(key) for key in ('comments', 'description')}),
               'method': 'DELETE', 'route': f'/api/v1/calendar_events/{reservation_id}', 'body': body,
               'effect': 'Cancels only this team reservation, including one booked by a teammate. '
                         'Every member is affected; the organizer may be notified and see the reason. '
                         'The parent slot and other bookings are not deleted; rebooking is not guaranteed.'}
    result = confirmed(client, preview, yes, confirm)
    return (_verify(client, result, identity, group_id, team_id, slot_id, member, max_pages,
                    reservation_id=reservation_id, deleted=True) if yes else result)
