"""Own native discussion display preferences, not shared topic configuration."""

from .client import CanvasError
from .contexts import discussion_base
from .writes import account, check_flags, review

FIELDS = {'sort_order': 'sortOrder', 'expanded': 'expanded', 'show_pinned_entries': 'showPinnedEntries'}
_METADATA = '_id contextId contextType sortOrder sortOrderLocked expanded expandedLocked permissions { read }'
_PARTICIPANT = 'participant { sortOrder expanded showPinnedEntries }'
_SCOPE = '_id contextId contextType'
_READ = 'query CanvasTopicView($topicId: ID!) { legacyNode(type: Discussion, _id: $topicId) { ... on Discussion { %s } } }'
_SET = ('mutation CanvasTopicViewSet($input: UpdateDiscussionTopicParticipantInput!) { '
        'updateDiscussionTopicParticipant(input: $input) { errors { attribute } discussionTopic { %s } } }') % _SCOPE
_NOTE = ('Native preference queries can initialize your own participant record, default subscription/unread counters '
         'and planner cache. The CLI does not request reply content, assessments or explicit read/subscription changes. '
         'Sort/expansion readback is effective display only: locks can mask overrides and matching defaults do not '
         'prove a saved override was cleared. Pinned-entry preference is a direct stored field, not UI visibility proof. '
         'No automatic retries or rollback.')


def _scope(row, context_id, topic_id, context_type):
    if (not isinstance(row, dict) or row.get('_id') != topic_id or row.get('contextId') != context_id or
            row.get('contextType') != context_type.title()):
        raise CanvasError('Canvas returned a different discussion or context; no private response was logged')


def _state(row, context_id, topic_id, context_type, *, participant=False):
    _scope(row, context_id, topic_id, context_type)
    if not isinstance(row.get('permissions'), dict) or row['permissions'].get('read') is not True:
        raise CanvasError('Canvas did not report native read permission for this discussion')
    if row.get('sortOrder') not in ('asc', 'desc'):
        raise CanvasError('Canvas returned unavailable discussion sort metadata')
    for key in ('sortOrderLocked', 'expanded', 'expandedLocked'):
        if key not in row or row[key] is not None and type(row[key]) is not bool:
            raise CanvasError('Canvas returned malformed discussion view metadata')
    shared = {'sort_order': row['sortOrder'], 'sort_order_locked': row['sortOrderLocked'],
              'expanded': row['expanded'], 'expanded_locked': row['expandedLocked']}
    result = {'shared': shared}
    if participant:
        own = row.get('participant')
        if not isinstance(own, dict) or own.get('sortOrder') not in ('asc', 'desc'):
            raise CanvasError('Canvas did not return your own effective discussion preferences')
        for key in ('expanded', 'showPinnedEntries'):
            if key not in own or own[key] is not None and type(own[key]) is not bool:
                raise CanvasError('Canvas returned malformed own discussion preferences')
        result['reported'] = {key: own[value] for key, value in FIELDS.items()}
        for key in ('sort_order', 'expanded'):
            if shared[key + '_locked'] is True and result['reported'][key] != shared[key]:
                raise CanvasError('Canvas returned inconsistent locked discussion display metadata')
    return result


def _query(client, context_id, topic_id, context_type, *, participant=False):
    document = _READ % (_METADATA + (' ' + _PARTICIPANT if participant else ''))
    data = client.graphql(document, {'topicId': topic_id}, 'CanvasTopicView')
    return _state(data.get('legacyNode'), context_id, topic_id, context_type, participant=participant)


def _read(client, context_id, topic_id, context_type, acknowledge):
    discussion_base(context_id, topic_id, context_type)
    if not acknowledge:
        raise CanvasError('Use --acknowledge-participant-initialization: native queries can create your own participant record')
    identity = account(client)
    metadata = _query(client, context_id, topic_id, context_type)
    state = _query(client, context_id, topic_id, context_type, participant=True)
    if state['shared'] != metadata['shared'] or account(client) != identity:
        raise CanvasError('Account or discussion defaults changed during the query. A participant record may have '
                          'been initialized; no preference mutation was sent. Review again.')
    return {**identity, 'context_type': context_type, 'context_id': context_id, 'topic_id': topic_id, **state}


def read(client, context_id, topic_id, *, context_type='course', acknowledge=False):
    return {'topic_view': _read(client, context_id, topic_id, context_type, acknowledge),
            'native_query_may_initialize_participant': True, 'note': _NOTE}


def _options(values):
    if not isinstance(values, dict) or not values or set(values) - FIELDS.keys():
        raise CanvasError('Select at least one supported personal discussion view option')
    for key, value in values.items():
        if key == 'sort_order':
            if value is not None and (not isinstance(value, str) or value not in ('asc', 'desc')):
                raise CanvasError('Personal sort must be asc, desc or explicit inheritance')
        elif value is not None and type(value) is not bool:
            raise CanvasError('Personal display options must be explicit booleans or inheritance')
    return {FIELDS[key]: value for key, value in values.items()}


def change(client, context_id, topic_id, values, *, context_type='course', acknowledge=False, yes=False, confirm=None):
    check_flags(yes, confirm)
    options = _options(values)
    before = _read(client, context_id, topic_id, context_type, acknowledge)
    variables = {'input': {'discussionTopicId': topic_id, **options}}
    preview = {**before, 'requested': values, 'method': 'POST', 'route': '/api/graphql',
               'body': {'query': _SET, 'variables': variables, 'operationName': 'CanvasTopicViewSet'},
               'native_query_may_initialize_participant': True, 'effect': _NOTE}
    result = review(preview, yes, confirm)
    if result is not None:
        return result
    data = client.graphql(_SET, variables, 'CanvasTopicViewSet')
    ack = data.get('updateDiscussionTopicParticipant')
    if not isinstance(ack, dict) or 'errors' not in ack or ack['errors'] not in (None, []):
        raise CanvasError('Canvas did not acknowledge the preference mutation without errors. It may have applied; '
                          'check Canvas before repeating. No automatic retries.')
    try:
        _scope(ack.get('discussionTopic'), context_id, topic_id, context_type)
        after = _query(client, context_id, topic_id, context_type, participant=True)
        identity_after = account(client)
    except CanvasError:
        raise CanvasError('The preference mutation outcome could not be independently verified; no private response '
                          'was logged. Check Canvas before repeating. No automatic retries.') from None
    if identity_after != {key: before[key] for key in ('origin', 'user_id')} or after['shared'] != before['shared']:
        raise CanvasError('Account or shared discussion defaults changed after the mutation; the outcome is unverified. '
                          'Check Canvas before repeating. No automatic retries.')
    masked = []
    verified = {}
    for key, value in values.items():
        locked = key != 'show_pinned_entries' and after['shared'][key + '_locked'] is True
        expected = after['shared'][key] if locked or value is None and key != 'show_pinned_entries' else value
        if after['reported'][key] != expected:
            raise CanvasError('Canvas did not independently read back the requested reported preference. '
                              'Some changes may have applied; check Canvas before repeating. No automatic retries.')
        if locked:
            masked.append(key)
        verified[key] = {'effective_value_verified': key != 'show_pinned_entries',
                         'stored_override_verified': key == 'show_pinned_entries'}
    return {'topic_view': {**before, **after}, 'requested': values, 'mutation_acknowledged': True,
            'verification': verified, 'masked_by_shared_locks': masked,
            'observed_changed_fields': sorted(key for key in FIELDS if before['reported'][key] != after['reported'][key]),
            'native_query_may_initialize_participant': True, 'note': _NOTE}
