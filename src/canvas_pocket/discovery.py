"""Find file references in course content the logged-in user can already read."""
import re
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit

from .client import CanvasError


def restricted(error):
    """Only permission/not-found failures may be skipped as partial coverage."""
    return error.status in (403, 404)


def file_index(client, course_id, max_pages, resolve=True, all_pages=False):
    """Use the Files API when available; label linked-content fallback incomplete."""
    base = f'/api/v1/courses/{course_id}'
    try:
        files = client.list(base + '/files?per_page=100', max_pages)
    except CanvasError as error:
        if error.status not in (403, 404):
            raise
        discovered = linked_files(client, course_id, max_pages, resolve, all_pages)
        return {
            'course_id': int(course_id), 'complete': False, 'source': 'linked-content',
            'files': discovered['files'], 'unavailable': [{'resource': 'files', 'status': error.status}],
            'skipped_sources': discovered['skipped_sources'], 'note': discovered['note'],
        }
    return {
        'course_id': int(course_id), 'complete': True, 'source': 'files-api',
        'files': [item for item in files if isinstance(item, dict) and not item.get('hidden_for_user')
                  and not item.get('locked_for_user')],
        'unavailable': [], 'skipped_sources': [],
        'note': 'Files visible through the course Files API to this user.',
    }


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        for key in ('href', 'src', 'data-api-endpoint'):
            if values.get(key):
                self.urls.append(values[key])


def referenced_ids(markup, host, course_id):
    parser = Links()
    parser.feed(markup or '')
    found = set()
    for raw in parser.urls:
        url = urlsplit(urljoin(host, raw))
        if f'{url.scheme}://{url.netloc}' != host:
            continue
        for pattern in (rf'/courses/{course_id}/files/(\d+)(?:/(?:download|preview))?',
                        rf'/api/v1/courses/{course_id}/files/(\d+)',
                        r'/api/v1/files/(\d+)'):
            match = re.fullmatch(pattern, url.path)
            if match:
                found.add(int(match.group(1)))
                break
    return found


def linked_files(client, course_id, max_pages, resolve=True, all_pages=False):
    base = f'/api/v1/courses/{course_id}'
    references = {}
    skipped = []

    def add(ids, source):
        for fid in ids:
            references.setdefault(int(fid), set()).add(source)

    try:
        syllabus, _ = client.request(base + '?include[]=syllabus_body')
        add(referenced_ids(syllabus.get('syllabus_body'), client.host, course_id), 'syllabus')
    except CanvasError as error:
        if not restricted(error):
            raise
        skipped.append('syllabus')
    try:
        modules = client.list(base + '/modules?include[]=items&per_page=100', max_pages)
    except CanvasError as error:
        if not restricted(error):
            raise
        skipped.append('modules')
        modules = []
    page_slugs = set()
    for module in modules:
        parts = module.get('items') or []
        if len(parts) < (module.get('items_count') or 0):
            try:
                parts = client.list(base + f"/modules/{module['id']}/items?per_page=100", max_pages)
            except CanvasError as error:
                if not restricted(error):
                    raise
                skipped.append(f"module: {module.get('name', module.get('id'))}")
                continue
        for item in parts:
            source = f"module: {module.get('name', module.get('id'))}"
            if item.get('type') == 'File' and item.get('content_id'):
                add([item['content_id']], source)
            if item.get('type') == 'Page' and item.get('page_url'):
                page_slugs.add((item['page_url'], item.get('title') or item['page_url']))
    if all_pages:
        try:
            pages = client.list(base + '/pages?per_page=100', max_pages)
            for page in pages:
                if page.get('published') is not False and not page.get('locked_for_user'):
                    slug = page.get('url')
                    if slug:
                        page_slugs.add((slug, page.get('title') or slug))
        except CanvasError as error:
            if not restricted(error):
                raise
            skipped.append('all pages')
    try:
        assignments = client.list(base + '/assignments?per_page=100', max_pages)
    except CanvasError as error:
        if not restricted(error):
            raise
        skipped.append('assignments')
        assignments = []
    for assignment in assignments:
        add(referenced_ids(assignment.get('description'), client.host, course_id),
            f"assignment: {assignment.get('name', assignment.get('id'))}")
    for kind, route in (
        ('announcements', base + '/discussion_topics?per_page=100&only_announcements=true'),
        ('discussions', base + '/discussion_topics?per_page=100'),
    ):
        try:
            topics = client.list(route, max_pages)
        except CanvasError as error:
            if not restricted(error):
                raise
            skipped.append(kind)
            continue
        for topic in topics:
            # A locked announcement can still be readable because replies are
            # closed. A locked discussion prompt may have an availability rule.
            if (not isinstance(topic, dict) or topic.get('published') is False or
                    (kind == 'discussions' and topic.get('locked_for_user'))):
                continue
            label = 'announcement' if kind == 'announcements' else 'discussion prompt'
            add(referenced_ids(topic.get('message'), client.host, course_id),
                f"{label}: {topic.get('title', topic.get('id'))}")
    for slug, title in sorted(page_slugs):
        try:
            page, _ = client.request(base + '/pages/' + quote(slug, safe=''))
            if page.get('published') is not False and not page.get('locked_for_user'):
                add(referenced_ids(page.get('body'), client.host, course_id), f'page: {title}')
        except CanvasError as error:
            if not restricted(error):
                raise
            skipped.append(f'page: {title}')

    files = []
    for fid, sources in sorted(references.items()):
        item = {'id': fid, 'sources': sorted(sources)}
        if not resolve:
            item['metadata_not_checked'] = True
            files.append(item)
            continue
        try:
            metadata, _ = client.request(base + f'/files/{fid}')
            locked = bool(metadata.get('locked_for_user'))
            hidden = bool(metadata.get('hidden_for_user'))
            item.update({'display_name': metadata.get('display_name'), 'size': metadata.get('size'),
                         'updated_at': metadata.get('updated_at'),
                         'modified_at': metadata.get('modified_at'),
                         'locked_for_user': locked, 'hidden_for_user': hidden,
                         'downloadable': not (locked or hidden) and bool(metadata.get('url'))})
        except CanvasError as error:
            if not restricted(error):
                raise
            item['metadata_unavailable'] = True
        files.append(item)
    return {'files': files, 'skipped_sources': skipped,
            'note': 'References from readable syllabus, modules, assignments, announcements, discussion prompts, and ' +
                    ('all listed published pages' if all_pages else 'module pages') +
                    ' only. This is not a complete course file listing.'}
