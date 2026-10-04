"""Native own what-if column update and calculation, independent of CLI implementation."""

import copy

from .appointments import _send
from .submission_attention import initialize as initialize_submission

READ = ('query CanvasWhatIfScore($assignmentId: ID!, $userId: ID!) { '
        'assignment(id: $assignmentId) { _id courseId submissionTypes allowedExtensions published dueAt unlockAt lockAt '
        'updatedAt groupCategoryId gradeGroupStudentsIndividually allowedAttempts state } '
        'submission(assignmentId: $assignmentId, userId: $userId) { _id userId assignmentId '
        'assignment { _id courseId } attempt state submittedAt studentEnteredScore } }')


def initialize(state, *, enabled=False):
    state.what_if_enabled = enabled
    initialize_submission(state)
    state.what_if_assignment = copy.deepcopy(state.attention_assignment)
    state.what_if_submission = copy.deepcopy(state.attention_submission)
    state.what_if_score = 4.0
    state.what_if_actual_grade = 20.0
    state.what_if_queries, state.what_if_mutations = [], []
    state.what_if_viewer = 7
    state.what_if_written = state.what_if_denied = state.what_if_ignore = False
    state.what_if_switch = state.what_if_advance = state.what_if_policy_after = state.what_if_read_after = False
    state.what_if_calculation_error = False
    state.what_if_ack = None
    state.what_if_forecasts = [{'current': {'grade': 85.0, 'total': 8.5, 'possible': 10.0, 'private': 'synthetic-private'},
                               'final': {'grade': None, 'full_weight': 100.0}, 'private': 'synthetic-private'}]


def read(state, handler):
    if not state.what_if_enabled:
        return False
    if handler.path == '/api/v1/users/self/profile':
        _send(handler, {'id': 8 if state.what_if_written and state.what_if_switch else state.what_if_viewer,
                        'email': 'synthetic-private@example.edu'})
        return True
    return False


def execute(state, handler, body):
    if not state.what_if_enabled:
        return False
    if handler.path == '/api/graphql' and body.get('operationName') == 'CanvasWhatIfScore':
        state.what_if_queries.append(copy.deepcopy(body))
        if body.get('query') != READ or body.get('variables') != {'assignmentId': '941', 'userId': str(state.what_if_viewer)}:
            _send(handler, {'errors': [{'message': 'synthetic-private-unsafe-query'}]})
            return True
        if state.what_if_written and state.what_if_read_after:
            _send(handler, {'errors': [{'message': 'synthetic-private-read-denied'}]})
            return True
        assignment, submission = copy.deepcopy(state.what_if_assignment), copy.deepcopy(state.what_if_submission)
        if state.what_if_written and state.what_if_policy_after:
            assignment['published'] = False
        if submission is not None:
            submission['studentEnteredScore'] = state.what_if_score
        _send(handler, {'data': {'assignment': assignment, 'submission': submission}})
        return True
    if handler.command != 'PUT' or handler.path != '/api/v1/submissions/741/what_if_grades':
        return False
    state.what_if_mutations.append(copy.deepcopy(body))
    state.what_if_written = True
    if set(body) != {'student_entered_score'}:
        _send(handler, {'error': 'synthetic-private-unsafe-write'}, 400)
        return True
    if state.what_if_denied:
        _send(handler, {'error': 'synthetic-private-denied'}, 403)
        return True
    if not state.what_if_ignore:
        state.what_if_score = body['student_entered_score']
    if state.what_if_calculation_error:
        _send(handler, {'error': 'synthetic-private-calculation-failed'}, 500)
        return True
    if state.what_if_advance:
        state.what_if_submission['attempt'] += 1
    response = {'submission': {'id': 741, 'student_entered_score': state.what_if_score, 'private': 'synthetic-private'},
                'grades': state.what_if_forecasts, 'private': 'synthetic-private'}
    _send(handler, response if state.what_if_ack is None else state.what_if_ack)
    return True
