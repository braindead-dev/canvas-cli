"""Comment only on the current user's submission, never update grading fields."""

from .client import CanvasError
from .writes import account, check_flags, confirmed


def comment(client, course_id, assignment_id, text, attempt=None,
            group_comment=False, yes=False, confirm=None):
    check_flags(yes, confirm)
    if not isinstance(text, str) or not text.strip():
        raise CanvasError('A nonempty plain-text submission comment is required')
    if attempt is not None and (type(attempt) is not int or attempt < 1):
        raise CanvasError('Comment attempt must be a positive integer')
    identity = account(client)
    assignment, _ = client.request(f'/api/v1/courses/{course_id}/assignments/{assignment_id}')
    if (not isinstance(assignment, dict) or str(assignment.get('id')) != assignment_id or
            (assignment.get('course_id') is not None and str(assignment['course_id']) != course_id)):
        raise CanvasError('Canvas returned a different assignment; refusing comment')
    if assignment.get('published') is False:
        raise CanvasError('Assignment is unpublished')
    submission, _ = client.request(f'/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/self')
    if (not isinstance(submission, dict) or str(submission.get('assignment_id')) != assignment_id or
            type(submission.get('user_id')) is not int or submission['user_id'] != identity['user_id'] or
            submission.get('assignment_visible') is False):
        raise CanvasError('Canvas did not confirm this submission belongs to the signed-in user')
    if group_comment and not assignment.get('group_category_id'):
        raise CanvasError('--group-comment requires a confirmed group assignment')
    if attempt is not None:
        current = submission.get('attempt')
        if type(current) is not int or attempt > current:
            raise CanvasError('That submission attempt has not been confirmed')
    body = {'comment': {'text_comment': text.strip(), 'group_comment': bool(group_comment)}}
    if attempt is not None:
        body['comment']['attempt'] = attempt
    preview = {**identity, 'method': 'PUT',
               'route': f"/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/{identity['user_id']}",
               'assignment': {key: assignment.get(key) for key in
                              ('id', 'name', 'course_id', 'group_category_id')},
               'submission': {key: submission.get(key) for key in
                              ('id', 'assignment_id', 'user_id', 'attempt', 'submitted_at', 'workflow_state')},
               'body': body,
               'effect': 'Adds a comment only, not a submission, grade, or read-status change.',
               'audience': 'Submission group and graders' if group_comment else
                           'Signed-in student and users permitted to view this submission'}
    return confirmed(client, preview, yes, confirm)
