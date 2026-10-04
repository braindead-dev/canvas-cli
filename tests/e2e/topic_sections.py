"""Independent native section associations and old/new section visibility checks."""

import copy
from urllib.parse import parse_qs, urlencode

from .appointments import _send


def initialize(state):
    state.topic_sections_enabled = False
    state.topic_sections = [{'id': value, 'course_id': 111, 'name': 'synthetic-private-section',
                             'nonxlist_course_id': None, 'start_at': None, 'end_at': None,
                             'restrict_enrollments_to_section_dates': False} for value in (331, 332)]
    state.topic_section_visible_ids = None  # Native :all, not a guessed role.
    state.topic_sections_list_denied = state.topic_sections_list_denied_after = False
    state.topic_sections_after = None
    state.topic_sections_error_after_apply = False


def read(state, handler, url, prefix):
    if not state.topic_sections_enabled or url.path != prefix + '/sections':
        return False
    if state.topic_sections_list_denied or state.topic_written and state.topic_sections_list_denied_after:
        _send(handler, {'private': 'synthetic-private-section-read-denial'}, 403)
        return True
    parameters = parse_qs(url.query)
    page = int(parameters.get('page', ['1'])[0])
    rows = state.topic_sections_after if state.topic_written and state.topic_sections_after is not None else state.topic_sections
    parameters['page'] = [str(page + 1)]
    link = f'<{url.path}?{urlencode(parameters, doseq=True)}>; rel="next"' if page < len(rows) else None
    _send(handler, rows[page - 1:page], link=link)
    return True


def write(state, handler, body, url, prefix, row):
    if (not state.topic_sections_enabled or handler.command != 'PUT' or set(body) != {'specific_sections'} or
            parse_qs(url.query) != {'no_verifiers': ['true']}):
        return False
    if not prefix.startswith('/api/v1/courses/') or row.get('assignment_id') is not None or row.get('group_category_id') is not None:
        _send(handler, {'private': 'synthetic-private-native-section-context'}, 400)
        return True
    value = body['specific_sections']
    try:
        selected = [] if value == 'all' else [int(part) for part in value.split(',')]
    except (ValueError, AttributeError):
        _send(handler, {'private': 'synthetic-private-invalid-section-selection'}, 400)
        return True
    active = {section['id'] for section in state.topic_sections}
    old = {section['id'] for section in row.get('sections', [])} if row['is_section_specific'] else set()
    visible = state.topic_section_visible_ids
    if ((value != 'all' and (not selected or set(selected) - active)) or
            visible is not None and ((old & active) - set(visible) or set(selected) - set(visible))):
        _send(handler, {'private': 'synthetic-private-native-old-or-new-section-denial'}, 400)
        return True
    state.topic_written = True
    if not state.topic_ignore and 'specific_sections' not in state.topic_ignored_fields:
        row['is_section_specific'] = value != 'all'
        row['sections'] = [copy.deepcopy(section) for section in state.topic_sections if section['id'] in selected]
        # Native serialization adds legacy section visibilities to the reported modern overrides.
        overrides = [override for override in row['ungraded_discussion_overrides'] if override.get('synthetic_legacy_section') is not True]
        row['ungraded_discussion_overrides'] = overrides + [{'set_type': 'CourseSection', 'set_id': section,
                                                          'synthetic_legacy_section': True} for section in selected]
        if state.topic_state_lose_edit:
            row['permissions']['update'] = False
        state.topic_notifications.append(row['id'])
    if state.topic_sections_error_after_apply:
        _send(handler, {'private': 'synthetic-private-section-failed-validation'}, 400)
        return True
    response = copy.deepcopy(row)
    if state.topic_ack_patch is not None:
        response = response | state.topic_ack_patch if isinstance(state.topic_ack_patch, dict) else state.topic_ack_patch
    _send(handler, response)
    return True
