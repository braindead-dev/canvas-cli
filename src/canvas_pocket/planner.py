"""Current-user planner reads and explicitly confirmed personal task creation."""

from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

from .client import CanvasError
from .writes import account, check_flags, confirmed, own_id


def validate_date(value):
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except (ValueError, TypeError):
        raise CanvasError('Planner dates must use YYYY-MM-DD') from None
    return value


def window(start=None, end=None):
    start = start or datetime.now(timezone.utc).astimezone().date().isoformat()
    try:
        first = date.fromisoformat(validate_date(start))
        end = end or (first + timedelta(days=13)).isoformat()
        last = date.fromisoformat(validate_date(end))
    except (ValueError, TypeError, OverflowError):
        raise CanvasError('Planner dates must use YYYY-MM-DD') from None
    if last < first:
        raise CanvasError('--end must not precede --start')
    return start, end


def items(client, max_pages, start=None, end=None, courses=(), groups=(), filter_by=None):
    start, end = window(start, end)
    if filter_by not in (None, 'new_activity', 'incomplete_items', 'complete_items'):
        raise CanvasError('Unsupported planner filter')
    contexts = list(dict.fromkeys([f'course_{n}' for n in courses] +
                                 [f'group_{n}' for n in groups]))
    query = [('start_date', start), ('end_date', end), ('per_page', '100')]
    query += [('context_codes[]', context) for context in contexts]
    if filter_by:
        query.append(('filter', filter_by))
    rows = client.list('/api/v1/planner/items?' + urlencode(query), max_pages)
    if any(not isinstance(row, dict) for row in rows):
        raise CanvasError('Canvas returned malformed planner items')
    if any(row.get(key) is not None and not isinstance(row[key], dict)
           for row in rows for key in ('plannable', 'planner_override')):
        raise CanvasError('Canvas returned malformed planner details')
    return {'planner_window': {'start': start, 'end': end}, 'contexts': contexts,
            'filter': filter_by, 'items': rows,
            'note': 'Planner completion can be a personal override, not proof of an assignment submission. '
                    'This feed does not replace assignment, calendar, or external-tool requirements.'}


def notes(client, max_pages, start=None, end=None, courses=(), personal=False):
    if start:
        validate_date(start)
    if end:
        validate_date(end)
    if start and end and end < start:
        raise CanvasError('--end must not precede --start')
    query = [('per_page', '100')]
    if start:
        query.append(('start_date', start))
    if end:
        query.append(('end_date', end))
    contexts = list(dict.fromkeys(f'course_{n}' for n in courses))
    if personal:
        profile, _ = client.request('/api/v1/users/self/profile')
        user_id = own_id(profile)
        contexts.append(f'user_{user_id}')
    query += [('context_codes[]', context) for context in contexts]
    return client.list('/api/v1/planner_notes?' + urlencode(query), max_pages)


def create_note(client, title, todo_date, details='', course_id=None, yes=False, confirm=None):
    check_flags(yes, confirm)
    if not isinstance(title, str) or not title.strip():
        raise CanvasError('A nonempty task title is required')
    validate_date(todo_date)
    if not isinstance(details, str):
        raise CanvasError('Task details must be plain text')
    profile, _ = client.request('/api/v1/users/self/profile')
    user_id = own_id(profile)
    course = None
    body = {'title': title.strip(), 'todo_date': todo_date, 'details': details}
    if course_id:
        course, _ = client.request(f'/api/v1/courses/{course_id}')
        if not isinstance(course, dict) or str(course.get('id')) != course_id:
            raise CanvasError('Canvas returned a different course; refusing task creation')
        course = {key: course.get(key) for key in ('id', 'name', 'course_code')}
        body['course_id'] = int(course_id)
    preview = {'origin': client.host, 'user_id': user_id, 'course': course,
               'method': 'POST', 'route': '/api/v1/planner_notes', 'body': body}
    return confirmed(client, preview, yes, confirm)


def change_note(client, note_id, title=None, todo_date=None, details=None,
                course_id=None, clear_course=False, delete=False, yes=False, confirm=None):
    """Update only requested fields, or explicitly remove one current-user task."""
    check_flags(yes, confirm)
    if course_id and clear_course:
        raise CanvasError('Choose a course or clear it, not both')
    changes = {}
    if title is not None:
        if not isinstance(title, str) or not title.strip():
            raise CanvasError('A nonempty task title is required')
        changes['title'] = title.strip()
    if todo_date is not None:
        changes['todo_date'] = validate_date(todo_date)
    if details is not None:
        if not isinstance(details, str):
            raise CanvasError('Task details must be plain text')
        changes['details'] = details
    if course_id or clear_course:
        changes['course_id'] = int(course_id) if course_id else None
    if delete and changes:
        raise CanvasError('Task removal cannot also edit fields')
    if not delete and not changes:
        raise CanvasError('Choose at least one task field to update')
    identity = account(client)
    route = f'/api/v1/planner_notes/{note_id}'
    note, _ = client.request(route)
    if (not isinstance(note, dict) or str(note.get('id')) != note_id
            or type(note.get('user_id')) is not int or note['user_id'] != identity['user_id']):
        raise CanvasError('Canvas did not confirm this task belongs to the signed-in user')
    if note.get('workflow_state') == 'deleted':
        raise CanvasError('Task was already deleted; refusing another mutation')
    if 'course_id' in changes and (note.get('linked_object_id') or note.get('linked_object_type')):
        raise CanvasError('A linked task cannot change course association')
    course = None
    if course_id:
        course, _ = client.request(f'/api/v1/courses/{course_id}')
        if not isinstance(course, dict) or str(course.get('id')) != course_id:
            raise CanvasError('Canvas returned a different course; refusing task update')
        course = {key: course.get(key) for key in ('id', 'name', 'course_code')}
    before = {key: note.get(key) for key in ('id', 'user_id', 'title', 'details', 'description',
              'todo_date', 'course_id', 'linked_object_type', 'linked_object_id',
              'workflow_state', 'updated_at')}
    preview = {**identity, 'method': 'DELETE' if delete else 'PUT', 'route': route,
               'before': before, 'course': course, 'body': None if delete else changes,
               'effect': 'Removes this personal task; no assignment is deleted.' if delete else
                         'Edits this personal task; no assignment or submission is changed.'}
    return confirmed(client, preview, yes, confirm)
