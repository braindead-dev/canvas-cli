"""One native course-page copy, with separate assignment-copy lineage verification."""

from urllib.parse import quote

from .client import CanvasError
from .events import timestamp
from .group_content import _context, _id, _number, base
from .page_history import _detail
from .wiki_content import PAGE_FIELDS, _assignment, _content, _inventory, _metadata
from .writes import account, check_flags, confirmed, digest

PERMISSIONS = ('manage_wiki_create', 'participate_as_student')
ASSIGNMENT_CONFIG = ('description', 'submission_types', 'points_possible', 'grading_type', 'assignment_group_id',
                     'group_category_id', 'grade_group_students_individually', 'allowed_attempts', 'allowed_extensions',
                     'due_at', 'lock_at', 'unlock_at', 'only_visible_to_overrides', 'omit_from_final_grade',
                     'hide_in_gradebook', 'peer_reviews', 'automatic_peer_reviews', 'peer_review_count',
                     'anonymous_peer_reviews', 'moderated_grading', 'grader_count', 'final_grader_id',
                     'anonymous_grading', 'anonymous_instructor_annotations', 'grading_standard_id',
                     'rubric', 'rubric_settings', 'use_rubric_for_grading', 'post_manually', 'post_to_sis',
                     'turnitin_enabled', 'turnitin_settings', 'vericite_enabled', 'vericite_settings')
WARNING = ('Copies shared course wiki content, not a private note or an assignment submission. '
           'Native duplication creates an unpublished page, chooses its title/URL, retains editing roles/todo date, '
           'does not copy the publication schedule or select a front page, and can rewrite content. '
           'A reported linked assignment is also copied, potentially with rubric/plagiarism/asset-processor '
           'associations and native resets to configuration; no individual submission/grade copying is asserted. '
           'A draft is not private from teachers/managers. Student wiki opt-in can permit creation without '
           'permission to read the resulting draft; failed readback is uncertain, not automatic publication. '
           'Page/assignment GET can record module read progress; latest-revision GET can repair legacy YAML. '
           'Native role, scope and institution restrictions remain authoritative. Confirmation is not an atomic '
           'lock. No automatic retry, second assignment POST, publication, deletion or rollback.')
UNCERTAIN = ('Could not verify the page copy or its linked-assignment copy. New content may already exist; '
             'check Canvas before repeating. No automatic retry, publication, deletion, rollback or private response-body logging.')


def _scope(client, item):
    route, context = _context(client, item, 'course')
    if context.get('workflow_state') == 'deleted':
        raise CanvasError('The wiki-copy course is deleted')
    permissions, _ = client.request(route + '/permissions?' + '&'.join('permissions%5B%5D=' + key for key in PERMISSIONS))
    if not isinstance(permissions, dict) or any(type(permissions.get(key)) is not bool for key in PERMISSIONS):
        raise CanvasError('Canvas did not report exact native wiki-create permissions')
    rights = {key: permissions[key] for key in PERMISSIONS}
    if not rights['manage_wiki_create'] and rights['participate_as_student']:
        settings, _ = client.request(route + '?include%5B%5D=allow_student_wiki_edits')
        if _id(settings) != int(item) or type(settings.get('allow_student_wiki_edits')) is not bool:
            raise CanvasError('Canvas did not report the course-wide student wiki-create setting')
        rights['allow_student_wiki_edits'] = settings['allow_student_wiki_edits']
    if not (rights['manage_wiki_create'] or rights.get('allow_student_wiki_edits') is True):
        raise CanvasError('Native page creation requires Manage Wiki Create or course-wide student wiki opt-in, not editing alone')
    return route, {key: context.get(key) for key in ('id', 'name', 'workflow_state', 'concluded', 'non_collaborative')}, rights


def _page(row, item, page_id=None):
    metadata = _metadata(row, page_id)
    todo = row.get('todo_date')
    if todo is not None:
        timestamp(todo)
    return {**metadata, 'todo_date': todo}, _content(row), _assignment(row.get('assignment'), item, 'course')


def _read_page(client, route, item, page_id):
    row, _ = client.request(route + '/pages/page_id:' + page_id + '?no_verifiers=true')
    return _page(row, item, page_id)


def _read_assignment(client, route, item, linked):
    row, _ = client.request(route + '/assignments/' + str(linked['id']) + '?no_verifiers=true')
    metadata = _assignment(row, item, 'course')
    if metadata != linked:
        raise CanvasError('Linked assignment changed during inspection')
    if row.get('can_duplicate') is False:
        raise CanvasError('Canvas does not permit duplication of this linked assignment')
    if row.get('can_duplicate') is not None and type(row['can_duplicate']) is not bool:
        raise CanvasError('Canvas returned a malformed assignment-copy permission flag')
    lineage = {key: row.get(key) for key in ('original_assignment_id', 'original_course_id')}
    if any(value is not None and (type(value) is not int or value < 1) for value in lineage.values()):
        raise CanvasError('Canvas returned malformed assignment-copy lineage')
    config = {key: digest(row[key]) for key in ASSIGNMENT_CONFIG if key in row}
    return {'metadata': metadata, 'lineage': lineage, 'config_fingerprints': config, 'can_duplicate': row.get('can_duplicate')}


def duplicate(client, item, page_id, *, acknowledge_shared=False, acknowledge_assignment=False,
              max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    base(item, 'course')
    _number(page_id)
    if acknowledge_shared is not True or type(acknowledge_assignment) is not bool:
        raise CanvasError('Page duplication requires --acknowledge-shared-page, including previews')
    if type(max_pages) is not int or max_pages < 1:
        raise CanvasError('Wiki-copy inventory limit must be a positive integer')
    identity = account(client)
    route, context, rights = _scope(client, item)
    source, content, linked = _read_page(client, route, item, page_id)
    if linked and not acknowledge_assignment:
        raise CanvasError('This operation also copies a linked wiki assignment; use --acknowledge-linked-assignment-copy')
    assignment = _read_assignment(client, route, item, linked) if linked else None
    target = route + '/pages/page_id:' + page_id
    revision = _detail(client, target, 'latest')  # Creation is not edit/history permission.
    if timestamp(revision['updated_at']) != timestamp(source['updated_at']):
        raise CanvasError('Source page changed during revision inspection; review a fresh preview')
    inventory = _inventory(client, route, max_pages)
    if {key: source[key] for key in PAGE_FIELDS} not in inventory:
        raise CanvasError('Source page changed during inventory inspection; review a fresh preview')
    front = next((row for row in inventory if row['front_page']), None)
    if (_read_page(client, route, item, page_id) != (source, content, linked) or
            linked and _read_assignment(client, route, item, linked) != assignment or account(client) != identity):
        raise CanvasError('Source page/assignment/account changed during copy preflight; review a fresh preview')
    preview = {**identity, 'course_id': int(item), 'context': context, 'permissions': rights, 'source_page': source,
               'content_fingerprint': content['fingerprint'], 'content_kind': content['kind'], 'current_revision': revision,
               'linked_assignment': linked, 'assignment_fingerprint': digest(assignment) if assignment else None,
               'inventory_digest': digest(inventory), 'current_front_page': front,
               'acknowledge_shared_page': True, 'acknowledge_linked_assignment_copy': acknowledge_assignment,
               'method': 'POST', 'route': target + '/duplicate?no_verifiers=true', 'body': {}, 'warning': WARNING}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        copied, copied_content, copied_linked = _page(response, item)
        if (copied['page_id'] in {row['page_id'] for row in inventory} or copied['published'] or copied['front_page'] or
                copied['publish_at'] is not None or any(copied[key] != source[key] for key in ('editing_roles', 'todo_date')) or
                content['block_id'] is not None and copied_content['block_id'] == content['block_id']):
            raise CanvasError('Canvas did not acknowledge a new native draft copy with independent content')
        next_route, next_context, next_rights = _scope(client, item)
        if next_context != context or next_rights != rights or account(client) != identity:
            raise CanvasError('Account, course or create permission changed after duplication')
        if (_read_page(client, next_route, item, str(copied['page_id'])) != (copied, copied_content, copied_linked) or
                _read_page(client, next_route, item, page_id) != (source, content, linked)):
            raise CanvasError('Copied page acknowledgement/readback disagreed or the source changed')
        listed = _inventory(client, next_route, max_pages)
        copied_metadata = {key: copied[key] for key in PAGE_FIELDS}
        if copied_metadata not in listed or next((row for row in listed if row['front_page']), None) != front:
            raise CanvasError('The copied page/front-page inventory did not verify the result')
        new_assignment = None
        changed_config = []
        compared_config = []
        unknown_config = []
        if bool(linked) != bool(copied_linked) or linked and copied_linked['id'] == linked['id']:
            raise CanvasError('Canvas did not report the independently copied assignment association')
        if linked:
            new_assignment = _read_assignment(client, next_route, item, copied_linked)
            if (new_assignment['metadata']['published'] or new_assignment['metadata']['name'] != copied['title'] or
                    new_assignment['lineage'] != {'original_assignment_id': linked['id'], 'original_course_id': int(item)} or
                    _read_assignment(client, next_route, item, linked) != assignment):
                raise CanvasError('Copied assignment lineage was not verified or the source assignment changed')
            compared_config = [key for key in ASSIGNMENT_CONFIG
                               if key in new_assignment['config_fingerprints'] and key in assignment['config_fingerprints']]
            unknown_config = [key for key in ASSIGNMENT_CONFIG if key not in compared_config]
            changed_config = [key for key in compared_config
                              if new_assignment['config_fingerprints'][key] != assignment['config_fingerprints'][key]]
        if account(client) != identity:
            raise CanvasError('Account changed during copy readback')
    except CanvasError:
        raise CanvasError(UNCERTAIN) from None
    return {'copied_page': {**copied, 'html_url': client.host + '/courses/' + item + '/pages/' + quote(copied['url'], safe='')},
            'course_id': int(item), 'source_page_id': int(page_id), 'source_unchanged': True,
            'acknowledgement_matches_readback': True, 'content_matches_source': copied_content['copy_fingerprint'] == content['copy_fingerprint'],
            'source_content_kind': content['kind'], 'copied_content_kind': copied_content['kind'],
            'copied_assignment': new_assignment['metadata'] if new_assignment else None,
            'assignment_lineage_verified': True if new_assignment else None,
            'assignment_configuration_changed_fields': changed_config,
            'assignment_configuration_compared_fields': compared_config, 'assignment_configuration_unknown_fields': unknown_config,
            'note': 'One native POST; exact new-page acknowledgement/readback, unchanged source, stable account/create rights and front page verified. '
                    'Reported assignment copies have separate readback and exact source lineage. Content equality, selected assignment-configuration differences and unavailable fields are labeled, '
                    'not proof of every copied association, integration, module link, historical grade or submission. Canvas chooses title/URL and native resets. '
                    'No automatic retry, publication, second assignment POST, deletion or rollback; no raw source HTML, block payloads or grading records emitted.'}
