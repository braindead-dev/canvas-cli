"""Synthetic own-contact routes, independent of the notification-preference fixture."""

import copy
import json
from urllib.parse import parse_qs, urlsplit


def initialize(state):
    state.communication_channels = [
        {'id': 19, 'user_id': 7, 'type': 'email', 'position': 1, 'workflow_state': 'active',
         'address': 'synthetic-contact@example.edu', 'bounce_count': 0,
         'last_bounce_summary': 'Synthetic private bounce details'},
        {'id': 20, 'user_id': 7, 'type': 'push', 'position': 2, 'workflow_state': 'active',
         'address': 'synthetic-private-push-token'}]
    state.contact_written = False
    state.contact_write = None
    state.contact_ack_mode = 'normal'
    state.contact_readback_denied = False
    state.contact_delete_keeps_row = False
    state.contact_restrict_delete = False


def _send(handler, data, status=200, link=None):
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    if link:
        handler.send_header('Link', link)
    handler.end_headers()
    handler.wfile.write(json.dumps(data).encode())


def read(state, handler):
    url = urlsplit(handler.path)
    if url.path != '/api/v1/users/self/communication_channels':
        return False
    if state.contact_written and state.contact_readback_denied:
        _send(handler, {'private': 'Synthetic private contact readback denial'}, 403)
        return True
    rows = [row for row in state.communication_channels if row['workflow_state'] != 'retired']
    page = parse_qs(url.query).get('page', ['1'])[0]
    if page == '1' and len(rows) > 1:
        _send(handler, rows[:1], link='</api/v1/users/self/communication_channels?page=2>; rel="next"')
    else:
        _send(handler, rows[1:] if page == '2' else rows)
    return True


def write(state, handler, body):
    route = '/api/v1/users/self/communication_channels'
    if not (handler.path == route and handler.command == 'POST' or
            handler.path in (route + '/19', route + '/20', route + '/21') and handler.command == 'DELETE'):
        return False
    state.contact_write = copy.deepcopy(body)
    if handler.command == 'POST':
        if (set(body) != {'communication_channel', 'skip_confirmation'} or body['skip_confirmation'] is not False or
                set(body['communication_channel']) != {'type', 'address'} or
                body['communication_channel']['type'] not in ('email', 'sms')):
            _send(handler, {'private': 'Synthetic private invalid contact create'}, 400)
            return True
        row = {'id': 21, 'user_id': 7, 'position': 3, 'workflow_state': 'unconfirmed',
               **body['communication_channel'], 'confirmation_code': 'Synthetic private confirmation secret'}
        state.communication_channels.append(row)
    else:
        if state.contact_restrict_delete:
            _send(handler, {'private': 'Synthetic private institution/OTP restriction'}, 400)
            return True
        row = next(item for item in state.communication_channels if item['id'] == int(handler.path.rsplit('/', 1)[1]))
        row = {**row, 'workflow_state': 'retired'}
        if not state.contact_delete_keeps_row:
            state.communication_channels = [item for item in state.communication_channels if item['id'] != row['id']]
    state.contact_written = True
    if state.contact_ack_mode == 'duplicate':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json')
        handler.end_headers()
        handler.wfile.write(b'{"id":21,"id":22,"private":"Synthetic private raw contact acknowledgement"}')
        return True
    _send(handler, row if state.contact_ack_mode == 'normal' else {'private': 'Synthetic private invalid contact acknowledgement'})
    return True
