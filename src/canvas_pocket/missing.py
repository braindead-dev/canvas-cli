"""Read the signed-in student's native missing-submission inventory, not a guess."""

from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .client import CanvasError
from .snapshot import redact
from .writes import account


def _courses(values):
    if values is None:
        return []
    if not isinstance(values, (list, tuple)):
        raise CanvasError('Course filters must be a list of positive numeric IDs')
    result = []
    for value in values:
        if (not isinstance(value, str) or not value.isascii() or not value.isdecimal() or
                int(value) < 1 or str(int(value)) != value):
            raise CanvasError('Expected a positive numeric course ID')
        if value not in result:
            result.append(value)
    return result


def read(client, max_pages=100, *, course_ids=None, submittable=False,
         current_grading_period=False, include_planner=False, time_zone='local'):
    selected = _courses(course_ids)
    if any(type(flag) is not bool for flag in (submittable, current_grading_period, include_planner)):
        raise CanvasError('Missing-work filters must be explicit booleans')
    try:
        zone = None if time_zone == 'local' else ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise CanvasError('Unknown IANA time zone; use e.g. America/Los_Angeles') from None
    identity = account(client)
    query = [('per_page', '100'), ('include[]', 'course')]
    if include_planner:
        query.append(('include[]', 'planner_overrides'))
    query.extend(('course_ids[]', value) for value in selected)
    if submittable:
        query.append(('filter[]', 'submittable'))
    if current_grading_period:
        query.append(('filter[]', 'current_grading_period'))
    route = '/api/v1/users/self/missing_submissions?' + urlencode(query)
    rows = client.list(route, max_pages)
    output, seen = [], set()
    for row in rows:
        if (not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] < 1 or
                type(row.get('course_id')) is not int or row['course_id'] < 1 or row.get('published') is False):
            raise CanvasError('Canvas returned invalid missing-work assignment metadata')
        if selected and str(row['course_id']) not in selected:
            raise CanvasError('Canvas returned missing work outside the selected courses')
        key = (row['course_id'], row['id'])
        if key in seen:
            raise CanvasError('Canvas returned duplicate missing-work assignments')
        seen.add(key)
        course = row.get('course')
        if course is not None and (not isinstance(course, dict) or type(course.get('id')) is not int or
                                   course['id'] != row['course_id']):
            raise CanvasError('Canvas returned a different course for a missing assignment')
        item = {key: row.get(key) for key in ('id', 'name', 'course_id', 'due_at', 'unlock_at', 'lock_at',
                                             'html_url', 'points_possible', 'submission_types', 'locked_for_user')}
        item['course_name'] = course.get('name') if course else None
        item['status_source'] = 'canvas_missing_submissions'
        item['due_local'] = None
        item['due_display'] = 'Unknown due time'
        value = row.get('due_at')
        if isinstance(value, str):
            try:
                instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
                if instant.tzinfo:
                    local = instant.astimezone(zone) if zone else instant.astimezone()
                    item['due_local'] = local.isoformat()
                    item['due_display'] = local.strftime('%a %b %d, %Y %I:%M %p %Z')
            except ValueError:
                pass
        if include_planner:
            override = row.get('planner_override')
            if override is not None:
                if (not isinstance(override, dict) or type(override.get('id')) is not int or override['id'] < 1 or
                        type(override.get('user_id')) is not int or override['user_id'] != identity['user_id'] or
                        override.get('plannable_type') != 'assignment' or
                        type(override.get('plannable_id')) is not int or override['plannable_id'] != row['id'] or
                        any(override.get(field) is not None and type(override[field]) is not bool
                            for field in ('marked_complete', 'dismissed'))):
                    raise CanvasError('Canvas returned a planner override outside this own assignment')
                item['planner_override'] = {key: override.get(key) for key in
                                            ('id', 'marked_complete', 'dismissed', 'updated_at')}
            else:
                item['planner_override'] = None
        output.append(redact(item))
    return {'missing_assignments': output, 'scope': 'own_student', 'user_id': identity['user_id'],
            'course_ids': [int(value) for value in selected], 'only_submittable': submittable,
            'current_grading_period': current_grading_period, 'time_zone': time_zone,
            'include_planner': include_planner, 'complete_for_endpoint': True,
            'complete_coursework_inventory': False,
            'note': 'Canvas lists native past-due missing submissions; this is not every unfinished task or '
                    'a recalculated late policy. Filters are applied by Canvas. A planner checkmark does not '
                    'submit work or clear the missing status. GET only; no grades or read markers changed.'}
