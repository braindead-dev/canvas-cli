"""Authorized course group-set metadata, not a student allocation workflow."""

from urllib.parse import urlencode

from .client import CanvasError
from .group_content import _context, _id, _number

COLLABORATION_STATES = ('collaborative', 'non_collaborative', 'all')
NOTE = ('Native authorized metadata only; visibility may be role/section limited. '
        'Self-signup settings and limits are not proof that you can join a particular group. '
        'No category/group creation, membership allocation, enrollment or content changes. '
        'Leader/user associations, SIS/import IDs, progress messages and unknown private fields are omitted.')


def _scope(row, course_id):
    _id(row)
    if row.get('context_type') != 'Course' or type(row.get('course_id')) is not int or row['course_id'] != int(course_id):
        raise CanvasError('Canvas returned group-set metadata outside the requested course')


def _project(row, text, numbers, booleans):
    result = {key: row[key] for key in ('id', 'context_type', 'course_id')}
    for key in text:
        if key in row:
            if row[key] is not None and not isinstance(row[key], str):
                raise CanvasError('Canvas returned invalid group-set text metadata')
            result[key] = row[key]
    for key in numbers:
        if key in row:
            if row[key] is not None and (type(row[key]) is not int or row[key] < 0):
                raise CanvasError('Canvas returned invalid group-set numeric metadata')
            result[key] = row[key]
    for key in booleans:
        if key in row:
            if row[key] is not None and type(row[key]) is not bool:
                raise CanvasError('Canvas returned invalid group-set boolean metadata')
            result[key] = row[key]
    return result


def _category(row, course_id, category_id=None):
    _scope(row, course_id)
    if category_id is not None and row['id'] != int(category_id):
        raise CanvasError('Canvas returned a different group category')
    return _project(row, ('name', 'role', 'self_signup', 'self_signup_end_at', 'auto_leader', 'created_at'),
                    ('group_limit',), ('non_collaborative', 'protected', 'allows_multiple_memberships', 'is_member'))


def _page_limit(max_pages):
    if type(max_pages) is not int or max_pages < 1:
        raise CanvasError('Group-set page limit must be a positive integer')


def listing(client, course_id, max_pages=100, *, collaboration_state='collaborative'):
    _number(course_id)
    _page_limit(max_pages)
    if collaboration_state not in COLLABORATION_STATES:
        raise CanvasError('Collaboration state must be collaborative, non_collaborative or all')
    route, course = _context(client, course_id, 'course')
    rows = client.list(route + '/group_categories?' + urlencode({'per_page': 100, 'collaboration_state': collaboration_state}), max_pages)
    categories = [_category(row, course_id) for row in rows]
    if len({row['id'] for row in categories}) != len(categories):
        raise CanvasError('Canvas returned duplicate group-category IDs')
    for row in categories:
        state = row.get('non_collaborative')
        if (collaboration_state == 'collaborative' and state is True or
                collaboration_state == 'non_collaborative' and state is False):
            raise CanvasError('Canvas returned group categories outside the requested collaboration filter')
    return {'course_id': int(course_id), 'course_name': course.get('name'), 'group_categories': categories,
            'collaboration_state': collaboration_state, 'complete_for_endpoint': True, 'note': NOTE}


def _read(client, course_id, category_id):
    _number(course_id)
    _number(category_id)
    _, course = _context(client, course_id, 'course')
    row, links = client.request(f'/api/v1/group_categories/{category_id}')
    if links and 'rel="next"' in links:
        raise CanvasError('Unexpected group-category pagination')
    return course, _category(row, course_id, category_id)


def read(client, course_id, category_id):
    course, category = _read(client, course_id, category_id)
    return {'course_id': int(course_id), 'course_name': course.get('name'), 'group_category': category, 'note': NOTE}


def groups(client, course_id, category_id, max_pages=100):
    _page_limit(max_pages)
    course, category = _read(client, course_id, category_id)
    rows = client.list(f'/api/v1/group_categories/{category_id}/groups?per_page=100', max_pages)
    result = []
    for row in rows:
        _scope(row, course_id)
        if type(row.get('group_category_id')) is not int or row['group_category_id'] != int(category_id):
            raise CanvasError('Canvas returned a group outside the requested group category')
        result.append({**_project(row, ('name', 'role', 'join_level', 'created_at'), ('members_count', 'max_membership'),
                                 ('non_collaborative', 'concluded', 'is_full')), 'group_category_id': int(category_id)})
    if len({row['id'] for row in result}) != len(result):
        raise CanvasError('Canvas returned duplicate category-group IDs')
    return {'course_id': int(course_id), 'course_name': course.get('name'), 'group_category': category,
            'category_groups': result, 'complete_for_endpoint': True, 'note': NOTE}
