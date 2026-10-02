"""Explicit asynchronous course exports with private, credential-free downloads."""

import re
from urllib.parse import urljoin, urlsplit

from .client import CanvasError
from .download import download
from .writes import account, check_flags, confirmed

SELECTION_TYPES = frozenset(('folders', 'files', 'attachments', 'assignments', 'announcements',
                            'calendar_events', 'discussion_topics', 'modules', 'module_items',
                            'pages', 'rubrics'))


def summary(record, expected_id=None):
    if (not isinstance(record, dict) or type(record.get('id')) is not int or record['id'] < 1
            or (expected_id is not None and str(record['id']) != expected_id)):
        raise CanvasError('Canvas returned a different or malformed export job')
    attachment = record.get('attachment')
    if attachment is not None and not isinstance(attachment, dict):
        raise CanvasError('Canvas returned malformed export attachment metadata')
    result = {key: record.get(key) for key in
              ('id', 'created_at', 'export_type', 'user_id', 'workflow_state')}
    result['download_available'] = bool(attachment and attachment.get('url') and
                                        record.get('workflow_state') == 'exported')
    result['progress_available'] = bool(record.get('progress_url'))
    return result  # No signed attachment or progress URLs in normal output.


def list_exports(client, course_id, max_pages):
    rows = client.list(f'/api/v1/courses/{course_id}/content_exports?per_page=100', max_pages)
    return [summary(row) for row in rows]


def read_export(client, course_id, export_id):
    record, _ = client.request(f'/api/v1/courses/{course_id}/content_exports/{export_id}')
    summary(record, export_id)
    return record


def status(client, course_id, export_id, with_progress=False):
    record = read_export(client, course_id, export_id)
    result = {'course_id': int(course_id), 'export': summary(record), 'progress': None}
    progress_url = record.get('progress_url')
    if with_progress and progress_url:
        if not isinstance(progress_url, str):
            raise CanvasError('Canvas returned malformed export progress metadata')
        url = urlsplit(urljoin(client.host, progress_url))
        match = re.fullmatch(r'/api/v1/progress/([1-9][0-9]*)', url.path)
        if (f'{url.scheme}://{url.netloc}' != client.host or url.query or url.fragment or
                url.username or url.password or not match):
            raise CanvasError('Export progress link is not a same-origin Canvas progress resource')
        progress, _ = client.request(url.path)
        if not isinstance(progress, dict) or str(progress.get('id')) != match[1]:
            raise CanvasError('Canvas returned a different progress job')
        result['progress'] = {key: progress.get(key) for key in
                              ('id', 'workflow_state', 'completion', 'tag', 'created_at', 'updated_at')}
    result['note'] = 'A queued/running job is not a finished export. Recheck this same job; do not create a duplicate.'
    return result


def create(client, course_id, export_type='zip', select=(), skip_notifications=False,
           yes=False, confirm=None):
    check_flags(yes, confirm)
    if export_type not in ('zip', 'common_cartridge'):
        raise CanvasError('Supported export types are zip and common_cartridge')
    selected = {}
    for kind, identifier in select:
        allowed = ('files', 'folders') if export_type == 'zip' else SELECTION_TYPES
        if kind not in allowed or not isinstance(identifier, str) or not identifier.isdecimal() or int(identifier) < 1:
            raise CanvasError('Selection is not supported for this export type')
        value = int(identifier)
        selected.setdefault(kind, [])
        if value in selected[kind]:
            raise CanvasError('Duplicate export selection refused')
        selected[kind].append(value)
    identity = account(client)
    course, _ = client.request(f'/api/v1/courses/{course_id}')
    if not isinstance(course, dict) or str(course.get('id')) != course_id:
        raise CanvasError('Canvas returned a different course; refusing export creation')
    body = {'export_type': export_type, 'skip_notifications': bool(skip_notifications)}
    if selected:
        body['select'] = selected
    preview = {**identity, 'course': {key: course.get(key) for key in ('id', 'name', 'course_code')},
               'method': 'POST', 'route': f'/api/v1/courses/{course_id}/content_exports', 'body': body,
               'effect': 'Starts an asynchronous export job, not an immediate download. '
                         'Canvas role permissions decide access; course materials may be private or copyrighted.'}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        result = summary(response)
        if (type(response.get('user_id')) is not int or response['user_id'] != identity['user_id']
                or response.get('export_type') != export_type):
            raise CanvasError('Export identity was not confirmed')
    except CanvasError:
        raise CanvasError('Export creation outcome uncertain; inspect exports in Canvas before repeating it') from None
    return {'course_id': int(course_id), 'export': result,
            'note': 'Export job returned. Recheck export-status before downloading; creation was not retried.'}


def download_export(client, course_id, export_id, destination, max_bytes=100 * 1024 * 1024):
    record = read_export(client, course_id, export_id)
    if record.get('workflow_state') != 'exported':
        raise CanvasError('Export is not finished; recheck the same job rather than starting another')
    attachment = record.get('attachment') or {}
    if not isinstance(attachment.get('url'), str) or not attachment['url']:
        raise CanvasError('Export download is unavailable or expired; no file was written')
    if attachment.get('locked_for_user') or attachment.get('hidden_for_user'):
        raise CanvasError('Export attachment is locked or hidden for this user')
    saved = download(attachment['url'], destination, max_bytes,
                     expected_bytes=attachment.get('size'))
    return {**saved, 'course_id': int(course_id), 'export_id': int(export_id),
            'export_type': record.get('export_type')}
