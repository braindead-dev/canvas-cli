"""Canvas's three-step file upload without forwarding API credentials to storage."""

import hashlib
import json
import mimetypes
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .client import CanvasError
from .group_content import ROOT_NOTE, base, folder
from .writes import account
from .writes import digest as revision_digest


def file_info(path, max_bytes):
    source = Path(path).expanduser()
    if source.is_symlink():
        raise CanvasError('Refusing a symlinked upload source')
    try:
        details = source.stat()
        if not stat.S_ISREG(details.st_mode):
            raise CanvasError('Upload source must be a regular file')
        if max_bytes < 1 or details.st_size < 1 or details.st_size > max_bytes:
            raise CanvasError('Upload file must be nonempty and within --max-bytes')
        digest = hashlib.sha256()
        total = 0
        with source.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                total += len(chunk)
                if total > max_bytes:
                    raise CanvasError('Upload file grew past --max-bytes')
                digest.update(chunk)
        if total != details.st_size or source.stat().st_size != details.st_size:
            raise CanvasError('Upload file changed during inspection')
    except OSError:
        raise CanvasError('Cannot read upload file') from None
    mime = mimetypes.guess_type(source.name)[0] or 'application/octet-stream'
    return {'source': str(source.resolve()), 'name': source.name,
            'size': details.st_size, 'content_type': mime, 'sha256': digest.hexdigest()}


@contextmanager
def staged_file(info, max_bytes):
    """Freeze exactly the inspected bytes before any native or storage write."""
    try:
        source = Path(info['source'])
        if source.is_symlink():
            raise CanvasError('Refusing a symlinked upload source')
        with source.open('rb') as stream, tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode='w+b') as staged:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_size != info['size']:
                raise CanvasError('Upload file changed after preview')
            current = hashlib.sha256()
            total = 0
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                current.update(chunk)
                staged.write(chunk)
                total += len(chunk)
                if total > max_bytes:
                    raise CanvasError('Upload file grew past --max-bytes')
            if total != info['size'] or current.hexdigest() != info['sha256']:
                raise CanvasError('Upload file changed after preview')
            staged.seek(0)
            yield staged
    except OSError:
        raise CanvasError('Upload file became unreadable; verify in Canvas before retrying') from None


def _destination(client, identity, context_type, context_id, folder_id):
    """Resolve a real, existing folder without implicit path creation or fallback."""
    if context_type is None:
        kind, item, route = 'user', str(identity['user_id']), '/api/v1/users/self'
        context = {'id': identity['user_id'], 'name': 'Own user'}
    else:
        kind, item = context_type, context_id
        route = base(item, kind)
        context, _ = client.request(route)
        if (not isinstance(context, dict) or type(context.get('id')) is not int or
                context['id'] != int(item) or context.get('workflow_state') in ('deleted', 'unpublished')):
            raise CanvasError('Canvas returned a different or unavailable upload context')
    row, _ = client.request(route + '/folders/' + (folder_id or 'root'))
    details = folder(row, item, kind)
    if folder_id is not None and details['id'] != int(folder_id):
        raise CanvasError('Canvas returned a different upload folder')
    if folder_id is None and details.get('parent_folder_id') is not None:
        raise CanvasError('Canvas did not return the upload context root')
    if (details.get('locked_for_user') or details.get('hidden_for_user') or
            details.get('for_submissions') or row.get('workflow_state') == 'deleted'):
        raise CanvasError('Upload folder is unavailable or read-only for submissions')
    fields = ('id', 'name', 'full_name', 'context_type', 'context_id', 'parent_folder_id',
              'locked', 'hidden', 'lock_at', 'unlock_at', 'locked_for_user', 'hidden_for_user', 'for_submissions')
    target = {'kind': 'context_files' if context_type else 'personal_files', 'context_type': kind,
              'context_id': int(item), 'context_name': context.get('name'),
              'context_revision': revision_digest({key: context.get(key) for key in ('id', 'name', 'workflow_state')}),
              'folder': {key: details[key] for key in fields if key in details},
              'on_duplicate': 'rename',
              'warning': 'This uploads to the selected existing folder, not an assignment submission. '
                         'Course/group files may be visible to others according to native permissions. '
                         'No visibility flags are requested; Canvas defaults apply. Reading a folder does '
                         'not prove Manage Files permission; Canvas enforces upload authorization.'}
    if folder_id is None:
        target['root_read_note'] = ROOT_NOTE
    return route + '/files', target


def prepare(client, source, max_bytes, course_id=None, assignment_id=None, *,
            context_type=None, context_id=None, folder_id=None):
    if context_type is not None:
        if context_type not in ('course', 'group') or course_id is not None or assignment_id is not None:
            raise CanvasError('Choose one explicit course/group upload context, not an assignment')
        base(context_id, context_type)
    elif context_id is not None:
        raise CanvasError('An upload context ID requires an explicit context type')
    if folder_id is not None:
        base(folder_id, 'user')  # canonical numeric ID validation before network/file inspection
        if assignment_id is not None:
            raise CanvasError('Assignment-file uploads do not accept a folder destination')
    if type(max_bytes) is not int or max_bytes < 1:
        raise CanvasError('--max-bytes must be a positive integer')
    info = file_info(source, max_bytes)
    identity = account(client)
    if context_type is not None or folder_id is not None:
        route, target = _destination(client, identity, context_type, context_id, folder_id)
    elif assignment_id:
        assignment, _ = client.request(f'/api/v1/courses/{course_id}/assignments/{assignment_id}')
        if not isinstance(assignment, dict) or str(assignment.get('id')) != assignment_id or (
                assignment.get('course_id') is not None and
                str(assignment['course_id']) != course_id):
            raise CanvasError('Canvas returned a different assignment; refusing upload')
        if assignment.get('published') is False or assignment.get('locked_for_user'):
            raise CanvasError('Assignment is unpublished or locked for this user')
        if 'online_upload' not in (assignment.get('submission_types') or []):
            raise CanvasError('Assignment does not allow file submissions')
        allowed = assignment.get('allowed_extensions') or []
        if allowed and info['name'].rsplit('.', 1)[-1].lower() not in {
                str(extension).lstrip('.').lower() for extension in allowed}:
            raise CanvasError('File extension is not allowed by this assignment')
        route = (f'/api/v1/courses/{course_id}/assignments/{assignment_id}'
                 '/submissions/self/files')
        target = {'kind': 'assignment_file_only', 'course_id': course_id,
                  'assignment_id': assignment_id, 'assignment_name': assignment.get('name'),
                  'due_at': assignment.get('due_at'), 'lock_at': assignment.get('lock_at'),
                  'note': 'Uploading the file does not submit the assignment.'}
    else:
        route = '/api/v1/users/self/files'
        target = {'kind': 'personal_files', 'on_duplicate': 'rename'}
    preview = {**identity, 'file': info, 'destination': target, 'init_route': route,
               'max_bytes': max_bytes}
    digest = hashlib.sha256(json.dumps(preview, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return preview, digest


def _upload_to_storage(url, params, stream, name, content_type):
    if not isinstance(url, str):
        raise CanvasError('Canvas returned an unsafe storage URL; upload not attempted')
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise CanvasError('Canvas returned an unsafe storage URL; upload not attempted')
    if not isinstance(params, dict) or 'file' in params or not all(
            isinstance(key, str) and isinstance(value, (str, int, float))
            for key, value in params.items()):
        raise CanvasError('Canvas returned unsupported upload parameters; upload not attempted')
    # HTTPX serializes data fields before the file part. This request has no Canvas
    # Authorization header, cookies or shared Canvas API client.
    try:
        with httpx.Client(follow_redirects=False, timeout=httpx.Timeout(60, connect=15)) as storage:
            response = storage.post(url, data={key: str(value) for key, value in params.items()},
                                    files={'file': (name, stream, content_type)},
                                    headers={'User-Agent': 'canvas-cli/0.1.0'})
    except (httpx.HTTPError, OSError):
        raise CanvasError('Storage upload outcome uncertain; verify in Canvas before retrying. No signed URL logged.') from None
    if response.status_code not in (201, 301, 302, 303, 307, 308):
        raise CanvasError(f'Storage upload HTTP {response.status_code}; verify in Canvas before retrying.')
    location = response.headers.get('Location')
    if not location:
        raise CanvasError('Storage gave no confirmation Location; verify in Canvas before retrying.')
    return location


def upload(client, source, max_bytes=25 * 1024 * 1024, course_id=None,
           assignment_id=None, yes=False, confirm=None, *,
           context_type=None, context_id=None, folder_id=None):
    if bool(yes) != bool(confirm):
        raise CanvasError('Uploading requires both --yes and --confirm from a prior preview')
    options = ({'context_type': context_type, 'context_id': context_id, 'folder_id': folder_id}
               if context_type is not None or context_id is not None or folder_id is not None else {})
    preview, digest = prepare(client, source, max_bytes, course_id, assignment_id, **options)
    if not yes:
        return {'dry_run': True, **preview, 'confirm': digest,
                'next': 'Review source, hash and destination, then repeat with --yes --confirm DIGEST.'}
    if confirm != digest:
        raise CanvasError('Preview changed (file or destination); review a fresh preview before uploading')
    info = preview['file']
    initial = {'name': info['name'], 'size': info['size'],
               'content_type': info['content_type']}
    if not assignment_id:
        initial['on_duplicate'] = 'rename'
    destination = preview['destination']
    if 'folder' in destination:
        initial['parent_folder_id'] = destination['folder']['id']
    try:
        with staged_file(info, max_bytes) as staged:
            response, _ = client.request(preview['init_route'], 'POST', initial)
            if not isinstance(response, dict) or not response.get('upload_url'):
                raise CanvasError('Canvas did not provide a direct upload URL; verify in Canvas before retrying')
            location = _upload_to_storage(response['upload_url'], response.get('upload_params'),
                                          staged, info['name'], info['content_type'])
    except OSError:
        raise CanvasError('Upload file became unreadable; verify in Canvas before retrying') from None
    # Only the normal Canvas API client can confirm, and it rejects other origins.
    try:
        file_record, _ = client.request(location)
    except CanvasError:
        raise CanvasError('Storage may have the file, but Canvas confirmation failed; verify before retrying') from None
    if (not isinstance(file_record, dict) or type(file_record.get('id')) is not int or file_record['id'] < 1):
        raise CanvasError('Canvas did not return a file ID; verify before retrying')
    if 'folder' in destination:
        try:
            _verify_file(file_record, info, destination)
            prefix = ('/api/v1/users/self' if destination['context_type'] == 'user' else
                      base(str(destination['context_id']), destination['context_type']))
            scoped, _ = client.request(prefix + f'/files/{file_record["id"]}')
            if not isinstance(scoped, dict) or scoped.get('id') != file_record['id']:
                raise CanvasError('Wrong uploaded file')
            _verify_file(scoped, info, destination)
        except CanvasError:
            raise CanvasError('File upload may have succeeded, but its scoped destination/size could not be verified. '
                              'Check Canvas before repeating; no automatic retry or response-body logging.') from None
    return {'uploaded_file_id': file_record['id'], 'destination': preview['destination'],
            'name': info['name'], 'bytes': info['size'],
            'note': ('File uploaded but assignment not submitted.' if assignment_id
                     else 'File uploaded and scoped folder/size verified; duplicate names were renamed. '
                          'Canvas permissions/default visibility apply; no assignment submitted.' if 'folder' in destination
                     else 'Personal file uploaded; duplicate names were renamed.')}


def _verify_file(row, info, destination):
    if (type(row.get('id')) is not int or row['id'] < 1 or
            type(row.get('folder_id')) is not int or row['folder_id'] != destination['folder']['id'] or
            type(row.get('size')) is not int or row['size'] != info['size'] or
            not isinstance(row.get('display_name'), str) or not row['display_name'] or
            row.get('locked_for_user') or row.get('hidden_for_user') or row.get('workflow_state') == 'deleted'):
        raise CanvasError('Uploaded file metadata mismatch')
    if row.get('context_type') is not None and row['context_type'] != destination['context_type'].title():
        raise CanvasError('Uploaded file context mismatch')
    if row.get('context_id') is not None and (type(row['context_id']) is not int or row['context_id'] != destination['context_id']):
        raise CanvasError('Uploaded file context mismatch')
    field = destination['context_type'] + '_id'
    if row.get(field) is not None and (type(row[field]) is not int or row[field] != destination['context_id']):
        raise CanvasError('Uploaded file context mismatch')
