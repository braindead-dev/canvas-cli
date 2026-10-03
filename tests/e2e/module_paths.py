"""Independent native choice/override effects on the synthetic module fixture."""

import copy
from urllib.parse import parse_qs, urlencode, urlsplit

from .appointments import _send


def initialize(state, *, enabled=False):
    state.module_paths_enabled = enabled
    if not enabled:
        return
    state.path_choices = {801: [91, 92], 802: [92, 93]}
    state.path_choice = None
    state.path_assigned = set()
    state.path_posted = True
    state.path_ignored = state.path_denied = state.path_readback_denied = False
    state.path_changed = False
    state.path_ack_override = None
    state.path_page_lists = 0
    state.path_item_type = 'Assignment'
    state.path_source = {'id': 77, 'course_id': 109, 'assignment_id': 88, 'body': 'synthetic-private-source'}
    state.path_trigger = {'id': 88, 'course_id': 109, 'name': 'Synthetic trigger', 'points_possible': 100,
                          'description': 'synthetic-private-trigger'}
    state.path_submission = {'id': 188, 'assignment_id': 88, 'user_id': 7, 'workflow_state': 'graded',
                             'posted_at': '2026-10-03T12:00:00Z', 'score': 0,
                             'body': 'synthetic-private-answer', 'url': 'https://foreign.example/?token=synthetic-private'}


def read(state, handler):
    if not state.module_paths_enabled:
        return False
    url = urlsplit(handler.path)
    prefix = '/api/v1/courses/109'
    path = url.path
    if path == prefix + '/module_item_sequence':
        if state.path_changed and state.path_readback_denied:
            _send(handler, {'private': 'synthetic-private-path-readback'}, 403)
            return True
        if parse_qs(url.query) != {'asset_type': ['ModuleItem'], 'asset_id': ['201']}:
            _send(handler, {'private': 'synthetic-private-query'}, 400)
            return True
        # Visibility/assignment effects can legitimately alter the module inventory after selection.
        item = copy.deepcopy(state.native_items[0])
        item.pop('content_details')
        item.update(type=state.path_item_type, content_id=88 if state.path_item_type == 'Assignment' else 77)
        if state.path_item_type == 'Page':
            item['page_url'] = 'welcome'
        paths = {'locked': False, 'awaiting_choice': state.path_choice is None, 'selected_set_id': state.path_choice,
                 'assignment_sets': [{'id': key, 'assignment_set_associations': [
                     {'assignment_set_id': key, 'assignment_id': value, 'model': {'body': 'synthetic-private-path'}}
                     for value in values]} for key, values in state.path_choices.items()]}
        _send(handler, {'items': [{'prev': None, 'current': item, 'next': None, 'mastery_path': paths}],
                        'modules': [state.native_module]})
    elif path in (prefix + '/quizzes/77', prefix + '/discussion_topics/77'):
        _send(handler, state.path_source)
    elif path == prefix + '/assignments/88':
        _send(handler, state.path_trigger)
    elif path == prefix + '/assignments/88/submissions/7':
        submission = copy.deepcopy(state.path_submission)
        if not state.path_posted:
            submission['posted_at'] = None
        _send(handler, submission)
    elif path == prefix + '/pages':
        state.path_page_lists += 1
        parameters = parse_qs(url.query)
        page = int(parameters.get('page', ['1'])[0])
        parameters['page'] = ['2']
        row = ({'page_id': 66, 'url': 'other', 'title': 'Synthetic unrelated page'} if page == 1 else
               {'page_id': 67, 'url': 'welcome', 'published': True, 'assignment': {'id': 88, 'course_id': 109,
                                                                               'description': 'synthetic-private-linked'}})
        _send(handler, [row], link=f'<{url.path}?{urlencode(parameters, doseq=True)}>; rel="next"' if page == 1 else None)
    else:
        return False
    return True


def write(state, handler, body):
    if not state.module_paths_enabled or not handler.path.endswith('/select_mastery_path'):
        return False
    if (handler.command != 'POST' or handler.path != '/api/v1/courses/109/modules/21/items/201/select_mastery_path' or
            body.get('student_id') != 7 or body.get('assignment_set_id') not in state.path_choices or
            set(body) != {'student_id', 'assignment_set_id'}):
        _send(handler, {'private': 'synthetic-private-path-destination'}, 400)
        return True
    if state.path_denied or not state.path_posted:
        _send(handler, {'private': 'synthetic-private-selection-denied'}, 403)
        return True
    state.path_changed = True
    chosen = body['assignment_set_id']
    if not state.path_ignored:
        state.path_choice = chosen
        state.path_assigned = set(state.path_choices[chosen])
    ack = state.path_ack_override if state.path_ack_override is not None else {
        'meta': {'primaryCollection': 'assignments'}, 'items': [],
        'assignments': [{'id': identifier, 'course_id': 109, 'description': 'synthetic-private-ack'}
                        for identifier in state.path_choices[chosen]]}
    _send(handler, ack)
    return True
