"""Search visible course titles via documented Canvas list filters."""

from urllib.parse import urlencode

from .client import CanvasError

AREAS = (
    ('assignments', 'assignments'),
    ('discussions', 'discussion_topics'),
    ('pages', 'pages'),
    ('files', 'files'),
    ('modules', 'modules'),
)


def find(client, course_id, query, max_pages=100, selected=None):
    query = query.strip()
    if not query or len(query) > 200:
        raise CanvasError('Use a nonempty query of at most 200 characters')
    choices = [pair for pair in AREAS if selected in (None, pair[0])]
    results, unavailable, coverage = [], {}, {}
    for area, resource in choices:
        params = [('per_page', '100'), ('search_term', query)]
        if area == 'pages':
            params.append(('published', 'true'))
        if area == 'modules':
            params.append(('include[]', 'items'))
        route = f'/api/v1/courses/{course_id}/{resource}?' + urlencode(params)
        try:
            rows = client.list(route, max_pages)
        except CanvasError as error:
            if area == 'files' and error.status in (403, 404):
                from .discovery import linked_files
                try:
                    index = linked_files(client, course_id, max_pages)
                except CanvasError as fallback_error:
                    if fallback_error.status == 429:
                        unavailable[area] = str(fallback_error)
                        coverage[area] = 'unavailable'
                        for remaining, _ in choices[choices.index((area, resource)) + 1:]:
                            coverage[remaining] = 'not_checked_after_rate_limit'
                        break
                    if fallback_error.status not in (403, 404):
                        raise
                    unavailable[area] = f'{error}; linked-file fallback: {fallback_error}'
                    coverage[area] = 'unavailable'
                    continue
                coverage[area] = ('linked_files_partially_searched' if index['skipped_sources']
                                  else 'linked_files_only')
                unavailable[area] = ('Canvas Files list unavailable; only accessible linked files searched'
                                     + (f'; {len(index["skipped_sources"])} source(s) also unavailable'
                                        if index['skipped_sources'] else ''))
                for file in index['files']:
                    if not file.get('downloadable'):
                        continue
                    title = file.get('display_name') or ''
                    if query.casefold() in title.casefold():
                        results.append({'area': 'file', 'id': file['id'],
                                        'title': title, 'due_at': None})
                continue
            if area == 'pages' and error.status in (403, 404):
                from .pages import module_page_index
                try:
                    index = module_page_index(client, course_id, max_pages, error.status)
                except CanvasError as fallback_error:
                    if fallback_error.status == 429:
                        unavailable[area] = str(fallback_error)
                        coverage[area] = 'unavailable'
                        for remaining, _ in choices[choices.index((area, resource)) + 1:]:
                            coverage[remaining] = 'not_checked_after_rate_limit'
                        break
                    if fallback_error.status not in (403, 404):
                        raise
                    unavailable[area] = f'{error}; module fallback: {fallback_error}'
                    coverage[area] = 'unavailable'
                    continue
                else:
                    blocked = [item for item in index['unavailable']
                               if item['resource'] != 'pages']
                    coverage[area] = ('module_pages_partially_searched' if blocked else
                                      'module_pages_only') if not index['complete'] else 'searched'
                    if not index['complete']:
                        unavailable[area] = ('Canvas pages list unavailable; only visible module pages searched'
                                             + (f'; {len(blocked)} module/page resource(s) also unavailable'
                                                if blocked else ''))
                    for page in index['pages']:
                        title = page.get('title') or page.get('url') or ''
                        if query.casefold() in title.casefold():
                            results.append({'area': 'page', 'id': page.get('url'),
                                            'title': title, 'due_at': None})
                    continue
            unavailable[area] = str(error)
            coverage[area] = 'unavailable'
            if error.status == 429:
                for remaining, _ in choices[choices.index((area, resource)) + 1:]:
                    coverage[remaining] = 'not_checked_after_rate_limit'
                break
            if error.status not in (403, 404):
                raise
            continue
        coverage[area] = 'searched'
        for row in rows:
            if not isinstance(row, dict) or row.get('published') is False or row.get('locked_for_user'):
                continue
            title = row.get('display_name') or row.get('name') or row.get('title') or row.get('url') or ''
            kind = area[:-1] if area != 'discussions' else 'discussion'
            if query.casefold() in str(title).casefold():
                results.append({'area': kind, 'id': row.get('id') or row.get('url'),
                                'title': title, 'due_at': row.get('due_at')})
            if area == 'modules':
                if row.get('items') is None:
                    coverage[area] = 'searched_module_names_items_may_be_omitted'
                else:
                    for item in row['items']:
                        if (isinstance(item, dict) and not item.get('locked_for_user') and
                                query.casefold() in str(item.get('title') or '').casefold()):
                            results.append({'area': 'module_item', 'id': item.get('id'),
                                            'title': item.get('title'), 'module_id': row.get('id'),
                                            'due_at': None})
    return {'course_id': course_id, 'query': query, 'results': results,
            'coverage': coverage, 'unavailable': unavailable,
            'complete': not unavailable and all(value == 'searched' for value in coverage.values()),
            'note': 'Title/name search only. Missing or restricted endpoints and omitted module items can hide matches.'}
