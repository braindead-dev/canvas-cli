"""Explicit controls for the signed-in user's course and group favorites."""

from .client import CanvasError
from .writes import account, check_flags, confirmed


def _namespace(context_type):
    if context_type not in ('course', 'group'):
        raise CanvasError('Favorites require an explicit course or group context')
    return context_type + 's'


def _identity(record, item_id=None):
    if (not isinstance(record, dict) or type(record.get('id')) is not int or record['id'] < 1 or
            (item_id is not None and str(record['id']) != item_id)):
        raise CanvasError('Canvas returned an invalid or different favorite destination')
    return {key: record.get(key) for key in ('id', 'name', 'course_code', 'workflow_state')}


def listing(client, max_pages=100, context_type='course'):
    """This is the displayed selection, not proof of explicitly starred records."""
    namespace = _namespace(context_type)
    return client.list(f'/api/v1/users/self/favorites/{namespace}?per_page=100', max_pages)


def change(client, action, item_id=None, *, context_type='course', max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    namespace = _namespace(context_type)
    if action not in ('add', 'remove', 'reset'):
        raise CanvasError('Favorite action must be add, remove or reset')
    if action == 'reset':
        if item_id is not None:
            raise CanvasError('Reset affects all favorites of the selected context, not one ID')
    elif (not isinstance(item_id, str) or not item_id.isascii() or not item_id.isdecimal() or
          int(item_id) < 1 or str(int(item_id)) != item_id):
        raise CanvasError('Expected a positive numeric favorite destination ID')
    identity = account(client)
    target = None
    if item_id is not None:
        target = _identity(client.request(f'/api/v1/{namespace}/{item_id}')[0], item_id)
    selection = [_identity(row) for row in listing(client, max_pages, context_type)]
    if len({row['id'] for row in selection}) != len(selection):
        raise CanvasError('Canvas returned duplicate favorite destinations; review the current dashboard')
    selection.sort(key=lambda row: row['id'])
    preview = {
        'method': 'POST' if action == 'add' else 'DELETE',
        'route': f'/api/v1/users/self/favorites/{namespace}' + (f'/{item_id}' if item_id else ''),
        'body': None, **identity, 'action': action, 'context_type': context_type,
        'target': target, 'displayed_selection': selection, 'manual_selection_known': False,
        'effect': ('Clear ALL custom favorites of this context and restore Canvas defaults.' if action == 'reset'
                   else f'{action.capitalize()} this {context_type} in your own favorites. This does not change enrollment.'),
        'warning': ('The list can be automatically generated rather than manually starred. Adding a first favorite '
                    'can replace the displayed default selection. Removing a course when there are no custom '
                    'favorites can first save other default courses as favorites. Removing the last favorite '
                    'or resetting can make defaults reappear. Canvas enforces membership and permissions.'),
    }
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    if action == 'reset':
        valid = isinstance(response, dict) and response.get('status') == 'ok'
    else:
        valid = (isinstance(response, dict) and type(response.get('context_id')) is int and
                 response['context_id'] == int(item_id) and response.get('context_type') == context_type.title())
        # The native remove endpoint acknowledges a missing explicit favorite with {}.
        valid = valid or (action == 'remove' and response == {})
    if not valid:
        raise CanvasError('Favorite write response did not identify the expected operation; verify Canvas before repeating')
    return {'favorite_change': {'action': action, 'context_type': context_type, 'target': target},
            'acknowledged': True, 'note': 'Canvas acknowledged the request. The displayed list may still include defaults; enrollment is unchanged.'}
