"""Own native mastery choices, with explicit switching and asynchronous readback."""

import math

from .client import CanvasError
from .group_content import _id, _number, base
from .module_items import _item, _limit, _scope, _state
from .module_navigation import _asset, sequence
from .progress import published
from .writes import account, check_flags, confirmed, digest

NOTE = ('Own currently reported eligible paths, not all instructor rules or future score ranges. '
        'Only assignment IDs are projected from nested path models. No content/launch URL is followed, '
        'quiz attempt started or grade changed. Module/conditional-release GET evaluation can recalculate '
        'progress and trigger configured downstream/SIS effects. Missing processing status is unknown. '
        'A single eligible set ID is reported automatically, not proof of stored assignment overrides.')
WARNING = ('Changes your own assignment overrides and submission availability, not just a checkbox. '
           'Switching can remove other assigned paths; shared assignments are retained by Canvas. '
           'Potential removals cover other currently eligible choices, not proof they are all assigned '
           'or will be removed. Deleted/unpublished assignments can be omitted, course pacing can change '
           'dates, and module progression/downstream/SIS effects can occur. These effects are not '
           'independently verified. Confirmation is not an atomic lock. No automatic retry, rollback or repair.')
UNCERTAIN = ('The mastery-path request may have changed assignments, dates or progress, but could not '
             'be verified. Check module-paths and Canvas before repeating. No automatic retry, rollback '
             'or private response-body logging.')


def _parent(row, course_id):
    if 'course_id' in row and _id(row, 'course_id') != int(course_id):
        raise CanvasError('Canvas returned a foreign mastery-path course resource')


def _assignment_id(client, course_id, item, max_pages):
    """Resolve all native ContentTag#assignment types without a page-view GET."""
    route = base(course_id, 'course')
    kind = item['type']
    if kind == 'Assignment':
        return _id(item, 'content_id')
    if kind in ('Quiz', 'Discussion'):
        identifier = _id(item, 'content_id')
        resource = 'quizzes' if kind == 'Quiz' else 'discussion_topics'
        row, _ = client.request(route + f'/{resource}/{identifier}')
        if _id(row) != identifier:
            raise CanvasError('Canvas returned a different mastery-path source asset')
        _parent(row, course_id)
        return _id(row, 'assignment_id')
    if kind == 'Page':
        slug = _asset('Page', item.get('page_url'))
        rows = client.list(route + '/pages?per_page=100', max_pages)
        matches = [row for row in rows if isinstance(row, dict) and row.get('url') == slug]
        if len(matches) != 1 or not published(matches[0]):
            raise CanvasError('The linked mastery page is absent, ambiguous or unavailable')
        row = matches[0]
        _id(row, 'page_id')
        _parent(row, course_id)
        linked = row.get('assignment')
        identifier = _id(linked)
        _parent(linked, course_id)
        return identifier
    raise CanvasError('This native mastery item does not have a graded assignment association')


def _grade(client, course_id, item, user_id, max_pages):
    assignment_id = _assignment_id(client, course_id, item, max_pages)
    route = base(course_id, 'course') + f'/assignments/{assignment_id}'
    assignment, _ = client.request(route)
    if _id(assignment) != assignment_id or not published(assignment):
        raise CanvasError('Canvas returned a different or unavailable mastery trigger assignment')
    _parent(assignment, course_id)
    for key in ('name', 'updated_at', 'grading_type'):
        if assignment.get(key) is not None and not isinstance(assignment[key], str):
            raise CanvasError('Canvas returned malformed mastery trigger metadata')
    points = assignment.get('points_possible')
    if points is not None and (type(points) not in (int, float) or
                               type(points) is float and not math.isfinite(points)):
        raise CanvasError('Canvas returned malformed mastery trigger points')
    submission, _ = client.request(route + f'/submissions/{user_id}')
    _id(submission)
    if _id(submission, 'assignment_id') != assignment_id or _id(submission, 'user_id') != user_id:
        raise CanvasError('Canvas returned a foreign mastery trigger submission')
    for key in ('workflow_state', 'posted_at', 'graded_at'):
        if submission.get(key) is not None and not isinstance(submission[key], str):
            raise CanvasError('Canvas returned malformed mastery trigger grading metadata')
    score = submission.get('score')
    if score is not None and (type(score) not in (int, float) or type(score) is float and not math.isfinite(score)):
        raise CanvasError('Canvas returned malformed mastery trigger score')
    if submission.get('attempt') is not None and (type(submission['attempt']) is not int or submission['attempt'] < 0):
        raise CanvasError('Canvas returned malformed mastery trigger attempt')
    return {'assignment': {key: assignment[key] for key in ('id', 'name', 'points_possible', 'updated_at', 'grading_type')
                           if key in assignment},
            'submission': {key: submission[key] for key in ('id', 'assignment_id', 'user_id', 'workflow_state',
                                                          'posted_at', 'graded_at', 'score', 'attempt') if key in submission}}


def _paths(client, course_id, module_id, item):
    result = sequence(client, course_id, 'ModuleItem', str(item['id']), include_assignments=True)
    nodes = result['module_sequence']
    if len(nodes) != 1 or nodes[0]['current']['module_id'] != int(module_id):
        raise CanvasError('Canvas did not return this exact mastery-path occurrence')
    current = nodes[0]['current']
    if any(current.get(key) != item.get(key) for key in ('type', 'content_id', 'page_url', 'title')):
        raise CanvasError('Module item changed during mastery-path inspection; review a fresh preview')
    return nodes[0]['mastery_path']


def _inspect(client, course_id, module_id, item_id, max_pages):
    identity = account(client)
    context, rights = _scope(client, course_id)
    module, item, inventory = _state(client, course_id, module_id, item_id, max_pages, student_id=identity['user_id'])
    paths = _paths(client, course_id, module_id, item)
    trigger = None
    if paths is not None and paths.get('locked') is False and paths.get('assignment_set_ids'):
        trigger = _grade(client, course_id, item, identity['user_id'], max_pages)
    if account(client) != identity:
        raise CanvasError('Account changed during mastery-path inspection; review a fresh preview')
    return {**identity, 'course_id': int(course_id), 'context': context, 'permissions': rights,
            'module': module, 'module_item': item, 'inventory_digest': digest(inventory),
            'mastery_paths': paths, 'trigger': trigger}


def read(client, course_id, module_id, item_id, *, max_pages=100):
    _limit(max_pages)
    for value in (course_id, module_id, item_id):
        _number(value)
    return {**_inspect(client, course_id, module_id, item_id, max_pages), 'note': NOTE}


def _effects(paths, set_id, reapply):
    if (paths is None or paths.get('locked') is not False or
            not isinstance(paths.get('assignment_sets'), list) or not paths['assignment_sets'] or
            'selected_set_id' not in paths or type(paths.get('awaiting_choice')) is not bool):
        raise CanvasError('Canvas did not report explicit own eligible mastery choices')
    sets = {row['id']: row['assignment_ids'] for row in paths['assignment_sets']}
    if any(value is None for value in sets.values()):
        raise CanvasError('Canvas omitted mastery assignment associations; potential switching effects are unknown')
    selected = paths['selected_set_id']
    if (selected is not None and selected not in sets or
            paths['awaiting_choice'] != (selected is None)):
        raise CanvasError('Canvas reported inconsistent mastery-choice state')
    if set_id not in sets:
        raise CanvasError('This assignment set is not currently eligible for this exact item')
    if set_id == selected and not reapply:
        raise CanvasError('This path already reports selected; no request was sent. Deliberate reapplication requires --reapply-selected-path')
    if reapply and set_id != selected:
        raise CanvasError('--reapply-selected-path is only for the already-reported selected set')
    target = set(sets[set_id])
    others = {identifier for key, values in sets.items() if key != set_id for identifier in values}
    return {'previous_set_id': selected, 'assignment_set_id': set_id,
            'switching': selected is not None and selected != set_id, 'reapplying': reapply,
            'target_assignment_ids': sets[set_id], 'potentially_removed_assignment_ids': sorted(others - target),
            'shared_with_other_choices_assignment_ids': sorted(others & target)}


def _acknowledgement(client, response, course_id, module_id, target, max_pages):
    if (not isinstance(response, dict) or not isinstance(response.get('meta'), dict) or
            response['meta'].get('primaryCollection') != 'assignments' or
            not isinstance(response.get('assignments'), list) or not isinstance(response.get('items'), list)):
        raise CanvasError('Canvas did not acknowledge a native mastery compound document')
    assignments = []
    for row in response['assignments']:
        identifier = _id(row)
        _parent(row, course_id)
        if identifier not in target or identifier in assignments:
            raise CanvasError('Canvas acknowledged a duplicate or unexpected mastery assignment')
        assignments.append(identifier)
    items = []
    for row in response['items']:
        item = _item(row, module_id, client, course_id, require_details=False)
        if item['id'] in items or _assignment_id(client, course_id, item, max_pages) not in assignments:
            raise CanvasError('Canvas acknowledged an unrelated mastery module item')
        items.append(item['id'])
    return {'assignment_ids': assignments, 'module_item_ids': items}


def select(client, course_id, module_id, item_id, set_id, *, acknowledge_change=False,
           acknowledge_switch=False, reapply_selected=False, max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    _limit(max_pages)
    for value in (course_id, module_id, item_id, set_id):
        _number(value)
    if acknowledge_change is not True:
        raise CanvasError('Require --acknowledge-path-change, including previews')
    before = _inspect(client, course_id, module_id, item_id, max_pages)
    effects = _effects(before['mastery_paths'], int(set_id), reapply_selected is True)
    if effects['switching'] and acknowledge_switch is not True:
        raise CanvasError('Switching requires --acknowledge-path-switch, including previews; old assignments can be removed')
    trigger = before['trigger']
    if (trigger is None or trigger['submission'].get('workflow_state') != 'graded' or
            not trigger['submission'].get('posted_at') or trigger['submission'].get('score') is None):
        raise CanvasError('Mastery selection requires your own native graded, posted trigger submission with a reported score')
    preview = {**before, 'effects': effects, 'acknowledge_path_change': True,
               'acknowledge_path_switch': acknowledge_switch is True, 'reapply_selected_path': reapply_selected is True,
               'method': 'POST',
               'route': base(course_id, 'course') + f'/modules/{module_id}/items/{item_id}/select_mastery_path',
               'body': {'assignment_set_id': int(set_id), 'student_id': before['user_id']}, 'warning': WARNING}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        ack = _acknowledgement(client, response, course_id, module_id, effects['target_assignment_ids'], max_pages)
        # A compound acknowledgement can omit unpublished/deleted assignments. It is not a choice proof.
        identity = account(client)
        context, rights = _scope(client, course_id)
        if (identity != {key: before[key] for key in ('origin', 'user_id')} or
                context != before['context'] or rights != before['permissions']):
            raise CanvasError('Account/course/participation changed during mastery verification')
        # Visibility and module counts can legitimately change; do not compare old inventories.
        paths = _paths(client, course_id, module_id, before['module_item'])
        if account(client) != identity:
            raise CanvasError('Account changed during final mastery verification')
    except CanvasError:
        raise CanvasError(UNCERTAIN) from None
    reported = (paths is not None and paths.get('selected_set_id') == int(set_id) and
                int(set_id) in paths.get('assignment_set_ids', []) and paths.get('locked') is False and
                paths.get('awaiting_choice') is False)
    automatic = reported and len(paths['assignment_set_ids']) == 1
    # Native single-set selected_set_id is inferred; still_processing only checks action existence,
    # not its latest assigned/unassigned state. Multiple choices use current AssignmentSetAction.
    verified = reported and not automatic
    return {'course_id': int(course_id), 'module_id': int(module_id), 'item_id': int(item_id),
            'assignment_set_id': int(set_id), 'request_acknowledged': True, 'choice_verified': verified,
            'choice_reported': reported, 'automatic_path_reported': automatic,
            'status': 'choice_verified' if verified else 'accepted_choice_unverified',
            'mastery_paths': paths, 'acknowledged': ack, 'effects': effects,
            'assignment_availability_verified': False, 'due_dates_verified': False,
            'note': ('A separate own native sequence reports this stored multiple-choice selection. ' if verified else
                     'Canvas reports a single automatic path, which does not prove stored assignment overrides. '
                     'Inspect module-paths and Canvas; do not automatically repeat. ' if automatic else
                     'Canvas accepted the request, but separate own metadata does not yet prove this choice. '
                     'It may be pending/cached, changed concurrently or not applied; check module-paths and Canvas, '
                     'do not automatically repeat. ') + NOTE + ' ' + WARNING}
