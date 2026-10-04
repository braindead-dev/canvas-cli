"""Native discussion copying, with explicit copy effects and no invented lineage."""

from .client import CanvasError
from .group_content import _id, _number, base
from .topic_authoring import _authority as creation_authority
from .topic_dates import matches
from .topic_management import _inventory, _inventory_delta, _read, _topic
from .writes import account, check_flags, confirmed, digest

COPIED = ('message_digest', 'discussion_type', 'require_initial_post', 'is_section_specific',
          'locked', 'pinned', 'delayed_post_at', 'lock_at', 'todo_date', 'allow_rating',
          'only_graders_can_rate', 'sort_order', 'sort_order_locked', 'expanded', 'expanded_locked',
          'section_ids', 'audience_digest')
WARNING = ('Copies a shared ungraded prompt, not replies or a private backup. Native copies do not clone '
           'reply/attachment associations; linked files inside the prompt can still reference original files. '
           'Section visibility is copied but participant overrides may not be, widening the new audience. '
           'Dates/options are copied; moderators normally get a draft while other creators are auto-published. '
           'Copied dates can affect availability and future jobs. A pinned copy is inserted after its source '
           'and shifts other topics. Native course duplication additionally requires instructor eligibility '
           'by date or context read_as_admin; creation/moderation flags alone do not prove it. The endpoint '
           'enforces eligibility, initial-post and editing restrictions. Preflight is not atomic; no peer '
           'entries, announcements, graded/group-set/root-child/anonymous copies or read-marker writes here. '
           'No automatic retry, cleanup or rollback.')
UNCERTAIN = ('Could not verify the copied discussion topic. Duplication may already have succeeded; '
             'check Canvas before repeating to avoid duplicates. No automatic retry, deletion, rollback '
             'or private response-body logging.')


def _authority(client, item, context_type):
    route, context, rights = creation_authority(client, item, context_type)
    if context_type == 'course':
        report, _ = client.request(route + '/permissions?permissions%5B%5D=read_as_admin')
        if not isinstance(report, dict) or type(report.get('read_as_admin')) is not bool:
            raise CanvasError('Canvas did not report its exact course context-admin permission')
        rights['read_as_admin'] = report['read_as_admin']
    return route, context, rights


def _positions(response, rows, identifier, after, source, acknowledged):
    mapping = response.get('new_positions')
    if not isinstance(mapping, dict) or not mapping:
        raise CanvasError('Canvas did not acknowledge native pinned-copy positions')
    for key, value in mapping.items():
        _number(key)
        if type(value) is not int or value < 0:
            raise CanvasError('Canvas returned malformed pinned-copy positions')
    pinned = [row for row in rows if row['pinned'] is True]
    if (any(type(row['pinned']) is not bool for row in rows) or
            any(type(row['position']) is not int or row['position'] < 0 for row in pinned) or
            len({row['position'] for row in pinned}) != len(pinned) or after['pinned'] is not True or
            type(acknowledged['position']) is not int or mapping.get(str(identifier)) != after['position'] or
            after['position'] != source['position'] + 1 or
            any(mapping.get(str(row['id'])) != row['position'] for row in pinned)):
        raise CanvasError('Independent pinned positions do not match the native copy acknowledgement')
    return {'accessible_positions_verified': True,
            'native_pre_insertion_position': acknowledged['position'], 'stored_copy_position': after['position'],
            'unverified_position_count': len(set(mapping) - {str(row['id']) for row in pinned})}


def duplicate(client, item, topic_id, *, context_type='course', acknowledge_shared=False,
              acknowledge_copy=False, max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    base(item, context_type)
    _number(topic_id)
    if context_type not in ('course', 'group') or acknowledge_shared is not True or acknowledge_copy is not True:
        raise CanvasError('Use a course/group context, --acknowledge-shared-topic and --acknowledge-copy-effects, including previews')
    if type(max_pages) is not int or max_pages < 1:
        raise CanvasError('Topic-copy inventory limit must be a positive integer')
    identity = account(client)
    route, context, rights = _authority(client, item, context_type)
    source = _read(client, route, item, topic_id, context_type)
    # Visibility alone omits native observer-associated users; use the exact hold reason.
    if source['subscription_hold'] == 'initial_post_required':
        raise CanvasError('The native initial-post restriction is not satisfied; duplication does not bypass it')
    if source['pinned'] and type(source['position']) is not int:
        raise CanvasError('Canvas did not report the pinned source position for native copy insertion')
    inventory = _inventory(client, route, item, context_type, max_pages)
    listed = {key: source[key] for key in ('id', 'title', 'published', 'locked', 'pinned', 'position')}
    if (listed not in inventory or _read(client, route, item, topic_id, context_type) != source or
            _authority(client, item, context_type) != (route, context, rights) or
            _inventory(client, route, item, context_type, max_pages) != inventory or account(client) != identity):
        raise CanvasError('Copy source, inventory, context, native rights or account changed during preflight')
    preview = {**identity, 'context_type': context_type, f'{context_type}_id': int(item), 'context': context,
               'source_topic': source, 'permissions': rights, 'inventory_digest': digest(inventory),
               'native_duplicate_eligibility': 'group creation' if context_type == 'group' else
               'context admin reported' if rights['read_as_admin'] else 'instructor-by-date check remains native-endpoint authoritative',
               'acknowledge_shared_topic': True, 'acknowledge_copy_effects': True,
               'native_initial_post_check': 'endpoint authoritative; explicit initial_post_required hold is refused',
               'method': 'POST', 'route': route + '/discussion_topics/' + topic_id + '/duplicate?no_verifiers=true',
               'body': None, 'warning': WARNING}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        identifier = _id(response)
        if identifier in {row['id'] for row in inventory}:
            raise CanvasError('Canvas acknowledged an existing topic, not a new copy')
        acknowledged = _topic(response, item, str(identifier), context_type)
        after = _read(client, route, item, str(identifier), context_type)
        # Native serialization precedes insert_at for pinned copies; the position map is authoritative.
        if (after['author_id'] != identity['user_id'] or
                any(after[key] != value for key, value in acknowledged.items() if not (source['pinned'] and key == 'position')) or
                _read(client, route, item, topic_id, context_type) != source or
                _authority(client, item, context_type) != (route, context, rights) or account(client) != identity):
            raise CanvasError('Copied-topic acknowledgement, source, rights or account failed independent readback')
        remaining = _inventory(client, route, item, context_type, max_pages)
        if ({key: after[key] for key in listed} not in remaining or account(client) != identity):
            raise CanvasError('The copied discussion is not verified in its accessible context inventory')
        ordering = _positions(response, remaining, identifier, after, source, acknowledged) if source['pinned'] else None
    except CanvasError:
        raise CanvasError(UNCERTAIN) from None
    equal = {key: matches(after, key, source[key]) if key in ('delayed_post_at', 'lock_at', 'todo_date') else after[key] == source[key]
             for key in COPIED}
    return {'copied_topic': {**after, 'html_url': client.host + f'/{context_type}s/{item}/discussion_topics/{identifier}'},
            'source_topic_id': int(topic_id), 'context_type': context_type, f'{context_type}_id': int(item),
            'new_id_verified': True, 'source_metadata_unchanged_at_readback': True,
            'acknowledgement_matches_readback_except_native_pre_insertion_position': True,
            'stored_fields_match_source': equal, 'source_attachment_count': len(source['attachments']),
            'copy_attachment_count': len(after['attachments']), 'pinned_ordering': ordering,
            'observed_inventory_changes': _inventory_delta(inventory, remaining),
            'note': 'One native exact-source POST, new ID, own author, independent topic/source and paginated inventory readback verified. '
                    'Native copied-field differences, attachment counts and accessible pinned positions are labeled, not a perfect-copy '
                    'or immutable-lineage guarantee. Participant overrides/publication can differ; inspect the new audience before use. '
                    'Other observed changes are not exclusive causal proof. Hidden ordering, peer content, future jobs, linked files, '
                    'notifications and downstream effects are not verified. No private prompt, signed URLs or raw response emitted; '
                    'no automatic retry, deletion or rollback.'}
