"""Native course section filtering, distinct from modern participant overrides."""

from .client import CanvasError
from .events import timestamp
from .group_content import _id
from .writes import digest

WARNING = ('Replaces the shared course topic section filter; it can grant or remove access to '
           'the prompt and existing replies. Native update permission and visibility checks on both '
           'old and new sections remain authoritative; section-list access is not edit authority. '
           'All sections disables this filter, not participant overrides or other availability rules. '
           'No roster/peer-reply enumeration, override replacement, grading or enrollment change. '
           'Canvas can invalidate module progressions and change notifications/activity. Stored '
           'section IDs and filter state are verified, not every participant\'s effective visibility '
           'or downstream effects. An HTTP error is not proof that section associations stayed '
           'unchanged; check Canvas before repeating. No automatic retry, cleanup or rollback.')


def validate(values, context_type):
    if context_type != 'course':
        raise CanvasError('Native section filtering belongs to course topics, not group contexts')
    if not isinstance(values, dict) or set(values) != {'specific_sections'}:
        raise CanvasError('Select --section-id values or --all-sections, not other audience fields')
    selected = values['specific_sections']
    if selected == 'all':
        return {'specific_sections': 'all'}
    if (not isinstance(selected, list) or not selected or
            any(type(value) is not int or value < 1 for value in selected) or len(set(selected)) != len(selected)):
        raise CanvasError('Select a nonempty list of unique positive section IDs')
    return {'specific_sections': ','.join(str(value) for value in sorted(selected))}


def inventory(client, route, item, max_pages):
    rows = []
    for row in client.list(route + '/sections?per_page=100', max_pages):
        identifier = _id(row)
        if (type(row.get('course_id')) is not int or row['course_id'] != int(item) or
                not isinstance(row.get('name'), str) or row.get('workflow_state') == 'deleted'):
            raise CanvasError('Canvas returned a foreign or malformed active course section')
        for key in ('start_at', 'end_at', 'created_at'):
            if row.get(key) is not None:
                timestamp(row[key])
        if (row.get('restrict_enrollments_to_section_dates') is not None and
                type(row['restrict_enrollments_to_section_dates']) is not bool or
                row.get('nonxlist_course_id') is not None and
                (type(row['nonxlist_course_id']) is not int or row['nonxlist_course_id'] < 1)):
            raise CanvasError('Canvas returned malformed course section restrictions')
        rows.append({'id': identifier, 'course_id': row['course_id'], 'metadata_digest': digest({
            key: row[key] for key in ('name', 'start_at', 'end_at', 'created_at',
                                     'restrict_enrollments_to_section_dates', 'nonxlist_course_id') if key in row})})
    if len({row['id'] for row in rows}) != len(rows):
        raise CanvasError('Canvas returned duplicate active course sections')
    return sorted(rows, key=lambda row: row['id'])


def check_selection(values, sections):
    if values['specific_sections'] != 'all':
        selected = {int(value) for value in values['specific_sections'].split(',')}
        if selected - {row['id'] for row in sections}:
            raise CanvasError('Every selected section must be in the complete active course section inventory')


def matches(row, values):
    selected = values['specific_sections']
    return (row['is_section_specific'] is False and row['section_ids'] == [] if selected == 'all' else
            row['is_section_specific'] is True and row['section_ids'] == [int(value) for value in selected.split(',')])
