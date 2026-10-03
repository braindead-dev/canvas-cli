"""Native RCE wiki revisions and one exact-ID, preview-bound restoration."""

from urllib.parse import quote

from .client import CanvasError
from .events import timestamp
from .group_content import _context, _id, _number, base
from .page_authoring import _read_page, _scope
from .wiki_content import _html, _inventory, _metadata
from .writes import account, check_flags, confirmed, digest

READ_NOTE = ('Only native-authorized RCE page revisions, not deleted-page recovery or a historical '
             'publication/permission snapshot. Latest detail needs page-read permission; numeric detail '
             'and history require native read-revisions permission. Page GET can record module read '
             'progress; revision GET can repair legacy imported YAML records. Content and editor '
             'details are opt-in. Canvas-rewritten HTML is not raw stored source.')
WARNING = ('Restores shared title, body and URL, not publication, editing roles or scheduling. '
           'Old content may contain private information; inspect it with page-revision --include-content '
           'before confirming. URL changes affect links/modules and may deselect the front page. '
           'Canvas may sanitize HTML or normalize URLs; title collisions can make verification uncertain. '
           'Native restore is not an atomic lock; concurrent edits can be overwritten. '
           'No automatic retry, front-page repair, notification request or rollback. ' + READ_NOTE)
UNCERTAIN = ('Could not verify the page restoration. It may have succeeded; check Canvas before '
             'repeating. No automatic retry, rollback or private response-body logging.')


def _target(item, page_id, context_type, max_pages):
    if context_type not in ('course', 'group'):
        raise CanvasError('Page history requires an explicit course or group context')
    base(item, context_type)
    _number(page_id)
    if type(max_pages) is not int or max_pages < 1:
        raise CanvasError('Page history/inventory limit must be a positive integer')


def _revision(row, revision_id=None, *, content=False, editors=False):
    identifier = _id(row, 'revision_id')
    if revision_id is not None and identifier != int(revision_id):
        raise CanvasError('Canvas returned a different page revision')
    if type(row.get('latest')) is not bool:
        raise CanvasError('Canvas did not report an exact revision latest flag')
    timestamp(row.get('updated_at'))
    result = {key: row[key] for key in ('revision_id', 'updated_at', 'latest')}
    if content:
        if any(not isinstance(row.get(key), str) or not row[key] for key in ('title', 'url')):
            raise CanvasError('Canvas did not return readable revision title/URL')
        result.update(title=row['title'], url=row['url'], body=_html(row))
    if editors and row.get('edited_by') is not None:
        actor = row['edited_by']
        result['edited_by'] = {'id': _id(actor)}
        for key in ('display_name', 'name'):
            if isinstance(actor.get(key), str):
                result['edited_by'][key] = actor[key]
    return result


def _detail(client, target, revision_id, *, content=False, editors=False):
    row, _ = client.request(target + '/revisions/' + revision_id +
                            '?summary=' + ('false' if content else 'true') + '&no_verifiers=true')
    result = _revision(row, None if revision_id == 'latest' else revision_id, content=content, editors=editors)
    if revision_id == 'latest' and not result['latest']:
        raise CanvasError('Canvas did not return the current page revision')
    return result


def _current(client, route, page_id):
    page, metadata = _read_page(client, route, page_id, no_verifiers=True)
    revision = _detail(client, route + '/pages/page_id:' + page_id, 'latest', content=True)
    if (timestamp(revision['updated_at']) != timestamp(metadata['updated_at']) or
            any(revision[key] != page[key] for key in ('title', 'url', 'body'))):
        raise CanvasError('Page changed during revision inspection; review a fresh result')
    return page, metadata, revision


def read(client, item, page_id, revision_id=None, *, context_type, content=False, editors=False, max_pages=100):
    _target(item, page_id, context_type, max_pages)
    if revision_id not in (None, 'latest'):
        _number(revision_id)
    if type(content) is not bool or type(editors) is not bool or content and revision_id is None:
        raise CanvasError('Select one revision for content; editor/content choices must be explicit booleans')
    identity = account(client)
    route, _ = _context(client, item, context_type)
    _, page = _read_page(client, route, page_id, no_verifiers=True)
    target = route + '/pages/page_id:' + page_id
    if revision_id is None:
        rows = [_revision(row, editors=editors) for row in client.list(target + '/revisions?per_page=100', max_pages)]
        latest = [row for row in rows if row['latest']]
        current = _detail(client, target, 'latest')
        if (len({row['revision_id'] for row in rows}) != len(rows) or len(latest) != 1 or
                any(latest[0][key] != current[key] for key in current) or
                timestamp(current['updated_at']) != timestamp(page['updated_at'])):
            raise CanvasError('Canvas returned ambiguous or changing revision history; inspect again')
        result = {'page_revisions': sorted(rows, key=lambda row: row['revision_id'], reverse=True),
                  'complete_for_endpoint': True}
    else:
        result = {'page_revision': _detail(client, target, revision_id, content=content, editors=editors)}
        if revision_id == 'latest' and timestamp(result['page_revision']['updated_at']) != timestamp(page['updated_at']):
            raise CanvasError('Page changed during revision inspection; inspect again')
    if account(client) != identity:
        raise CanvasError('Canvas account changed during revision inspection')
    # Default output never includes prior bodies/titles/URLs or full native actor records.
    page.pop('body_digest')
    return {**identity, 'context_type': context_type, f'{context_type}_id': int(item),
            'page': page, **result, 'note': READ_NOTE}


def restore(client, item, page_id, revision_id, *, context_type, acknowledge_shared=False,
            acknowledge_front=False, max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    _target(item, page_id, context_type, max_pages)
    _number(revision_id)  # Restores always name an exact immutable revision, never "latest".
    if acknowledge_shared is not True or type(acknowledge_front) is not bool:
        raise CanvasError('Restoration requires --acknowledge-shared-page, including previews')
    identity = account(client)
    route, context, rights = _scope(client, item, context_type)
    if not (rights['manage_wiki_update'] or
            rights['participate_as_student'] and rights.get('allow_student_wiki_edits') is True):
        raise CanvasError('Restoring title/body/URL requires full native page-update permission, not body-only editing')
    target = route + '/pages/page_id:' + page_id
    current, before, revision = _current(client, route, page_id)
    selected = _detail(client, target, revision_id, content=True)  # Native read-revisions authorization.
    if selected['revision_id'] > revision['revision_id'] or selected['latest'] != (selected['revision_id'] == revision['revision_id']):
        raise CanvasError('Canvas returned a revision outside the observed current history')
    inventory = _inventory(client, route, max_pages)
    if not any(row == _metadata(current, page_id) for row in inventory):
        raise CanvasError('Page changed during inventory inspection; review a fresh preview')
    front = next((row for row in inventory if row['front_page']), None)
    front_risk = before['front_page'] and any(selected[key] != before[key] for key in ('title', 'url'))
    if front_risk and not acknowledge_front:
        raise CanvasError('Restoring this front page can deselect it; use --acknowledge-front-page-change')
    _, fresh_before, fresh_revision = _current(client, route, page_id)
    if fresh_before != before or fresh_revision != revision or account(client) != identity:
        raise CanvasError('Page/account changed during restoration preflight; review a fresh preview')
    preview = {**identity, 'context_type': context_type, 'context': context, 'permissions': rights,
               'page_id': int(page_id), 'before': before,
               'current_revision': {key: revision[key] for key in ('revision_id', 'updated_at', 'latest')},
               'restore_revision': {key: selected[key] for key in ('revision_id', 'updated_at', 'title', 'url')},
               'restore_body_digest': digest(selected['body']), 'inventory_digest': digest(inventory),
               'current_front_page': front, 'front_page_may_be_deselected': bool(front_risk),
               'acknowledge_shared_page': True, 'acknowledge_front_page_change': acknowledge_front,
               'method': 'POST', 'route': target + '/revisions/' + revision_id + '?no_verifiers=true',
               'body': {}, 'warning': WARNING}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        restored = _revision(response, content=True)
        if not restored['latest'] or restored['revision_id'] < revision['revision_id'] or restored['title'] != selected['title']:
            raise CanvasError('The restoration did not acknowledge the selected title/current revision')
        next_route, next_context, next_rights = _scope(client, item, context_type)
        if next_context != context or next_rights != rights or account(client) != identity:
            raise CanvasError('Account/context/permissions changed after restoration')
        stored, after, readback = _current(client, next_route, page_id)
        if restored != readback or any(after[key] != before[key] for key in ('editing_roles', 'published', 'publish_at')):
            raise CanvasError('Revision acknowledgement/current page disagree or unselected metadata changed')
        changed = any(stored[key] != current[key] for key in ('title', 'url', 'body'))
        intended_change = any(selected[key] != current[key] for key in ('title', 'url', 'body'))
        if (intended_change and not changed or changed and restored['revision_id'] <= revision['revision_id'] or
                selected['body'] != current['body'] and stored['body'] == current['body']):
            raise CanvasError('The selected restoration was not observed')
        if before['front_page'] and not stored['front_page'] and not acknowledge_front:
            raise CanvasError('Native URL normalization unexpectedly deselected the front page without acknowledgement')
        listed = _inventory(client, route, max_pages)
        expected_front = (front['page_id'] if front and
                          (front['page_id'] != int(page_id) or front['url'] == stored['url']) else None)
        actual_front = next((row['page_id'] for row in listed if row['front_page']), None)
        if (not any(row == _metadata(stored, page_id) for row in listed) or actual_front != expected_front or
                account(client) != identity):
            raise CanvasError('Restored page/front-page inventory or account did not verify')
    except CanvasError:
        raise CanvasError(UNCERTAIN) from None
    output = _metadata(stored, page_id)
    output['html_url'] = client.host + f'/{context_type}s/{item}/pages/' + quote(stored['url'], safe='')
    return {'restored_page': output, 'context_type': context_type, f'{context_type}_id': int(item),
            'selected_revision_id': int(revision_id), 'current_revision_id': restored['revision_id'],
            'acknowledgement_matches_readback': True, 'html_matches_revision': stored['body'] == selected['body'],
            'url_matches_revision': stored['url'] == selected['url'], 'front_page_deselected': before['front_page'] and not stored['front_page'],
            'note': 'Exact page ID/title, current revision and separate page/front-page readback verified, not an atomic lock. '
                    'HTML/URL differences are reported, not claimed equivalent. Read page-revision --include-content to inspect '
                    'the result. Publication, editing roles and schedule preserved. No automatic retry or front-page repair.'}
