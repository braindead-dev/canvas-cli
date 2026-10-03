"""Native publication callbacks layered on the existing independent RCE fixture."""

import copy
from urllib.parse import urlsplit

from . import page_authoring
from .appointments import _send


def initialize(state, *, enabled=False):
    state.scheduling_enabled = enabled
    if not enabled:
        return
    page_authoring.initialize(state, enabled=True)
    state.page_context['root_account_id'] = 2
    state.schedule_feature = {'feature': 'scheduled_page_publication', 'state': 'on', 'locked': False,
                              'context_type': 'Account', 'context_id': 2, 'private': 'synthetic-private-feature'}
    state.schedule_feature_denied = False
    state.schedule_feature_lost = False
    state.schedule_missing_ack_date = False


def read(state, handler):
    if not state.scheduling_enabled:
        return False
    if urlsplit(handler.path).path != '/api/v1/accounts/2/features/flags/scheduled_page_publication':
        return False
    if state.schedule_feature_denied:
        _send(handler, {'private': 'synthetic-private-root-feature-denial'}, 403)
    else:
        flag = copy.deepcopy(state.schedule_feature)
        if state.page_write is not None and state.schedule_feature_lost:
            flag['state'] = 'off'
        _send(handler, flag)
    return True


def write(state, handler, body):
    if not state.scheduling_enabled:
        return False
    path = urlsplit(handler.path).path
    if path != '/api/v1/courses/107/pages/page_id:1001':
        return False
    state.page_write = copy.deepcopy(body)
    if state.page_write_denied:
        _send(handler, {'private': 'synthetic-private-scheduling-blueprint'}, 403)
        return True
    changes = body.get('wiki_page', {})
    if handler.command != 'PUT' or set(changes) != {'publish_at', 'notify_of_update'} or changes['notify_of_update'] is not False:
        _send(handler, {'private': 'synthetic-private-invalid-schedule-write'}, 400)
        return True
    record = state.page_records[1001]
    if state.page_delete_race:
        record = {**copy.deepcopy(record), 'page_id': 1003, 'title': 'Unwanted', 'url': 'unwanted'}
        state.page_records[1003] = record
    if 'publish_at' not in state.page_ignored_fields:
        previous = record['published']
        value = changes['publish_at']
        record['publish_at'] = value.replace('+00:00', 'Z') if value is not None else None
        record['published'] = False  # Both future scheduling and clearing a date leave native drafts.
        if previous:
            record['updated_at'] = '2026-10-03T12:00:00Z'
            state.page_revision_id += 1
    acknowledged = {**record, **state.page_ack_patch}
    if state.schedule_missing_ack_date:
        acknowledged.pop('publish_at', None)
    _send(handler, acknowledged)
    return True
