"""Build a deadline index from assignments rather than Canvas's short upcoming feed."""
from datetime import datetime, timedelta, timezone

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
