"""Best-effort index of pages the current Canvas user may read."""

from urllib.parse import quote

from .client import CanvasError


def page_index(client, course_id, max_pages):
    """Return an explicit coverage envelope; module fallback is never a full list."""
    base = f'/api/v1/courses/{course_id}'
    try:
        listed = client.list(base + '/pages?per_page=100', max_pages)
    except CanvasError as error:
        if error.status not in (403, 404):
            raise
        return module_page_index(client, course_id, max_pages, error.status)
    return {
        'course_id': int(course_id), 'complete': True, 'source': 'pages-api',
        'pages': [page for page in listed if visible(page)], 'unavailable': [],
    }


def visible(item):
    return (item.get('published') is not False
            and item.get('state') != 'unpublished'
            and not item.get('locked_for_user')
            and not item.get('hidden_for_user'))


def module_page_index(client, course_id, max_pages, listing_status):
    base = f'/api/v1/courses/{course_id}'
    modules = client.list(base + '/modules?per_page=100', max_pages)
    slugs = {}
    unavailable = [{'resource': 'pages', 'status': listing_status}]
    for module in modules:
        if not visible(module):
            continue
        module_id = module.get('id')
        if not module_id:
            continue
        try:
            items = client.list(base + f'/modules/{module_id}/items?per_page=100', max_pages)
        except CanvasError as error:
            if error.status not in (403, 404):
                raise
            unavailable.append({'resource': f'module {module_id} items', 'status': error.status})
            continue
        for item in items:
            if item.get('type') != 'Page' or not item.get('page_url') or not visible(item):
                continue
            slug = item['page_url']
            module_ids = slugs.setdefault(slug, {'url': slug, 'module_ids': []})['module_ids']
            if module_id not in module_ids:
                module_ids.append(module_id)
    pages = []
    for slug, entry in slugs.items():
        try:
            page, _ = client.request(base + '/pages/' + quote(slug, safe=''))
        except CanvasError as error:
            if error.status not in (403, 404):
                raise
            unavailable.append({'resource': f'page {slug}', 'status': error.status})
            continue
        if not isinstance(page, dict) or page.get('url') != slug or not visible(page):
            continue
        pages.append({**entry, 'title': page.get('title'), 'updated_at': page.get('updated_at')})
    return {
        'course_id': int(course_id), 'complete': False,
        'source': 'module-pages', 'pages': pages, 'unavailable': unavailable,
        'note': 'Only readable pages linked from visible modules were found; other course pages may exist.',
    }
