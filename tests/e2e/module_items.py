"""Native own module events and paginated metadata; no real Canvas account."""

import copy
from urllib.parse import parse_qs, urlencode, urlsplit

from .appointments import _send


def initialize(state, *, enabled=False):
    state.module_items_enabled = enabled
    if not enabled:
        return
    state.module_viewer = 7
    state.module_course = {'id': 109, 'name': 'Synthetic Horizon course', 'workflow_state': 'available'}
    state.module_rights = {'participate_as_student': True}
    state.native_module = {'id': 21, 'name': 'Synthetic module', 'position': 1, 'state': 'started',
                           'completed_at': None, 'require_sequential_progress': False,
                           'requirement_type': 'all', 'items_count': 2, 'prerequisite_module_ids': [],
                           'publish_final_grade': False, 'private': 'synthetic-private-module'}
    state.native_items = [
        {'id': 201, 'module_id': 21, 'title': 'Synthetic checkbox', 'type': 'Assignment', 'position': 1,
         'content_id': 88, 'completion_requirement': {'type': 'must_mark_done', 'completed': False},
         'content_details': {'locked_for_user': False, 'thumbnail_url': 'https://foreign.example/?token=synthetic-private'},
         'url': 'https://foreign.example/?token=synthetic-private', 'external_url': 'https://foreign.example/?token=synthetic-private'},
        {'id': 202, 'module_id': 21, 'title': 'Synthetic optional file', 'type': 'File', 'position': 2,
         'content_id': 89, 'content_details': {'locked_for_user': False}}]
    state.module_event = None
    state.module_events_denied = state.module_ignore_event = state.module_readback_denied = False
    state.module_acknowledgement = {'message': 'D’accord', 'private': 'synthetic-private-ack'}
    state.module_post_patch = {}
    state.module_planner_complete = False
    state.module_single_gets = 0
    state.module_sequence = {'items': [{'prev': None, 'current': copy.deepcopy({key: value for key, value in state.native_items[0].items()
                                                                              if key != 'content_details'}),
                                       'next': {key: value for key, value in state.native_items[1].items() if key != 'content_details'},
                                       'mastery_path': {'locked': False, 'awaiting_choice': True, 'selected_set_id': None,
                                                       'assignment_sets': [{'id': 801, 'private': 'synthetic-private-path'}],
                                                       'choose_url': 'https://foreign.example/?token=synthetic-private'}}],
                             'modules': [copy.deepcopy(state.native_module)]}
    state.module_sequence['items'][0]['current']['completion_requirement'].pop('completed')
    state.module_source = {'id': 77, 'course_id': 109, 'assignment_id': 88, 'body': 'synthetic-private-source'}


def read(state, handler):
    if not state.module_items_enabled:
        return False
    url = urlsplit(handler.path)
    parameters = parse_qs(url.query)
    if url.path == '/api/v1/users/self/profile':
        _send(handler, {'id': state.module_viewer, 'email': 'synthetic-private@example.edu'})
        return True
    prefix = '/api/v1/courses/109'
    if not (url.path == prefix or url.path.startswith(prefix + '/')):
        return False
    suffix = url.path[len(prefix):]
    if not suffix:
        _send(handler, state.module_course)
    elif suffix == '/permissions':
        if parameters != {'permissions[]': ['participate_as_student']}:
            _send(handler, {'private': 'synthetic-private-permission-query'}, 400)
        else:
            _send(handler, state.module_rights)
    elif suffix == '/module_item_sequence':
        if set(parameters) != {'asset_type', 'asset_id'}:
            _send(handler, {'private': 'synthetic-private-invalid-sequence-query'}, 400)
        else:
            _send(handler, state.module_sequence)
    elif suffix in ('/quizzes/77', '/discussion_topics/77'):
        _send(handler, state.module_source)
    elif parameters.get('student_id') not in (None, [str(state.module_viewer)]):
        _send(handler, {'private': 'synthetic-private-foreign-student'}, 403)
    elif state.module_event is not None and state.module_readback_denied:
        _send(handler, {'private': 'synthetic-private-progress-readback'}, 403)
    elif suffix == '/modules/21':
        _send(handler, state.native_module)
    elif suffix == '/modules/21/items':
        if parameters.get('include[]') != ['content_details']:
            _send(handler, {'private': 'synthetic-private-incomplete-metadata'}, 400)
        else:
            page = int(parameters.get('page', ['1'])[0])
            parameters['page'] = ['2']
            link = f'<{url.path}?{urlencode(parameters, doseq=True)}>; rel="next"' if page == 1 else None
            _send(handler, state.native_items[page - 1:page], link=link)
    elif suffix == '/modules/21/items/201':
        state.module_single_gets += 1
        criterion = state.native_items[0].get('completion_requirement')
        if criterion and criterion['type'] == 'must_view':
            criterion['completed'] = True  # Native Horizon single-item GET sends a read event.
        _send(handler, state.native_items[0])
    else:
        _send(handler, {'private': 'synthetic-private-wrong-module-route'}, 404)
    return True


def write(state, handler, body):
    if not state.module_items_enabled or not urlsplit(handler.path).path.startswith('/api/v1/courses/109/'):
        return False
    path = urlsplit(handler.path).path
    if (handler.command, path) not in (
        ('PUT', '/api/v1/courses/109/modules/21/items/201/done'),
        ('DELETE', '/api/v1/courses/109/modules/21/items/201/done'),
        ('POST', '/api/v1/courses/109/modules/21/items/201/mark_read')) or body:
        _send(handler, {'private': 'synthetic-private-wrong-module-event'}, 400)
        return True
    state.module_event = (handler.command, path)
    if state.module_events_denied:
        _send(handler, {'private': 'synthetic-private-module-event-denied'}, 403)
        return True
    criterion = state.native_items[0].get('completion_requirement')
    if criterion and not state.module_ignore_event:
        if handler.command == 'PUT' and criterion['type'] == 'must_mark_done':
            criterion['completed'] = True
            state.module_planner_complete = True
        elif handler.command == 'DELETE':
            criterion['completed'] = False
            state.module_planner_complete = False
        elif handler.command == 'POST' and criterion['type'] == 'must_view':
            criterion['completed'] = True
        state.native_module.update(state='completed' if criterion.get('completed') else 'started',
                                   completed_at='2026-10-03T12:00:00Z' if criterion.get('completed') else None)
    state.native_items[0].update(copy.deepcopy(state.module_post_patch))
    _send(handler, state.module_acknowledgement)
    return True
