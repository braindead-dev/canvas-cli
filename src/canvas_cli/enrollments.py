"""Own Canvas enrollment metadata and explicitly confirmed invitation responses."""

from urllib.parse import urlencode

from .client import CanvasError
from .group_content import _id, _number
from .roster import _enrollment, _filters
from .writes import account, check_flags, confirmed

TYPES = ('StudentEnrollment', 'TeacherEnrollment', 'TaEnrollment', 'DesignerEnrollment', 'ObserverEnrollment')
STATES = ('active', 'invited', 'creation_pending', 'deleted', 'rejected', 'completed', 'inactive',
          'current_and_invited', 'current_and_future', 'current_future_and_restricted', 'current_and_concluded')
NOTE = ('Own Canvas enrollment metadata only, complete for this native endpoint and its filters. '
        'Multiple sections/roles in one course remain separate records. Omitted states preserve Canvas defaults, '
        'normally active/invited, not every historical record. Canvas is not the university registrar: '
        'these records do not prove official registration, credits, waitlist position or tuition eligibility. '
        'No enrollment, role, read-marker or assessment change requested; grades/SIS/user associations are omitted.')


def _inventory(client, identity, max_pages, *, types=(), states=(), term=None):
    query = [('per_page', '100')]
    query.extend(('type[]', value) for value in types)
    query.extend(('state[]', value) for value in states)
    if term is not None:
        query.append(('enrollment_term_id', term))
    rows = client.list('/api/v1/users/self/enrollments?' + urlencode(query), max_pages)
    result = []
    for row in rows:
        course_id = _id(row, 'course_id')
        result.append(_enrollment(row, identity['user_id'], str(course_id)))
    if len({row['id'] for row in result}) != len(result):
        raise CanvasError('Canvas returned duplicate own enrollment IDs')
    return result


def read(client, max_pages=100, *, types=(), states=(), courses=(), term=None):
    if type(max_pages) is not int or max_pages < 1:
        raise CanvasError('Enrollment page limit must be a positive integer')
    selected_types, selected_states = _filters(types, TYPES), _filters(states, STATES)
    if not isinstance(courses, (list, tuple)):
        raise CanvasError('Course filters must be distinct numeric IDs')
    for course_id in courses:
        _number(course_id)
    if len(set(courses)) != len(courses):
        raise CanvasError('Course filters must be distinct numeric IDs')
    if term is not None:
        _number(term)
    identity = account(client)
    rows = _inventory(client, identity, max_pages, types=selected_types, states=selected_states, term=term)
    selected_courses = {int(course_id) for course_id in courses}
    return {**identity, 'enrollments': [row for row in rows if not selected_courses or row['course_id'] in selected_courses],
            'filters': {'types': selected_types, 'states': selected_states, 'course_ids': sorted(selected_courses),
                        'enrollment_term_id': int(term) if term is not None else None},
            'course_filter_applied_locally': bool(courses), 'complete_for_endpoint': True, 'note': NOTE}


def respond(client, course_id, enrollment_id, action, *, acknowledge=False, max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    _number(course_id)
    _number(enrollment_id)
    if action not in ('accept', 'reject') or acknowledge is not True:
        raise CanvasError('Invitation response requires accept/reject and --acknowledge-canvas-enrollment')
    if type(max_pages) is not int or max_pages < 1:
        raise CanvasError('Enrollment page limit must be a positive integer')
    identity = account(client)
    rows = _inventory(client, identity, max_pages, states=['invited'])
    current = next((row for row in rows if row['id'] == int(enrollment_id)), None)
    if current is None or current['course_id'] != int(course_id) or current.get('enrollment_state') != 'invited':
        raise CanvasError('The exact own course enrollment was not returned as an invitation; no change requested')
    preview = {**identity, 'invitation': current, 'action': action,
               'method': 'POST', 'route': f'/api/v1/courses/{course_id}/enrollments/{enrollment_id}/{action}', 'body': None,
               'acknowledge_canvas_enrollment': True,
               'effect': 'Respond only to this exact pending own Canvas course invitation.',
               'warning': 'Accepting changes Canvas membership/access; rejecting can hide coursework and may require '
                          'a new invitation or instructor help. This is not official university registration/drop, '
                          'a waitlist acceptance or a tuition adjustment. No new enrollment, role change or other '
                          'user is requested. Native course/self-enrollment restrictions still apply. The accept '
                          'endpoint can revive a concurrently rejected invitation; preflight is not an atomic lock. '
                          'Check an uncertain result before repeating.'}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    if not isinstance(response, dict) or response.get('success') is not True:
        raise CanvasError('Could not verify Canvas invitation acknowledgement. It may have succeeded; '
                          'check Canvas before repeating. No automatic retries or response-body logging.')
    return {**identity, 'course_id': int(course_id), 'enrollment_id': int(enrollment_id),
            'invitation_response': action, 'acknowledged': True,
            'note': 'Native acknowledgement only, not an independent readback or official university registration. '
                    'Only the selected own pending invitation was requested; verify uncertain access changes in Canvas.'}
