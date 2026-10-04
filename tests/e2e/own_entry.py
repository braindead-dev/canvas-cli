"""Independent modern ownership queries and native quote/file-preserving edits."""

import copy

from .appointments import _send

SCOPE = ('_id discussionTopicId parentId deleted createdAt updatedAt author { _id } '
         'anonymousAuthor { id shortName } permissions { read update attach } '
         'discussionTopic { _id contextId contextType anonymousState permissions { read } }')
FIELDS = SCOPE + ' message quotedEntry { _id } attachment { _id displayName sizeBytes updatedAt }'
DOCUMENTS = {
    'CanvasOwnEntryOwner': ('query CanvasOwnEntryOwner($entryId: ID!) { legacyNode(type: DiscussionEntry, _id: $entryId) '
                            '{ ... on DiscussionEntry { ' + SCOPE + ' } } }'),
    'CanvasOwnEntryDetails': ('query CanvasOwnEntryDetails($entryId: ID!) { legacyNode(type: DiscussionEntry, _id: $entryId) '
                              '{ ... on DiscussionEntry { ' + FIELDS + ' } } }'),
    'CanvasOwnEntryEdit': ('mutation CanvasOwnEntryEdit($input: UpdateDiscussionEntryInput!) { updateDiscussionEntry(input: $input) '
                           '{ errors { attribute } discussionEntry { ' + FIELDS + ' } } }'),
}


def initialize(state):
    state.own_entry_enabled = False
    state.own_entry_viewer = 7
    state.own_entry_context = {'id': 123, 'name': 'Synthetic own entry context'}
    state.own_entry_row = {'_id': '301', 'discussionTopicId': '9', 'parentId': '300', 'deleted': False,
                           'createdAt': '2026-10-04T12:00:00Z', 'updatedAt': '2026-10-04T12:00:00Z',
                           'author': {'_id': '7'}, 'anonymousAuthor': None,
                           'permissions': {'read': True, 'update': True, 'attach': False},
                           'discussionTopic': {'_id': '9', 'contextId': '123', 'contextType': 'Course',
                                               'anonymousState': None, 'permissions': {'read': True}},
                           'message': '<p>synthetic-private-old-body</p>', 'quotedEntry': {'_id': '302'},
                           'attachment': {'_id': '61', 'displayName': 'Synthetic file', 'sizeBytes': 4, 'updatedAt': None}}
    state.own_entry_queries, state.own_entry_mutations = [], []
    state.own_entry_written = False
    state.own_entry_mode = None
    state.own_entry_ack_patch = state.own_entry_read_patch = None


def read(state, handler):
    if not state.own_entry_enabled:
        return False
    if handler.path == '/api/v1/users/self/profile':
        _send(handler, {'id': state.own_entry_viewer})
    elif handler.path in ('/api/v1/courses/123', '/api/v1/groups/123'):
        _send(handler, state.own_entry_context)
    else:
        return False
    return True


def execute(state, handler, body):
    if not state.own_entry_enabled or handler.path != '/api/graphql':
        return False
    name = body.get('operationName')
    variables = body.get('variables')
    if name not in DOCUMENTS or body.get('query') != DOCUMENTS[name] or not isinstance(variables, dict):
        _send(handler, {'errors': [{'message': 'synthetic-private-wrong-own-entry-operation'}]}, 400)
        return True
    row = state.own_entry_row
    if name != 'CanvasOwnEntryEdit':
        state.own_entry_queries.append(name)
        if variables != {'entryId': '301'}:
            _send(handler, {'errors': [{'message': 'synthetic-private-wrong-entry-id'}]})
            return True
        if state.own_entry_written and state.own_entry_mode == 'denied-readback':
            _send(handler, {'errors': [{'message': 'synthetic-private-readback-denial'}]})
            return True
        result = copy.deepcopy(row)
        if name == 'CanvasOwnEntryOwner':
            for key in ('message', 'quotedEntry', 'attachment'):
                result.pop(key)
        elif state.own_entry_written and state.own_entry_read_patch:
            result.update(state.own_entry_read_patch)
        _send(handler, {'data': {'legacyNode': result}})
        return True
    supplied = variables.get('input')
    if (not isinstance(supplied, dict) or supplied.get('discussionEntryId') != '301' or
            not isinstance(supplied.get('message'), str) or set(supplied) - {'discussionEntryId', 'message', 'quotedEntryId'}):
        _send(handler, {'errors': [{'message': 'synthetic-private-invalid-edit-input'}]}, 400)
        return True
    state.own_entry_mutations.append(copy.deepcopy(supplied))
    if row['permissions']['update'] is not True:
        _send(handler, {'data': {'updateDiscussionEntry': {'errors': [{'attribute': 'permission'}], 'discussionEntry': None}}})
        return True
    state.own_entry_written = True
    if state.own_entry_mode != 'ignored':
        row['message'] = supplied['message']
        row['updatedAt'] = '2026-10-04T13:00:00Z'
        if row['parentId'] is not None:
            quoted = supplied.get('quotedEntryId')
            row['quotedEntry'] = {'_id': quoted} if quoted is not None else None
    if state.own_entry_mode == 'clear-file':
        row['attachment'] = None
    elif state.own_entry_mode == 'clear-quote':
        row['quotedEntry'] = None
    elif state.own_entry_mode == 'error-after-save':
        _send(handler, {'errors': [{'message': 'synthetic-private-error-after-save'}]})
        return True
    result = copy.deepcopy(row)
    if state.own_entry_ack_patch is not None:
        result.update(state.own_entry_ack_patch)
    _send(handler, {'data': {'updateDiscussionEntry': {'errors': [], 'discussionEntry': result}}})
    return True
