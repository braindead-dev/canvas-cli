"""Synthetic native participation items versus independent preference markers."""

import copy

from .appointments import _send

READ = ('query CanvasSubmissionAttention($assignmentId: ID!, $userId: ID!) { '
        'assignment(id: $assignmentId) { _id courseId submissionTypes allowedExtensions published dueAt unlockAt lockAt '
        'updatedAt groupCategoryId gradeGroupStudentsIndividually allowedAttempts state } '
        'submission(assignmentId: $assignmentId, userId: $userId) { _id userId assignmentId '
        'assignment { _id courseId } attempt state submittedAt readState } }')


def initialize(state, *, enabled=False):
    state.attention_enabled = enabled
    state.attention_assignment = {'_id': '941', 'courseId': '141', 'submissionTypes': ['online_upload'], 'allowedExtensions': None,
                                  'published': True, 'dueAt': None, 'unlockAt': None, 'lockAt': None, 'updatedAt': None,
                                  'groupCategoryId': None, 'gradeGroupStudentsIndividually': False, 'allowedAttempts': None, 'state': 'published'}
    state.attention_submission = {'_id': '741', 'userId': '7', 'assignmentId': '941', 'assignment': {'_id': '941', 'courseId': '141'},
                                  'attempt': 2, 'state': 'submitted', 'submittedAt': '2026-10-03T00:00:00Z'}
    state.attention_items = {'grade': 'unread', 'comment': 'unread', 'rubric': 'unread'}
    state.attention_preferences = {'document_annotations': False, 'rubric_assessments': False}
    state.attention_queries = []
    state.attention_mutations = []
    state.attention_viewed_comments = []
    state.attention_written = state.attention_denied = state.attention_ignore = False
    state.attention_bad_ack = None
    state.attention_switch = state.attention_advance = state.attention_policy_after = state.attention_read_after = False
    state.attention_read_state_override = None
    state.attention_marker_override = None
    state.attention_viewer = 7


def aggregate(state):
    return 'unread' if 'unread' in state.attention_items.values() else 'read'


def read(state, handler):
    if not state.attention_enabled:
        return False
    if handler.path == '/api/v1/users/self/profile':
        _send(handler, {'id': 8 if state.attention_written and state.attention_switch else state.attention_viewer,
                        'email': 'synthetic-private@example.edu'})
        return True
    prefix = '/api/v1/courses/141/assignments/941/submissions/7/'
    for surface in state.attention_preferences:
        if handler.path == prefix + surface + '/read':
            row = {'read': state.attention_preferences[surface], 'private': 'synthetic-private-marker'}
            _send(handler, row if state.attention_marker_override is None else state.attention_marker_override)
            return True
    return False


def execute(state, handler, body):
    if not state.attention_enabled:
        return False
    if handler.path == '/api/graphql' and body.get('operationName') == 'CanvasSubmissionAttention':
        state.attention_queries.append(copy.deepcopy(body))
        if body.get('query') != READ or body.get('variables') != {'assignmentId': '941', 'userId': str(state.attention_viewer)}:
            _send(handler, {'errors': [{'message': 'synthetic-private-unexpected-query'}]})
            return True
        if state.attention_written and state.attention_read_after:
            _send(handler, {'errors': [{'message': 'synthetic-private-read-denied'}]})
            return True
        assignment, submission = copy.deepcopy(state.attention_assignment), copy.deepcopy(state.attention_submission)
        if state.attention_written and state.attention_policy_after:
            assignment['published'] = False
        if submission is not None:
            submission['readState'] = aggregate(state) if state.attention_read_state_override is None else state.attention_read_state_override
        _send(handler, {'data': {'assignment': assignment, 'submission': submission}})
        return True
    prefix = '/api/v1/courses/141/assignments/941/submissions/7/'
    if handler.command not in ('PUT', 'DELETE') or not handler.path.startswith(prefix):
        return False
    state.attention_mutations.append((handler.command, handler.path, copy.deepcopy(body)))
    state.attention_written = True
    if state.attention_denied:
        _send(handler, {'error': 'synthetic-private-denied'}, 403)
        return True
    surface = handler.path.removeprefix(prefix)
    selected = 'unread' if handler.command == 'DELETE' else 'read'
    preference = next((key for key in state.attention_preferences if surface == key + '/read'), None)
    if preference is not None:
        if not state.attention_ignore:
            state.attention_preferences[preference] = True
    elif surface == 'read':
        # Native legacy whole read only touches the default grade item and skips already-matching aggregate state.
        if not state.attention_ignore and aggregate(state) != selected:
            state.attention_items['grade'] = selected
    elif surface in ('read/grade', 'read/comment', 'read/rubric') and handler.command == 'PUT':
        if not state.attention_ignore:
            item = surface.removeprefix('read/')
            state.attention_items[item] = 'read'
            if item == 'comment':
                state.attention_viewed_comments.extend(('synthetic-visible-own', 'synthetic-visible-grader'))
    else:
        _send(handler, {'error': 'synthetic-private-unsafe-route'}, 400)
        return True
    if state.attention_advance:
        state.attention_submission['attempt'] += 1
    if state.attention_bad_ack == 'http':
        _send(handler, {'error': 'synthetic-private-after-mutation'}, 500)
    elif state.attention_bad_ack == 'body':
        _send(handler, {'read': True}, 200)
    elif preference is not None:
        _send(handler, {'read': True} if state.attention_bad_ack is None else {'read': 'true'})
    else:
        handler.send_response(204)
        handler.end_headers()
    return True
