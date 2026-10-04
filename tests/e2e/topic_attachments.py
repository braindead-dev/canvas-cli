"""Independent native multipart parsing and association-before-store failure model."""

import copy
from email import policy
from email.parser import BytesParser
from urllib.parse import parse_qs, urlsplit

from .announcement_authoring import _scoped
from .appointments import _send


def initialize(state):
    state.attachment_enabled = False
    state.attachment_parts = []
    state.attachment_destroyed = []
    state.attachment_ignore = state.attachment_late_drop_attach = state.attachment_quota_denied = False
    state.attachment_error_after_removal = state.attachment_error_after_store = state.attachment_lose_attach = False
    state.attachment_ack_patch = None


def write(state, handler, raw):
    if not state.attachment_enabled:
        return False
    url = urlsplit(handler.path)
    announcement = state.announcement_enabled
    prefix = ('/api/v1/groups/123' if '/groups/' in url.path else '/api/v1/courses/123') if announcement else (
              '/api/v1/groups/119' if '/groups/' in url.path else '/api/v1/courses/111')
    identifier = 9 if announcement else 901
    rows = state.announcements if announcement else state.managed_topics
    if (handler.command != 'PUT' or url.path != prefix + '/discussion_topics/' + str(identifier) or
            parse_qs(url.query) != {'no_verifiers': ['true']}):
        _send(handler, {'private': 'synthetic-private-invalid-attachment-route'}, 400)
        return True
    mime = BytesParser(policy=policy.default).parsebytes(
        b'Content-Type: ' + handler.headers['Content-Type'].encode('ascii') + b'\r\n\r\n' + raw)
    parts = list(mime.iter_parts())
    names = [part.get_param('name', header='content-disposition') for part in parts]
    allowed = ['is_announcement', 'lock_comment', 'attachment'] if announcement else ['attachment']
    if names != allowed or parts[-1].get_filename() is None:
        _send(handler, {'private': 'synthetic-private-invalid-attachment-parts'}, 400)
        return True
    body = {name: part.get_payload(decode=True).decode('utf-8') for name, part in zip(names[:-1], parts[:-1])}
    if announcement and (body['is_announcement'] != 'true' or body['lock_comment'] not in ('true', 'false')):
        _send(handler, {'private': 'synthetic-private-invalid-attachment-booleans'}, 400)
        return True
    part = parts[-1]
    content = part.get_payload(decode=True)
    state.attachment_parts.append({'fields': body, 'filename': part.get_filename(),
                                   'content_type': part.get_content_type(), 'content': content,
                                   'authorization': handler.headers.get('Authorization')})
    row = rows[identifier]
    if row['permissions']['update'] is not True:
        _send(handler, {'private': 'synthetic-private-denied-attachment-update'}, 403)
        return True
    if len(content) > 1024 and state.attachment_quota_denied:
        _send(handler, {'private': 'synthetic-private-attachment-quota'}, 400)
        return True
    if announcement:
        state.announcement_written = True
    else:
        state.topic_written = True
    if row['permissions'].get('attach') is True and not state.attachment_ignore and not state.attachment_late_drop_attach:
        state.attachment_destroyed.extend(attached['id'] for attached in row['attachments'] or [])
        row['attachments'] = []
        if state.attachment_error_after_removal:
            _send(handler, {'private': 'synthetic-private-error-after-attachment-destruction'}, 500)
            return True
        # Native duplicate-name handling can rename the upload; metadata proof
        # must not claim byte integrity or assume the requested basename survives.
        row['attachments'] = [{'id': 1201, 'filename': 'renamed-' + part.get_filename(), 'display_name': part.get_filename(),
                               'size': len(content), 'updated_at': '2026-10-04T12:00:00Z',
                               'url': 'https://storage.example/?token=synthetic-private-new-file'}]
        if state.attachment_lose_attach:
            row['permissions']['attach'] = False
        if state.attachment_error_after_store:
            _send(handler, {'private': 'synthetic-private-error-after-file-store'}, 500)
            return True
    if announcement:
        row['locked'] = body['lock_comment'] == 'true'
        state.announcement_notifications.append(identifier)
        result = _scoped(row, prefix)
    else:
        state.topic_notifications.append(identifier)
        result = copy.deepcopy(row)
    if state.attachment_ack_patch is not None:
        result = result | state.attachment_ack_patch if isinstance(state.attachment_ack_patch, dict) else state.attachment_ack_patch
    _send(handler, result)
    return True
