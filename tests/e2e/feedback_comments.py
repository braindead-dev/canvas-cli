"""Independent native selected viewed-row state, with no comment-body reads."""

import copy

from .appointments import _send
from .submission_comments import record

FIELDS = ('_id submissionId assignment { _id courseId } course { _id } '
          'draft attempt createdAt updatedAt provisional read')
READ = ('query CanvasFeedbackComments($assignmentId: ID!, $userId: ID!, $attempt: Int, $after: String) { '
        'assignment(id: $assignmentId) { _id courseId submissionTypes allowedExtensions published dueAt unlockAt lockAt '
        'updatedAt groupCategoryId gradeGroupStudentsIndividually allowedAttempts state } '
        'submission(assignmentId: $assignmentId, userId: $userId) { _id userId assignmentId '
        'assignment { _id courseId } attempt state submittedAt readState '
        'commentsConnection(first: 50, after: $after, filter: {allComments: false, forAttempt: $attempt, peerReview: false}, '
        'includeDraftComments: false, includeDraftsFromOthers: false, includeProvisionalComments: false) { '
        'nodes { ' + FIELDS + ' } pageInfo { hasNextPage endCursor } } } }')
MARK = ('mutation CanvasFeedbackCommentRead($input: MarkSubmissionCommentsReadInput!) { '
        'markSubmissionCommentsRead(input: $input) { errors { attribute } submissionComments { ' + FIELDS + ' } } }')


def initialize(state, *, enabled=False):
    state.feedback_comments_enabled = enabled
    state.feedback_assignment = {'_id': '941', 'courseId': '141', 'submissionTypes': ['online_upload'], 'allowedExtensions': None,
                                 'published': True, 'dueAt': None, 'unlockAt': None, 'lockAt': None, 'updatedAt': None,
                                 'groupCategoryId': None, 'gradeGroupStudentsIndividually': False, 'allowedAttempts': None, 'state': 'published'}
    state.feedback_submission = {'_id': '741', 'userId': '7', 'assignmentId': '941', 'assignment': {'_id': '941', 'courseId': '141'},
                                 'attempt': 2, 'state': 'submitted', 'submittedAt': '2026-10-03T00:00:00Z'}
    state.feedback_rows = [record('961', draft=False), record('962', attempt=0, draft=False), record('963', draft=False, author='8'),
                           record('964'), record('965', submission='742', draft=False)]
    state.feedback_viewed = set()
    state.feedback_queries, state.feedback_mutations = [], []
    state.feedback_aggregate = 'unread'
    state.feedback_viewer = 7
    state.feedback_page_size = 1
    state.feedback_written = state.feedback_ignore = state.feedback_denied = False
    state.feedback_switch = state.feedback_advance = state.feedback_policy_after = state.feedback_read_after = False
    state.feedback_ack = state.feedback_query_patch = state.feedback_page_patch = None
    state.feedback_other_read = False


def read(state, handler):
    if not state.feedback_comments_enabled:
        return False
    if handler.path == '/api/v1/users/self/profile':
        _send(handler, {'id': 8 if state.feedback_written and state.feedback_switch else state.feedback_viewer,
                        'email': 'synthetic-private@example.edu'})
        return True
    return False


def _row(state, row):
    fields = ('_id', 'submissionId', 'assignment', 'course', 'draft', 'attempt', 'createdAt', 'updatedAt', 'provisional')
    return {**{key: copy.deepcopy(row[key]) for key in fields},
            'read': state.feedback_aggregate == 'read' or row['_id'] in state.feedback_viewed}


def execute(state, handler, body):
    if not state.feedback_comments_enabled or handler.path != '/api/graphql':
        return False
    operation = body.get('operationName')
    if operation == 'CanvasFeedbackComments':
        state.feedback_queries.append(copy.deepcopy(body))
        variables = body.get('variables', {})
        if body.get('query') != READ or variables.get('assignmentId') != '941' or variables.get('userId') != str(state.feedback_viewer):
            _send(handler, {'errors': [{'message': 'synthetic-private-unsafe-query'}]})
            return True
        if state.feedback_written and state.feedback_read_after:
            _send(handler, {'errors': [{'message': 'synthetic-private-read-failure'}]})
            return True
        assignment, submission = copy.deepcopy(state.feedback_assignment), copy.deepcopy(state.feedback_submission)
        if state.feedback_written and state.feedback_policy_after:
            assignment['published'] = False
        if submission is not None:
            selected = submission['attempt'] if variables['attempt'] is None else variables['attempt']
            rows = [_row(state, row) for row in state.feedback_rows if not row['draft'] and not row['provisional']
                    and row['submissionId'] == submission['_id'] and row['attempt'] in ((0, 1) if selected <= 1 else (selected,))]
            offset = 0 if variables['after'] is None else int(variables['after'].removeprefix('f:'))
            nodes = rows[offset:offset + state.feedback_page_size]
            page = {'hasNextPage': offset + len(nodes) < len(rows), 'endCursor': f'f:{offset + len(nodes)}' if nodes else None}
            if state.feedback_page_patch:
                page.update(state.feedback_page_patch)
            submission.update(readState=state.feedback_aggregate, commentsConnection={'nodes': nodes, 'pageInfo': page})
            if state.feedback_query_patch:
                submission.update(copy.deepcopy(state.feedback_query_patch))
        _send(handler, {'data': {'assignment': assignment, 'submission': submission}})
        return True
    if operation != 'CanvasFeedbackCommentRead':
        return False
    state.feedback_mutations.append(copy.deepcopy(body))
    state.feedback_written = True
    variables = body.get('variables', {})
    selected = variables.get('input', {})
    if (body.get('query') != MARK or set(variables) != {'input'} or set(selected) != {'submissionId', 'submissionCommentIds'}
            or selected['submissionId'] != '741' or len(selected['submissionCommentIds']) != 1):
        _send(handler, {'errors': [{'message': 'synthetic-private-unsafe-mark'}]})
        return True
    if state.feedback_denied:
        _send(handler, {'errors': [{'message': 'synthetic-private-denied'}]}, 403)
        return True
    identifiers = selected['submissionCommentIds']
    matched = [row for row in state.feedback_rows if row['_id'] in identifiers and row['submissionId'] == '741']
    if not state.feedback_ignore:
        state.feedback_viewed.update(row['_id'] for row in matched)
    if state.feedback_other_read:
        state.feedback_viewed.add('963')
    response = {'data': {'markSubmissionCommentsRead': {'errors': None, 'submissionComments': [_row(state, row) for row in matched]}}}
    if state.feedback_advance:
        state.feedback_submission['attempt'] += 1
    _send(handler, response if state.feedback_ack is None else state.feedback_ack)
    return True
