"""Synthetic page validators and fresh inventories, isolated from wiki-write fixtures."""

import json
from urllib.parse import urlsplit


def initialize(cls):
    cls.snapshot_revalidation = None


def read(cls, handler):
    state = cls.snapshot_revalidation
    if state is None:
        return False
    path = urlsplit(handler.path).path
    base = '/api/v1/courses/101'
    if not path.startswith(base):
        return False
    if path == base:
        data = {'id': 101, 'name': 'Synthetic snapshot course', 'syllabus_body': 'Synthetic syllabus'}
    elif path == base + '/pages':
        data = state['listed']
        if state.get('paginate') and 'page=2' not in handler.path:
            data = []
            handler.send_response(200)
            handler.send_header('Link', f'<{base}/pages?page=2>; rel="next"')
            handler.end_headers()
            handler.wfile.write(b'[]')
            return True
    elif path.startswith(base + '/pages/'):
        state['requests'].append((path, handler.headers.get('If-None-Match')))
        status = state.get('page_status', 200)
        tag = state.get('etag')
        if status == 200 and tag and handler.headers.get('If-None-Match') == tag:
            status = 304
        handler.send_response(status)
        if tag:
            handler.send_header('ETag', '"different"' if state.get('bad_ack') else tag)
        for name, value in state.get('headers', {}).items():
            handler.send_header(name, value)
        handler.end_headers()
        if status == 200:
            handler.wfile.write(json.dumps(state['page']).encode())
        if state.get('change_account'):
            cls.own_profile = {**cls.own_profile, 'id': 8}
        return True
    elif path in (base + '/assignments', base + '/modules', base + '/discussion_topics'):
        data = []
    else:
        return False
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json')
    handler.end_headers()
    handler.wfile.write(json.dumps(data).encode())
    return True
