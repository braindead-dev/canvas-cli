"""Native shared prompt attachment transfer, not a file upload then ID association."""

from .announcement_authoring import _listed, _published
from .client import CanvasError
from .group_content import _number, base
from .multipart import MAX_BYTES, inspect_file
from .topic_management import _inventory, _inventory_delta, _read, _scope, _topic
from .writes import account, check_flags, digest, review

WARNING = ('Uploads a file to a shared discussion or announcement using one native multipart PUT. '
           'Update and attach permissions are separate; quota, blueprint and native restrictions still apply. '
           'Replacement can clear the old association and soft-delete its file record before the new file is '
           'stored; a later error can leave the old file removed or a new file orphaned. Native deletion can '
           'affect content tags, media/LTI/draft associations and other references. Native duplicate-name '
           'renaming and usage-right defaults apply; no copyright/visibility choice is made here. Only exact '
           'topic attachment metadata, new ID and size are verified, not stored bytes, file deletion, storage '
           'erasure, audience access, notifications or recall. Preflight is not an atomic lock. No peer reads, '
           'downloads, separate file deletion, automatic retry, cleanup or rollback.')
UNCERTAIN = ('Could not verify the native attachment upload. The old attachment may be removed and the new '
             'file may already exist; check Canvas before repeating. No automatic retry, cleanup, rollback '
             'or private response-body logging.')


def _metadata(row, item, identifier, context_type, announcement):
    result = _topic(row, item, identifier, context_type, announcement=announcement, require_attach=True)
    return _published(result) if announcement else result


def _current(client, route, item, identifier, context_type, announcement):
    result = _read(client, route, item, identifier, context_type, announcement=announcement, require_attach=True)
    return _published(result) if announcement else result


def set_attachment(client, item, identifier, source, *, kind='topic', context_type='course', max_bytes=MAX_BYTES,
                   acknowledge_shared=False, acknowledge_upload=False, acknowledge_replacement=False,
                   acknowledge_broadcast=False, max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    if kind not in ('topic', 'announcement') or context_type not in ('course', 'group'):
        raise CanvasError('Attachment authoring needs an explicit course/group discussion or announcement')
    base(item, context_type)
    _number(identifier)
    announcement = kind == 'announcement'
    if (acknowledge_shared is not True or acknowledge_upload is not True or
            type(acknowledge_replacement) is not bool or type(acknowledge_broadcast) is not bool or
            acknowledge_broadcast != announcement):
        raise CanvasError('Use explicit shared/upload consent; announcements also require broadcast consent, including previews')
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_BYTES or type(max_pages) is not int or max_pages < 1:
        raise CanvasError('Attachment limits must be positive; native multipart files are bounded to 25 MiB')
    info, content = inspect_file(source, max_bytes)
    identity = account(client)
    route, context = _scope(client, item, context_type)
    before = _current(client, route, item, identifier, context_type, announcement)
    if before['permissions']['update'] is not True or before['permissions']['attach'] is not True:
        raise CanvasError('Canvas did not grant exact native update and attach permissions for this prompt')
    if len(before['attachments']) > 1:
        raise CanvasError('Native prompt attachment transfer requires zero or one existing attachment')
    replacing = bool(before['attachments'])
    if acknowledge_replacement != replacing:
        raise CanvasError('Replacing an existing attachment requires --acknowledge-attachment-replacement; not for an empty prompt')
    inventory = _inventory(client, route, item, context_type, max_pages, announcement=announcement)
    if (_listed(before) not in inventory or
            _current(client, route, item, identifier, context_type, announcement) != before or
            _scope(client, item, context_type) != (route, context) or
            _inventory(client, route, item, context_type, max_pages, announcement=announcement) != inventory or
            account(client) != identity):
        raise CanvasError('Attachment/context/inventory/account changed during preflight; review a fresh preview')
    fields = {'is_announcement': True, 'lock_comment': before['locked']} if announcement else {}
    preview = {**identity, 'context_type': context_type, f'{context_type}_id': int(item), 'context': context,
               'kind': kind, 'topic': before, 'inventory_digest': digest(inventory),
               'file': {key: value for key, value in info.items() if key != 'source'},
               'source_path_digest': digest(info['source']), 'max_bytes': max_bytes,
               'acknowledge_shared': True, 'acknowledge_attachment_upload': True,
               'acknowledge_attachment_replacement': replacing, 'acknowledge_broadcast': announcement,
               'method': 'PUT', 'route': route + '/discussion_topics/' + identifier + '?no_verifiers=true',
               'body': fields, 'encoding': 'multipart/form-data', 'warning': WARNING}
    result = review(preview, yes, confirm)
    if result is not None:
        return result
    try:
        response, _ = client.multipart(preview['route'], 'PUT', fields, info['name'], info['content_type'], content)
        after = _metadata(response, item, identifier, context_type, announcement)
        if (_current(client, route, item, identifier, context_type, announcement) != after or
                _scope(client, item, context_type) != (route, context) or account(client) != identity or
                any(after['permissions'][key] is not True for key in ('update', 'attach')) or
                after['locked'] is not before['locked'] or after['published'] is not before['published']):
            raise CanvasError('Attachment acknowledgement, independent readback, rights or preserved state did not agree')
        if len(after['attachments']) != 1:
            raise CanvasError('Canvas did not report exactly one new prompt attachment')
        attached = after['attachments'][0]
        if (attached['id'] in {row['id'] for row in before['attachments']} or attached['size'] != info['size'] or
                not attached['filename'] or not attached['display_name']):
            raise CanvasError('Canvas did not verify a new attachment ID and exact inspected file size')
        remaining = _inventory(client, route, item, context_type, max_pages, announcement=announcement)
        if _listed(after) not in remaining or account(client) != identity:
            raise CanvasError('New attachment target was not verified in the complete accessible prompt inventory')
    except CanvasError:
        raise CanvasError(UNCERTAIN) from None
    return {'attached_topic': {**after, 'html_url': client.host + f'/{context_type}s/{item}/discussion_topics/{identifier}'},
            'kind': kind, 'context_type': context_type, f'{context_type}_id': int(item),
            'attachment_transfer': {'new_attachment_id': attached['id'], 'bytes': info['size'], 'local_sha256': info['sha256'],
                'replaced_attachment_id': before['attachments'][0]['id'] if replacing else None,
                'new_id_and_size_verified': True, 'stored_bytes_verified': False, 'old_file_deletion_verified': False,
                'storage_erasure_verified': False, 'participant_access_verified': False, 'notification_delivery_verified': False},
            'unrequested_changed_fields': [key for key in before if key != 'attachments' and before[key] != after[key]],
            'observed_inventory_changes': _inventory_delta(inventory, remaining), 'note': WARNING}
