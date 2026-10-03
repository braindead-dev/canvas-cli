"""Create one native ungraded prompt, without guessing roles or posting a reply."""

from .client import CanvasError
from .group_content import _id, base
from .topic_management import _changes, _inventory, _read, _scope, _topic
from .writes import account, check_flags, confirmed, digest

WARNING = ('Creates a shared ungraded discussion, not a reply, assignment or private note. '
           'Canvas defaults to draft for native forum moderators and published for other creators. '
           'A draft is not guaranteed private from moderators. Creation can notify people and update '
           'activity/order; native HTML processing and discussion defaults remain authoritative. '
           'No attachments, section overrides, anonymous/group-set topics, grading, scheduling or '
           'read-marker writes are requested. Preflight is not atomic; no automatic retry or cleanup.')
UNCERTAIN = ('Could not verify the new discussion topic. Creation may already have succeeded; '
             'check Canvas before repeating to avoid duplicates. No automatic retry, deletion, '
             'rollback or private response-body logging.')


def _authority(client, item, context_type):
    route, context = _scope(client, item, context_type)
    row, _ = client.request(route + '?include%5B%5D=permissions')
    if _id(row) != int(item) or {key: row.get(key) for key in context} != context:
        raise CanvasError('Discussion context changed while reading native creation permissions')
    permissions = row.get('permissions')
    if not isinstance(permissions, dict) or type(permissions.get('create_discussion_topic')) is not bool:
        raise CanvasError('Canvas did not report the dynamic native discussion creation permission')
    if permissions['create_discussion_topic'] is not True:
        raise CanvasError('Canvas does not permit discussion creation in this exact context')
    rights, _ = client.request(route + '/permissions?permissions%5B%5D=moderate_forum')
    if not isinstance(rights, dict) or type(rights.get('moderate_forum')) is not bool:
        raise CanvasError('Canvas did not report the native forum moderation permission')
    return route, context, {'create_discussion_topic': True, 'moderate_forum': rights['moderate_forum']}


def create(client, item, *, title, message=None, context_type='course', published=None,
           acknowledge_shared=False, max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    if context_type not in ('course', 'group'):
        raise CanvasError('Topic creation requires a course or group context')
    base(item, context_type)
    if acknowledge_shared is not True:
        raise CanvasError('Use --acknowledge-shared-topic for topic creation, including previews')
    if title is None:
        raise CanvasError('Topic creation requires a title')
    if type(max_pages) is not int or max_pages < 1 or published is not None and type(published) is not bool:
        raise CanvasError('Use a positive inventory limit and an explicit boolean publication choice')
    changes = _changes(title, message)
    identity = account(client)
    route, context, rights = _authority(client, item, context_type)
    state = not rights['moderate_forum'] if published is None else published
    if state is False and rights['moderate_forum'] is not True:
        raise CanvasError('Canvas requires native forum moderation permission to create a draft')
    inventory = _inventory(client, route, item, context_type, max_pages)
    if (_authority(client, item, context_type) != (route, context, rights) or
            _inventory(client, route, item, context_type, max_pages) != inventory or account(client) != identity):
        raise CanvasError('Discussion context, permissions, inventory or account changed during preflight')
    preview = {**identity, 'context_type': context_type, f'{context_type}_id': int(item), 'context': context,
               'permissions': rights, 'inventory_digest': digest(inventory), 'acknowledge_shared_topic': True,
               'publication_choice': 'native_default' if published is None else 'explicit',
               'method': 'POST', 'route': route + '/discussion_topics?no_verifiers=true',
               'body': {**changes, 'published': state}, 'warning': WARNING}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        identifier = _id(response)
        if identifier in {row['id'] for row in inventory}:
            raise CanvasError('Canvas acknowledged an existing topic, not a new one')
        after = _topic(response, item, str(identifier), context_type)
        if after['author_id'] != identity['user_id']:
            raise CanvasError('Canvas did not identify the new topic author as the signed-in user')
        if (_authority(client, item, context_type) != (route, context, rights) or account(client) != identity or
                _read(client, route, item, str(identifier), context_type) != after):
            raise CanvasError('Created-topic acknowledgement and independent readback do not agree')
        remaining = _inventory(client, route, item, context_type, max_pages)
        listed = {key: after[key] for key in ('id', 'title', 'published', 'locked', 'pinned', 'position')}
        if listed not in remaining or account(client) != identity:
            raise CanvasError('The new topic is not verified in the accessible context inventory')
    except CanvasError:
        raise CanvasError(UNCERTAIN) from None
    matches = {key: after['message_digest'] == digest(value) if key == 'message' else after[key] == value
               for key, value in preview['body'].items()}
    return {'created_topic': {**after, 'html_url': client.host + f'/{context_type}s/{item}/discussion_topics/{identifier}'},
            'context_type': context_type, f'{context_type}_id': int(item), 'acknowledgement_matches_readback': True,
            'new_id_verified': True, 'stored_fields_match_request': matches,
            'note': 'One native POST, new ID, own author, independent exact-topic readback and paginated inventory verified. '
                    'Account/context/native permissions remained stable. Stored-field equality is labeled; '
                    'HTML normalization and ignored publication choices are not hidden. Native defaults appear in metadata; '
                    'notification/order effects and future audience changes are not verified. No private prompt, signed URLs, '
                    'peer replies or raw response emitted; no automatic retry or cleanup.'}
