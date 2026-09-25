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
