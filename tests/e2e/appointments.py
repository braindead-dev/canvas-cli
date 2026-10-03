"""Synthetic Scheduler routes, kept separate from the shared HTTPS server."""

import copy
import json
from urllib.parse import parse_qs, urlencode, urlsplit


def initialize(state):
    state.appointment_slot = {'id': 601, 'context_code': 'appointment_group_501', 'appointment_group_id': 501,
                              'participant_type': 'User', 'parent_event_id': None, 'workflow_state': 'active',
                              'title': 'Synthetic slot', 'start_at': '2099-10-05T19:00:00-07:00',
                              'end_at': '2099-10-05T19:30:00-07:00', 'reserved': False, 'available_slots': 2,
                              'participants_per_appointment': 2, 'updated_at': '2026-10-02T12:00:00Z',
                              'child_events': [{'user': {'email': 'synthetic-private-appointment-peer@example.edu'}}],
                              'reserve_comments': 'Synthetic private peer appointment comments'}
    state.appointment_group = {'id': 501, 'workflow_state': 'active', 'participant_type': 'User',
                               'title': 'Synthetic office hours', 'context_codes': ['course_101'],
                               'max_appointments_per_participant': 2, 'reserved_times': [],
                               'description': 'Synthetic private office hours description',
                               'updated_at': '2026-10-02T12:00:00Z'}
    state.appointment_second_group = {**state.appointment_group, 'id': 502, 'title': 'Synthetic other office hours',
                                      'context_codes': ['course_102'], 'reserved_times': []}
    state.appointment_reservation = None
    state.appointment_ack_mode = 'normal'
    state.appointment_readback_denied = False
    state.appointment_write = None


def _send(handler, data, status=200, link=None):
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    if link:
        handler.send_header('Link', link)
    handler.end_headers()
    handler.wfile.write(json.dumps(data).encode())


def read(state, handler):
    url = urlsplit(handler.path)
    query = parse_qs(url.query)
    if url.path == '/api/v1/appointment_groups':
        if query.get('scope') != ['reservable'] or query.get('include[]') != ['reserved_times']:
            _send(handler, {'private': 'Synthetic never log malformed query'}, 400)
            return True
        rows = [state.appointment_group, state.appointment_second_group]
        if query.get('context_codes[]'):
            rows = [row for row in rows if set(row['context_codes']) & set(query['context_codes[]'])]
        page = int(query.get('page', ['1'])[0])
        link = None
        if len(rows) > 1 and page == 1:
            query['page'] = ['2']
            link = f'<{url.path}?{urlencode(query, doseq=True)}>; rel="next"'
        _send(handler, rows[page - 1:page], link=link)
        return True
    if url.path == '/api/v1/appointment_groups/501':
        _send(handler, {**state.appointment_group, 'appointments': [state.appointment_slot]})
        return True
    if url.path in ('/api/v1/calendar_events/601', '/api/v1/calendar_events/701'):
        if query.get('excludes[]') != ['child_events']:
            _send(handler, {'private': 'Synthetic child-event exclusion required'}, 400)
        elif url.path.endswith('/601'):
            _send(handler, state.appointment_slot)
        elif state.appointment_readback_denied or state.appointment_reservation is None:
            _send(handler, {'private': 'Synthetic private reservation denial'}, 403)
        else:
            _send(handler, state.appointment_reservation)
        return True
    return False


def write(state, handler, body):
    if handler.path not in ('/api/v1/calendar_events/601/reservations', '/api/v1/calendar_events/701'):
        return False
    state.appointment_write = copy.deepcopy(body)
    if handler.command == 'POST' and handler.path.endswith('/reservations'):
        if body.get('participant_id') != 7 or body.get('cancel_existing') is not False:
            _send(handler, {'private': 'Synthetic private incorrect participant'}, 400)
            return True
        state.appointment_reservation = {
            'id': 701, 'appointment_group_id': 501, 'parent_event_id': 601, 'context_code': 'user_7',
            'participant_type': 'User', 'workflow_state': 'locked',
            'start_at': state.appointment_slot['start_at'], 'end_at': state.appointment_slot['end_at'],
            'comments': body.get('comments'), 'description': 'Synthetic private inherited appointment description'}
        state.appointment_slot.update(reserved=True, available_slots=1, workflow_state='locked')
        state.appointment_group['reserved_times'] = [{key: state.appointment_reservation[key] for key in ('id', 'start_at', 'end_at')}]
    elif handler.command == 'DELETE' and state.appointment_reservation and body.get('which') == 'one':
        state.appointment_reservation['workflow_state'] = 'deleted'
        state.appointment_group['reserved_times'] = []
        state.appointment_slot.update(reserved=False, available_slots=2)
    else:
        _send(handler, {'private': 'Synthetic private invalid Scheduler write'}, 400)
        return True
    data = ({**state.appointment_reservation, 'context_code': 'course_101'}
            if state.appointment_ack_mode == 'normal' else {'private': 'Synthetic private malformed reservation ack'})
    _send(handler, data)
    return True
