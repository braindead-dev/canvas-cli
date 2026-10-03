"""Own membership controls, never group-set switches or other people's roles."""

from .access import query
from .client import CanvasError
from .group_content import _context, _id, _number
from .writes import account, check_flags, confirmed

STATES = ('accepted', 'invited', 'requested')
JOIN_LEVELS = ('parent_context_auto_join', 'parent_context_request')
SAFE_ROLES = ('student_organized', 'communities')
NOTE = ('Own active membership only, from the fully paginated authorized membership endpoint. '
        'Absent means no active record was returned, not that no deleted/rejected record ever existed. '
        'An invitation/request is not accepted membership. No enrollment or membership change requested.')


def _metadata(row, group_id):
    membership_id, user_id = _id(row), _id(row, 'user_id')
    if type(row.get('group_id')) is not int or row['group_id'] != int(group_id):
        raise CanvasError('Canvas returned membership outside the requested group')
    if row.get('workflow_state') not in STATES or type(row.get('moderator')) is not bool:
        raise CanvasError('Canvas returned invalid active group-membership metadata')
    result = {'id': membership_id, 'group_id': int(group_id), 'user_id': user_id,
              'workflow_state': row['workflow_state'], 'moderator': row['moderator']}
    if row.get('created_at') is not None:
        if not isinstance(row['created_at'], str):
            raise CanvasError('Canvas returned invalid membership creation metadata')
        result['created_at'] = row['created_at']
    return result


def _current(client, group_id, user_id, max_pages):
    if type(max_pages) is not int or max_pages < 1:
        raise CanvasError('Membership page limit must be a positive integer')
    rows = client.list(f'/api/v1/groups/{group_id}/memberships?per_page=100', max_pages)
    seen_ids, seen_users, current = set(), set(), None
    for row in rows:
        item = _metadata(row, group_id)
        if item['id'] in seen_ids or item['user_id'] in seen_users:
            raise CanvasError('Canvas returned duplicate group-membership records')
        seen_ids.add(item['id'])
        seen_users.add(item['user_id'])
        if item['user_id'] == user_id:
            current = item
    return current


def read(client, group_id, max_pages=100):
    _number(group_id)
    if type(max_pages) is not int or max_pages < 1:
        raise CanvasError('Membership page limit must be a positive integer')
    identity = account(client)
    _, group = _context(client, group_id, 'group')
    current = _current(client, group_id, identity['user_id'], max_pages)
    return {**identity, 'group_id': int(group_id), 'group_name': group.get('name'),
            'membership': current, 'complete_for_endpoint': True, 'note': NOTE}


def change(client, group_id, action, *, max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    _number(group_id)
    if action not in ('join', 'leave'):
        raise CanvasError('Own membership action must be join or leave')
    if type(max_pages) is not int or max_pages < 1:
        raise CanvasError('Membership page limit must be a positive integer')
    identity = account(client)
    route, group = _context(client, group_id, 'group')
    # These two native roles allow multiple memberships. Project/category changes can
    # implicitly remove another membership and recompute submissions; do not guess.
    if (group.get('role') not in SAFE_ROLES or group.get('non_collaborative') is not False or
            group.get('concluded') is not False or type(group.get('group_category_id')) is not int or
            group['group_category_id'] < 1):
        raise CanvasError('Membership writes require a current collaborative student-organized/community group; '
                          'project groups, differentiation tags and unknown group types are not supported')
    permissions = query(client, route, [action])
    if permissions[action] is not True:
        raise CanvasError('Canvas did not explicitly grant the requested own-group permission')
    current = _current(client, group_id, identity['user_id'], max_pages)
    if action == 'join':
        if current is not None and current['workflow_state'] in ('accepted', 'requested'):
            raise CanvasError('You already have accepted membership or a pending request; no duplicate join requested')
        if group.get('join_level') not in JOIN_LEVELS:
            raise CanvasError('This is not a native join/request group; invitation acceptance is not supported')
        method, target, body = 'POST', route + '/memberships', {'user_id': 'self'}
    else:
        if current is None:
            raise CanvasError('No active own membership was returned; no leave requested')
        method, target, body = 'DELETE', route + '/users/self', None
    preview = {**identity, 'action': action,
               'group': {key: group.get(key) for key in ('id', 'name', 'role', 'group_category_id', 'join_level',
                                                        'non_collaborative', 'concluded')},
               'current_membership': current, 'native_permission': {action: True},
               'method': method, 'route': target, 'body': body,
               'effect': 'Join/request this group as yourself only.' if action == 'join' else
                         'Leave this group or cancel your pending request/invitation only.',
               'warning': 'Membership can affect access to shared files/discussions and send native notifications. '
                          'Canvas determines the resulting state; a request or invitation is not acceptance. '
                          'No other user, moderator role, course enrollment or project-group switch is requested. '
                          'Preflight cannot eliminate concurrent changes; verify uncertain outcomes before repeating.'}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        if action == 'join':
            accepted = _metadata(response, group_id)
            if accepted['user_id'] != identity['user_id'] or current is not None and accepted['id'] != current['id']:
                raise CanvasError('Membership acknowledgement mismatch')
        else:
            if not isinstance(response, dict) or response.get('ok') is not True:
                raise CanvasError('Leave acknowledgement mismatch')
            accepted = None
    except CanvasError:
        raise CanvasError('Could not verify the own-group membership acknowledgement. It may have succeeded; '
                          'check Canvas before repeating. No automatic retries or response-body logging.') from None
    return {**identity, 'group_id': int(group_id), 'group_name': group.get('name'), 'action': action,
            'membership': accepted, 'acknowledged': True,
            'note': 'Native acknowledgement only, not an independent readback or proof of continued access. '
                    'Only your own selected group membership was requested; no enrollment or moderator change.'}
