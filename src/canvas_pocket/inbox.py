"""Preview-first organization of only the signed-in user's Inbox view."""

from .client import CanvasError
from .writes import account, check_flags, confirmed, digest


def _summary(record, conversation_id):
    if (not isinstance(record, dict) or type(record.get('id')) is not int or
            str(record['id']) != conversation_id or record.get('workflow_state') not in ('read', 'unread', 'archived') or
            type(record.get('message_count')) is not int or record['message_count'] < 0):
        raise CanvasError('Canvas did not confirm the expected Inbox conversation and state')
    return {key: record.get(key) for key in ('id', 'subject', 'workflow_state', 'message_count',
                                            'last_message_at', 'starred', 'subscribed', 'private')}


def change(client, conversation_id, *, state=None, starred=None, subscribed=None,
           delete=False, permanent=False, yes=False, confirm=None):
    check_flags(yes, confirm)
    if (not isinstance(conversation_id, str) or not conversation_id.isascii() or
            not conversation_id.isdecimal() or int(conversation_id) < 1 or str(int(conversation_id)) != conversation_id):
        raise CanvasError('Expected a positive numeric conversation ID')
    if state is not None and state not in ('read', 'unread', 'archived'):
        raise CanvasError('Inbox state must be read, unread or archived')
    if any(value is not None and type(value) is not bool for value in (starred, subscribed)):
        raise CanvasError('Starred and subscribed changes must be explicit booleans')
    fields = {key: value for key, value in [('workflow_state', state), ('starred', starred), ('subscribed', subscribed)]
              if value is not None}
    if delete:
        if not permanent or fields:
            raise CanvasError('Inbox deletion requires --permanent and cannot combine with state edits')
    elif permanent or not fields:
        raise CanvasError('Choose at least one Inbox state change; --permanent is only for deletion')
    identity = account(client)
    route = f'/api/v1/conversations/{conversation_id}'
    current, _ = client.request(route + '?auto_mark_as_read=false')
    summary = _summary(current, conversation_id)
    messages = current.get('messages')
    if not isinstance(messages, list) or any(not isinstance(row, dict) for row in messages):
        raise CanvasError('Canvas did not provide the visible thread revision; refusing to change it')
    if subscribed is not None and current.get('private') is not False:
        raise CanvasError('Subscription changes require a confirmed group conversation, not a private thread')
    revisions = [{key: row.get(key) for key in ('id', 'author_id', 'body', 'created_at', 'generated')}
                 for row in messages]
    preview = {**identity, 'method': 'DELETE' if delete else 'PUT', 'route': route,
               'body': None if delete else {'conversation': fields},
               'conversation': summary, 'message_revision': digest(revisions), 'permanent': bool(permanent),
               'effect': ('Remove ALL visible messages from your own view. This does not unsend them for others. '
                          'Pocket has no restore command; archive instead to keep the thread.' if delete else
                          'Change only your Inbox view. No message is sent, and other participants are unaffected.'),
               'warning': 'Changing subscription can change unread flags and Inbox ordering. A read marker is not proof you read the content.'}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        result = _summary(response, conversation_id)
    except CanvasError:
        raise CanvasError('Inbox response did not confirm the expected conversation; verify Canvas before repeating') from None
    if delete:
        valid = result['message_count'] == 0
    else:
        valid = all(type(response.get(key)) is type(value) and response[key] == value for key, value in fields.items())
    if not valid:
        raise CanvasError('Inbox response did not confirm the requested changes; verify Canvas before repeating')
    return {'inbox_change': result, 'deleted_from_own_view': bool(delete), 'acknowledged': True,
            'note': 'Canvas acknowledged the change to your own view. No message was sent or removed from other participants.'}
