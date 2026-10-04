"""Independent native entry-before-file writes and exact own-entry readback."""

import copy
from email import policy
from email.parser import BytesParser
from urllib.parse import parse_qs, urlsplit

from .appointments import _send


def initialize(state):
    state.entry_attachment_enabled = False
    state.entry_attachment_context = 'course'
    state.entry_attachment_viewer = 7
    state.entry_attachment_context_row = {'id': 123, 'name': 'Synthetic attached-post context'}
    state.entry_attachment_topic = {'id': 9, 'context_id': 123, 'context_type': 'Course',
                                    'title': 'Synthetic prompt', 'message': '<p>Synthetic prompt</p>',
                                    'published': True, 'locked': False, 'locked_for_user': False,
                                    'require_initial_post': False, 'user_can_see_posts': True,
                                    'permissions': {'update': False, 'attach': False, 'reply': True}}
    state.entry_attachment_parent = {'id': 301, 'user_id': 8, 'parent_id': None,
                                     'message': '<p>synthetic-private-parent</p>',
                                     'attachment': {'id': 61, 'url': 'https://storage.example/?token=synthetic-private-parent'}}
    state.entry_attachment_parts, state.entry_attachment_posts, state.entry_attachment_files = [], {}, []
    state.entry_attachment_can_attach = True
    state.entry_attachment_user_quota_denied = False
    state.entry_attachment_error_after_entry = state.entry_attachment_error_after_store = False
    state.entry_attachment_read_denied = state.entry_attachment_duplicate_read = False
    state.entry_attachment_ack_patch = state.entry_attachment_read_patch = None
    state.entry_attachment_after_viewer = state.entry_attachment_after_context = state.entry_attachment_after_prompt = False


def _base(state):
    return f'/api/v1/{state.entry_attachment_context}s/123/discussion_topics/9'


def read(state, handler):
    if not state.entry_attachment_enabled:
        return False
    url = urlsplit(handler.path)
    base = _base(state)
    if url.path == '/api/v1/users/self/profile':
        _send(handler, {'id': 8 if state.entry_attachment_posts and state.entry_attachment_after_viewer
                       else state.entry_attachment_viewer})
    elif url.path == f'/api/v1/{state.entry_attachment_context}s/123':
        row = copy.deepcopy(state.entry_attachment_context_row)
        if state.entry_attachment_posts and state.entry_attachment_after_context:
            row['name'] = 'Changed context'
        _send(handler, row)
    elif url.path == base:
        row = copy.deepcopy(state.entry_attachment_topic)
        if state.entry_attachment_posts and state.entry_attachment_after_prompt:
            row['message'] = 'Changed prompt'
        _send(handler, row)
    elif url.path == base + '/entry_list':
        query = parse_qs(url.query)
        if query.get('ids[]') not in (['301'], ['402']) or query.get('per_page') != ['100']:
            _send(handler, {'private': 'synthetic-private-wrong-entry-selection'}, 400)
            return True
        identifier = int(query['ids[]'][0])
        if identifier == 402 and state.entry_attachment_read_denied:
            _send(handler, {'private': 'synthetic-private-entry-read-denied'}, 403)
            return True
        if query.get('page') != ['2']:
            _send(handler, [], link=f'<{handler.path}&page=2>; rel="next"')
            return True
        row = copy.deepcopy(state.entry_attachment_parent if identifier == 301 else
                            state.entry_attachment_posts.get(identifier))
        if identifier == 402 and state.entry_attachment_read_patch is not None:
            row = row | state.entry_attachment_read_patch
        _send(handler, [row, row] if identifier == 402 and state.entry_attachment_duplicate_read else [row])
    else:
        return False
    return True


def write(state, handler, raw):
    if not state.entry_attachment_enabled:
        return False
    base = _base(state)
    reply = handler.path == base + '/entries/301/replies'
    if handler.command != 'POST' or handler.path not in (base + '/entries', base + '/entries/301/replies'):
        _send(handler, {'private': 'synthetic-private-wrong-entry-write'}, 400)
        return True
    mime = BytesParser(policy=policy.default).parsebytes(
        b'Content-Type: ' + handler.headers['Content-Type'].encode('ascii') + b'\r\n\r\n' + raw)
    parts = list(mime.iter_parts())
    if ([part.get_param('name', header='content-disposition') for part in parts] != ['message', 'attachment'] or
            parts[-1].get_filename() is None):
        _send(handler, {'private': 'synthetic-private-wrong-entry-parts'}, 400)
        return True
    message, content = parts[0].get_payload(decode=True).decode('utf-8'), parts[1].get_payload(decode=True)
    state.entry_attachment_parts.append({'message': message, 'name': parts[1].get_filename(), 'content': content,
                                         'content_type': parts[1].get_content_type(),
                                         'authorization': handler.headers.get('Authorization')})
    topic = state.entry_attachment_topic
    if topic['permissions'].get('reply') is False or reply and not topic['user_can_see_posts']:
        _send(handler, {'private': 'synthetic-private-entry-denial'}, 403)
        return True
    if (state.entry_attachment_can_attach and not topic.get('assignment_id') and len(content) > 1024 and
            state.entry_attachment_user_quota_denied):
        _send(handler, {'private': 'synthetic-private-own-user-quota-denial'}, 400)
        return True
    # Native entry save/participation precedes attachment storage. Prompt editing
    # rights are deliberately absent: students attach through separate entry rights.
    entry = {'id': 402, 'user_id': state.entry_attachment_viewer, 'parent_id': 301 if reply else None,
             'message': message, 'created_at': '2026-10-04T12:00:00Z', 'updated_at': '2026-10-04T12:00:00Z',
             'user_name': 'synthetic-private-author', 'user': {'email': 'synthetic-private-profile'}}
    state.entry_attachment_posts[402] = entry
    topic['user_can_see_posts'] = True
    topic['discussion_subentry_count'] = 10
    if state.entry_attachment_error_after_entry:
        _send(handler, {'private': 'synthetic-private-error-after-entry-save'}, 500)
        return True
    if state.entry_attachment_can_attach:
        stored = {'id': 73, 'filename': 'renamed-' + parts[1].get_filename(), 'display_name': parts[1].get_filename(),
                  'size': len(content), 'url': 'https://storage.example/?token=synthetic-private-file'}
        state.entry_attachment_files.append(stored)
        if state.entry_attachment_error_after_store:
            _send(handler, {'private': 'synthetic-private-error-after-file-store'}, 500)
            return True
        entry['attachment'] = stored
    result = copy.deepcopy(entry)
    if state.entry_attachment_ack_patch is not None:
        result = result | state.entry_attachment_ack_patch if isinstance(state.entry_attachment_ack_patch, dict) else state.entry_attachment_ack_patch
    _send(handler, result, 201)
    return True
