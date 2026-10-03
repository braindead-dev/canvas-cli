"""Guarded URL and plain-text assignment submissions."""

import hashlib
import html
import json
from urllib.parse import urlsplit

from .client import CanvasError
from .writes import account


def prepare(client, course_id, assignment_id, submission_type, content):
    identity = account(client)
    assignment, _ = client.request(f'/api/v1/courses/{course_id}/assignments/{assignment_id}')
    if not isinstance(assignment, dict) or str(assignment.get('id')) != assignment_id or (
            assignment.get('course_id') is not None and
            str(assignment['course_id']) != course_id):
        raise CanvasError('Canvas returned a different assignment; refusing submission')
    if assignment.get('published') is False or assignment.get('locked_for_user'):
        raise CanvasError('Assignment is unpublished or locked for this user')
    if submission_type not in (assignment.get('submission_types') or []):
        raise CanvasError('Assignment does not allow this submission type')
    content = content.strip()
    if not content:
        raise CanvasError('Empty submission refused')
    if submission_type == 'online_url':
        url = urlsplit(content)
        if (url.scheme not in ('http', 'https') or not url.hostname or
                url.username or url.password or any(ch.isspace() for ch in content)):
            raise CanvasError('Submission URL must be absolute HTTP(S) without embedded credentials')
        details = {'url': content}
    elif submission_type == 'online_text_entry':
        details = {'body': '<p>' + html.escape(content).replace('\n', '<br>') + '</p>'}
    else:
        raise CanvasError('Unsupported submission type')
    route = f'/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions'
    body = {'submission': {'submission_type': submission_type, **details}}
    preview = {**identity, 'course_id': course_id, 'assignment_id': assignment_id,
               'assignment_name': assignment.get('name'),
               'due_at': assignment.get('due_at'), 'lock_at': assignment.get('lock_at'),
               'submission_types': assignment.get('submission_types'),
               'route': route, 'body': body}
    digest = hashlib.sha256(json.dumps(preview, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return preview, digest


def submit(client, course_id, assignment_id, submission_type, content,
           yes=False, confirm=None):
    if bool(yes) != bool(confirm):
        raise CanvasError('Sending requires both --yes and --confirm from a prior preview')
    preview, digest = prepare(client, course_id, assignment_id, submission_type, content)
    if not yes:
        return {'dry_run': True, **preview, 'confirm': digest,
                'next': 'Review the assignment and exact body, then repeat with --yes --confirm DIGEST.'}
    if confirm != digest:
        raise CanvasError('Preview changed (assignment or content); review a fresh preview before submitting')
    return client.request(preview['route'], 'POST', preview['body'])[0]


def prepare_file(client, course_id, assignment_id, file_id):
    """Preview already uploaded files; never upload or submit in this step.

    A single ID remains supported; passing a sequence submits all selected IDs.
    """
    try:
        file_ids = [file_id] if isinstance(file_id, str) else list(file_id)
    except TypeError:
        raise CanvasError('Choose one or more distinct positive Canvas file IDs') from None
    if (not file_ids or any(not isinstance(n, str) or not n.isdecimal() or int(n) < 1
                            for n in file_ids) or len(set(file_ids)) != len(file_ids)):
        raise CanvasError('Choose one or more distinct positive Canvas file IDs')
    file_ids = [str(int(n)) for n in file_ids]
    if len(set(file_ids)) != len(file_ids):
        raise CanvasError('Choose one or more distinct positive Canvas file IDs')
    identity = account(client)
    assignment, _ = client.request(f'/api/v1/courses/{course_id}/assignments/{assignment_id}')
    if (not isinstance(assignment, dict) or str(assignment.get('id')) != assignment_id or
            (assignment.get('course_id') is not None and
             str(assignment['course_id']) != course_id)):
        raise CanvasError('Canvas returned a different assignment; refusing submission')
    if assignment.get('published') is False or assignment.get('locked_for_user'):
        raise CanvasError('Assignment is unpublished or locked for this user')
    if 'online_upload' not in (assignment.get('submission_types') or []):
        raise CanvasError('Assignment does not allow file submissions')
    allowed = assignment.get('allowed_extensions') or []
    files = []
    for selected_id in file_ids:
        file_record, _ = client.request(f'/api/v1/files/{selected_id}')
        if not isinstance(file_record, dict) or str(file_record.get('id')) != selected_id:
            raise CanvasError('Canvas returned a different file; refusing submission')
        if file_record.get('locked_for_user') or file_record.get('hidden_for_user'):
            raise CanvasError('File is locked or hidden for this user')
        if type(file_record.get('size')) is not int or file_record['size'] < 1:
            raise CanvasError('File has no confirmed nonempty size')
        name = file_record.get('display_name') or file_record.get('filename') or ''
        if not isinstance(name, str) or (allowed and name.rsplit('.', 1)[-1].lower() not in {
                str(extension).lstrip('.').lower() for extension in allowed}):
            raise CanvasError('File extension is not allowed by this assignment')
        files.append({'id': int(selected_id), 'name': name, 'size': file_record['size'],
                      'uuid': file_record.get('uuid'), 'updated_at': file_record.get('updated_at')})
    route = f'/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions'
    body = {'submission': {'submission_type': 'online_upload', 'file_ids': [int(n) for n in file_ids]}}
    preview = {**identity, 'course_id': course_id, 'assignment_id': assignment_id,
               'assignment_name': assignment.get('name'), 'due_at': assignment.get('due_at'),
               'lock_at': assignment.get('lock_at'),
               'files': files,
               'route': route, 'body': body}
    if len(files) == 1:
        preview['file'] = files[0]  # Preserve the single-file preview field for existing callers.
    digest = hashlib.sha256(json.dumps(preview, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return preview, digest


def submit_file(client, course_id, assignment_id, file_id, yes=False, confirm=None):
    if bool(yes) != bool(confirm):
        raise CanvasError('Sending requires both --yes and --confirm from a prior preview')
    preview, digest = prepare_file(client, course_id, assignment_id, file_id)
    if not yes:
        return {'dry_run': True, **preview, 'confirm': digest,
                'next': 'Review the assignment and exact file, then repeat with --yes --confirm DIGEST.'}
    if confirm != digest:
        raise CanvasError('Preview changed (assignment or file); review a fresh preview before submitting')
    return client.request(preview['route'], 'POST', preview['body'])[0]
