"""Scoped module metadata and explicit own progression events, never assessment completion."""

import math
from urllib.parse import urlencode

from .access import query
from .client import CanvasError
from .group_content import _context, _id, _number, base
from .progress import published
from .writes import account, check_flags, confirmed, digest

MODULE_FIELDS = ('id', 'name', 'position', 'published', 'state', 'completed_at', 'unlock_at',
                 'require_sequential_progress', 'requirement_type', 'requirement_count',
                 'prerequisite_module_ids', 'items_count', 'publish_final_grade')
ITEM_FIELDS = ('id', 'module_id', 'title', 'type', 'position', 'indent', 'content_id',
               'page_url', 'published', 'new_tab', 'publish_at')
READ_NOTE = ('Metadata only, through the complete paginated item list, not the single-item GET '
             'that can mark Horizon content read. No content URLs are followed and no explicit '
             'view/done events or assessment attempts are sent. Native module evaluation can '
             'materialize/recalculate progression records. Missing completion is unknown.')
WARNING = ('Changes only your own module progress. Done/not-done can also synchronize your planner '
           'checkbox; completion can unlock/re-lock modules and, where configured, publish an existing '
           'final grade to the SIS. Read acknowledges content you already accessed separately, not '
           'proof that you read it. This does not submit, contribute, start an assessment, satisfy a '
           'score requirement or change shared module configuration. Native GET evaluation can '
           'materialize/recalculate progress. Confirmation is not an atomic lock; no automatic retry, '
           'rollback or repair. Planner synchronization and downstream/SIS effects are not verified.')
UNCERTAIN = ('Could not verify the module event. Your progress/planner or downstream module state '
             'may have changed; check Canvas before repeating. No automatic retry, rollback, repair '
             'or private response-body logging.')


def _limit(value):
    if type(value) is not int or value < 1:
        raise CanvasError('Module inventory page limit must be a positive integer')


def _module_metadata(row):
    _id(row)
    for key in ('require_sequential_progress', 'publish_final_grade', 'locked_for_user', 'published'):
        if key in row and type(row[key]) is not bool:
            raise CanvasError('Canvas returned malformed module policy')
    for key in ('name', 'state', 'requirement_type', 'completed_at', 'unlock_at'):
        if row.get(key) is not None and not isinstance(row[key], str):
            raise CanvasError('Canvas returned malformed module metadata')
    for key in ('position', 'items_count', 'requirement_count'):
        if row.get(key) is not None and (type(row[key]) is not int or row[key] < (1 if key == 'position' else 0)):
            raise CanvasError('Canvas returned malformed module counts or position')
    if 'prerequisite_module_ids' in row:
        values = row['prerequisite_module_ids']
        if not isinstance(values, list) or any(type(value) is not int or value < 1 for value in values) or len(set(values)) != len(values):
            raise CanvasError('Canvas returned malformed module prerequisites')
    return {key: row[key] for key in MODULE_FIELDS if key in row}


def _module(row, module_id):
    metadata = _module_metadata(row)
    if row['id'] != int(module_id) or not published(row):
        raise CanvasError('Canvas returned a different or unavailable module')
    if row.get('state') == 'locked' or row.get('locked_for_user'):
        raise CanvasError('This module is locked; its items were not requested')
    return metadata


def _item(row, module_id, client, course_id, *, require_details=True):
    _id(row)
    if _id(row, 'module_id') != int(module_id):
        raise CanvasError('Canvas returned an item outside the requested module')
    if any(not isinstance(row.get(key), str) or not row[key] for key in ('type', 'title')):
        raise CanvasError('Canvas returned malformed module item metadata')
    for key in ('content_id', 'position', 'indent'):
        if row.get(key) is not None and (type(row[key]) is not int or row[key] < (0 if key == 'indent' else 1)):
            raise CanvasError('Canvas returned malformed module item IDs or position')
    for key in ('page_url', 'publish_at'):
        if row.get(key) is not None and not isinstance(row[key], str):
            raise CanvasError('Canvas returned malformed module item text metadata')
    for key in ('published', 'locked_for_user', 'hidden_for_user', 'new_tab'):
        if key in row and type(row[key]) is not bool:
            raise CanvasError('Canvas returned malformed module item visibility')
    requirement = row.get('completion_requirement')
    if requirement is not None:
        if (not isinstance(requirement, dict) or not isinstance(requirement.get('type'), str) or
                not requirement['type'] or 'completed' in requirement and type(requirement['completed']) is not bool):
            raise CanvasError('Canvas returned malformed module completion requirements')
        requirement = {key: requirement[key] for key in ('type', 'completed', 'min_score', 'min_percentage') if key in requirement}
        for key in ('min_score', 'min_percentage'):
            if key in requirement and (type(requirement[key]) not in (int, float) or
                                       type(requirement[key]) is float and not math.isfinite(requirement[key])):
                raise CanvasError('Canvas returned a malformed module score requirement')
    details = row.get('content_details')
    if details is None and not require_details:
        details = {}
    if not isinstance(details, dict):
        raise CanvasError('Canvas did not report module content lock metadata')
    for key in ('locked_for_user', 'hidden', 'locked'):
        if key in details and type(details[key]) is not bool:
            raise CanvasError('Canvas returned malformed module content visibility')
    for key in ('due_at', 'unlock_at', 'lock_at'):
        if details.get(key) is not None and not isinstance(details[key], str):
            raise CanvasError('Canvas returned malformed module content dates')
    points = details.get('points_possible')
    if points is not None and (type(points) not in (int, float) or type(points) is float and not math.isfinite(points)):
        raise CanvasError('Canvas returned malformed module content points')
    return {**{key: row[key] for key in ITEM_FIELDS if key in row},
            'requirement': requirement,
            'completion': ('not_required' if requirement is None else 'unknown' if 'completed' not in requirement
                           else 'completed' if requirement['completed'] else 'incomplete'),
            'visible': published(row) and not details.get('hidden'),
            'locked_for_user': bool(row.get('locked_for_user') or details.get('locked_for_user') or details.get('locked')),
            'content_lock_reported': type(details.get('locked_for_user')) is bool,
            **{key: details[key] for key in ('due_at', 'unlock_at', 'lock_at', 'points_possible') if key in details},
            'html_url': client.host + f'/courses/{course_id}/modules/items/{row["id"]}'}


def _state(client, course_id, module_id, item_id, max_pages, *, student_id=None):
    route = base(course_id, 'course') + '/modules/' + module_id
    parameters = [('student_id', str(student_id))] if student_id is not None else []
    module_route = route + ('?' + urlencode(parameters) if parameters else '')
    before, _ = client.request(module_route)
    module = _module(before, module_id)
    rows = client.list(route + '/items?' + urlencode([('per_page', '100'), ('include[]', 'content_details'), *parameters]), max_pages)
    items = [_item(row, module_id, client, course_id) for row in rows]
    if len({row['id'] for row in items}) != len(items):
        raise CanvasError('Canvas returned duplicate module item IDs')
    if 'items_count' in module and (type(module['items_count']) is not int or module['items_count'] != len(items)):
        raise CanvasError('Canvas returned an incomplete module inventory')
    selected = next((row for row in items if row['id'] == int(item_id)), None)
    if selected is None or not selected['visible']:
        raise CanvasError('The item is absent or unavailable in the requested module')
    after, _ = client.request(module_route)
    if _module(after, module_id) != module:
        raise CanvasError('Module state changed during inventory inspection; review a fresh preview')
    return module, selected, sorted(items, key=lambda row: row['id'])


def read(client, course_id, module_id, item_id, *, max_pages=100):
    _limit(max_pages)
    for value in (course_id, module_id, item_id):
        _number(value)
    _, context = _context(client, course_id, 'course')
    module, item, _ = _state(client, course_id, module_id, item_id, max_pages)
    return {'course_id': int(course_id), 'course_name': context.get('name'), 'module': module,
            'module_item': item, 'complete_item_inventory': True, 'note': READ_NOTE}


def _scope(client, course_id):
    route, context = _context(client, course_id, 'course')
    if (context.get('workflow_state') != 'available' or context.get('concluded') or
            context.get('access_restricted_by_date')):
        raise CanvasError('Module progress requires an available, unconcluded course')
    rights = query(client, route, ('participate_as_student',))
    if rights['participate_as_student'] is not True:
        raise CanvasError('Module progress requires native participation as the signed-in student')
    return {key: context.get(key) for key in ('id', 'name', 'workflow_state', 'concluded', 'access_restricted_by_date')}, rights


def _validate_change(module, item, operation):
    if (module.get('state') not in ('unlocked', 'started', 'completed') or
            type(module.get('require_sequential_progress')) is not bool or
            type(module.get('publish_final_grade')) is not bool or
            module.get('requirement_type') not in ('all', 'one')):
        raise CanvasError('Canvas did not report an explicit own progression and module completion policy')
    if item['locked_for_user'] or not item['content_lock_reported'] or item['type'] == 'SubHeader':
        raise CanvasError('This item is locked, lacks native lock metadata or is a non-viewable heading')
    if operation != 'read':
        requirement = item['requirement']
        if (requirement is None or requirement['type'] != 'must_mark_done' or
                type(requirement.get('completed')) is not bool):
            raise CanvasError('Done/not-done requires a reported own must_mark_done checkbox, not a submission or score requirement')
        if requirement['completed'] == (operation == 'done'):
            raise CanvasError('This checkbox already reports the selected state; no event was sent')


def change(client, course_id, module_id, item_id, operation, *, acknowledge_progress=False,
           acknowledge_viewed=False, max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    _limit(max_pages)
    for value in (course_id, module_id, item_id):
        _number(value)
    if operation not in ('done', 'not-done', 'read'):
        raise CanvasError('Choose an explicit native done, not-done or read event')
    if acknowledge_progress is not True or operation == 'read' and acknowledge_viewed is not True:
        raise CanvasError('Require --acknowledge-module-progress and, for read, --acknowledge-content-viewed, including previews')
    identity = account(client)
    context, rights = _scope(client, course_id)
    module, before, inventory = _state(client, course_id, module_id, item_id, max_pages, student_id=identity['user_id'])
    _validate_change(module, before, operation)
    if account(client) != identity:
        raise CanvasError('Account changed during module preflight; review a fresh preview')
    preview = {**identity, 'course_id': int(course_id), 'context': context, 'permissions': rights,
               'module_id': int(module_id), 'item_id': int(item_id), 'module': module, 'before': before,
               'inventory_digest': digest(inventory), 'operation': operation,
               'acknowledge_module_progress': True, 'acknowledge_content_viewed': operation == 'read',
               'method': {'done': 'PUT', 'not-done': 'DELETE', 'read': 'POST'}[operation],
               'route': base(course_id, 'course') + f'/modules/{module_id}/items/{item_id}/' +
                        ('mark_read' if operation == 'read' else 'done'), 'warning': WARNING}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        # Native acknowledgement is localized and is not a stored-state proof.
        if not isinstance(response, dict) or not isinstance(response.get('message'), str) or not response['message']:
            raise CanvasError('Canvas did not acknowledge the module event')
        next_context, next_rights = _scope(client, course_id)
        if next_context != context or next_rights != rights or account(client) != identity:
            raise CanvasError('Account/course/participation changed during module verification')
        after_module, after, _ = _state(client, course_id, module_id, item_id, max_pages, student_id=identity['user_id'])
        if ({key: value for key, value in after_module.items() if key not in ('state', 'completed_at')} !=
                {key: value for key, value in module.items() if key not in ('state', 'completed_at')}):
            raise CanvasError('Module completion policy changed')
        if ({key: value for key, value in after.items() if key not in ('completion', 'requirement')} !=
                {key: value for key, value in before.items() if key not in ('completion', 'requirement')}):
            raise CanvasError('Module item metadata changed')
        requirement = before['requirement']
        stored = after['requirement']
        if (({key: value for key, value in stored.items() if key != 'completed'} if stored else None) !=
                ({key: value for key, value in requirement.items() if key != 'completed'} if requirement else None)):
            raise CanvasError('Module requirement changed')
        verifiable = operation != 'read' or requirement is not None and requirement['type'] == 'must_view'
        if verifiable and (stored is None or stored.get('completed') is not (operation != 'not-done')):
            raise CanvasError('Canvas did not store the selected own requirement state')
        if account(client) != identity:
            raise CanvasError('Account changed during final module verification')
    except CanvasError:
        raise CanvasError(UNCERTAIN) from None
    return {'course_id': int(course_id), 'module': after_module, 'module_item': after, 'operation': operation,
            'event_acknowledged': True, 'requirement_status_verified': True if verifiable else None,
            'planner_synchronization_verified': False,
            'note': 'One native event, stable account/course/participation and separate paginated metadata '
                    'readback. Module state is reported, not inferred. ' +
                    ('The selected own requirement state was verified. ' if verifiable else
                     'There is no must_view requirement to verify; acknowledgement does not prove a stored view event '
                     'or completion of another requirement. ') + WARNING}
