"""Shared GraphQL metadata checks for an existing, exact own submission."""

from .client import CanvasError
from .group_content import _number

POLICY = {'submission_types': 'submissionTypes', 'allowed_extensions': 'allowedExtensions', 'published': 'published',
          'due_at': 'dueAt', 'unlock_at': 'unlockAt', 'lock_at': 'lockAt', 'updated_at': 'updatedAt',
          'group_category_id': 'groupCategoryId', 'grade_group_students_individually': 'gradeGroupStudentsIndividually',
          'allowed_attempts': 'allowedAttempts', 'state': 'state'}
ASSIGNMENT_FIELDS = '_id courseId ' + ' '.join(POLICY.values())
SUBMISSION_FIELDS = '_id userId assignmentId assignment { _id courseId } attempt state submittedAt'


def context(data, identity, course_id, assignment_id):
    _number(course_id)
    _number(assignment_id)
    if not isinstance(data, dict) or any(key not in data for key in ('assignment', 'submission')):
        raise CanvasError('Canvas omitted selected own submission or assignment metadata')
    assignment = data['assignment']
    if not isinstance(assignment, dict) or assignment.get('_id') != assignment_id or assignment.get('courseId') != course_id:
        raise CanvasError('Canvas returned a different assignment or course')
    if any(key not in assignment for key in POLICY.values()):
        raise CanvasError('Canvas omitted selected assignment policy')
    policy = {key: assignment[native] for key, native in POLICY.items()}
    for key in ('submission_types', 'allowed_extensions'):
        if policy[key] is not None and (not isinstance(policy[key], list) or any(not isinstance(item, str) for item in policy[key])):
            raise CanvasError('Canvas returned malformed assignment policy')
    for key in ('published', 'grade_group_students_individually'):
        if policy[key] is not None and type(policy[key]) is not bool:
            raise CanvasError('Canvas returned malformed assignment policy')
    row, submission = data['submission'], None
    if row is not None:
        if (not isinstance(row, dict) or row.get('userId') != str(identity['user_id']) or row.get('assignmentId') != assignment_id
                or row.get('assignment') != {'_id': assignment_id, 'courseId': course_id}):
            raise CanvasError('Canvas returned a different or anonymously hidden submission owner/assignment/course')
        if (type(row.get('attempt')) is not int or row['attempt'] < 0 or not isinstance(row.get('state'), str)
                or not row['state'] or 'submittedAt' not in row
                or row['submittedAt'] is not None and not isinstance(row['submittedAt'], str)):
            raise CanvasError('Canvas returned unavailable own submission metadata')
        submission = {'id': _number(row.get('_id')), 'attempt': row['attempt'], 'state': row['state'],
                      'submitted_at': row['submittedAt']}
    return {**identity, 'course_id': course_id, 'assignment_id': assignment_id,
            'assignment_policy': policy, 'submission': submission}
