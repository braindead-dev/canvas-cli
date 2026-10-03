"""Isolated native shared-team Scheduler endpoints for the local HTTPS fixture."""

import copy
from urllib.parse import parse_qs, urlencode, urlsplit

from .appointments import _send


def initialize(state, *, enabled=False):
    state.team_appointments_enabled = enabled
    state.team_slot = {'id': 703, 'context_code': 'appointment_group_503', 'appointment_group_id': 503,
                       'participant_type': 'Group', 'parent_event_id': None, 'workflow_state': 'active',
                       'start_at': '2099-10-05T19:00:00-07:00', 'end_at': '2099-10-05T19:30:00-07:00',
                       'reserved': False, 'available_slots': 2, 'participants_per_appointment': 2,
                       'child_events': [{'group': {'users': [{'email': 'synthetic-private-team-peer@example.edu'}]}}]}
    state.team_past_slot = {**state.team_slot, 'id': 705, 'start_at': '2020-10-05T19:00:00-07:00',
                            'end_at': '2020-10-05T19:30:00-07:00'}
    state.team_scheduler = {'id': 503, 'participant_type': 'Group', 'workflow_state': 'active',
                            'title': 'Synthetic team hours', 'context_codes': ['course_103'],
                            'sub_context_codes': ['group_category_31'], 'reserved_times': [],
                            'max_appointments_per_participant': 2}
    state.team_context = {'id': 13, 'name': 'Synthetic project team', 'course_id': 103, 'group_category_id': 31,
                          'concluded': False, 'non_collaborative': False,
                          'users': [{'email': 'synthetic-private-team-roster@example.edu'}]}
    state.team_membership = {'id': 93, 'group_id': 13, 'user_id': 7, 'moderator': False, 'workflow_state': 'accepted'}
    state.team_calendar = [{'id': 901, 'context_code': 'group_13', 'title': 'Synthetic private regular meeting'}]
    state.team_reservation = None
    state.team_permission = True
    state.team_write = None
    state.team_ack_malformed = state.team_native_denial = state.team_readback_denied = False
    state.team_membership_denied_after_write = state.team_missing_after_write = False


def _paginate(handler, query, rows):
    page = int(query.get('page', ['1'])[0])
    query['page'] = [str(page + 1)]
    link = f'<{urlsplit(handler.path).path}?{urlencode(query, doseq=True)}>; rel="next"' if page < len(rows) else None
    _send(handler, rows[page - 1:page], link=link)


def read(state, handler):
    if not state.team_appointments_enabled:
        return False
    url = urlsplit(handler.path)
    query = parse_qs(url.query)
    if url.path == '/api/v1/appointment_groups':
        if query.get('scope') != ['reservable'] or query.get('include[]') != ['reserved_times']:
            _send(handler, {'private': 'Synthetic private incorrect Scheduler scope'}, 400)
        else:
            _paginate(handler, query, [state.team_scheduler, state.appointment_second_group])
    elif url.path == '/api/v1/appointment_groups/503':
        if query.get('include_past_appointments') != ['true']:
            _send(handler, {'private': 'Synthetic private past slots required'}, 400)
        else:
            _send(handler, {**state.team_scheduler, 'appointments': [state.team_slot, state.team_past_slot]})
    elif url.path == '/api/v1/groups/13':
        _send(handler, state.team_context)
    elif url.path == '/api/v1/groups/13/memberships/self':
        if state.team_write is not None and state.team_membership_denied_after_write:
            _send(handler, {'private': 'Synthetic private post-write membership denial'}, 403)
        else:
            _send(handler, state.team_membership)
    elif url.path == '/api/v1/groups/13/permissions':
        _send(handler, {'manage_calendar': state.team_permission})
    elif url.path == '/api/v1/calendar_events':
        if (query.get('context_codes[]') != ['group_13'] or query.get('all_events') != ['true'] or
                set(query.get('excludes[]', [])) != {'child_events', 'description'}):
            _send(handler, {'private': 'Synthetic private wrong team calendar scope'}, 400)
        else:
            rows = state.team_calendar
            if state.team_write is not None and state.team_missing_after_write:
                rows = [row for row in rows if row.get('appointment_group_id') is None]
            _paginate(handler, query, rows)
    elif url.path in ('/api/v1/calendar_events/703', '/api/v1/calendar_events/803'):
        if query.get('excludes[]') != ['child_events']:
            _send(handler, {'private': 'Synthetic private child-event exclusion required'}, 400)
        elif url.path.endswith('/703'):
            _send(handler, state.team_slot)
        elif state.team_reservation is None or state.team_write is not None and state.team_readback_denied:
            _send(handler, {'private': 'Synthetic private post-write reservation denial'}, 403)
        else:
            _send(handler, state.team_reservation)
    else:
        return False
    return True


def write(state, handler, body):
    if not state.team_appointments_enabled or handler.path not in ('/api/v1/calendar_events/703/reservations', '/api/v1/calendar_events/803'):
        return False
    state.team_write = copy.deepcopy(body)
    if state.team_native_denial:
        _send(handler, {'private': 'Synthetic private native booking conflict'}, 400)
        return True
    if handler.command == 'POST' and handler.path.endswith('/reservations'):
        if body.get('participant_id') != 13 or body.get('cancel_existing') is not False or state.team_reservation is not None:
            _send(handler, {'private': 'Synthetic private wrong participant or duplicate booking'}, 400)
            return True
        state.team_reservation = {'id': 803, 'context_code': 'group_13', 'appointment_group_id': 503,
                                  'parent_event_id': 703, 'participant_type': 'Group', 'workflow_state': 'locked',
                                  'start_at': state.team_slot['start_at'], 'end_at': state.team_slot['end_at'],
                                  'comments': body.get('comments'), 'description': 'Synthetic private team booking details'}
        state.team_calendar.append(copy.deepcopy(state.team_reservation))
        state.team_slot.update(available_slots=1, reserved=True, workflow_state='locked')
    elif handler.command == 'DELETE' and state.team_reservation and body.get('which') == 'one':
        state.team_reservation['workflow_state'] = 'deleted'
        state.team_calendar = [row for row in state.team_calendar if row['id'] != 803]
    else:
        _send(handler, {'private': 'Synthetic private invalid team booking write'}, 400)
        return True
    data = {'private': 'Synthetic private malformed team acknowledgement'} if state.team_ack_malformed else {
        **state.team_reservation, 'context_code': 'course_103'}
    _send(handler, data)
    return True
