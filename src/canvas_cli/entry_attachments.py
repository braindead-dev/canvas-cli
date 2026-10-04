"""Native entry/reply uploads: a post can be saved before its file is attached."""

from .client import CanvasError
from .contexts import discussion_base, read_topic, require_entry_api
from .discussion import _entry, _message
from .group_content import _context, _id, _number
from .multipart import MAX_BYTES, inspect_file
from .writes import account, check_flags, digest, review

WARNING = ('Posts a visible entry/reply with one native multipart attachment, not a private draft or a Files-ID '
           'association. Native entry create/attach rights, availability and initial-post restrictions govern '
           'access; shared prompt update/attach rights do not substitute. Student attachment settings can '
           'silently omit the file. Canvas can save the entry and its participation/graded-discussion effects '
           'before file storage succeeds; a failed upload may leave a posted entry without its file or an '
           'orphan file. Native user storage, submissions-folder placement and duplicate renaming apply. '
           'Only exact own entry/parent and attachment ID/size metadata are verified, not stored bytes, '
           'grade/submission credit, storage location, audience access or notifications. No initial-post bypass, '
           'bulk peer reads, quiz attempt, download, automatic retry, post deletion or orphan cleanup.')
UNCERTAIN = ('Could not verify the attached post. The entry may already be posted without its file, and '
             'the file may already exist. Check Canvas before repeating; no automatic retry, deletion, '
             'rollback, orphan cleanup or private response-body logging.')
TOPIC_FIELDS = ('id', 'title', 'published', 'locked', 'locked_for_user', 'lock_at', 'delayed_post_at',
                'require_initial_post', 'is_announcement', 'assignment_id', 'root_topic_id', 'group_category_id')


def _topic_state(row):
    require_entry_api(row)
    rights = row.get('permissions')
    if rights is not None and (not isinstance(rights, dict) or 'reply' in rights and type(rights['reply']) is not bool):
        raise CanvasError('Canvas returned malformed native reply permission metadata')
    if isinstance(rights, dict) and rights.get('reply') is False:
        raise CanvasError('Canvas denied posting replies on this exact topic')
    if not isinstance(row.get('message'), (str, type(None))):
        raise CanvasError('Canvas returned malformed discussion prompt metadata')
    if any(key in row and row[key] is not None and type(row[key]) is not bool for key in
           ('published', 'locked', 'locked_for_user', 'require_initial_post', 'user_can_see_posts', 'is_announcement')):
        raise CanvasError('Canvas returned malformed discussion availability metadata')
    return {**{key: row.get(key) for key in TOPIC_FIELDS}, 'prompt_digest': digest(row.get('message')),
            'reply_permission': rights.get('reply') if isinstance(rights, dict) else None}


def _context_state(client, item, context_type):
    _, row = _context(client, item, context_type)
    return {key: row.get(key) for key in ('id', 'name', 'workflow_state', 'concluded', 'non_collaborative')}


def _entry_state(row, topic_id, *, user_id=None, parent_id=None, attached=False):
    identifier = _id(row)
    if (type(row.get('user_id')) is not int or row['user_id'] < 1 or
            user_id is not None and row['user_id'] != user_id or row.get('deleted') or
            row.get('workflow_state') == 'deleted' or row.get('hidden_for_user') or row.get('locked_for_user') or
            not isinstance(row.get('message'), str) or
            any(row.get(key) is not None and (type(row[key]) is not int or row[key] != int(topic_id))
                for key in ('topic_id', 'discussion_topic_id'))):
        raise CanvasError('Canvas did not identify the exact active discussion entry and author')
    if attached and ('parent_id' not in row or row['parent_id'] != parent_id or
                     row['parent_id'] is not None and type(row['parent_id']) is not int):
        raise CanvasError('Canvas did not report the selected root or reply parent')
    attachment = row.get('attachment')
    if attached:
        _id(attachment)
        if (type(attachment.get('size')) is not int or attachment['size'] < 1 or
                not isinstance(attachment.get('filename'), str) or not attachment['filename'] or
                not isinstance(attachment.get('display_name'), str) or not attachment['display_name']):
            raise CanvasError('Canvas did not report complete native entry attachment metadata')
        attachment = {key: attachment.get(key) for key in ('id', 'filename', 'display_name', 'size', 'updated_at')}
    else:
        attachment = {'metadata_digest': digest(attachment)} if attachment is not None else None
    return {'id': identifier, 'user_id': row['user_id'], 'parent_id': row.get('parent_id'),
            'message_digest': digest(row['message']), 'created_at': row.get('created_at'),
            'updated_at': row.get('updated_at'), 'attachment': attachment}


def post(client, item, topic_id, reply_to, message, source, *, context_type='course', max_bytes=MAX_BYTES,
         acknowledge_upload=False, max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    base = discussion_base(item, topic_id, context_type)
    if acknowledge_upload is not True or type(max_pages) is not int or max_pages < 1:
        raise CanvasError('An attached post requires --acknowledge-attachment-upload and a positive page limit, including previews')
    if reply_to is not None:
        _number(reply_to)
    message_html = _message(message)
    try:
        valid_message = len(message_html.encode('utf-8')) <= 40000 and '\x00' not in message_html
    except UnicodeError:
        valid_message = False
    if not valid_message:
        raise CanvasError('Attached post text must be bounded UTF-8 without NUL characters')
    info, content = inspect_file(source, max_bytes)
    identity = account(client)
    context = _context_state(client, item, context_type)
    before = _topic_state(read_topic(client, item, topic_id, context_type, require_entries=reply_to is not None))
    parent = _entry_state(_entry(client, base, topic_id, reply_to, max_pages), topic_id) if reply_to is not None else None
    if (account(client) != identity or
            _context_state(client, item, context_type) != context or
            _topic_state(read_topic(client, item, topic_id, context_type, require_entries=reply_to is not None)) != before or
            reply_to is not None and _entry_state(_entry(client, base, topic_id, reply_to, max_pages), topic_id) != parent):
        raise CanvasError('Attached-post account/context/topic/parent changed during preflight')
    preview = {**identity, 'context_type': context_type, f'{context_type}_id': int(item), 'context': context,
               'topic_id': int(topic_id), 'topic': before, 'reply_parent': parent,
               'file': {key: value for key, value in info.items() if key != 'source'}, 'source_path_digest': digest(info['source']),
               'max_bytes': max_bytes, 'acknowledge_attachment_upload': True, 'method': 'POST',
               'route': base + (f'/entries/{reply_to}/replies' if reply_to is not None else '/entries'),
               'body': {'message': message_html}, 'encoding': 'multipart/form-data', 'warning': WARNING,
               'native_entry_attachment_permission_preverified': False}
    result = review(preview, yes, confirm)
    if result is not None:
        return result
    try:
        response, _ = client.multipart(preview['route'], 'POST', preview['body'], info['name'], info['content_type'], content)
        after = _entry_state(response, topic_id, user_id=identity['user_id'],
                             parent_id=int(reply_to) if reply_to is not None else None, attached=True)
        if parent is not None and after['id'] == parent['id']:
            raise CanvasError('Canvas returned the existing parent instead of a new reply')
        actual = _entry_state(_entry(client, base, topic_id, str(after['id']), max_pages), topic_id,
                              user_id=identity['user_id'], parent_id=after['parent_id'], attached=True)
        if (after != actual or after['attachment']['size'] != info['size'] or account(client) != identity or
                _context_state(client, item, context_type) != context or
                _topic_state(read_topic(client, item, topic_id, context_type, require_entries=True)) != before):
            raise CanvasError('Attached entry acknowledgement/readback, size, account or context did not agree')
    except CanvasError:
        raise CanvasError(UNCERTAIN) from None
    return {'attached_post': after, 'context_type': context_type, f'{context_type}_id': int(item), 'topic_id': int(topic_id),
            'entry_identity_and_parent_verified': True, 'attachment_id_and_size_verified': True,
            'new_id_historical_uniqueness_verified': False,
            'reported_html_matches_request': after['message_digest'] == digest(message_html), 'stored_bytes_verified': False,
            'native_entry_attachment_permission_preverified': False, 'grade_credit_verified': False,
            'storage_location_verified': False, 'notification_delivery_verified': False, 'note': WARNING}
