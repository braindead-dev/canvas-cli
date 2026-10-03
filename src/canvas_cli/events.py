"""Personal calendar events, with explicit times and account-bound write previews."""

import html
import re
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .client import CanvasError
from .planner import validate_date
from .writes import account, check_flags, confirmed

EVENT_FIELDS = ('id', 'context_code', 'title', 'description', 'start_at', 'end_at',
                'all_day', 'all_day_date', 'location_name', 'location_address',
                'workflow_state', 'updated_at', 'series_uuid', 'rrule')


def zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise CanvasError('Use an installed IANA time zone, such as America/Los_Angeles or UTC') from None


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)', value):
        raise CanvasError('Event times need YYYY-MM-DDTHH:MM:SS with Z or an explicit UTC offset')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if value.endswith('-00:00'):
            raise ValueError  # RFC 3339's unknown offset is not an explicit time zone.
        return parsed
    except ValueError:
        raise CanvasError('Invalid event timestamp or UTC offset') from None


def timing(start=None, end=None, day=None, time_zone=None):
    """No implicit local time, ambiguous date parsing, or inherited end time."""
    if day is not None:
        if start is not None or end is not None:
            raise CanvasError('Choose --date for an all-day event or --start/--end, not both')
        if not time_zone:
            raise CanvasError('An all-day date requires --timezone to preserve the intended calendar day')
        validate_date(day)
        tz = zone(time_zone)
        midnight = datetime.combine(date.fromisoformat(day), time(), tzinfo=tz)
        roundtrip = midnight.astimezone(timezone.utc).astimezone(tz)
        if (roundtrip.replace(tzinfo=None) != midnight.replace(tzinfo=None) or
                midnight.replace(fold=1).utcoffset() != midnight.utcoffset()):
            raise CanvasError('This date has a skipped or ambiguous midnight in that time zone')
        return {'start_at': midnight.isoformat(), 'end_at': midnight.isoformat(),
                'all_day': True, 'time_zone_edited': time_zone}
    if start is None and end is None:
        if time_zone is not None:
            raise CanvasError('--timezone needs --date or --start/--end')
        return {}
    if start is None or end is None:
        raise CanvasError('Provide both --start and --end when setting event times')
    first, last = timestamp(start), timestamp(end)
    if last <= first:
        raise CanvasError('Event end must be later than start')
    result = {'start_at': first.isoformat(), 'end_at': last.isoformat(), 'all_day': False}
    if time_zone:
        tz = zone(time_zone)
        if any(value.astimezone(tz).utcoffset() != value.utcoffset() for value in (first, last)):
            raise CanvasError('Timestamp offsets do not match --timezone on those dates')
        result['time_zone_edited'] = time_zone
    return result


def fields(title=None, details=None, location=None, address=None,
           start=None, end=None, day=None, time_zone=None):
    changes = timing(start, end, day, time_zone)
    if title is not None:
        if not isinstance(title, str) or not title.strip():
            raise CanvasError('A nonempty event title is required')
        changes['title'] = title.strip()
    if details is not None:
        if not isinstance(details, str):
            raise CanvasError('Event details must be plain text')
        changes['description'] = '<p>' + html.escape(details).replace('\n', '<br>') + '</p>' if details else ''
    for key, value in (('location_name', location), ('location_address', address)):
        if value is not None:
            if not isinstance(value, str):
                raise CanvasError('Event location fields must be text')
            changes[key] = value
    return changes


def read(client, event_id, *, exclude_children=False):
    if not isinstance(event_id, str) or not re.fullmatch(r'[1-9][0-9]*', event_id):
        raise CanvasError('Expected a positive calendar event ID, not an assignment ID')
    route = f'/api/v1/calendar_events/{event_id}'
    if exclude_children:
        route += '?excludes%5B%5D=child_events'
    record, _ = client.request(route)
    if (not isinstance(record, dict) or type(record.get('id')) is not int or
            str(record['id']) != event_id):
        raise CanvasError('Canvas returned a different or malformed calendar event')
    return record


def personal(record, identity):
    if record.get('context_code') != f"user_{identity['user_id']}":
        raise CanvasError('This is not the signed-in user\'s personal calendar event')
    if (record.get('workflow_state') != 'active' or record.get('hidden') or
            record.get('locked_for_user') or record.get('appointment_group_id') or
            record.get('parent_event_id') or record.get('child_events_count') or
            record.get('child_events') or record.get('own_reservation')):
        raise CanvasError('Locked, hidden, deleted, section or appointment events cannot use this personal-event command')


def write_result(result, identity, event_id=None, delete=False):
    if (not isinstance(result, dict) or type(result.get('id')) is not int or result['id'] < 1 or
            (event_id is not None and str(result['id']) != event_id) or
            result.get('context_code') != f"user_{identity['user_id']}" or
            result.get('workflow_state') != ('deleted' if delete else 'active')):
        raise CanvasError('Calendar write outcome uncertain; inspect the calendar before repeating the command')
    return {'calendar_event': {key: result.get(key) for key in EVENT_FIELDS},
            'note': 'Personal calendar only; no assignment, submission or reservation was changed.'}


def create(client, title, start=None, end=None, day=None, time_zone=None, details=None,
           location=None, address=None, yes=False, confirm=None):
    check_flags(yes, confirm)
    if title is None:
        raise CanvasError('A nonempty event title is required')
    changes = fields(title, details, location, address, start, end, day, time_zone)
    if 'start_at' not in changes:
        raise CanvasError('Choose an all-day --date or explicit --start/--end')
    identity = account(client)
    body = {'calendar_event': {**changes, 'context_code': f"user_{identity['user_id']}"}}
    preview = {**identity, 'method': 'POST', 'route': '/api/v1/calendar_events', 'body': body,
               'effect': 'Creates one personal calendar event. It is not an assignment or course event.'}
    result = confirmed(client, preview, yes, confirm)
    return write_result(result, identity) if yes else result


def change(client, event_id, title=None, start=None, end=None, day=None, time_zone=None,
           details=None, location=None, address=None, delete=False, cancel_reason=None,
           yes=False, confirm=None):
    check_flags(yes, confirm)
    changes = fields(title, details, location, address, start, end, day, time_zone)
    if delete and changes:
        raise CanvasError('Event removal cannot also edit fields')
    if not delete and not changes:
        raise CanvasError('Choose at least one event field to update')
    if cancel_reason is not None and (not delete or not isinstance(cancel_reason, str)):
        raise CanvasError('A cancellation reason is text and applies only to event deletion')
    identity = account(client)
    record = read(client, event_id)
    personal(record, identity)
    body = {'which': 'one'}  # Never silently update or delete an entire recurring series.
    if delete:
        if cancel_reason is not None:
            body['cancel_reason'] = cancel_reason
    else:
        body['calendar_event'] = changes
    preview = {**identity, 'method': 'DELETE' if delete else 'PUT',
               'route': f'/api/v1/calendar_events/{event_id}',
               'before': {key: record.get(key) for key in EVENT_FIELDS}, 'body': body,
               'effect': 'Removes only this personal occurrence; no assignment or reservation is deleted.' if delete else
                         'Edits only this personal occurrence; no assignment or reservation is changed.'}
    result = confirmed(client, preview, yes, confirm)
    return write_result(result, identity, event_id, delete) if yes else result
