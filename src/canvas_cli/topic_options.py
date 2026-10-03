"""Documented/native discussion options, not arbitrary topic or assignment fields."""

from .client import CanvasError

FIELDS = {'discussion_type': ('side_comment', 'not_threaded', 'threaded', 'flat'),
          'require_initial_post': None, 'allow_rating': None, 'only_graders_can_rate': None,
          'sort_order': ('asc', 'desc'), 'sort_order_locked': None,
          'expanded': None, 'expanded_locked': None}


def validate(options, context_type):
    if not isinstance(options, dict) or not options or options.keys() - FIELDS.keys():
        raise CanvasError('Select supported discussion options, not arbitrary topic fields')
    for key, value in options.items():
        choices = FIELDS[key]
        if (choices is None and type(value) is not bool or
                choices is not None and (not isinstance(value, str) or value not in choices)):
            raise CanvasError('Discussion options require explicit booleans or supported named choices')
    if context_type == 'group' and 'require_initial_post' in options:
        raise CanvasError('Native group topic updates do not accept require_initial_post')
    return dict(options)


def validate_current(options, before):
    if any(before.get(key) is None for key in options):
        raise CanvasError('Canvas did not report the current value of every selected discussion option')
    if options.keys() & {'expanded', 'expanded_locked'}:
        if any(type(before.get(key)) is not bool for key in ('expanded', 'expanded_locked')):
            raise CanvasError('Canvas did not report both native expansion settings')
        selected = before | options
        if selected['expanded_locked'] and not selected['expanded']:
            raise CanvasError('Canvas does not permit locking a collapsed discussion; expand it or unlock expansion')
