"""Guarded URL and plain-text assignment submissions."""

import hashlib
import html
import json
from urllib.parse import urlsplit

from .client import CanvasError


def prepare(client, course_id, assignment_id, submission_type, content):
    assignment, _ = client.request(f'/api/v1/courses/{course_id}/assignments/{assignment_id}')
    if str(assignment.get('id')) != assignment_id or (
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
    preview = {'course_id': course_id, 'assignment_id': assignment_id,
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
