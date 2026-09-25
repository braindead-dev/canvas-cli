"""Find file references in course content the logged-in user can already read."""
from html.parser import HTMLParser
from urllib.parse import quote, urlsplit, urljoin
import re
from .client import CanvasError


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
        match = re.fullmatch(rf'/courses/{course_id}/files/(\d+)(?:/(?:download|preview))?', url.path)
        if match:
            found.add(int(match.group(1)))
    return found


def linked_files(client, course_id, max_pages):
    base = f'/api/v1/courses/{course_id}'
    references = {}
    skipped = []

    def add(ids, source):
        for fid in ids:
            references.setdefault(int(fid), set()).add(source)

    try:
        syllabus, _ = client.request(base + '?include[]=syllabus_body')
        add(referenced_ids(syllabus.get('syllabus_body'), client.host, course_id), 'syllabus')
    except CanvasError:
        skipped.append('syllabus')
    try:
        modules = client.list(base + '/modules?include[]=items&per_page=100', max_pages)
    except CanvasError:
        skipped.append('modules')
        modules = []
    page_slugs = set()
    for module in modules:
        parts = module.get('items') or []
        if len(parts) < (module.get('items_count') or 0):
            try:
                parts = client.list(base + f"/modules/{module['id']}/items?per_page=100", max_pages)
            except CanvasError:
                skipped.append(f"module: {module.get('name', module.get('id'))}")
                continue
        for item in parts:
            source = f"module: {module.get('name', module.get('id'))}"
            if item.get('type') == 'File' and item.get('content_id'):
                add([item['content_id']], source)
            if item.get('type') == 'Page' and item.get('page_url'):
                page_slugs.add((item['page_url'], item.get('title') or item['page_url']))
    try:
        assignments = client.list(base + '/assignments?per_page=100', max_pages)
    except CanvasError:
        skipped.append('assignments')
        assignments = []
    for assignment in assignments:
        add(referenced_ids(assignment.get('description'), client.host, course_id),
            f"assignment: {assignment.get('name', assignment.get('id'))}")
    for slug, title in sorted(page_slugs):
        try:
            page, _ = client.request(base + '/pages/' + quote(slug, safe=''))
            add(referenced_ids(page.get('body'), client.host, course_id), f'page: {title}')
        except CanvasError:
            skipped.append(f'page: {title}')

    files = []
    for fid, sources in sorted(references.items()):
        item = {'id': fid, 'sources': sorted(sources)}
        try:
            metadata, _ = client.request(base + f'/files/{fid}')
            item.update({'display_name': metadata.get('display_name'), 'size': metadata.get('size'),
                         'locked_for_user': metadata.get('locked_for_user', False)})
        except CanvasError:
            item['metadata_unavailable'] = True
        files.append(item)
    return {'files': files, 'skipped_sources': skipped,
            'note': 'References from readable syllabus, modules, module pages, and assignments only. This is not a complete course file listing.'}
