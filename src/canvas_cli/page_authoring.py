"""Explicit shared RCE page authoring, never slug-based upserts or generic writes."""

from datetime import datetime, timezone
from urllib.parse import quote

from .client import CanvasError
from .events import timestamp
from .group_content import _context, _id, _number, base
from .writes import account, check_flags, confirmed, digest

PERMISSIONS = ('manage_wiki_create', 'manage_wiki_update', 'participate_as_student')
PAGE_FIELDS = ('page_id', 'url', 'title', 'editing_roles', 'published', 'front_page', 'updated_at', 'publish_at')
WARNING = ('Shared wiki content, not a private note or assignment submission. Editing can affect module '
           'contribution/read progress. Canvas enforces role, blueprint, scope and institution restrictions '
           'and may sanitize/rewrite HTML. Front-page changes affect the whole context. Native page PUT '
           'is an upsert: preflight is not an atomic lock, so a concurrent deletion can create an unwanted '
           'page and concurrent edits can be overwritten. Native creation of a default-named front page can '
           'select it implicitly; use --front-page when intended. Verify uncertain results; never automatically retry.')
UNCERTAIN = ('Could not verify the page write. It may have succeeded or created an unwanted page; '
             'check Canvas before repeating. No automatic retry or private response-body logging.')


def _fields(title, body, roles, published, front_page, notify, context_type, creating):
    if context_type not in ('course', 'group'):
        raise CanvasError('Page authoring requires an explicit course or group context')
    changes = {}
    if title is not None:
        if (not isinstance(title, str) or not title.strip() or len(title.strip()) > 255 or
                any(ord(char) < 32 or 0x7f <= ord(char) < 0xa0 for char in title)):
            raise CanvasError('Page title must be nonempty, at most 255 characters and contain no controls')
        changes['title'] = title.strip()
        try:
            changes['title'].encode('utf-8')
        except UnicodeError:
            raise CanvasError('Page title must be valid UTF-8 text') from None
    if creating and title is None:
        raise CanvasError('Page creation requires --title')
    if body is not None:
        try:
            valid = isinstance(body, str) and len(body.encode('utf-8')) <= 40000 and '\x00' not in body
        except UnicodeError:
            valid = False
        if not valid:
            raise CanvasError('Page body must be UTF-8 HTML within 40000 bytes, without NUL characters')
        changes['body'] = body
    if roles is not None:
        allowed = {'teachers', 'students', 'public'} if context_type == 'course' else {'members', 'public'}
        values = [value.strip() for value in roles.split(',')] if isinstance(roles, str) else []
        if not values or len(set(values)) != len(values) or not set(values) <= allowed:
            raise CanvasError('Use distinct context-appropriate editing roles separated by commas')
        changes['editing_roles'] = ','.join(sorted(values))
    for key, value in (('published', published), ('front_page', front_page)):
        if value is not None:
            if type(value) is not bool:
                raise CanvasError('Page publication and front-page changes must be explicit booleans')
            changes[key] = value
    if type(notify) is not bool:
        raise CanvasError('Page notification choice must be an explicit boolean')
    if not changes and not notify:
        raise CanvasError('Select at least one page change')
    changes['notify_of_update'] = notify
    return changes


def _scope(client, item, context_type):
    route, context = _context(client, item, context_type)
    if (context.get('workflow_state') in ('deleted', 'completed') or context.get('concluded') or
            context.get('non_collaborative') or context.get('access_restricted_by_date')):
        raise CanvasError('This page context is unavailable, concluded or non-collaborative')
    permissions, _ = client.request(route + '/permissions?' + '&'.join(
        'permissions%5B%5D=' + key for key in PERMISSIONS))
    if not isinstance(permissions, dict) or any(type(permissions.get(key)) is not bool for key in PERMISSIONS):
        raise CanvasError('Canvas did not report exact native page permissions')
    rights = {key: permissions[key] for key in PERMISSIONS}
    if context_type == 'course' and rights['participate_as_student']:
        settings, _ = client.request(route + '?include%5B%5D=allow_student_wiki_edits')
        if _id(settings) != int(item) or type(settings.get('allow_student_wiki_edits')) is not bool:
            raise CanvasError('Canvas did not report the course-wide student wiki-edit setting')
        rights['allow_student_wiki_edits'] = settings['allow_student_wiki_edits']
    return route, {key: context.get(key) for key in ('id', 'name', 'workflow_state', 'concluded', 'non_collaborative')}, rights


def _metadata(row, page_id=None):
    identifier = _id(row, 'page_id')
    if page_id is not None and identifier != int(page_id):
        raise CanvasError('Canvas returned a different page ID')
    if (any(not isinstance(row.get(key), str) or not row[key] for key in ('url', 'title', 'editing_roles', 'updated_at')) or
            any(type(row.get(key)) is not bool for key in ('published', 'front_page')) or
            row.get('workflow_state') == 'deleted' or row.get('hidden_for_user') or row.get('locked_for_user')):
        raise CanvasError('Canvas returned an unavailable or malformed page')
    timestamp(row['updated_at'])
    if row.get('publish_at') is not None:
        timestamp(row['publish_at'])
    return {key: row.get(key) for key in PAGE_FIELDS}


def _read_page(client, route, page_id, *, no_verifiers=False):
    # Successful native Page GET authorizes this exact page, including readable drafts.
    # Do not invent manager permissions for read-only revision access.
    row, _ = client.request(route + '/pages/page_id:' + page_id + ('?no_verifiers=true' if no_verifiers else ''))
    metadata = _metadata(row, page_id)
    if (row.get('editor') not in (None, 'rce') or row.get('block_editor_attributes') is not None or
            row.get('block_editor_data') is not None):
        raise CanvasError('The page is not authorized readable RCE content; block-editor pages require their native editor')
    content = _html(row)
    return {**row, 'body': content}, {**metadata, 'body_digest': digest(content)}


def _page(client, route, page_id, rights):
    row, metadata = _read_page(client, route, page_id)
    if not row['published'] and not (rights['manage_wiki_update'] or rights['manage_wiki_create']):
        raise CanvasError('The page is not authorized readable RCE content; block-editor pages require their native editor')
    return row, metadata


def _html(row):
    if 'body' not in row or row['body'] is not None and not isinstance(row['body'], str):
        raise CanvasError('Canvas did not return readable page HTML')
    return row['body'] if row['body'] is not None else ''  # Native nil represents an unedited empty RCE page.


def _revision(client, route, page_id):
    target = route + '/pages/page_id:' + page_id
    # A bounded permission probe, not a complete revision inventory. Latest alone only requires read rights.
    sample, _ = client.request(target + '/revisions?per_page=1')
    if not isinstance(sample, list) or not sample or len(sample) > 1:
        raise CanvasError('Canvas did not authorize readable page-edit history')
    _id(sample[0], 'revision_id')
    revision, _ = client.request(target + '/revisions/latest?summary=true')
    _id(revision, 'revision_id')
    if revision.get('latest') is not True:
        raise CanvasError('Canvas did not report the current page revision')
    timestamp(revision.get('updated_at'))
    return {key: revision[key] for key in ('revision_id', 'updated_at', 'latest')}


def _inventory(client, route, max_pages):
    rows = [_metadata(row) for row in client.list(route + '/pages?per_page=100', max_pages)]
    if len({row['page_id'] for row in rows}) != len(rows) or sum(row['front_page'] for row in rows) > 1:
        raise CanvasError('Canvas returned an ambiguous page/front-page inventory')
    return sorted(rows, key=lambda row: row['page_id'])


def change(client, item, page_id=None, *, context_type, title=None, body=None, roles=None,
           published=None, front_page=None, notify=False, acknowledge_shared=False,
           max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    base(item, context_type)
    if page_id is not None:
        _number(page_id)
    if acknowledge_shared is not True:
        raise CanvasError('Page authoring requires --acknowledge-shared-page, including previews')
    if type(max_pages) is not int or max_pages < 1:
        raise CanvasError('Page inventory limit must be a positive integer')
    creating = page_id is None
    changes = _fields(title, body, roles, published, front_page, notify, context_type, creating)
    identity = account(client)
    route, context, rights = _scope(client, item, context_type)
    student_wiki = rights['participate_as_student'] and rights.get('allow_student_wiki_edits') is True
    manager = rights['manage_wiki_update']
    full_edit = manager or student_wiki
    if any(key in changes for key in ('editing_roles', 'published', 'front_page')) and not manager:
        raise CanvasError('Publication, editing roles and front-page controls require native Manage Wiki Update permission')
    before = revision = None
    if creating:
        if not (rights['manage_wiki_create'] or student_wiki):
            raise CanvasError('Canvas does not permit page creation in this context')
        # Native defaults: course managers create drafts; group or student pages are automatically published.
        changes.setdefault('published', not (context_type == 'course' and manager))
        changes.setdefault('body', '')
    else:
        current, before = _page(client, route, page_id, rights)
        revision = _revision(client, route, page_id)
        if timestamp(revision['updated_at']) != timestamp(before['updated_at']):
            raise CanvasError('Page changed during revision inspection; review a fresh preview')
        if not full_edit and ('title' in changes or notify):
            raise CanvasError('Page-level content editing does not grant title or notification controls')
        if (current.get('publish_at') is not None and timestamp(current['publish_at']) > datetime.now(timezone.utc) and
                ('published' in changes or front_page is True)):
            raise CanvasError('Future-scheduled pages need explicit scheduling controls before publication changes')
    if (front_page if front_page is not None else before and before['front_page']) and not changes.get('published', before and before['published']):
        raise CanvasError('A front page must remain published; explicitly unset it before unpublishing')
    inventory = _inventory(client, route, max_pages) if creating or front_page is not None else None
    if account(client) != identity:
        raise CanvasError('Canvas account changed during page preflight')
    preview = {**identity, 'context_type': context_type, 'context': context, 'permissions': rights,
               'page_id': int(page_id) if page_id is not None else None, 'before': before, 'revision': revision,
               'inventory_digest': digest(inventory) if inventory is not None else None,
               'current_front_page': next((row for row in inventory or [] if row['front_page']), None),
               'duplicate_titles': sum(row['title'] == title.strip() for row in inventory or []) if creating else None,
               'method': 'POST' if creating else 'PUT',
               'route': route + '/pages' + ('' if creating else '/page_id:' + page_id),
               'body': {'wiki_page': changes}, 'acknowledge_shared_page': True, 'warning': WARNING}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        result = _metadata(response, page_id)
        if creating and result['page_id'] in {row['page_id'] for row in inventory}:
            raise CanvasError('Creation returned a previously listed page')
        if any(result.get(key) != value for key, value in changes.items() if key not in ('body', 'notify_of_update')):
            raise CanvasError('The requested page metadata was not applied')
        if before and any(result[key] != before[key] for key in ('title', 'editing_roles', 'published', 'front_page', 'publish_at')
                          if key not in changes):
            raise CanvasError('Unselected page metadata changed')
        next_route, next_context, next_rights = _scope(client, item, context_type)
        if next_context != context or next_rights != rights or account(client) != identity:
            raise CanvasError('Page account, context or permissions changed after the write')
        stored, _ = _page(client, next_route, str(result['page_id']), next_rights)
        if (_metadata(stored, str(result['page_id'])) != result or
                stored['body'] != _html(response)):
            raise CanvasError('Page acknowledgement and separate readback disagree')
        if 'body' in changes and before and digest(stored['body']) == before['body_digest'] and digest(changes['body']) != before['body_digest']:
            raise CanvasError('The changed body was not observed; sanitization or ignored fields may have removed the change')
        if inventory is not None:
            listed = _inventory(client, route, max_pages)
            old_front = preview['current_front_page']
            expected_front = (result['page_id'] if front_page is True else
                              old_front['page_id'] if old_front and old_front['page_id'] != result['page_id'] else None)
            actual_front = next((row['page_id'] for row in listed if row['front_page']), None)
            if not any(row == result for row in listed) or actual_front != expected_front:
                raise CanvasError('The page/front-page inventory did not verify the change')
        if account(client) != identity:
            raise CanvasError('Canvas account changed during page readback')
    except CanvasError:
        raise CanvasError(UNCERTAIN) from None
    output = {'shared_page': result, 'context_type': context_type, f'{context_type}_id': int(item),
              'created': creating, 'acknowledgement_matches_readback': True,
              'html_matches_request': stored['body'] == changes['body'] if 'body' in changes else None,
              'note': 'Exact page ID, requested metadata and acknowledgement/readback verified, not an atomic lock. '
                      'Canvas HTML can differ from the input; inspect returned content before treating it as equivalent. '
                      'Notifications are requested, not delivery-verified. No automatic retries.'}
    if 'body' in changes:
        output['shared_page']['body'] = stored['body']
    output['shared_page']['html_url'] = client.host + f'/{context_type}s/{item}/pages/' + quote(result['url'], safe='')
    return output
