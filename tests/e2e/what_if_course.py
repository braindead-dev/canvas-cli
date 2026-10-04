"""Independent native reported-row visibility and genuinely whole-course reset fixture."""

import copy

from .appointments import _send

READ = ('query CanvasCourseWhatIf($courseId: ID!, $userId: ID!, $after: String) { '
        'course(id: $courseId) { _id state submissionsConnection(first: 50, after: $after, studentIds: [$userId], '
        'filter: {states: [unsubmitted, submitted, pending_review, graded, ungraded]}) { '
        'nodes { _id userId assignmentId assignment { _id courseId published } attempt state submittedAt studentEnteredScore } '
        'pageInfo { hasNextPage endCursor } } } }')


def initialize(state, *, enabled=False):
    state.what_if_course_enabled = enabled
    state.course_hypotheses = [{'_id': '741', 'userId': '7', 'assignmentId': '941',
                               'assignment': {'_id': '941', 'courseId': '141', 'published': True},
                               'attempt': 0, 'state': 'unsubmitted', 'submittedAt': None, 'studentEnteredScore': 8.0},
                              {'_id': '742', 'userId': '7', 'assignmentId': '942',
                               'assignment': {'_id': '942', 'courseId': '141', 'published': True},
                               'attempt': 2, 'state': 'graded', 'submittedAt': None, 'studentEnteredScore': None}]
    state.course_hidden_hypotheses = [5.0, None]
    state.course_reset_permission = True
    state.course_hypothesis_state = 'available'
    state.course_hypothesis_timestamps = 0
    state.course_hypothesis_actual_grade = 90.0
    state.course_hypothesis_queries, state.course_hypothesis_mutations = [], []
    state.course_reset_written = state.course_reset_denied = state.course_reset_ignore = state.course_reset_calculation_error = False
    state.course_reset_switch = state.course_reset_permission_after = state.course_reset_row_after = state.course_reset_read_after = False
    state.course_hypothesis_paginate = False
    state.course_reset_ack = None
    state.course_reset_totals = [{'current': {'grade': 90.0, 'total': 9.0, 'possible': 10.0, 'private': 'synthetic-private'},
                                 'final': {'grade': None}, 'private': 'synthetic-private'}]


def read(state, handler):
    if not state.what_if_course_enabled:
        return False
    if handler.path == '/api/v1/users/self/profile':
        _send(handler, {'id': 8 if state.course_reset_written and state.course_reset_switch else 7,
                        'email': 'synthetic-private@example.edu'})
        return True
    if handler.path == '/api/v1/courses/141/permissions?permissions%5B%5D=reset_what_if_grades':
        _send(handler, {'reset_what_if_grades': state.course_reset_permission and not (
            state.course_reset_written and state.course_reset_permission_after), 'private': 'synthetic-private'})
        return True
    return False


def execute(state, handler, body):
    if not state.what_if_course_enabled:
        return False
    if handler.path == '/api/graphql' and body.get('operationName') == 'CanvasCourseWhatIf':
        state.course_hypothesis_queries.append(copy.deepcopy(body))
        variables = body.get('variables', {})
        if (body.get('query') != READ or variables not in ({'courseId': '141', 'userId': '7', 'after': None},
                                                         {'courseId': '141', 'userId': '7', 'after': 'opaque'})):
            _send(handler, {'errors': [{'message': 'synthetic-private-unsafe-query'}]})
            return True
        if state.course_reset_written and state.course_reset_read_after:
            _send(handler, {'errors': [{'message': 'synthetic-private-readback-denial'}]})
            return True
        nodes = copy.deepcopy(state.course_hypotheses)
        more = state.course_hypothesis_paginate and len(nodes) > 1 and variables['after'] is None
        if state.course_hypothesis_paginate:
            nodes = nodes[:1] if variables['after'] is None else nodes[1:]
        _send(handler, {'data': {'course': {'_id': '141', 'state': state.course_hypothesis_state,
                                          'submissionsConnection': {'nodes': nodes, 'pageInfo': {
                                              'hasNextPage': more, 'endCursor': 'opaque' if more else None}}}}})
        return True
    if handler.command != 'PUT' or handler.path != '/api/v1/courses/141/what_if_grades/reset':
        return False
    state.course_hypothesis_mutations.append(copy.deepcopy(body))
    state.course_reset_written = True
    if body or not state.course_reset_permission or state.course_reset_denied:
        _send(handler, {'error': 'synthetic-private-reset-denial'}, 403)
        return True
    if not state.course_reset_ignore:
        for row in state.course_hypotheses:
            row['studentEnteredScore'] = None
        state.course_hidden_hypotheses = [None] * len(state.course_hidden_hypotheses)
        state.course_hypothesis_timestamps += len(state.course_hypotheses) + len(state.course_hidden_hypotheses)
    if state.course_reset_calculation_error:
        _send(handler, {'error': 'synthetic-private-calculation-failure'}, 500)
        return True
    if state.course_reset_row_after:
        state.course_hypotheses[0]['attempt'] += 1
    response = {'grades': state.course_reset_totals, 'private': 'synthetic-private'}
    _send(handler, response if state.course_reset_ack is None else state.course_reset_ack)
    return True
