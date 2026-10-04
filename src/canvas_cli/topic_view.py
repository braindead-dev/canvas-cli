"""Own native discussion display preferences, not shared topic configuration."""

import re

from .client import CanvasError
from .contexts import discussion_base
from .writes import account, check_flags, review

FIELDS = {'sort_order': 'sortOrder', 'expanded': 'expanded', 'show_pinned_entries': 'showPinnedEntries',
          'preferred_language': 'preferredLanguage', 'summary_enabled': 'summaryEnabled',
          'has_unread_pinned_entry': 'hasUnreadPinnedEntry'}
BASE_FIELDS = ('sort_order', 'expanded', 'show_pinned_entries')
ASSIST_FIELDS = ('preferred_language', 'summary_enabled')
MARKER_FIELDS = ('has_unread_pinned_entry',)
EFFECTIVE_FIELDS = ('sort_order', 'expanded')
_ENUM_NAME = re.compile(r'[_A-Za-z][_0-9A-Za-z]*')
_METADATA = '_id contextId contextType sortOrder sortOrderLocked expanded expandedLocked permissions { read }'
_LANGUAGES = ('query CanvasDiscussionLanguages { __type(name: "PreferredLanguageType") { '
              'name kind enumValues(includeDeprecated: true) { name isDeprecated } } }')
_SCOPE = '_id contextId contextType'
_READ = 'query CanvasTopicView($topicId: ID!) { legacyNode(type: Discussion, _id: $topicId) { ... on Discussion { %s } } }'
_SET = ('mutation CanvasTopicViewSet($input: UpdateDiscussionTopicParticipantInput!) { '
        'updateDiscussionTopicParticipant(input: $input) { errors { attribute } discussionTopic { %s } } }') % _SCOPE
_NOTE = ('Native preference queries can initialize your own participant record, default subscription/unread counters '
         'and planner cache. The CLI does not request reply content, assessments, entry/topic read-state or subscription changes. '
         'The optional pinned-unread flag is your own indicator only, not proof any reply was read or seen. '
         'Sort/expansion readback is effective display only: locks can mask overrides and matching defaults do not '
         'prove a saved override was cleared. Pinned-entry preference is a direct stored field, not UI visibility proof. '
         'Optional language/summary preferences are stored fields, not translation/summary access or generation proof. '
         'A null language readback can mask an unsupported saved locale; clearing its raw storage stays unverified. '
         'The CLI does not request either service or send discussion content to them. '
         'No automatic retries or rollback.')


def languages(client):
    data = client.graphql(_LANGUAGES, {}, 'CanvasDiscussionLanguages')
    row = data.get('__type')
    if (not isinstance(row, dict) or row.get('name') != 'PreferredLanguageType' or row.get('kind') != 'ENUM' or
            not isinstance(row.get('enumValues'), list) or not row['enumValues']):
        raise CanvasError('Canvas did not expose the native preferred-language enum. No fallback language list was guessed.')
    values = {}
    for item in row['enumValues']:
        if (not isinstance(item, dict) or not isinstance(item.get('name'), str) or
                not _ENUM_NAME.fullmatch(item['name']) or type(item.get('isDeprecated')) is not bool or
                item['name'] in values):
            raise CanvasError('Canvas returned malformed or duplicate language enum metadata; no private response was logged')
        values[item['name']] = {'enum': item['name'], 'deprecated': item['isDeprecated']}
    return {'discussion_languages': {'origin': client.host, 'values': [values[key] for key in sorted(values)],
                                    'translation_service_access_verified': False},
            'note': 'These are schema-accepted preference values, including deprecated values, not proof of '
                    'translation service availability, UI locale support or access. No participant query or translation request.'}


def _scope(row, context_id, topic_id, context_type):
    if (not isinstance(row, dict) or row.get('_id') != topic_id or row.get('contextId') != context_id or
            row.get('contextType') != context_type.title()):
        raise CanvasError('Canvas returned a different discussion or context; no private response was logged')


def _state(row, context_id, topic_id, context_type, *, participant=False, fields=BASE_FIELDS):
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
        for field in fields:
            key = FIELDS[field]
            if key not in own:
                raise CanvasError('Canvas returned malformed own discussion preferences')
            if field == 'preferred_language':
                if own[key] is not None and (not isinstance(own[key], str) or not _ENUM_NAME.fullmatch(own[key])):
                    raise CanvasError('Canvas returned malformed own language preference; no private response was logged')
            elif field != 'sort_order' and own[key] is not None and type(own[key]) is not bool:
                raise CanvasError('Canvas returned malformed own discussion preferences')
        result['reported'] = {key: own[FIELDS[key]] for key in fields}
        for key in EFFECTIVE_FIELDS:
            if shared[key + '_locked'] is True and result['reported'][key] != shared[key]:
                raise CanvasError('Canvas returned inconsistent locked discussion display metadata')
    return result


def _query(client, context_id, topic_id, context_type, *, participant=False, fields=BASE_FIELDS):
    selected = ' participant { ' + ' '.join(FIELDS[key] for key in fields) + ' }' if participant else ''
    document = _READ % (_METADATA + selected)
    data = client.graphql(document, {'topicId': topic_id}, 'CanvasTopicView')
    return _state(data.get('legacyNode'), context_id, topic_id, context_type, participant=participant, fields=fields)


def _read(client, context_id, topic_id, context_type, acknowledge, *, fields=BASE_FIELDS, language=None):
    discussion_base(context_id, topic_id, context_type)
    if not acknowledge:
        raise CanvasError('Use --acknowledge-participant-initialization: native queries can create your own participant record')
    identity = account(client)
    metadata = _query(client, context_id, topic_id, context_type)
    catalogue = None
    if language is not None:
        catalogue = languages(client)['discussion_languages']['values']
        if language not in {item['enum'] for item in catalogue}:
            raise CanvasError('The selected language is not accepted by this Canvas schema. Use topic-languages; '
                              'no participant query or preference mutation was sent.')
    state = _query(client, context_id, topic_id, context_type, participant=True, fields=fields)
    if state['shared'] != metadata['shared'] or account(client) != identity:
        raise CanvasError('Account or discussion defaults changed during the query. A participant record may have '
                          'been initialized; no preference mutation was sent. Review again.')
    result = {**identity, 'context_type': context_type, 'context_id': context_id, 'topic_id': topic_id, **state}
    if catalogue is not None:
        result['language_catalogue'] = catalogue
    return result


def read(client, context_id, topic_id, *, context_type='course', acknowledge=False, include_assist=False, include_marker=False):
    fields = BASE_FIELDS + (ASSIST_FIELDS if include_assist else ()) + (MARKER_FIELDS if include_marker else ())
    return {'topic_view': _read(client, context_id, topic_id, context_type, acknowledge, fields=fields),
            'native_query_may_initialize_participant': True, 'note': _NOTE}


def _options(values):
    if not isinstance(values, dict) or not values or set(values) - FIELDS.keys():
        raise CanvasError('Select at least one supported personal discussion view option')
    for key, value in values.items():
        if key == 'sort_order':
            if not isinstance(value, str) or value not in ('asc', 'desc'):
                raise CanvasError('Personal sort must be asc or desc. Canvas does not expose a valid stored-inheritance reset.')
        elif key == 'preferred_language':
            if value is not None and (not isinstance(value, str) or not _ENUM_NAME.fullmatch(value)):
                raise CanvasError('Preferred language must be an exact schema enum value or explicit clearing; use topic-languages')
        elif key in ('show_pinned_entries', 'summary_enabled', 'has_unread_pinned_entry') and type(value) is not bool:
            raise CanvasError('Pinned-entry, summary and pinned-unread fields require booleans; native storage does not allow null resets')
        elif value is not None and type(value) is not bool:
            raise CanvasError('Personal display options must be explicit booleans or inheritance')
    return {FIELDS[key]: value for key, value in values.items()}


def change(client, context_id, topic_id, values, *, context_type='course', acknowledge=False,
           acknowledge_marker=False, yes=False, confirm=None):
    check_flags(yes, confirm)
    options = _options(values)
    if 'has_unread_pinned_entry' in values and not acknowledge_marker:
        raise CanvasError('Use --acknowledge-pinned-marker-change: this changes your pinned-reply unread indicator, '
                          'not the replies themselves or proof of reading them')
    fields = BASE_FIELDS + tuple(key for key in ASSIST_FIELDS + MARKER_FIELDS if key in values)
    before = _read(client, context_id, topic_id, context_type, acknowledge, fields=fields,
                   language=values.get('preferred_language'))
    variables = {'input': {'discussionTopicId': topic_id, **options}}
    preview = {**before, 'requested': values, 'method': 'POST', 'route': '/api/graphql',
               'body': {'query': _SET, 'variables': variables, 'operationName': 'CanvasTopicViewSet'},
               'native_query_may_initialize_participant': True, 'pinned_marker_change_acknowledged': acknowledge_marker,
               'effect': _NOTE}
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
        after = _query(client, context_id, topic_id, context_type, participant=True, fields=fields)
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
        effective = key in EFFECTIVE_FIELDS
        locked = effective and after['shared'][key + '_locked'] is True
        expected = after['shared'][key] if locked or value is None and effective else value
        if after['reported'][key] != expected:
            raise CanvasError('Canvas did not independently read back the requested reported preference. '
                              'Some changes may have applied; check Canvas before repeating. No automatic retries.')
        if locked:
            masked.append(key)
        stored = not effective and not (key == 'preferred_language' and value is None)
        verified[key] = {'effective_value_verified': effective, 'stored_override_verified': stored}
    return {'topic_view': {**before, **after}, 'requested': values, 'mutation_acknowledged': True,
            'verification': verified, 'masked_by_shared_locks': masked,
            'observed_changed_fields': sorted(key for key in fields if before['reported'][key] != after['reported'][key]),
            'native_query_may_initialize_participant': True, 'note': _NOTE}
