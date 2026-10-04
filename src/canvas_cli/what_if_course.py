"""Own published-submission hypotheses and explicitly whole-course native reset."""

from .access import query
from .client import CanvasError
from .group_content import _number
from .what_if import _forecasts, _score
from .writes import account, check_flags, review

_READ = ('query CanvasCourseWhatIf($courseId: ID!, $userId: ID!, $after: String) { '
         'course(id: $courseId) { _id state submissionsConnection(first: 50, after: $after, studentIds: [$userId], '
         'filter: {states: [unsubmitted, submitted, pending_review, graded, ungraded]}) { '
         'nodes { _id userId assignmentId assignment { _id courseId published } attempt state submittedAt studentEnteredScore } '
         'pageInfo { hasNextPage endCursor } } } }')
_NOTE = ('Reported own active submissions for published assignments only, including unsubmitted rows. '
         'Pagination completeness is not a complete inventory of all stored hypotheses; hidden/deleted assignment or submission rows remain unknown. '
         'No answers, comments, official grades, assessment attempts or submission creation requested.')
_EFFECT = ('Clears ALL own saved what-if scores in this course, including hidden/historical rows absent from the reported inventory. '
           'The native bulk operation updates timestamps on every own submission row, including already-clear rows, then recalculates course totals. '
           'Only reported rows can be independently checked; hidden-row clearing is unverified. No official grade or coursework-completion change requested. '
           'Calculation can fail after clearing. No per-assignment fallback, polling, automatic retries or rollback. Confirmation is not an atomic lock.')
_UNCERTAIN = ('The course-wide what-if reset is unverified; ALL own hypotheses may already have been cleared even if calculation failed. '
              'Inspect Canvas before repeating. No private response was logged. No automatic retries.')


def _row(row, identity, course_id):
    if (not isinstance(row, dict) or row.get('userId') != str(identity['user_id'])
            or row.get('assignment') != {'_id': row.get('assignmentId'), 'courseId': course_id, 'published': True}
            or row.get('assignment', {}).get('published') is not True
            or type(row.get('attempt')) is not int or row['attempt'] < 0
            or row.get('state') not in ('unsubmitted', 'submitted', 'pending_review', 'graded', 'ungraded')
            or 'submittedAt' not in row or row['submittedAt'] is not None and not isinstance(row['submittedAt'], str)
            or 'studentEnteredScore' not in row):
        raise CanvasError('Canvas returned unavailable, foreign or unpublished own hypothesis metadata')
    return {'id': _number(row.get('_id')), 'assignment_id': _number(row['assignmentId']), 'attempt': row['attempt'],
            'state': row['state'], 'submitted_at': row['submittedAt'], 'student_entered_score': _score(row['studentEnteredScore'])}


def read(client, course_id, *, max_pages=100):
    _number(course_id)
    if type(max_pages) is not int or max_pages < 1:
        raise CanvasError('Use a positive hypothesis-inventory page cap')
    identity = account(client)
    route = f'/api/v1/courses/{course_id}'
    rights = query(client, route, ['reset_what_if_grades'])
    baseline, rows, cursor, cursors = None, {}, None, set()
    for _ in range(max_pages):
        data = client.graphql(_READ, {'courseId': course_id, 'userId': str(identity['user_id']), 'after': cursor}, 'CanvasCourseWhatIf')
        course = data.get('course') if isinstance(data, dict) else None
        if (not isinstance(course, dict) or course.get('_id') != course_id
                or course.get('state') not in ('created', 'claimed', 'available', 'completed', 'deleted')):
            raise CanvasError('Canvas returned unavailable or different course metadata')
        state = {'course_id': course_id, 'course_state': course['state']}
        if baseline is not None and state != baseline:
            raise CanvasError('Course changed during hypothesis pagination; no mutation sent')
        baseline = state
        connection = course.get('submissionsConnection')
        if (not isinstance(connection, dict) or not isinstance(connection.get('nodes'), list)
                or not isinstance(connection.get('pageInfo'), dict)):
            raise CanvasError('Canvas returned unavailable reported hypothesis inventory')
        for value in connection['nodes']:
            item = _row(value, identity, course_id)
            if item['id'] in rows:
                raise CanvasError('Duplicate own submission IDs; reported hypothesis inventory is incomplete')
            rows[item['id']] = item
        page = connection['pageInfo']
        if (type(page.get('hasNextPage')) is not bool or 'endCursor' not in page
                or page['endCursor'] is not None and not isinstance(page['endCursor'], str)):
            raise CanvasError('Canvas returned malformed hypothesis pagination')
        if not page['hasNextPage']:
            break
        if not page['endCursor'] or page['endCursor'] in cursors or not connection['nodes']:
            raise CanvasError('Canvas returned looping or empty hypothesis pagination')
        cursor = page['endCursor']
        cursors.add(cursor)
    else:
        raise CanvasError('Reported hypothesis inventory exceeded the page cap; no mutation sent')
    if account(client) != identity or query(client, route, ['reset_what_if_grades']) != rights:
        raise CanvasError('Signed-in account or reset permission changed during inspection; no mutation sent')
    return {**identity, **baseline, 'reset_permission': rights['reset_what_if_grades'], 'submissions': rows,
            'what_if_course_inventory': 'complete_reported_published_active', 'hidden_rows_verified': False, 'note': _NOTE}


def reset(client, course_id, *, acknowledge_all=False, include_totals=False, max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    if not acknowledge_all:
        raise CanvasError('Use --acknowledge-all-what-if even for preview: ' + _EFFECT)
    before = read(client, course_id, max_pages=max_pages)
    if before['course_state'] != 'available' or not before['reset_permission']:
        raise CanvasError('Native course reset permission is unavailable; no reset or individual-score fallback sent')
    route = f'/api/v1/courses/{course_id}/what_if_grades/reset'
    preview = {**before, 'method': 'PUT', 'route': route, 'include_totals': include_totals, 'effect': _EFFECT}
    result = review(preview, yes, confirm)
    if result is not None:
        return result
    try:
        ack, _ = client.request(route, 'PUT')
        totals = _forecasts(ack.get('grades') if isinstance(ack, dict) else None)
        after = read(client, course_id, max_pages=max_pages)
        expected = {**before, 'submissions': {key: {**row, 'student_entered_score': None} for key, row in before['submissions'].items()}}
        if after != expected:
            raise CanvasError(_UNCERTAIN)
    except CanvasError as error:
        raise CanvasError(_UNCERTAIN, status=error.status) from None
    return {**after, 'mutation_acknowledged': True, 'reported_hypotheses_clear_verified': True,
            'totals_included': include_totals, 'native_total_count': len(totals),
            **({'native_recalculated_totals': totals} if include_totals else {}),
            'official_grade_change_requested': False, 'coursework_completion_requested': False, 'note': _NOTE + ' ' + _EFFECT}
