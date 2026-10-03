"""Scoped, metadata-first rosters. Native visibility is not a universal census."""

from urllib.parse import urlencode

from .client import CanvasError
from .group_content import _context, _id, _number

ENROLLMENT_TYPES = ('teacher', 'student', 'student_view', 'ta', 'observer', 'designer')
ENROLLMENT_STATES = ('active', 'invited', 'rejected', 'completed', 'inactive')
NOTE = ('Complete only for this authorized endpoint and its filters. Section restrictions and native '
        'visibility may omit people; this is not a total membership count or proof of empty seats. '
        'No enrollment, membership, message or read-marker changes. Canvas may log roster-access analytics. '
        'Names and optional email are private data; do not commit live output to a public repository.')


def _filters(values, allowed):
    if not isinstance(values, (list, tuple)) or any(value not in allowed for value in values) or len(set(values)) != len(values):
        raise CanvasError('Roster filters must be distinct supported values')
    return sorted(values)


def _strings(row, fields):
    result = {}
    for key in fields:
        if key in row:
            if row[key] is not None and not isinstance(row[key], str):
                raise CanvasError('Canvas returned invalid roster text metadata')
            result[key] = row[key]
    return result


def _enrollment(row, user_id, course_id):
    _id(row)
    if (type(row.get('course_id')) is not int or row['course_id'] != int(course_id) or
            type(row.get('user_id')) is not int or row['user_id'] != user_id):
        raise CanvasError('Canvas returned an enrollment outside the requested course/user')
    result = {key: row[key] for key in ('id', 'course_id', 'user_id')}
    result.update(_strings(row, ('type', 'role', 'enrollment_state', 'created_at', 'updated_at', 'start_at', 'end_at')))
    for key in ('course_section_id', 'role_id'):
        if key in row and row[key] is not None:
            result[key] = _id(row, key)
    # Never include grades, private pseudonyms, login/SIS IDs, analytics or observer associations.
    return result


def _user(row, course_id=None, *, include_email=False, include_enrollments=False):
    user_id = _id(row)
    result = {'id': user_id, **_strings(row, ('name', 'short_name', 'sortable_name'))}
    if include_email:
        result.update(_strings(row, ('email',)))
    if include_enrollments:
        rows = row.get('enrollments')
        if not isinstance(rows, list):
            raise CanvasError('Canvas did not return the requested enrollment metadata')
        result['enrollments'] = [_enrollment(enrollment, user_id, course_id) for enrollment in rows]
        if len({item['id'] for item in result['enrollments']}) != len(rows):
            raise CanvasError('Canvas returned duplicate enrollment IDs')
    return result


def listing(client, context_id, context_type='course', max_pages=100, *, search=None,
            enrollment_types=(), enrollment_states=(), sections=(), include_enrollments=False,
            include_email=False, exclude_inactive=None):
    if context_type not in ('course', 'group'):
        raise CanvasError('Roster context must be course or group')
    _number(context_id)
    if type(max_pages) is not int or max_pages < 1:
        raise CanvasError('Roster page limit must be a positive integer')
    if search is not None and (not isinstance(search, str) or len(search.strip()) < 2 or
                              any(ord(char) < 32 or ord(char) == 127 for char in search)):
        raise CanvasError('Roster search must contain at least two characters and no controls')
    types = _filters(enrollment_types, ENROLLMENT_TYPES)
    states = _filters(enrollment_states, ENROLLMENT_STATES)
    if not isinstance(sections, (list, tuple)):
        raise CanvasError('Section filters must be numeric IDs')
    for section in sections:
        _number(section)
    if len(set(sections)) != len(sections):
        raise CanvasError('Section filters must be distinct numeric IDs')
    if exclude_inactive is not None and type(exclude_inactive) is not bool:
        raise CanvasError('Exclude-inactive must be an explicit boolean')
    if (context_type == 'group' and (types or states or sections or include_enrollments) or
            context_type == 'course' and exclude_inactive is not None):
        raise CanvasError('Use enrollment/section filters for course rosters, exclude-inactive for group rosters')
    query = [('per_page', '100')]
    if search is not None:
        query.append(('search_term', search.strip()))
    query.extend(('enrollment_type[]', value) for value in types)
    query.extend(('enrollment_state[]', value) for value in states)
    query.extend(('section_ids[]', value) for value in sorted(sections, key=int))
    if include_enrollments:
        query.append(('include[]', 'enrollments'))
    if exclude_inactive is not None:
        query.append(('exclude_inactive', str(exclude_inactive).lower()))
    route, context = _context(client, context_id, context_type)
    rows = client.list(route + '/users?' + urlencode(query), max_pages)
    users = [_user(row, context_id if context_type == 'course' else None,
                   include_email=include_email, include_enrollments=include_enrollments) for row in rows]
    if len({row['id'] for row in users}) != len(users):
        raise CanvasError('Canvas returned duplicate roster user IDs; no partial roster emitted')
    result = {'context_type': context_type, f'{context_type}_id': int(context_id),
              'context_name': context.get('name'), 'users': users, 'returned_user_count': len(users),
              'filters': {'search_term': search.strip() if search is not None else None,
                          'enrollment_types': types, 'enrollment_states': states,
                          'section_ids': [int(value) for value in sorted(sections, key=int)],
                          'exclude_inactive': exclude_inactive},
              'email_included': include_email, 'enrollments_included': include_enrollments,
              'complete_for_endpoint': True, 'note': NOTE}
    if context_type == 'group':
        if context.get('members_count') is not None:
            if type(context['members_count']) is not int or context['members_count'] < 0:
                raise CanvasError('Canvas returned an invalid group member count')
            result['reported_members_count'] = context['members_count']
        if context.get('is_full') is not None:
            if type(context['is_full']) is not bool:
                raise CanvasError('Canvas returned invalid native group-capacity metadata')
            result['native_is_full'] = context['is_full']
    return result
