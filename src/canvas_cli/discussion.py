"""Guarded discussion entry and reply composition."""

import hashlib
import html
import json
from urllib.parse import urlencode

from .client import CanvasError
from .contexts import discussion_base, read_topic, require_entry_api
from .writes import account, check_flags, confirmed, digest


def _message(text):
    if not isinstance(text, str) or not text.strip():
        raise CanvasError('Empty message refused')
    return '<p>' + html.escape(text).replace('\n', '<br>') + '</p>'


def _entry(client, base, topic_id, entry_id, max_pages):
    if not isinstance(entry_id, str) or not entry_id.isdecimal() or int(entry_id) < 1:
        raise CanvasError('Expected a positive discussion entry ID')
    rows = client.list(base + '/entry_list?' + urlencode({'ids[]': entry_id, 'per_page': 100}), max_pages)
    if (len(rows) != 1 or not isinstance(rows[0], dict) or type(rows[0].get('id')) is not int or
            str(rows[0]['id']) != entry_id or any(rows[0].get(key) is not None and
                str(rows[0][key]) != topic_id for key in ('topic_id', 'discussion_topic_id'))):
        raise CanvasError('Canvas did not return the exact requested discussion entry')
    return rows[0]


def entry(client, context_id, topic_id, entry_id, max_pages=100, context_type='course'):
    base = discussion_base(context_id, topic_id, context_type)
    read_topic(client, context_id, topic_id, context_type, require_entries=True)
    return _entry(client, base, topic_id, entry_id, max_pages)


def state(client, context_id, topic_id, action, *, entry_id=None, forced=None,
          max_pages=100, context_type='course', yes=False, confirm=None):
    """Change only the signed-in user's subscription or read markers, never content."""
    check_flags(yes, confirm)
    if action not in ('subscribe', 'unsubscribe', 'read', 'unread'):
        raise CanvasError('Unknown discussion state change')
    if entry_id is not None and action in ('subscribe', 'unsubscribe'):
        raise CanvasError('Subscriptions apply to topics, not individual entries')
    if forced is not None and (entry_id is None or type(forced) is not bool):
        raise CanvasError('Forced read state is an explicit boolean for one entry only')
    base = discussion_base(context_id, topic_id, context_type)
    identity = account(client)
    topic = read_topic(client, context_id, topic_id, context_type,
                       require_entries=entry_id is not None, allow_locked=True)
    before = {key: topic.get(key) for key in ('id', 'title', 'message', 'subscribed', 'read_state', 'updated_at')}
    route = base + ('/subscribed' if action in ('subscribe', 'unsubscribe') else '/read')
    effect = ('Changes only your topic notification subscription.' if action in ('subscribe', 'unsubscribe') else
              'Changes only your read marker for the initial topic text, not its replies.')
    if entry_id is not None:
        current = _entry(client, base, topic_id, entry_id, max_pages)
        if current.get('deleted') or current.get('workflow_state') == 'deleted' or current.get('hidden_for_user'):
            raise CanvasError('Cannot change a read marker for a deleted or hidden entry')
        before['entry'] = {key: current.get(key) for key in
                           ('id', 'user_id', 'message', 'updated_at', 'read_state', 'forced_read_state')}
        route = base + f'/entries/{entry_id}/read'
        effect = 'Changes only your read marker for this visible entry, not its content or author.'
    preview = {**identity, f'{context_type}_id': context_id, 'context_type': context_type,
               'topic_id': topic_id, 'topic_title': topic.get('title'), 'entry_id': entry_id,
               'action': action, 'before': before, 'method': 'PUT' if action in ('subscribe', 'read') else 'DELETE',
               'route': route, 'body': {'forced_read_state': forced} if forced is not None else None,
               'expected_response': 'no_content', 'effect': effect}
    result = confirmed(client, preview, yes, confirm)
    if not yes:
        return result
    return {'discussion_state': {'context_type': context_type, f'{context_type}_id': int(context_id),
                                 'topic_id': int(topic_id), 'entry_id': int(entry_id) if entry_id else None,
                                 'action': action, 'forced_read_state': forced},
            'note': 'Canvas acknowledged the requested state change with HTTP 204. ' + effect}


def _revision(entry):
    fields = {key: entry.get(key) for key in
              ('id', 'user_id', 'message', 'created_at', 'updated_at', 'parent_id', 'deleted', 'permissions')}
    attachment = entry.get('attachment')
    if attachment is not None:
        if not isinstance(attachment, dict) or type(attachment.get('id')) is not int or attachment['id'] < 1:
            raise CanvasError('Canvas returned malformed discussion attachment metadata')
        fields['attachment'] = {key: attachment.get(key) for key in
                                ('id', 'display_name', 'size', 'updated_at', 'uuid')}
    else:
        fields['attachment'] = None
    return fields


def change_entry(client, context_id, topic_id, entry_id, message=None, *, delete=False,
                 remove_attachment=False, max_pages=100, context_type='course', yes=False, confirm=None):
    check_flags(yes, confirm)
    body = None if delete else {'message': _message(message)}
    if delete and (message is not None or remove_attachment):
        raise CanvasError('Entry deletion cannot be combined with text or attachment changes')
    base = discussion_base(context_id, topic_id, context_type)
    identity = account(client)
    topic = read_topic(client, context_id, topic_id, context_type, require_entries=True)
    current = _entry(client, base, topic_id, entry_id, max_pages)
    if (type(current.get('user_id')) is not int or current['user_id'] != identity['user_id'] or
            current.get('deleted') or current.get('workflow_state') == 'deleted' or
            current.get('locked_for_user') or current.get('hidden_for_user')):
        raise CanvasError('Only your own active, visible discussion entries can be changed')
    permission = 'delete' if delete else 'update'
    permissions = current.get('permissions')
    if isinstance(permissions, dict) and permissions.get(permission) is False:
        raise CanvasError('Canvas does not permit this discussion entry change')
    revision = _revision(current)
    if not delete and revision['attachment'] and not remove_attachment:
        raise CanvasError('Canvas text edits remove existing attachments. Use --remove-attachment '
                          'to acknowledge that loss, or edit this entry in Canvas instead.')
    if remove_attachment:
        body['remove_attachment'] = '1'
    preview = {**identity, f'{context_type}_id': context_id, 'context_type': context_type,
               'topic_id': topic_id, 'topic_title': topic.get('title'), 'entry_id': entry_id,
               'before': revision, 'revision_digest': digest(revision),
               'method': 'DELETE' if delete else 'PUT', 'route': base + f'/entries/{entry_id}',
               'body': body, 'removes_attachment': bool(revision['attachment']),
               'effect': 'Changes only this entry, not the topic. It can affect graded discussion participation.'}
    if delete:
        preview['expected_response'] = 'no_content'
    result = confirmed(client, preview, yes, confirm)
    if not yes:
        return result
    if delete:
        return {'entry_id': int(entry_id), 'context_type': context_type,
                f'{context_type}_id': int(context_id), 'topic_id': int(topic_id), 'deleted': True,
                'note': 'Canvas acknowledged entry deletion with HTTP 204. The topic was not deleted.'}
    if (not isinstance(result, dict) or type(result.get('id')) is not int or str(result['id']) != entry_id or
            type(result.get('user_id')) is not int or result['user_id'] != identity['user_id'] or
            result.get('deleted') or any(result.get(key) is not None and str(result[key]) != topic_id
                for key in ('topic_id', 'discussion_topic_id'))):
        raise CanvasError('Canvas returned an unexpected entry after the edit. Verify in Canvas '
                          'before repeating it; no automatic retries.')
    return {'entry': result, 'context_type': context_type, f'{context_type}_id': int(context_id),
            'topic_id': int(topic_id), 'note': 'Canvas returned the edited entry. No automatic retries.'}


def prepare(client, course_id, topic_id, reply_to, message, context_type='course'):
    message_html = _message(message)
    discussion_base(course_id, topic_id, context_type)
    identity = account(client)
    topic = read_topic(client, course_id, topic_id, context_type, require_entries=bool(reply_to))
    require_entry_api(topic)
    route = discussion_base(course_id, topic_id, context_type) + '/entries'
    if reply_to:
        target = _entry(client, discussion_base(course_id, topic_id, context_type), topic_id, reply_to, 100)
        if target.get('deleted') or target.get('workflow_state') == 'deleted':
            raise CanvasError('Cannot reply to a deleted discussion entry')
        route += f'/{reply_to}/replies'
    body = {'message': message_html}
    preview = {**identity, f'{context_type}_id': course_id, 'context_type': context_type, 'topic_id': topic_id,
               'topic_title': topic.get('title'), 'published': topic.get('published'),
               'locked': topic.get('locked'), 'lock_at': topic.get('lock_at'),
               'reply_to': reply_to, 'route': route, 'body': body}
    if reply_to:
        preview['reply_target'] = _revision(target)
    digest = hashlib.sha256(json.dumps(preview, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return preview, digest


def post(client, course_id, topic_id, reply_to, message, yes=False, confirm=None, context_type='course'):
    if bool(yes) != bool(confirm):
        raise CanvasError('Posting requires both --yes and --confirm from a prior preview')
    preview, digest = prepare(client, course_id, topic_id, reply_to, message, context_type)
    if not yes:
        return {'dry_run': True, **preview, 'confirm': digest,
                'next': 'Review topic, reply target and exact message, then repeat with --yes --confirm DIGEST.'}
    if confirm != digest:
        raise CanvasError('Preview changed (topic or message); review a fresh preview before posting')
    return client.request(preview['route'], 'POST', preview['body'])[0]
