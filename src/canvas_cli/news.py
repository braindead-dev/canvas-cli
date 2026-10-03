"""Cross-course announcement feed using Canvas's announcements endpoint."""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from .client import CanvasError
from .planning import active_courses


def announcement_feed(client, max_pages, days=14, course_ids=None):
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    courses = ([{'id': cid} for cid in dict.fromkeys(course_ids)] if course_ids
               else active_courses(client, max_pages))
    announcements, unavailable = [], []
    for course in courses:
        cid = course.get('id')
        if not cid:
            continue
        query = urlencode({
            'context_codes[]': f'course_{cid}',
            'start_date': start.isoformat(timespec='seconds'),
            'end_date': now.isoformat(timespec='seconds'),
            'active_only': 'true',
            'per_page': '100',
        })
        try:
            rows = client.list('/api/v1/announcements?' + query, max_pages)
        except CanvasError as exc:
            if exc.status not in (403, 404):
                raise
            if course_ids and len(course_ids) == 1:
                raise
            unavailable.append({'course_id': cid, 'reason': str(exc)})
            continue
        for item in rows:
            # Preserve the full visible announcement, including its HTML body.
            announcements.append({**item, 'course_id': cid, 'course_name': course.get('name')})

    def posted(item):
        raw = item.get('posted_at') or item.get('created_at')
        if raw:
            try:
                parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
                if parsed.tzinfo:
                    return parsed.astimezone(timezone.utc)
            except ValueError:
                pass
        return datetime.min.replace(tzinfo=timezone.utc)

    announcements.sort(key=lambda item: (posted(item), str(item.get('id'))), reverse=True)
    return {'announcements': announcements, 'unavailable_courses': unavailable,
            'window_days': days, 'generated_at': now.isoformat()}
