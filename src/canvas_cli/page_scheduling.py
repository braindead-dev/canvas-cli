"""Exact course-page publication dates, never implicit publish/unpublish controls."""

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from .client import CanvasError
from .events import timestamp
from .group_content import _id, _number, base
from .page_authoring import _read_page, _revision, _scope
from .wiki_content import PAGE_FIELDS, _html, _inventory, _metadata
from .writes import account, check_flags, confirmed, digest

FEATURE = 'scheduled_page_publication'
WARNING = ('Changes a shared course page publication schedule, not a private reminder. Setting a future '
           'date unpublishes the page; cancelling a stored date leaves it unpublished, including previously '
           'published pages. Requires native Manage Wiki Update, readable RCE/history and an enabled root-account '
           'feature. Front pages and reported linked wiki assignments are refused; no implicit deselection, '
           'assignment write, content replay or notification request. Native PUT is an upsert: concurrent '
           'deletion can create an unwanted page and confirmation is not an atomic lock. Page/revision reads '
           'can record module progress or repair legacy YAML. Stored dates do not prove a future background '
           'job will execute. No automatic retry, publication, rollback or repair.')
UNCERTAIN = ('Could not verify the publication schedule. The page may have been changed or an unwanted '
             'page created; inspect Canvas before repeating. No automatic retry, publication, rollback, '
             'repair or private response-body logging.')


def _future(value):
    parsed = timestamp(value)
    if parsed <= datetime.now(timezone.utc) + timedelta(seconds=60):
        raise CanvasError('A publication schedule must be at least 60 seconds in the future with an explicit UTC offset')
    return parsed.astimezone(timezone.utc).isoformat()


def _feature(client, route, item):
    context, _ = client.request(route)
    if _id(context) != int(item):
        raise CanvasError('Canvas returned a different scheduling course')
    root = _id(context, 'root_account_id')
    flag, _ = client.request(f'/api/v1/accounts/{root}/features/flags/{FEATURE}')
    if (not isinstance(flag, dict) or flag.get('feature') != FEATURE or
            flag.get('state') not in ('on', 'allowed_on') or type(flag.get('locked')) is not bool):
        raise CanvasError('Canvas did not report enabled root-account scheduled page publication')
    # The root-account endpoint can legitimately report an inherited site-admin/global flag.
    if flag.get('context_id') is not None or flag.get('context_type') is not None:
        if flag.get('context_type') != 'Account':
            raise CanvasError('Canvas returned a non-account publication feature flag')
        _id(flag, 'context_id')
    return {'root_account_id': root, **{key: flag.get(key) for key in ('feature', 'state', 'context_id', 'context_type', 'locked')}}


def _page(client, route, page_id):
    row, metadata = _read_page(client, route, page_id, no_verifiers=True)
    if 'publish_at' not in row:
        raise CanvasError('Canvas did not report the current publication date, including an explicit null')
    if row.get('assignment') is not None:
        raise CanvasError('Publication scheduling of linked wiki assignments needs separate assignment controls')
    if metadata['front_page']:
        raise CanvasError('Front pages cannot be scheduled or unscheduled here; no implicit front-page change')
    return metadata


def schedule(client, item, page_id, *, publish_at=None, cancel=False, acknowledge_shared=False,
             max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    base(item, 'course')
    _number(page_id)
    if acknowledge_shared is not True:
        raise CanvasError('Publication scheduling requires --acknowledge-shared-page, including previews')
    if type(cancel) is not bool or (publish_at is None) == (not cancel):
        raise CanvasError('Choose exactly one explicit --publish-at or --cancel')
    if type(max_pages) is not int or max_pages < 1:
        raise CanvasError('Scheduling inventory limit must be a positive integer')
    selected = _future(publish_at) if publish_at is not None else None
    identity = account(client)
    route, context, rights = _scope(client, item, 'course')
    if rights['manage_wiki_update'] is not True:
        raise CanvasError('Publication scheduling requires native Manage Wiki Update, not student/content editing alone')
    feature = _feature(client, route, item)
    before = _page(client, route, page_id)
    if cancel and before['publish_at'] is None:
        raise CanvasError('The page has no reported publication date to cancel')
    if selected is not None and before['publish_at'] is not None and timestamp(selected) == timestamp(before['publish_at']):
        raise CanvasError('The page already reports this publication date; no rescheduling POST/PUT is sent')
    revision = _revision(client, route, page_id)
    if timestamp(revision['updated_at']) != timestamp(before['updated_at']):
        raise CanvasError('Page changed during schedule revision inspection; review a fresh preview')
    inventory = _inventory(client, route, max_pages)
    if {key: before[key] for key in PAGE_FIELDS} not in inventory:
        raise CanvasError('Page changed during schedule inventory inspection; review a fresh preview')
    front = next((row for row in inventory if row['front_page']), None)
    if _page(client, route, page_id) != before or account(client) != identity:
        raise CanvasError('Page/account changed during scheduling preflight; review a fresh preview')
    preview = {**identity, 'course_id': int(item), 'context': context, 'permissions': rights,
               'publication_feature': feature, 'page_id': int(page_id), 'before': before,
               'revision': revision, 'inventory_digest': digest(inventory), 'current_front_page': front,
               'operation': 'cancel' if cancel else 'schedule', 'acknowledge_shared_page': True,
               'method': 'PUT', 'route': route + '/pages/page_id:' + page_id + '?no_verifiers=true',
               'body': {'wiki_page': {'publish_at': selected, 'notify_of_update': False}}, 'warning': WARNING}
    if selected is not None:
        _future(selected)  # Do not send a date that expired while fetching a long inventory.
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        result = _metadata(response, page_id)
        applied = result['publish_at']
        if ('publish_at' not in response or result['published'] or result['front_page'] or
                (applied is None) != (selected is None) or
                applied is not None and timestamp(applied) != timestamp(selected)):
            raise CanvasError('Canvas did not store the selected publication date and draft state')
        if any(result[key] != before[key] for key in ('page_id', 'title', 'url', 'editing_roles', 'front_page')):
            raise CanvasError('Unselected page metadata changed')
        next_route, next_context, next_rights = _scope(client, item, 'course')
        if (next_context != context or next_rights != rights or _feature(client, next_route, item) != feature or
                account(client) != identity):
            raise CanvasError('Scheduling account/course/permissions/root feature changed')
        stored = _page(client, next_route, page_id)
        if ({key: stored[key] for key in PAGE_FIELDS} != result or
                stored['body_digest'] != before['body_digest'] or digest(_html(response)) != before['body_digest']):
            raise CanvasError('Schedule acknowledgement/readback disagreed or page content changed')
        listed = _inventory(client, next_route, max_pages)
        if result not in listed or next((row for row in listed if row['front_page']), None) != front:
            raise CanvasError('The scheduled page/front-page inventory did not verify the result')
        if account(client) != identity:
            raise CanvasError('Account changed during schedule verification')
    except CanvasError:
        raise CanvasError(UNCERTAIN) from None
    return {'scheduled_page': {**result, 'html_url': client.host + '/courses/' + item + '/pages/' + quote(result['url'], safe='')},
            'course_id': int(item), 'operation': preview['operation'], 'publication_feature': feature,
            'stored_date_verified': True, 'draft_state_verified': True, 'content_unchanged': True,
            'acknowledgement_matches_readback': True, 'future_publication_verified': False,
            'note': 'One native PUT; exact page ID, stored date/draft state, unchanged content/metadata/front page '
                    'and stable account/course/update permission/root feature verified. This does not prove future '
                    'background-job execution, student visibility, cache propagation or an atomic lock. No automatic '
                    'retry, notification request, publication, rollback or repair.'}
