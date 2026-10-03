"""Efficient own-course submission reads with opt-in history and private content."""

from urllib.parse import urlencode

from .client import CanvasError
from .snapshot import redact
from .writes import account

STATES = ('submitted', 'unsubmitted', 'graded', 'pending_review')
FIELDS = ('id', 'assignment_id', 'user_id', 'attempt', 'workflow_state', 'submitted_at', 'graded_at',
          'posted_at', 'grade', 'score', 'grade_matches_current_submission', 'submission_type',
          'html_url', 'preview_url', 'late', 'missing', 'excused', 'assignment_visible',
          'late_policy_status', 'points_deducted', 'seconds_late', 'redo_request')


def _number(value):
    if (not isinstance(value, str) or not value.isascii() or not value.isdecimal() or
            int(value) < 1 or str(int(value)) != value):
        raise CanvasError('Expected a positive numeric course or assignment ID')
    return value


def _item(row, assignment_id, user_id, content, *, history=False):
    # Classic Quiz version serialization can contain null historical attempts.
    if history and row is None:
        return None
    if not isinstance(row, dict):
        raise CanvasError('Canvas returned invalid submission metadata')
    for key, expected in (('assignment_id', assignment_id), ('user_id', user_id)):
        if (not history or row.get(key) is not None) and (type(row.get(key)) is not int or row[key] != expected):
            raise CanvasError('Canvas returned submission data outside the signed-in user or assignment')
    result = {key: row[key] for key in FIELDS if key in row}
    if content:
        for key in ('body', 'url', 'attachments'):
            if key in row:
                result[key] = row[key]
    return redact(result)


def read(client, course_id, max_pages=100, *, assignment_ids=None, state=None,
         include_history=False, include_comments=False, include_content=False):
    _number(course_id)
    if assignment_ids is not None and not isinstance(assignment_ids, (list, tuple)):
        raise CanvasError('Assignment filters must be a list of positive numeric IDs')
    selected = list(dict.fromkeys(_number(value) for value in assignment_ids or []))
    if state is not None and state not in STATES:
        raise CanvasError('Unsupported native submission workflow state')
    if any(type(flag) is not bool for flag in (include_history, include_comments, include_content)):
        raise CanvasError('Submission association flags must be explicit booleans')
    identity = account(client)
    query = [('student_ids[]', str(identity['user_id'])), ('include[]', 'assignment'), ('per_page', '100')]
    query.extend(('assignment_ids[]', value) for value in selected)
    if state:
        query.append(('workflow_state', state))
    if include_history:
        query.append(('include[]', 'submission_history'))
    if include_comments:
        query.append(('include[]', 'submission_comments'))
    rows = client.list(f'/api/v1/courses/{course_id}/students/submissions?' + urlencode(query), max_pages)
    output, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or type(row.get('assignment_id')) is not int or row['assignment_id'] < 1:
            raise CanvasError('Canvas returned invalid submission assignment IDs')
        assignment_id = row['assignment_id']
        if (selected and str(assignment_id) not in selected or
                row.get('course_id') is not None and (type(row['course_id']) is not int or str(row['course_id']) != course_id)):
            raise CanvasError('Canvas returned submissions outside the selected course or assignments')
        if assignment_id in seen:
            raise CanvasError('Canvas returned duplicate own assignment submissions')
        seen.add(assignment_id)
        if state and row.get('workflow_state') != state:
            raise CanvasError('Canvas returned submissions outside the selected workflow state')
        assignment = row.get('assignment')
        if assignment is not None and (not isinstance(assignment, dict) or type(assignment.get('id')) is not int or
                                       assignment['id'] != assignment_id or
                                       assignment.get('course_id') is not None and (
                                           type(assignment['course_id']) is not int or str(assignment['course_id']) != course_id)):
            raise CanvasError('Canvas returned a different assignment or course association')
        readable = row.get('assignment_visible') is not False and (not assignment or assignment.get('published') is not False)
        content = include_content and readable
        item = _item(row, assignment_id, identity['user_id'], content)
        item['assignment'] = ({key: assignment.get(key) for key in
                               ('id', 'course_id', 'name', 'due_at', 'published', 'html_url')}
                              if assignment else None)
        if include_content and not readable:
            item['content_withheld'] = 'Assignment is not currently visible/published; no bodies or attachments exposed.'
        if include_history:
            history = row.get('submission_history')
            if history is not None and not isinstance(history, list):
                raise CanvasError('Canvas returned invalid submission history')
            item['submission_history'] = ([_item(attempt, assignment_id, identity['user_id'], content, history=True)
                                            for attempt in history] if history is not None else None)
        if include_comments:
            comments = row.get('submission_comments')
            if comments is not None and (not isinstance(comments, list) or any(not isinstance(c, dict) for c in comments)):
                raise CanvasError('Canvas returned invalid submission comments')
            item['submission_comments'] = ([{key: comment[key] for key in
                                             ('id', 'author_id', 'created_at', 'edited_at') +
                                             (('comment', 'media_comment', 'attachments') if content else ())
                                             if key in comment} for comment in comments] if comments is not None else None)
        output.append(redact(item))
    return {**identity, 'course_id': int(course_id), 'submissions': output,
            'assignment_ids': [int(value) for value in selected], 'workflow_state': state,
            'include_history': include_history, 'include_comments': include_comments, 'include_content': include_content,
            'complete_for_endpoint': True, 'complete_coursework_inventory': False,
            'note': 'Own native submission records only, with all pages followed. Missing associations remain unknown. '
                    'History and bodies may contain private academic data; grades can describe an earlier attempt '
                    'when grade_matches_current_submission is false. GET only; no read_status inclusion, '
                    'assessment attempts, grading or submission writes.'}
