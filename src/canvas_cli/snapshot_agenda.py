"""Offline date index from explicitly selected private snapshots, never live state."""

import re
from urllib.parse import urlsplit

from .client import CanvasError, origin
from .pages import visible
from .planning import parse_instant, project_agenda

NOTE = ('Offline cached dates only: submission status is unknown even if the file contains a submission. '
        'Opening/closing labels are calculated from saved bounds, not current permission. '
        'Refresh Canvas for current dates, publication, access and completion. '
        'File identity and completeness metadata are reported claims, not authorization or a full coursework guarantee.')


def _positive_id(value):
    return type(value) is int and value > 0


def _label(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise CanvasError('Malformed snapshot text metadata')
    return ' '.join(re.sub(r'[\x00-\x1f\x7f]', ' ', value).split())


def _date(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise CanvasError('Malformed snapshot assignment date metadata')
    instant = parse_instant(value)
    return instant.isoformat() if instant is not None else 'unknown_invalid_date'


def _context(snapshot):
    if (not isinstance(snapshot, dict) or type(snapshot.get('schema_version')) is not int
            or snapshot['schema_version'] != 1):
        raise CanvasError('Unsupported snapshot schema')
    host = snapshot.get('origin')
    try:
        if not isinstance(host, str) or any(character.isspace() or ord(character) < 32
                                           or ord(character) == 127 for character in host):
            raise ValueError
        host = origin(host)
        _ = urlsplit(host).port
    except (CanvasError, ValueError):
        raise CanvasError('Malformed snapshot origin metadata') from None
    cid = snapshot.get('course_id')
    course = snapshot.get('course')
    viewer = snapshot.get('viewer_user_id')
    if (not _positive_id(cid) or not isinstance(course, dict)
            or not _positive_id(course.get('id')) or course['id'] != cid
            or 'viewer_user_id' in snapshot and not _positive_id(viewer)):
        raise CanvasError('Malformed snapshot course or viewer identity metadata')
    captured = parse_instant(snapshot.get('captured_at'))
    unavailable = snapshot.get('unavailable')
    if (captured is None or type(snapshot.get('complete')) is not bool
            or not isinstance(unavailable, dict) or not all(isinstance(key, str) for key in unavailable)
            or snapshot['complete'] and unavailable or not isinstance(snapshot.get('assignments'), list)):
        raise CanvasError('Malformed snapshot capture or coverage metadata')
    return {'origin': host, 'course_id': cid,
            'course_name': _label(course.get('name')) or _label(course.get('course_code')),
            'reported_viewer_user_id': viewer, 'captured_at': captured.isoformat(),
            'snapshot_reported_complete': snapshot['complete'],
            'assignment_inventory_reported_complete': 'assignments' not in unavailable}


def agenda(snapshots, days=14, time_zone='local', include_undated=False, now=None):
    """One snapshot per course, one reported origin, no implicit account/history merge."""
    if not isinstance(snapshots, list) or not snapshots:
        raise CanvasError('Select at least one snapshot')
    contexts = [_context(snapshot) for snapshot in snapshots]
    if len({context['origin'] for context in contexts}) != 1:
        raise CanvasError('Snapshots must report the same Canvas origin')
    viewers = {context['reported_viewer_user_id'] for context in contexts
               if context['reported_viewer_user_id'] is not None}
    if len(viewers) > 1:
        raise CanvasError('Snapshots report different viewers; refusing mixed-account agenda')
    if len({context['course_id'] for context in contexts}) != len(contexts):
        raise CanvasError('Choose one snapshot per course; no implicit history merge')
    assignments, unavailable = [], []
    for snapshot, context in zip(snapshots, contexts):
        cid = context['course_id']
        seen, excluded = set(), 0
        for row in snapshot['assignments']:
            if (not isinstance(row, dict) or not _positive_id(row.get('id'))
                    or 'course_id' in row and (not _positive_id(row['course_id']) or row['course_id'] != cid)):
                raise CanvasError('Malformed or foreign snapshot assignment identity')
            if row['id'] in seen:
                raise CanvasError('Duplicate snapshot assignment identity; refusing ambiguous dates')
            seen.add(row['id'])
            if not visible(row):
                excluded += 1
                continue
            assignments.append({'course_id': cid, 'course_name': context['course_name'],
                                'assignment_id': row['id'], 'name': _label(row.get('name')),
                                'html_url': f"{context['origin']}/courses/{cid}/assignments/{row['id']}",
                                **{field: _date(row.get(field)) for field in ('due_at', 'unlock_at', 'lock_at')},
                                'status': 'unknown'})
        context['excluded_saved_visibility_rows'] = excluded
        if not context['assignment_inventory_reported_complete']:
            unavailable.append({'course_id': cid,
                                'reason': 'Assignments were reported unavailable in this saved snapshot; refresh Canvas.'})
    result = project_agenda(assignments, unavailable, days, time_zone, include_undated, now)
    clock = parse_instant(result['generated_at'])
    for context in contexts:
        context['age_seconds'] = (clock - parse_instant(context['captured_at'])).total_seconds()
        context['future_dated_capture'] = context['age_seconds'] < 0
    return {**result, 'agenda_source': 'snapshot', 'snapshots': contexts,
            'live_state_verified': False,
            'all_snapshots_report_viewer_identity': all(context['reported_viewer_user_id'] is not None
                                                       for context in contexts),
            'note': NOTE}
