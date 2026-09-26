"""Canvas's three-step file upload without forwarding API credentials to storage."""

import hashlib
import json
import mimetypes
import os
from pathlib import Path
import stat
from urllib.parse import urlsplit

import httpx

from .client import CanvasError


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
        with source.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        if source.stat().st_size != details.st_size:
            raise CanvasError('Upload file changed during inspection')
    except OSError:
        raise CanvasError('Cannot read upload file') from None
    mime = mimetypes.guess_type(source.name)[0] or 'application/octet-stream'
    return {'source': str(source.resolve()), 'name': source.name,
            'size': details.st_size, 'content_type': mime, 'sha256': digest.hexdigest()}


def prepare(client, source, max_bytes, course_id=None, assignment_id=None):
    info = file_info(source, max_bytes)
    if assignment_id:
        assignment, _ = client.request(f'/api/v1/courses/{course_id}/assignments/{assignment_id}')
        if str(assignment.get('id')) != assignment_id or (
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
    preview = {'file': info, 'destination': target, 'init_route': route,
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
                                    headers={'User-Agent': 'canvas-pocket/0.1.0'})
    except (httpx.HTTPError, OSError):
        raise CanvasError('Storage upload outcome uncertain; verify in Canvas before retrying. No signed URL logged.') from None
    if response.status_code not in (201, 301, 302, 303, 307, 308):
        raise CanvasError(f'Storage upload HTTP {response.status_code}; verify in Canvas before retrying.')
    location = response.headers.get('Location')
    if not location:
        raise CanvasError('Storage gave no confirmation Location; verify in Canvas before retrying.')
    return location


def upload(client, source, max_bytes=25 * 1024 * 1024, course_id=None,
           assignment_id=None, yes=False, confirm=None):
    if bool(yes) != bool(confirm):
        raise CanvasError('Uploading requires both --yes and --confirm from a prior preview')
    preview, digest = prepare(client, source, max_bytes, course_id, assignment_id)
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
    try:
        with Path(info['source']).open('rb') as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_size != info['size']:
                raise CanvasError('Upload file changed after preview')
            current = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                current.update(chunk)
            if current.hexdigest() != info['sha256']:
                raise CanvasError('Upload file changed after preview')
            stream.seek(0)
            response, _ = client.request(preview['init_route'], 'POST', initial)
            if not isinstance(response, dict) or not response.get('upload_url'):
                raise CanvasError('Canvas did not provide a direct upload URL; verify in Canvas before retrying')
            location = _upload_to_storage(response['upload_url'], response.get('upload_params'),
                                          stream, info['name'], info['content_type'])
    except OSError:
        raise CanvasError('Upload file became unreadable; verify in Canvas before retrying') from None
    # Only the normal Canvas API client can confirm, and it rejects other origins.
    try:
        file_record, _ = client.request(location)
    except CanvasError:
        raise CanvasError('Storage may have the file, but Canvas confirmation failed; verify before retrying') from None
    if not isinstance(file_record, dict) or not file_record.get('id'):
        raise CanvasError('Canvas did not return a file ID; verify before retrying')
    return {'uploaded_file_id': file_record['id'], 'destination': preview['destination'],
            'name': info['name'], 'bytes': info['size'],
            'note': ('File uploaded but assignment not submitted.' if assignment_id
                     else 'Personal file uploaded; duplicate names were renamed.')}
