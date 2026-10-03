"""One native wiki deletion, with separate permission and cascade verification."""

from urllib.parse import quote

from .client import CanvasError
from .events import timestamp
from .group_content import _context, _id, _number, base
from .page_authoring import PAGE_FIELDS, _html, _inventory, _metadata
from .page_history import _detail
from .writes import account, check_flags, confirmed, digest

WARNING = ('Deletes shared wiki content, not a private note or a submission. Canvas soft-deletes pages; '
           'this is not permanent erasure or a recovery promise. Module entries and links can be affected; '
           'a reported linked wiki assignment can also be deleted, affecting its gradebook presence. '
           'Front pages cannot be deleted; no unsetting, replacement or cascading DELETE requests are sent. '
           'Native role, blueprint and institution restrictions remain authoritative. Page/assignment GET '
           'can record module read progress; revision GET can repair legacy imported YAML. '
           'Confirmation is not an atomic lock. No automatic retry, backup, rollback or undelete.')
UNCERTAIN = ('Could not verify the page deletion or its linked-assignment cascade. It may have succeeded; '
             'check Canvas before repeating. No automatic retry, rollback or private response-body logging.')


def _scope(client, item, context_type):
    route, row = _context(client, item, context_type)
    if row.get('workflow_state') == 'deleted':
        raise CanvasError('The page context is deleted')
    permissions, _ = client.request(route + '/permissions?permissions%5B%5D=manage_wiki_delete')
    if not isinstance(permissions, dict) or type(permissions.get('manage_wiki_delete')) is not bool:
        raise CanvasError('Canvas did not report exact native wiki-delete permission')
    if not permissions['manage_wiki_delete']:
        raise CanvasError('Page deletion requires native Manage Wiki Delete permission, not editing or ownership alone')
    # Do not impose edit-only rules: native deletion permission is separate, including concluded contexts.
    context = {key: row.get(key) for key in ('id', 'name', 'workflow_state', 'concluded', 'non_collaborative')}
    return route, context, {'manage_wiki_delete': True}


def _assignment(row, item, context_type):
    if row is None:
        return None
    _id(row)
    if (context_type != 'course' or type(row.get('course_id')) is not int or row['course_id'] != int(item) or
            not isinstance(row.get('name'), str) or not row['name'] or type(row.get('published')) is not bool or
            not isinstance(row.get('submission_types'), list) or not row['submission_types'] or
            any(not isinstance(value, str) for value in row['submission_types']) or
            len(set(row['submission_types'])) != len(row['submission_types']) or
            'wiki_page' not in row['submission_types'] or
            row.get('workflow_state') is not None and not isinstance(row['workflow_state'], str) or
            row.get('workflow_state') == 'deleted'):
        raise CanvasError('Canvas returned an invalid or foreign linked wiki assignment')
    timestamp(row.get('updated_at'))
    return {key: row.get(key) for key in ('id', 'course_id', 'name', 'submission_types', 'published', 'updated_at', 'workflow_state')}


def _page(client, route, page_id, item, context_type):
    row, _ = client.request(route + '/pages/page_id:' + page_id + '?no_verifiers=true')
    metadata = _metadata(row, page_id)
    editor = row.get('editor')
    if editor not in (None, 'rce', 'block_editor', 'block_content_editor'):
        raise CanvasError('Canvas returned an unknown native wiki editor')
    blocks, external = row.get('block_editor_attributes'), row.get('block_editor_data')
    if blocks is not None and external is not None:
        raise CanvasError('Canvas returned ambiguous native wiki content')
    if blocks is not None:
        if not isinstance(blocks, dict) or 'blocks' not in blocks:
            raise CanvasError('Canvas did not return readable native block content')
        _id(blocks)
        content = {'editor': editor, 'block_editor_attributes': blocks}
    elif external is not None:
        if not isinstance(external, (dict, list, str)):
            raise CanvasError('Canvas did not return readable native external block content')
        content = {'editor': editor, 'block_editor_data': external}
    else:
        content = {'editor': editor, 'body': _html(row)}
    # Opaque native block content is fingerprinted, never converted to HTML or replayed as an edit.
    linked = _assignment(row.get('assignment'), item, context_type)
    return metadata, digest(content), linked


def _absent(client, route, allowed=(404,)):
    try:
        client.request(route)
    except CanvasError as error:
        if error.status in allowed:
            return error.status
        raise
    raise CanvasError('The deleted resource remained readable')


def _old_link(client, route, page, listed):
    try:
        row, _ = client.request(route + '/pages/' + quote(page['url'], safe='') + '?no_verifiers=true')
    except CanvasError as error:
        if error.status == 404:
            return {'status': 'not_found'}
        raise
    rebound = _metadata(row)
    if rebound['page_id'] == page['page_id'] or rebound not in listed:
        raise CanvasError('The old URL did not independently verify removal of the original page')
    # Numeric slugs can fall back to another numeric page ID after deletion. Never delete that page.
    return {'status': 'resolves_to_another_page', 'page_id': rebound['page_id']}


def delete(client, item, page_id, *, context_type, acknowledge=False, acknowledge_assignment=False,
           max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    if context_type not in ('course', 'group'):
        raise CanvasError('Page deletion requires an explicit course or group context')
    base(item, context_type)
    _number(page_id)
    if acknowledge is not True or type(acknowledge_assignment) is not bool:
        raise CanvasError('Page deletion requires --acknowledge-page-deletion, including previews')
    if type(max_pages) is not int or max_pages < 1:
        raise CanvasError('Page inventory limit must be a positive integer')
    identity = account(client)
    route, context, rights = _scope(client, item, context_type)
    before, content_digest, linked = _page(client, route, page_id, item, context_type)
    if before['front_page']:
        raise CanvasError('The native front page cannot be deleted; no automatic front-page change will be sent')
    if linked and not acknowledge_assignment:
        raise CanvasError('This deletion also removes a linked wiki assignment; use --acknowledge-linked-assignment-deletion')
    if linked:
        assignment, _ = client.request(route + '/assignments/' + str(linked['id']))
        if _assignment(assignment, item, context_type) != linked:
            raise CanvasError('Linked assignment changed during inspection; review a fresh preview')
    target = route + '/pages/page_id:' + page_id
    revision = _detail(client, target, 'latest')  # Read permission, not an edit-history permission probe.
    if timestamp(revision['updated_at']) != timestamp(before['updated_at']):
        raise CanvasError('Page changed during revision inspection; review a fresh preview')
    inventory = _inventory(client, route, max_pages)
    if before not in inventory:
        raise CanvasError('Page changed during inventory inspection; review a fresh preview')
    front = next((row for row in inventory if row['front_page']), None)
    if _page(client, route, page_id, item, context_type) != (before, content_digest, linked) or account(client) != identity:
        raise CanvasError('Page/account changed during deletion preflight; review a fresh preview')
    preview = {**identity, 'context_type': context_type, 'context': context, 'permissions': rights,
               'page_id': int(page_id), 'before': before, 'content_digest': content_digest, 'revision': revision,
               'linked_assignment': linked, 'inventory_digest': digest(inventory), 'current_front_page': front,
               'acknowledge_page_deletion': True, 'acknowledge_linked_assignment_deletion': acknowledge_assignment,
               'method': 'DELETE', 'route': target + '?no_verifiers=true', 'body': None, 'warning': WARNING}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        if not isinstance(response, dict) or response.get('workflow_state') not in (None, 'deleted'):
            raise CanvasError('Canvas did not acknowledge a native page deletion')
        # Deleted content need not remain readable. Validate acknowledgement metadata, not its body/lock fields.
        acknowledged = _metadata({key: response.get(key) for key in PAGE_FIELDS}, page_id)
        if (acknowledged['published'] or acknowledged['front_page'] or
                any(acknowledged[key] != before[key] for key in ('url', 'title', 'editing_roles', 'publish_at'))):
            raise CanvasError('Canvas acknowledged different page metadata or an undeleted state')
        next_route, next_context, next_rights = _scope(client, item, context_type)
        if next_context != context or next_rights != rights or account(client) != identity:
            raise CanvasError('Account, context or delete permission changed after deletion')
        listed = _inventory(client, next_route, max_pages)
        if (any(row['page_id'] == int(page_id) for row in listed) or
                next((row for row in listed if row['front_page']), None) != front):
            raise CanvasError('The original page remained listed or the front page changed')
        # Native exact-ID lookup includes deleted rows: 403 alone is ambiguous. Pair it with index AND URL evidence.
        exact_status = _absent(client, target + '?no_verifiers=true', (403, 404))
        old_link = _old_link(client, next_route, before, listed)
        assignment_status = _absent(client, next_route + '/assignments/' + str(linked['id'])) if linked else None
        if account(client) != identity:
            raise CanvasError('Canvas account changed during deletion readback')
    except CanvasError:
        raise CanvasError(UNCERTAIN) from None
    return {'deleted_page': {'page_id': int(page_id), 'title': before['title'], 'url': before['url']},
            'context_type': context_type, f'{context_type}_id': int(item), 'removed_from_page_inventory': True,
            'exact_id_read_status': exact_status, 'original_url_resolution': old_link,
            'linked_assignment_id': linked['id'] if linked else None, 'linked_assignment_read_status': assignment_status,
            'note': 'Exact-ID acknowledgement, separate page inventory/ID/old-link reads and stable account/delete permission verified. '
                    'Any reported linked assignment independently returned 404. Front page unchanged. '
                    'Native soft deletion, not permanent erasure, an atomic lock or proof of every external-link/module consequence. '
                    'No automatic retry, cascading DELETE request or undelete.'}
