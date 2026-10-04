"""Visible own-submission comment indicators, not feedback content or completion."""

from .client import CanvasError
from .comment_inventory import inspect
from .group_content import _number
from .own_submission import ASSIGNMENT_FIELDS, SUBMISSION_FIELDS
from .writes import check_flags, review

_FIELDS = ('_id submissionId assignment { _id courseId } course { _id } '
           'draft attempt createdAt updatedAt provisional read')
_READ = ('query CanvasFeedbackComments($assignmentId: ID!, $userId: ID!, $attempt: Int, $after: String) { '
         'assignment(id: $assignmentId) { ' + ASSIGNMENT_FIELDS + ' } '
         'submission(assignmentId: $assignmentId, userId: $userId) { ' + SUBMISSION_FIELDS + ' readState '
         'commentsConnection(first: 50, after: $after, filter: {allComments: false, forAttempt: $attempt, peerReview: false}, '
         'includeDraftComments: false, includeDraftsFromOthers: false, includeProvisionalComments: false) { '
         'nodes { ' + _FIELDS + ' } pageInfo { hasNextPage endCursor } } } }')
_MARK = ('mutation CanvasFeedbackCommentRead($input: MarkSubmissionCommentsReadInput!) { '
         'markSubmissionCommentsRead(input: $input) { errors { attribute } submissionComments { ' + _FIELDS + ' } } }')
_NOTE = ('Visible published comment metadata on your own submission, including your own and others\' comments, '
         'not a grader-only or owed-review inventory. No author identities, bodies, scores, annotations or assessment '
         'attempts are requested. Native attempts nil/0/1 share a bucket. Effective comment read can be true because '
         'the aggregate submission is read; it does not independently prove a stored viewed-comment row or content viewing.')
_EFFECT = ('Marks exactly one selected published comment viewed for the signed-in user. It does not mark every visible '
           'comment, clear grade/comment/rubric participation items, acknowledge other feedback preferences, or complete work. '
           'Confirmation is not an atomic lock. Native viewed-row creation may have applied before an error. '
           'No unread inverse is exposed by this command; no automatic retries, bulk marking or rollback.')
_UNCERTAIN = ('The selected comment indicator outcome is unverified; it may have applied. Inspect Canvas before repeating. '
              'No private response was logged. No automatic retries.')


def _comment(row, state, attempt):
    if (not isinstance(row, dict) or any(key not in row for key in (
            '_id', 'submissionId', 'assignment', 'course', 'draft', 'attempt', 'createdAt', 'updatedAt', 'provisional', 'read'))
            or row['submissionId'] != state['submission']['id']
            or row['assignment'] != {'_id': state['assignment_id'], 'courseId': state['course_id']}
            or row['course'] != {'_id': state['course_id']}):
        raise CanvasError('Canvas returned unavailable or foreign feedback-comment metadata')
    if (row['draft'] is not False or row['provisional'] is not False or type(row['read']) is not bool
            or type(row['attempt']) is not int or row['attempt'] < 0
            or row['attempt'] not in ((0, 1) if attempt <= 1 else (attempt,))
            or not isinstance(row['createdAt'], str) or not row['createdAt']
            or row['updatedAt'] is not None and not isinstance(row['updatedAt'], str)):
        raise CanvasError('Canvas returned malformed, draft or provisional feedback-comment indicators')
    return {'id': _number(row['_id']), 'attempt': row['attempt'], 'created_at': row['createdAt'],
            'updated_at': row['updatedAt'], 'effective_read': row['read']}


def _inspect(client, course_id, assignment_id, *, attempt=None, all_attempts=False, max_pages=100):
    return inspect(client, course_id, assignment_id, _READ, 'CanvasFeedbackComments', _comment, feedback=True,
                   attempt=attempt, all_attempts=all_attempts, max_pages=max_pages)


def _projection(state):
    return {**{key: value for key, value in state.items() if key != 'comments'},
            'comments': [state['comments'][key] for key in sorted(state['comments'], key=int)],
            'feedback_comment_indicators': True, 'note': _NOTE}


def read(client, course_id, assignment_id, *, attempt=None, all_attempts=False, max_pages=100):
    return _projection(_inspect(client, course_id, assignment_id, attempt=attempt, all_attempts=all_attempts, max_pages=max_pages))


def mark_read(client, course_id, assignment_id, comment_id, *, attempt=None, max_pages=100,
              acknowledge=False, yes=False, confirm=None):
    check_flags(yes, confirm)
    _number(comment_id)
    if not acknowledge:
        raise CanvasError('Use --acknowledge-feedback-indicators even for preview: ' + _EFFECT)
    before = _inspect(client, course_id, assignment_id, attempt=attempt, max_pages=max_pages)
    if before['submission'] is None or comment_id not in before['comments']:
        raise CanvasError('Choose an exact visible published comment on your existing own submission in the selected attempt')
    body = {'query': _MARK, 'operationName': 'CanvasFeedbackCommentRead',
            'variables': {'input': {'submissionId': before['submission']['id'], 'submissionCommentIds': [comment_id]}}}
    preview = {**_projection(before), 'method': 'POST', 'route': '/api/graphql', 'body': body,
               'selected_comment_id': comment_id, 'effect': _EFFECT}
    result = review(preview, yes, confirm)
    if result is not None:
        return result
    try:
        data = client.graphql(_MARK, body['variables'], body['operationName'])
        ack = data.get('markSubmissionCommentsRead')
        if (not isinstance(ack, dict) or 'errors' not in ack or ack['errors'] not in (None, [])
                or not isinstance(ack.get('submissionComments'), list)
                or len(ack['submissionComments']) != 1):
            raise CanvasError(_UNCERTAIN)
        item = _comment(ack['submissionComments'][0], before, before['selected_attempts'][0])
        selected = before['comments'][comment_id]
        if not item['effective_read'] or {key: value for key, value in item.items() if key != 'effective_read'} != {
                key: value for key, value in selected.items() if key != 'effective_read'}:
            raise CanvasError(_UNCERTAIN)
        after = _inspect(client, course_id, assignment_id, attempt=before['selected_attempts'][0], max_pages=max_pages)
        excluded = ('comments', 'aggregate_read_state')
        if {key: value for key, value in before.items() if key not in excluded} != {
                key: value for key, value in after.items() if key not in excluded}:
            raise CanvasError(_UNCERTAIN)
        observed = after['comments'].get(comment_id)
        if observed != {**selected, 'effective_read': True}:
            raise CanvasError(_UNCERTAIN)
    except CanvasError as error:
        raise CanvasError(_UNCERTAIN, status=error.status) from None
    changed = (set(before['comments']) ^ set(after['comments'])) - {comment_id}
    changed |= {key for key in set(before['comments']) & set(after['comments'])
                if key != comment_id and before['comments'][key] != after['comments'][key]}
    return {**_projection(after), 'mutation_acknowledged': True, 'selected_comment_id': comment_id,
            'effective_readback_verified': True, 'viewed_row_storage_verified': False,
            'other_observed_comment_changes': sorted(changed, key=int), 'coursework_completion_requested': False,
            'note': _NOTE + ' ' + _EFFECT + ' Other observed changes are not attributed exclusively to this request.'}
