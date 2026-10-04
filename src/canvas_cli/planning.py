"""Build a deadline index from assignments rather than Canvas's short upcoming feed."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .client import CanvasError


def parse_instant(value):
    """Parse a reported aware date; absent or invalid dates remain unknown."""
    if not isinstance(value, str):
        return None
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return instant.astimezone(timezone.utc) if instant.tzinfo else None
    except (ValueError, OverflowError):
        return None


def _availability(assignment, now):
    """Describe reported date bounds, not native access or submission permission."""
    opening, closing = (parse_instant(assignment.get(field)) for field in ('unlock_at', 'lock_at'))
    if any(assignment.get(field) is not None and instant is None
           for field, instant in (('unlock_at', opening), ('lock_at', closing))):
        return 'unknown_invalid_dates'
    if opening is not None and closing is not None and opening > closing:
        return 'unknown_invalid_dates'
    if closing is not None and closing < now:
        return 'closed'
    if opening is not None and opening > now:
        return 'not_yet_open'
    if opening is not None and closing is not None:
        return 'within_window'
    return 'not_specified'


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
            due = parse_instant(raw_due)
            if due is None:
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
            due = parse_instant(raw_due)
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


def _agenda_clock(days, time_zone, now):
    now = datetime.now(timezone.utc) if now is None else now
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise CanvasError('Agenda clock must include a time zone')
    if type(days) is not int or days < 1:
        raise CanvasError('--days must be positive')
    if not isinstance(time_zone, str):
        raise CanvasError('Unknown IANA time zone; use e.g. America/Los_Angeles')
    try:
        zone = None if time_zone == 'local' else ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise CanvasError('Unknown IANA time zone; use e.g. America/Los_Angeles') from None
    try:
        now = now.astimezone(timezone.utc)
        local_now = now.astimezone(zone) if zone else now.astimezone()
        cutoff = now + timedelta(days=days)
    except (ValueError, OverflowError):
        raise CanvasError('Agenda clock or window is outside the representable date range') from None
    return now, zone, local_now, cutoff


def agenda(client, max_pages, days=14, course_id=None, time_zone='local',
           include_undated=False, now=None, course_ids=None):
    """Fetch own unfinished visible work; invalid options fail before Canvas reads."""
    now = _agenda_clock(days, time_zone, now)[0]
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
    return project_agenda(assignments, unavailable, days, time_zone,
                          include_undated, now, course_names)


def project_agenda(assignments, unavailable, days=14, time_zone='local',
                   include_undated=False, now=None, course_names=None):
    """Pure date projection shared by live work and explicitly selected snapshots.

    Urgency is time only, not grade impact or workload. Callers supply the status
    evidence; cached rows must not be represented as current submission state.
    """
    now, zone, local_now, cutoff = _agenda_clock(days, time_zone, now)
    course_names = course_names or {}
    items, undated = [], []
    finished = {'submitted', 'graded', 'pending_review', 'excused'}
    for assignment in assignments:
        if assignment['status'] in finished:
            continue
        raw_due = assignment.get('due_at')
        due = parse_instant(raw_due)
        base = {key: assignment.get(key) for key in
                ('course_id', 'course_name', 'assignment_id', 'name', 'html_url',
                 'due_at', 'unlock_at', 'lock_at', 'status')}
        base['course_name'] = base['course_name'] or course_names.get(str(base['course_id']))
        if due is None:
            undated.append(base)
            continue
        if due > cutoff:
            continue
        try:
            due_local = due.astimezone(zone) if zone else due.astimezone()
        except OverflowError:
            raise CanvasError('Assignment due date is outside the selected time zone display range; use UTC') from None
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
        base['availability'] = _availability(assignment, now)
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
