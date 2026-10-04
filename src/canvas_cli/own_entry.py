"""Modern own-entry inspection; establish ownership before requesting body/files."""

import re

from .client import CanvasError
from .contexts import discussion_base
from .discussion import _message
from .group_content import _context, _number
from .snapshot import redact
from .writes import account, check_flags, digest, review

_SCOPE = ('_id discussionTopicId parentId deleted createdAt updatedAt author { _id } '
          'anonymousAuthor { id shortName } permissions { read update attach } '
          'discussionTopic { _id contextId contextType anonymousState permissions { read } }')
_OWNER = ('query CanvasOwnEntryOwner($entryId: ID!) { legacyNode(type: DiscussionEntry, _id: $entryId) '
          '{ ... on DiscussionEntry { ' + _SCOPE + ' } } }')
_DETAIL_FIELDS = _SCOPE + ' message quotedEntry { _id } attachment { _id displayName sizeBytes updatedAt }'
_DETAIL = ('query CanvasOwnEntryDetails($entryId: ID!) { legacyNode(type: DiscussionEntry, _id: $entryId) '
           '{ ... on DiscussionEntry { ' + _DETAIL_FIELDS + ' } } }')
_EDIT = ('mutation CanvasOwnEntryEdit($input: UpdateDiscussionEntryInput!) { updateDiscussionEntry(input: $input) '
         '{ errors { attribute } discussionEntry { ' + _DETAIL_FIELDS + ' } } }')
_HISTORY = ('query CanvasOwnEntryHistory($entryId: ID!, $includeContent: Boolean!) '
            '{ legacyNode(type: DiscussionEntry, _id: $entryId) { ... on DiscussionEntry { ' + _SCOPE +
            ' discussionEntryVersions { _id version createdAt updatedAt message @include(if: $includeContent) } } } }')
_NOTE = ('Exact own entry only. Ownership/scope metadata is verified before body or attachment metadata is requested. '
         'Anonymous ownership uses the native current_user marker, never a participant-ID to user-ID guess. '
         'No peer inventory, quoted body, participant initialization, read marker, file URL/download, '
         'submission/checkpoint, assessment or mutation is requested. Content is a native rendered representation, '
         'not raw-storage proof; hidden quoted associations, file bytes/storage and grade credit remain unverified.')
_EDIT_NOTE = ('Updates only your exact entry text through native GraphQL, leaving fileId/removeAttachment omitted '
              'to retain the existing file association. The visible quoted-entry ID is retained for replies; '
              'hidden/dangling quote storage remains unverified. Native read/update rights govern access, not '
              'shared-prompt or attach rights. A save can affect participation, graded discussion credit, editor '
              'history and notifications; none of those effects are proven. Rendered text/file association and '
              'visible quote readback are verified, not raw storage, file bytes/access or delivery. '
              'Preflight is not an atomic lock. No file upload/download, pin change, peer-body read, quiz attempt, '
              'automatic retry, rollback, deletion or cleanup.')
_HISTORY_NOTE = ('Own-entry version metadata only unless content is explicitly selected. Canvas exposes this '
                 'association as an unpaginated list; the local version cap cannot limit server-side loading. '
                 'Only the reported list is checked; gaps, an empty list or the latest version do not prove a '
                 'complete archive or exact storage. Native timestamps may be inferred for legacy versions. '
                 'No editor identities, peer history, restore, read marker, participant initialization, '
                 'assessment or mutation is requested.')


def _scope(row, identity, item, topic_id, entry_id, context_type):
    if not isinstance(row, dict) or row.get('_id') != entry_id or row.get('discussionTopicId') != topic_id:
        raise CanvasError('Canvas returned a different modern discussion entry')
    topic = row.get('discussionTopic')
    if (not isinstance(topic, dict) or topic.get('_id') != topic_id or topic.get('contextId') != item or
            topic.get('contextType') != context_type.title() or not isinstance(topic.get('permissions'), dict) or
            topic['permissions'].get('read') is not True or 'anonymousState' not in topic or
            topic['anonymousState'] not in (None, 'off', 'partial_anonymity', 'full_anonymity')):
        raise CanvasError('Canvas returned unavailable or foreign modern discussion context')
    rights = row.get('permissions')
    if (not isinstance(rights, dict) or rights.get('read') is not True or
            any(key not in rights or rights[key] is not None and type(rights[key]) is not bool for key in ('update', 'attach')) or
            row.get('deleted') is not False or 'parentId' not in row):
        raise CanvasError('Canvas did not expose the active modern entry and native rights')
    parent = row['parentId']
    if parent is not None:
        _number(parent)
    for key in ('createdAt', 'updatedAt'):
        if key not in row or row[key] is not None and not isinstance(row[key], str):
            raise CanvasError('Canvas returned unavailable modern entry timestamps')
    author, anonymous = row.get('author'), row.get('anonymousAuthor')
    if isinstance(author, dict) and author.get('_id') == str(identity['user_id']):
        proof = 'native_author_id'
    elif (author is None and topic['anonymousState'] in ('partial_anonymity', 'full_anonymity') and
          isinstance(anonymous, dict) and anonymous.get('shortName') == 'current_user' and
          isinstance(anonymous.get('id'), str) and re.fullmatch(r'[0-9a-z]{1,128}', anonymous['id'])):
        proof = 'native_current_user_anonymous_marker'
    else:
        raise CanvasError('Modern entry inspection is restricted to the signed-in author')
    return {'id': int(entry_id), 'topic_id': int(topic_id), 'parent_id': int(parent) if parent is not None else None,
            'ownership_proof': proof, 'anonymous_state': topic['anonymousState'],
            'permissions': {key: rights[key] for key in ('read', 'update', 'attach')},
            'created_at': row['createdAt'], 'updated_at': row['updatedAt']}


def _details(row):
    if not isinstance(row.get('message'), str) or 'attachment' not in row or 'quotedEntry' not in row:
        raise CanvasError('Canvas omitted selected own-entry content associations')
    attachment = row['attachment']
    if attachment is not None:
        if not isinstance(attachment, dict):
            raise CanvasError('Canvas returned malformed own-entry attachment metadata')
        identifier = _number(attachment.get('_id'))
        if (not isinstance(attachment.get('displayName'), str) or not attachment['displayName'] or
                type(attachment.get('sizeBytes')) is not int or attachment['sizeBytes'] < 0 or
                'updatedAt' not in attachment or attachment['updatedAt'] is not None and
                not isinstance(attachment['updatedAt'], str)):
            raise CanvasError('Canvas returned incomplete own-entry file metadata')
        attachment = {'id': int(identifier), 'display_name': attachment['displayName'],
                      'size_bytes': attachment['sizeBytes'], 'updated_at': attachment['updatedAt']}
    quote = row['quotedEntry']
    if quote is not None:
        if not isinstance(quote, dict):
            raise CanvasError('Canvas returned malformed quoted-entry association')
        quote = int(_number(quote.get('_id')))
    return {'message': row['message'], 'attachment': attachment, 'quoted_entry_id': quote}


def inspect(client, item, topic_id, entry_id, *, context_type='course'):
    discussion_base(item, topic_id, context_type)
    for selected in (item, topic_id, entry_id):
        _number(selected)
    identity = account(client)
    _, context = _context(client, item, context_type)
    owner = client.graphql(_OWNER, {'entryId': entry_id}, 'CanvasOwnEntryOwner').get('legacyNode')
    before = _scope(owner, identity, item, topic_id, entry_id, context_type)
    detail = client.graphql(_DETAIL, {'entryId': entry_id}, 'CanvasOwnEntryDetails').get('legacyNode')
    if _scope(detail, identity, item, topic_id, entry_id, context_type) != before or account(client) != identity:
        raise CanvasError('Own entry or signed-in account changed during inspection')
    _, after_context = _context(client, item, context_type)
    if {key: context.get(key) for key in ('id', 'name', 'workflow_state')} != {
            key: after_context.get(key) for key in ('id', 'name', 'workflow_state')}:
        raise CanvasError('Own-entry context changed during inspection')
    return {**identity, 'context_type': context_type, f'{context_type}_id': int(item),
            'context': {key: context.get(key) for key in ('id', 'name', 'workflow_state')}, **before, **_details(detail)}


def read(client, item, topic_id, entry_id, *, context_type='course', include_content=False):
    if type(include_content) is not bool:
        raise CanvasError('Select own rendered content with an explicit boolean')
    row = inspect(client, item, topic_id, entry_id, context_type=context_type)
    message = row.pop('message')
    row['rendered_message_digest'] = digest(message)
    if include_content:
        row['rendered_message'] = redact(message)
    return {'own_entry': row, 'raw_storage_verified': False, 'stored_file_bytes_verified': False,
            'hidden_quote_storage_verified': False, 'grade_credit_verified': False, 'note': _NOTE}


def history(client, item, topic_id, entry_id, *, context_type='course', include_content=False, max_versions=100):
    if type(include_content) is not bool or type(max_versions) is not int or not 1 <= max_versions <= 1000:
        raise CanvasError('Select content explicitly and a local version cap between 1 and 1000')
    before = inspect(client, item, topic_id, entry_id, context_type=context_type)
    node = client.graphql(_HISTORY, {'entryId': entry_id, 'includeContent': include_content},
                          'CanvasOwnEntryHistory').get('legacyNode')
    scope = _scope(node, before, item, topic_id, entry_id, context_type)
    if any(before[key] != value for key, value in scope.items()):
        raise CanvasError('Own entry changed during history inspection')
    rows = node.get('discussionEntryVersions')
    if not isinstance(rows, list) or len(rows) > max_versions:
        raise CanvasError('Canvas returned unavailable history or exceeded the local version cap')
    versions, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise CanvasError('Canvas returned malformed own-entry version metadata')
        identifier = int(_number(row.get('_id')))
        if (identifier in seen or type(row.get('version')) is not int or row['version'] < 1 or
                any(key not in row or row[key] is not None and not isinstance(row[key], str)
                    for key in ('createdAt', 'updatedAt')) or include_content and not isinstance(row.get('message'), str)):
            raise CanvasError('Canvas returned ambiguous or incomplete own-entry version metadata')
        seen.add(identifier)
        result = {'id': identifier, 'version': row['version'], 'created_at': row['createdAt'], 'updated_at': row['updatedAt']}
        if include_content:
            result['message'] = redact(row['message'])
        versions.append(result)
    if inspect(client, item, topic_id, entry_id, context_type=context_type) != before:
        raise CanvasError('Own entry, account or context changed during history inspection')
    selected = {key: before[key] for key in ('origin', 'user_id', 'context_type', f'{context_type}_id', 'context',
                                             'id', 'topic_id', 'ownership_proof')}
    return {'own_entry_history': {**selected, 'versions': sorted(versions, key=lambda row: (row['version'], row['id']), reverse=True)},
            'native_unpaginated': True, 'complete_history_verified': False, 'raw_storage_verified': False, 'note': _HISTORY_NOTE}


def edit(client, item, topic_id, entry_id, message, *, context_type='course', yes=False, confirm=None):
    check_flags(yes, confirm)
    body = _message(message)
    try:
        valid = len(body.encode('utf-8')) <= 40000 and '\x00' not in body
    except UnicodeError:
        valid = False
    if not valid:
        raise CanvasError('Entry text must be bounded UTF-8 without NUL characters')
    before = inspect(client, item, topic_id, entry_id, context_type=context_type)
    if before['permissions']['update'] is not True:
        raise CanvasError('Canvas did not grant native update rights for your exact entry')
    native_input = {'discussionEntryId': entry_id, 'message': body}
    if before['parent_id'] is not None:
        native_input['quotedEntryId'] = str(before['quoted_entry_id']) if before['quoted_entry_id'] is not None else None
    state = {key: value for key, value in before.items() if key != 'message'}
    preview = {**state, 'rendered_message_digest': digest(before['message']), 'method': 'POST', 'route': '/api/graphql',
               'operation': 'CanvasOwnEntryEdit', 'input': native_input, 'preserve_attachment': True, 'warning': _EDIT_NOTE}
    result = review(preview, yes, confirm)
    if result is not None:
        return result
    try:
        data = client.graphql(_EDIT, {'input': native_input}, 'CanvasOwnEntryEdit').get('updateDiscussionEntry')
        if not isinstance(data, dict) or data.get('errors') not in (None, []):
            raise CanvasError('Canvas did not acknowledge the native entry edit')
        response = data.get('discussionEntry')
        acknowledged = {**{key: before[key] for key in ('origin', 'user_id', 'context_type', f'{context_type}_id', 'context')},
                        **_scope(response, before, item, topic_id, entry_id, context_type), **_details(response)}
        actual = inspect(client, item, topic_id, entry_id, context_type=context_type)
        stable = ('origin', 'user_id', 'context_type', f'{context_type}_id', 'context', 'id', 'topic_id', 'parent_id',
                  'ownership_proof', 'anonymous_state', 'created_at', 'attachment', 'quoted_entry_id')
        if (acknowledged != actual or any(actual[key] != before[key] for key in stable) or
                actual['message'] != body):
            raise CanvasError('Native entry text, file/quote association or scope did not agree with readback')
    except CanvasError:
        raise CanvasError('Entry edit outcome is unverified and may have applied. Check Canvas before repeating; '
                          'no automatic retry, rollback or private response-body logging.') from None
    return {'own_entry': {key: value for key, value in actual.items() if key != 'message'},
            'rendered_text_verified': True, 'attachment_association_verified': True, 'visible_quote_association_verified': True,
            'raw_storage_verified': False, 'stored_file_bytes_verified': False, 'hidden_quote_storage_verified': False,
            'grade_credit_verified': False, 'notification_delivery_verified': False, 'note': _EDIT_NOTE}
