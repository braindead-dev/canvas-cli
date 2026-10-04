"""Independent native GraphQL participant state, including query-side initialization."""

import copy

from .appointments import _send


def initialize(state, *, enabled=False):
    state.topic_view_enabled = enabled
    state.view_topic = {'_id': '931', 'contextId': '131', 'contextType': 'Course', 'sortOrder': 'desc',
                        'sortOrderLocked': False, 'expanded': False, 'expandedLocked': False,
                        'permissions': {'read': True, 'update': False},
                        'private': 'synthetic-private-prompt-and-audience'}
    state.view_own = None
    state.view_viewer = 7
    state.view_author = 8
    state.view_initialized = state.view_written = False
    state.view_mutations = []
    state.view_ignored = set()
    state.view_ack = state.view_readback_patch = None
    state.view_shared_after = state.view_account_after = False
    state.view_query_count = 0
    state.view_query_error = state.view_write_error = state.view_post_error = None
    state.view_query_patch = None
    state.view_language_type = {'name': 'PreferredLanguageType', 'kind': 'ENUM',
                               'enumValues': [{'name': name, 'isDeprecated': False} for name in ('EN', 'FR', 'PT_BR')]}
    state.view_language_error = None
    state.view_generation_requests = []


def read(state, handler):
    if _generation(state, handler):
        return True
    if state.topic_view_enabled and handler.path == '/api/v1/users/self/profile':
        _send(handler, {'id': 8 if state.view_written and state.view_account_after else state.view_viewer,
                        'email': 'synthetic-private@example.edu'})
        return True
    return False


def _participant(state):
    if state.view_own is None:
        state.view_initialized = True
        state.view_own = {'sortOrder': 'inherit', 'expanded': None, 'showPinnedEntries': True,
                          'read': False, 'subscribed': state.view_author == state.view_viewer,
                          'unreadCount': 2, 'hasUnreadPinnedEntry': True, 'summaryEnabled': False,
                          'preferredLanguage': None, 'plannerCacheCleared': True}
    return state.view_own


def _effective(state):
    own = _participant(state)
    values = {}
    for key in ('sortOrder', 'expanded'):
        values[key] = state.view_topic[key] if state.view_topic[key + 'Locked'] or own[key] in (None, 'inherit') else own[key]
    values['showPinnedEntries'] = own['showPinnedEntries']
    return values


def _generation(state, handler):
    if state.topic_view_enabled and handler.path.endswith(('/summaries', '/translate')):
        state.view_generation_requests.append(handler.path)
        _send(handler, {'private': 'synthetic-private-no-service-access'}, 403)
        return True
    return False


def execute(state, handler, body):
    if not state.topic_view_enabled:
        return False
    if _generation(state, handler):
        return True
    if handler.path != '/api/graphql':
        return False
    document, variables, name = body.get('query'), body.get('variables'), body.get('operationName')
    if handler.command != 'POST' or not isinstance(document, str) or not isinstance(variables, dict):
        _send(handler, {'errors': [{'message': 'synthetic-private-invalid-request'}]}, 400)
        return True
    if name == 'CanvasDiscussionLanguages':
        if (variables != {} or document != 'query CanvasDiscussionLanguages { __type(name: "PreferredLanguageType") { '
                'name kind enumValues(includeDeprecated: true) { name isDeprecated } } }'):
            _send(handler, {'errors': [{'message': 'synthetic-private-unsupported-catalogue'}]})
            return True
        if state.view_language_error:
            status = state.view_language_error if isinstance(state.view_language_error, int) else 200
            _send(handler, {'data': {'__type': state.view_language_type},
                            'errors': [{'message': 'synthetic-private-schema-denial'}]}, status)
        else:
            _send(handler, {'data': {'__type': state.view_language_type}})
        return True
    if name == 'CanvasTopicView':
        state.view_query_count += 1
        if state.view_query_error or state.view_written and state.view_post_error:
            mode = state.view_query_error or state.view_post_error
            if isinstance(mode, int):
                _send(handler, {'private': 'synthetic-private-query-error'}, mode)
            else:
                _send(handler, {'data': {'legacyNode': state.view_topic}, 'errors': [{'message': 'synthetic-private-query-error'}]})
            return True
        if (variables != {'topicId': '931'} or 'query CanvasTopicView($topicId: ID!)' not in document or
                'legacyNode(type: Discussion, _id: $topicId)' not in document or
                any(key in document for key in ('discussionEntries', 'author', 'message', 'subscribed', 'posted', 'readStatus'))):
            _send(handler, {'errors': [{'message': 'synthetic-private-unsupported-query'}]})
            return True
        row = {key: copy.deepcopy(value) for key, value in state.view_topic.items() if key != 'private'}
        if 'participant {' in document:
            row['participant'] = _effective(state)
            for key in ('preferredLanguage', 'summaryEnabled'):
                if key in document:
                    value = state.view_own[key]
                    if key == 'preferredLanguage' and value not in {item['name'] for item in state.view_language_type['enumValues']}:
                        value = None
                    row['participant'][key] = value
        if state.view_query_patch:
            row.update(state.view_query_patch)
        if state.view_written and state.view_readback_patch:
            row.update(state.view_readback_patch)
        _send(handler, {'data': {'legacyNode': row}})
        return True
    if name != 'CanvasTopicViewSet' or 'mutation CanvasTopicViewSet($input: UpdateDiscussionTopicParticipantInput!)' not in document:
        _send(handler, {'errors': [{'message': 'synthetic-private-unsupported-operation'}]})
        return True
    selected = variables.get('input')
    if (not isinstance(selected, dict) or selected.get('discussionTopicId') != '931' or
            set(selected) - {'discussionTopicId', 'sortOrder', 'expanded', 'showPinnedEntries', 'preferredLanguage', 'summaryEnabled'} or
            'participant {' in document):
        _send(handler, {'errors': [{'message': 'synthetic-private-unsupported-mutation'}]})
        return True
    state.view_mutations.append(copy.deepcopy(selected))
    # Native storage constraints, unlike the nullable GraphQL input declaration.
    if any(key in selected and selected[key] is None for key in ('sortOrder', 'showPinnedEntries', 'summaryEnabled')):
        _send(handler, {'errors': [{'message': 'synthetic-private-native-not-null-violation'}]})
        return True
    if ('sortOrder' in selected and selected['sortOrder'] not in ('asc', 'desc') or
            any(key in selected and type(selected[key]) is not bool for key in ('showPinnedEntries', 'summaryEnabled')) or
            'expanded' in selected and selected['expanded'] is not None and type(selected['expanded']) is not bool or
            'preferredLanguage' in selected and selected['preferredLanguage'] is not None and
            selected['preferredLanguage'] not in {item['name'] for item in state.view_language_type['enumValues']}):
        _send(handler, {'errors': [{'message': 'synthetic-private-invalid-native-input'}]})
        return True
    if not state.view_topic['permissions']['read'] or state.view_write_error:
        _send(handler, {'errors': [{'message': 'synthetic-private-permission-denial'}]}, state.view_write_error or 200)
        return True
    own = _participant(state)
    for key, value in selected.items():
        if key != 'discussionTopicId' and key not in state.view_ignored:
            own[key] = value
    state.view_written = True
    if state.view_shared_after:
        state.view_topic['sortOrderLocked'] = not state.view_topic['sortOrderLocked']
    if state.view_ack == 'error_after_apply':
        _send(handler, {'errors': [{'message': 'synthetic-private-post-apply-error'}]})
        return True
    ack = {'errors': None, 'discussionTopic': {key: state.view_topic[key] for key in ('_id', 'contextId', 'contextType')}}
    if state.view_ack is not None:
        ack = state.view_ack
    _send(handler, {'data': {'updateDiscussionTopicParticipant': ack}})
    return True
