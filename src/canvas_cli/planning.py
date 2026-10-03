"""Build a deadline index from assignments rather than Canvas's short upcoming feed."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .client import CanvasError


def active_courses(client, max_pages):
    return client.list('/api/v1/courses?enrollment_state=active&per_page=100', max_pages)


def deadlines(client, max_pages, days=14, course_id=None, courses=None):
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days) if days is not None else None
    courses = [{'id': course_id}] if course_id else (courses if courses is not None else active_courses(client, max_pages))
    dated_items, unavailable = [], []
    for course in courses:
        cid = course.get('id')
        if not cid:
            continue
        try:
            assignments = client.list(f'/api/v1/courses/{cid}/assignments?per_page=100', max_pages)
        except CanvasError as exc:
            if exc.status not in (403, 404):
                raise
            if course_id:
                raise
            unavailable.append({'course_id': cid, 'reason': str(exc)})
            continue
        for assignment in assignments:
            raw_due = assignment.get('due_at')
            if not raw_due:
                continue
            try:
                due = datetime.fromisoformat(raw_due.replace('Z', '+00:00'))
                if due.tzinfo is None:
                    continue
                due = due.astimezone(timezone.utc)
            except ValueError:
                continue
            if due < now or (cutoff is not None and due > cutoff):
                continue
            dated_items.append((due, {'course_id': cid, 'course_name': course.get('name'),
                                      'assignment_id': assignment.get('id'), 'name': assignment.get('name'),
                                      'due_at': raw_due, 'html_url': assignment.get('html_url'),
                                      'points_possible': assignment.get('points_possible')}))
    dated_items.sort(key=lambda pair: (pair[0], str(pair[1]['course_id']), str(pair[1]['assignment_id'])))
    return {'assignments': [item for _, item in dated_items], 'unavailable_courses': unavailable,
            'window_days': days, 'generated_at': now.isoformat()}


def work(client, max_pages, course_id=None, days=None, status=None):
    """Index visible assignments with the current user's Canvas submission state.

    Canvas applies the caller's assignment-date overrides by default. A missing
    submission field is *unknown*, not evidence that work was not submitted.
    """
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days) if days is not None else None
    courses = ([{'id': course_id}] if course_id else active_courses(client, max_pages))
    items, unavailable = [], []
    for course in courses:
        cid = course.get('id')
        if not cid:
            continue
        try:
            assignments = client.list(
                f'/api/v1/courses/{cid}/assignments?include%5B%5D=submission&per_page=100',
                max_pages)
        except CanvasError as exc:
            if exc.status not in (403, 404):
                raise
            if course_id:
                raise
            unavailable.append({'course_id': cid, 'reason': str(exc)})
            continue
        for assignment in assignments:
            raw_due = assignment.get('due_at')
            due = None
            if raw_due:
                try:
                    due = datetime.fromisoformat(raw_due.replace('Z', '+00:00'))
                    due = due.astimezone(timezone.utc) if due.tzinfo else None
                except ValueError:
                    pass
            if cutoff is not None and (due is None or not now <= due <= cutoff):
                continue
            submission = assignment.get('submission')
            if not isinstance(submission, dict):
                state = 'unknown'
                submission = {}
            elif submission.get('excused'):
                state = 'excused'
            elif submission.get('missing'):
                state = 'missing'
            else:
                state = submission.get('workflow_state') or 'unknown'
            if status and state != status:
                continue
            items.append((due, {
                'course_id': cid, 'course_name': course.get('name'),
                'assignment_id': assignment.get('id'), 'name': assignment.get('name'),
                'due_at': raw_due, 'unlock_at': assignment.get('unlock_at'),
                'lock_at': assignment.get('lock_at'), 'html_url': assignment.get('html_url'),
                'points_possible': assignment.get('points_possible'),
                'submission_types': assignment.get('submission_types'),
                'status': state, 'submitted_at': submission.get('submitted_at'),
                'grade': submission.get('grade'), 'late': submission.get('late'),
            }))
    items.sort(key=lambda pair: (pair[0] is None, pair[0] or now,
                                 str(pair[1]['course_id']), str(pair[1]['assignment_id'])))
    return {'assignments': [item for _, item in items], 'unavailable_courses': unavailable,
            'window_days': days, 'status_filter': status, 'generated_at': now.isoformat()}


def agenda(client, max_pages, days=14, course_id=None, time_zone='local',
           include_undated=False, now=None, course_ids=None):
    """Show unfinished visible assignments, with honest local times and coverage.

    Urgency is only a time bucket, not an estimate of grade impact or workload.
    Undated items are counted but not presented as deadlines unless requested.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise CanvasError('Agenda clock must include a time zone')
    now = now.astimezone(timezone.utc)
    if days < 1:
        raise CanvasError('--days must be positive')
    try:
        zone = None if time_zone == 'local' else ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise CanvasError('Unknown IANA time zone; use e.g. America/Los_Angeles') from None
    local_now = now.astimezone(zone) if zone else now.astimezone()
    cutoff = now + timedelta(days=days)
    selected = list(dict.fromkeys(course_ids or ([course_id] if course_id else [])))
    course_names = {}
    if selected:
        try:
            course_names = {str(course['id']): course.get('name')
                            for course in active_courses(client, max_pages) if course.get('id')}
        except CanvasError as exc:
            if exc.status not in (403, 404):
                raise
    sources = ([work(client, max_pages, course_id=cid) for cid in selected]
               if selected else [work(client, max_pages)])
    assignments = [item for source in sources for item in source['assignments']]
    unavailable = [item for source in sources for item in source['unavailable_courses']]
    items, undated = [], []
    finished = {'submitted', 'graded', 'pending_review', 'excused'}
    for assignment in assignments:
        if assignment['status'] in finished:
            continue
        raw_due = assignment.get('due_at')
        due = None
        if raw_due:
            try:
                parsed = datetime.fromisoformat(raw_due.replace('Z', '+00:00'))
                due = parsed.astimezone(timezone.utc) if parsed.tzinfo else None
            except ValueError:
                pass
        base = {key: assignment.get(key) for key in
                ('course_id', 'course_name', 'assignment_id', 'name', 'html_url',
                 'due_at', 'unlock_at', 'lock_at', 'status')}
        base['course_name'] = base['course_name'] or course_names.get(str(base['course_id']))
        if due is None:
            undated.append(base)
            continue
        if due > cutoff:
            continue
        due_local = due.astimezone(zone) if zone else due.astimezone()
        base['due_local'] = due_local.isoformat()
        base['due_display'] = due_local.strftime('%a %b %d, %Y %I:%M %p %Z')
        if due < now:
            base['urgency'] = 'overdue'
        elif due_local.date() == local_now.date():
            base['urgency'] = 'today'
        elif due - now <= timedelta(hours=72):
            base['urgency'] = 'next_72h'
        else:
            base['urgency'] = 'later'
        base['availability'] = 'not_specified'
        for field, label, condition in (('unlock_at', 'not_yet_open', lambda t: t > now),
                                        ('lock_at', 'closed', lambda t: t < now)):
            value = assignment.get(field)
            if not value:
                continue
            try:
                instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
                if instant.tzinfo and condition(instant.astimezone(timezone.utc)):
                    base['availability'] = label
            except ValueError:
                pass
        if (base['availability'] == 'not_specified' and assignment.get('unlock_at')
                and assignment.get('lock_at')):
            base['availability'] = 'within_window'
        items.append((due, base))
    items.sort(key=lambda pair: (pair[0] >= now,
                                 -pair[0].timestamp() if pair[0] < now else pair[0].timestamp(),
                                 str(pair[1]['course_id']), str(pair[1]['assignment_id'])))
    return {'generated_at': now.isoformat(), 'time_zone': time_zone,
            'window_days': days, 'items': [item for _, item in items],
            'undated_count': len(undated),
            'undated': undated if include_undated else None,
            'unavailable_courses': unavailable,
            'priority_basis': 'Due-time urgency only; course meetings and workload are not inferred.'}
