"""Shared ungraded discussion to-do dates, not private tasks or graded due dates."""

from .client import CanvasError
from .topic_dates import instant

WARNING = ('Changes the shared student to-do date, not a private reminder, graded due date or '
           'publication/opening/closing control. Setting a date requires the exact context '
           'manage_course_content_add permission as well as topic update permission; native clearing '
           'does not require that additional add permission. Course and group contexts are supported. '
           'Only the stored instant or explicit clearing is verified, not planner/feed visibility, '
           'completion, notifications, future jobs or student availability. No peer-post reads, '
           'automatic retry, cleanup or rollback.')


def validate(values):
    if not isinstance(values, dict) or set(values) != {'todo_date'}:
        raise CanvasError('Select one --todo-at instant or --clear-todo for the shared discussion to-do date')
    return {'todo_date': instant(values['todo_date'])}


def authority(client, route, values):
    if values['todo_date'] is None:
        return None
    report, _ = client.request(route + '/permissions?permissions%5B%5D=manage_course_content_add')
    if not isinstance(report, dict) or report.get('manage_course_content_add') is not True:
        raise CanvasError('Canvas did not permit manage_course_content_add in this exact context for a shared to-do date')
    return {'manage_course_content_add': True}
