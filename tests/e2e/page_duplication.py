"""Independent synthetic native page-copy and linked-assignment lineage endpoints."""

import copy
from urllib.parse import parse_qs, urlencode, urlsplit

from .appointments import _send


def initialize(state, *, enabled=False):
    state.page_duplication_enabled = enabled
    state.copy_viewer = 7
    state.copy_context = {'name': 'Synthetic copy context', 'workflow_state': 'available'}
    state.copy_permissions = {'manage_wiki_create': True, 'participate_as_student': False}
    state.copy_student_wiki = False
    state.copy_pages = {
        4001: {'page_id': 4001, 'title': 'Target', 'url': 'current', 'published': True, 'front_page': False,
               'editing_roles': 'teachers', 'body': '<p>synthetic-private-source-page</p>', 'publish_at': None,
               'todo_date': '2026-10-16T12:00:00Z', 'updated_at': '2026-10-01T12:00:00Z'},
        4002: {'page_id': 4002, 'title': 'Numeric slug', 'url': '4001', 'published': True, 'front_page': True,
               'editing_roles': 'teachers', 'body': '<p>synthetic-private-other-page</p>', 'publish_at': None,
               'updated_at': '2026-10-01T12:00:00Z'}}
    state.copy_revision = {'revision_id': 3, 'updated_at': '2026-10-01T12:00:00Z', 'latest': True}
    state.copy_assignments = {83: {'id': 83, 'course_id': 110, 'name': 'Synthetic source assignment',
                                  'submission_types': ['wiki_page'], 'published': True, 'workflow_state': 'published',
                                  'can_duplicate': True, 'original_assignment_id': None, 'original_course_id': None,
                                  'updated_at': '2026-10-01T12:00:00Z', 'points_possible': 15, 'grading_type': 'points',
                                  'peer_review_count': 2, 'post_to_sis': True,
                                  'description': '<p>synthetic-private-source-description</p>',
                                  'rubric': [{'description': 'synthetic-private-rubric', 'points': 15}],
                                  'submission': {'body': 'synthetic-private-submission'}, 'secure_params': 'synthetic-private-token'}}
    state.copy_written = state.copy_deny = state.copy_read_denied = False
    state.copy_account_changed = state.copy_permission_lost = state.copy_source_changed = False
    state.copy_front_changed = state.copy_inventory_denied = state.copy_reuse_assignment = False
    state.copy_page_patch = {}
    state.copy_assignment_patch = {}
    state.copy_content_patch = {}
    state.copy_ack_patch = {}
    state.copy_ack_response = None


def _route(state, handler):
    if not state.page_duplication_enabled:
        return None
    url = urlsplit(handler.path)
    prefix = '/api/v1/courses/110'
    suffix = url.path[len(prefix):] if url.path == prefix or url.path.startswith(prefix + '/') else None
    return url, suffix, parse_qs(url.query)


def read(state, handler):
    parsed = _route(state, handler)
    if parsed is None:
        return False
    url, suffix, query = parsed
    if url.path == '/api/v1/users/self/profile':
        _send(handler, {'id': 8 if state.copy_written and state.copy_account_changed else state.copy_viewer})
        return True
    if suffix is None:
        return False
    if not suffix:
        row = {'id': 110, **state.copy_context}
        if query.get('include[]') == ['allow_student_wiki_edits']:
            row['allow_student_wiki_edits'] = state.copy_student_wiki
        _send(handler, row)
    elif suffix == '/permissions':
        if query.get('permissions[]') != ['manage_wiki_create', 'participate_as_student']:
            _send(handler, {'private': 'synthetic-private-copy-does-not-need-update'}, 403)
        else:
            _send(handler, {'manage_wiki_create': False, 'participate_as_student': False}
                  if state.copy_written and state.copy_permission_lost else state.copy_permissions)
    elif suffix == '/pages':
        if state.copy_written and state.copy_inventory_denied:
            _send(handler, {'private': 'synthetic-private-copy-inventory-denial'}, 403)
        else:
            rows = [{key: value for key, value in row.items() if key not in ('body', 'assignment', 'block_editor_attributes', 'block_editor_data')}
                    for row in state.copy_pages.values()]
            page = int(query.get('page', ['1'])[0])
            query['page'] = [str(page + 1)]
            link = f'<{url.path}?{urlencode(query, doseq=True)}>; rel="next"' if page < len(rows) else None
            _send(handler, rows[page - 1:page], link=link)
    elif suffix.startswith('/assignments/'):
        identifier = int(suffix.rsplit('/', 1)[1])
        _send(handler, state.copy_assignments[identifier] if identifier in state.copy_assignments else
              {'private': 'synthetic-private-missing-scoped-assignment'}, 200 if identifier in state.copy_assignments else 404)
    elif suffix.startswith('/pages/page_id:'):
        identifier = int(suffix.split(':')[1].split('/')[0])
        if identifier not in state.copy_pages:
            _send(handler, {'private': 'synthetic-private-missing-scoped-page'}, 404)
        elif identifier == 4003 and state.copy_read_denied:
            _send(handler, {'private': 'synthetic-private-copied-draft-denied'}, 403)
        elif suffix.endswith('/revisions/latest'):
            _send(handler, {**state.copy_revision, 'edited_by': {'email': 'synthetic-private-editor@example.edu'}})
        elif '/revisions' in suffix:
            _send(handler, {'private': 'synthetic-private-no-copy-history-permission'}, 403)
        else:
            _send(handler, {**state.copy_pages[identifier], 'last_edited_by': {'email': 'synthetic-private-page-editor@example.edu'}})
    else:
        _send(handler, {'private': 'synthetic-private-unknown-copy-route'}, 400)
    return True


def write(state, handler, body):
    parsed = _route(state, handler)
    if parsed is None:
        return False
    _, suffix, query = parsed
    if suffix is None:
        return False
    permitted = state.copy_permissions['manage_wiki_create'] or state.copy_permissions['participate_as_student'] and state.copy_student_wiki
    if (suffix != '/pages/page_id:4001/duplicate' or handler.command != 'POST' or body != {} or
            query.get('no_verifiers') != ['true'] or not permitted or state.copy_deny):
        _send(handler, {'private': 'synthetic-private-native-copy-denial'}, 403)
        return True
    state.copy_written = True
    row = copy.deepcopy(state.copy_pages[4001])
    row.update(page_id=4003, title='Copie de Target 🌿', url='copy-2', published=False, front_page=False,
               publish_at=None, updated_at='2026-10-03T12:00:00Z')
    if row.get('block_editor_attributes'):
        row['block_editor_attributes']['id'] += 1
    row.update(state.copy_content_patch)
    if row.get('assignment'):
        assignment = copy.deepcopy(state.copy_assignments[83])
        assignment.update(id=83 if state.copy_reuse_assignment else 84, name=row['title'], published=False,
                          workflow_state='unpublished', updated_at='2026-10-03T12:00:00Z', peer_review_count=0,
                          original_assignment_id=83, original_course_id=110, post_to_sis=False)
        row['assignment'] = copy.deepcopy(assignment)
        state.copy_assignments[assignment['id']] = {**assignment, **state.copy_assignment_patch}
    row.update(state.copy_page_patch)
    state.copy_pages[4003] = copy.deepcopy(row)
    if state.copy_source_changed:
        state.copy_pages[4001]['body'] = 'Changed source'
    if state.copy_front_changed:
        state.copy_pages[4002]['front_page'] = False
    _send(handler, state.copy_ack_response if state.copy_ack_response is not None else {**row, **state.copy_ack_patch})
    return True
