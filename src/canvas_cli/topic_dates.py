"""Exact course discussion instants, with no implicit midnight normalization."""

from datetime import timezone

from .client import CanvasError
from .events import timestamp, zone

FIELDS = ('delayed_post_at', 'lock_at')
WARNING = ('Changing or clearing course discussion dates can publish a draft, delay its opening, '
           'reopen replies or close replies immediately. It is not a private reminder or a promise '
           'to preserve draft/closed state. Native course-midnight closing dates are rewritten to '
           'end of day; use an explicit non-midnight instant instead. Only selected stored dates '
           'and observed publication/closed state are verified, not future jobs, notifications or '
           'student availability through modules, pacing or audience overrides. No retry or rollback.')


def validate(values, context_type):
    if context_type != 'course' or not isinstance(values, dict) or not values or set(values) - set(FIELDS):
        raise CanvasError('Select opening/closing dates or explicit clearing for an ordinary course discussion')
    selected = {}
    for key, value in values.items():
        parsed = timestamp(value) if value is not None else None
        if parsed is not None and parsed.microsecond:
            raise CanvasError('Discussion scheduling requires whole-second instants; do not guess subsecond storage')
        try:
            selected[key] = parsed.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z') if parsed else None
        except OverflowError:
            raise CanvasError('Discussion instant is outside the supported UTC date range') from None
    return selected


def matches(row, key, value):
    stored = row[key]
    return stored is value if stored is None or value is None else timestamp(stored) == timestamp(value)


def validate_current(values, before, context):
    merged = before | values
    opening, closing = (timestamp(merged[key]) if merged[key] is not None else None for key in FIELDS)
    if opening is not None and closing is not None and closing <= opening:
        raise CanvasError('Discussion closing must be later than opening, including preserved dates')
    if values.get('lock_at') is not None:
        try:
            local = closing.astimezone(zone(context.get('time_zone')))
        except OverflowError:
            raise CanvasError('Discussion closing is outside the supported course time-zone date range') from None
        if (local.hour, local.minute, local.second, local.microsecond) == (0, 0, 0, 0):
            raise CanvasError('Canvas rewrites course-midnight closing to end of day; select an explicit non-midnight instant')
