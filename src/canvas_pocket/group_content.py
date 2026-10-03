"""Authorized group content reads; groups are not course/module namespaces."""

import re
from urllib.parse import quote

from .client import CanvasError
from .pages import visible
from .snapshot import redact
from .writes import account


def _number(item):
    if not isinstance(item, str) or not re.fullmatch(r'[1-9][0-9]*', item):
        raise CanvasError('Expected a positive numeric content ID')
    return item


def base(item, context_type):
    if context_type not in ('course', 'group', 'user'):
        raise CanvasError('Content context must be course, group or own user')
    _number(item)
    return f'/api/v1/{context_type}s/{item}'


def _context(client, item, context_type):
    route = base(item, context_type)
    if context_type == 'user':
        identity = account(client)
        if identity['user_id'] != int(item):
            raise CanvasError('User content reads are restricted to the signed-in user')
        return '/api/v1/users/self', {'id': identity['user_id'], 'name': 'Own user'}
    context, _ = client.request(route)
    if not isinstance(context, dict) or type(context.get('id')) is not int or context['id'] != int(item):
        raise CanvasError('Canvas returned a different content context')
    return route, context


def _id(row, field='id'):
    if not isinstance(row, dict) or type(row.get(field)) is not int or row[field] < 1:
        raise CanvasError('Canvas returned invalid content identifiers')
    return row[field]


def _group_association(row, group_id):
    if row.get('context_type') is not None and (not isinstance(row['context_type'], str) or row['context_type'].lower() != 'group'):
        raise CanvasError('Canvas returned content outside the requested group')
    for field in ('context_id', 'group_id'):
        if row.get(field) is not None and (type(row[field]) is not int or row[field] != int(group_id)):
            raise CanvasError('Canvas returned content outside the requested group')


def folder(row, item, context_type):
    _id(row)
    if row.get('context_type') != context_type.title() or type(row.get('context_id')) is not int or row['context_id'] != int(item):
        raise CanvasError('Canvas returned a folder outside the requested context')
    fields = ('id', 'name', 'full_name', 'context_type', 'context_id', 'parent_folder_id', 'position',
              'files_count', 'folders_count', 'created_at', 'updated_at', 'lock_at', 'unlock_at',
              'hidden', 'hidden_for_user', 'locked', 'locked_for_user', 'for_submissions', 'files_url', 'folders_url')
    return redact({key: row[key] for key in fields if key in row})


def root(client, item, context_type='course'):
    route, context = _context(client, item, context_type)
    row, _ = client.request(route + '/folders/root')
    result = folder(row, item, context_type)
    if result.get('parent_folder_id') is not None:
        raise CanvasError('Canvas did not return the context root folder')
    return {'context_type': context_type, f'{context_type}_id': int(item), 'context_name': context.get('name'),
            'root_folder': result, 'note': 'Root metadata only. No folder creation, content download or enrollment change.'}


def quota(client, item, context_type='course'):
    route, context = _context(client, item, context_type)
    row, _ = client.request(route + '/files/quota')
    if (not isinstance(row, dict) or any(type(row.get(key)) is not int or row[key] < 0 for key in ('quota', 'quota_used'))):
        raise CanvasError('Canvas returned invalid storage-quota metadata')
    return {'context_type': context_type, f'{context_type}_id': int(item), 'context_name': context.get('name'),
            'quota_bytes': row['quota'], 'used_bytes': row['quota_used'],
            'remaining_bytes': max(0, row['quota'] - row['quota_used']),
            'over_quota': row['quota_used'] > row['quota'],
            'note': 'Native storage bytes, not a guarantee that an upload is permitted. No upload or settings change.'}


def _page(row, group_id, key=None):
    if not isinstance(row, dict) or not visible(row):
        raise CanvasError('Group page is unpublished, hidden or locked for this user')
    if not isinstance(row.get('url'), str) or not row['url']:
        raise CanvasError('Canvas returned an invalid group page')
    _group_association(row, group_id)
    if key is not None and (str(row.get('page_id')) != key if key.isascii() and key.isdecimal() else row['url'] != key):
        raise CanvasError('Canvas returned a different group page')
    return redact(row)


def page(client, group_id, key=None):
    if key is not None and (not isinstance(key, str) or not key or key in ('.', '..') or
                            '/' in key or '\\' in key or any(ord(char) < 32 or ord(char) == 127 for char in key)):
        raise CanvasError('Use one page slug or ID, not a URL or path')
    route, _ = _context(client, group_id, 'group')
    row, _ = client.request(route + ('/front_page' if key is None else '/pages/' + quote(key, safe='')))
    return _page(row, group_id, key)


def listing(client, group_id, resource, max_pages=100):
    if resource not in ('files', 'folders', 'pages', 'tabs'):
        raise CanvasError('Unsupported group content resource')
    route, context = _context(client, group_id, 'group')
    rows = client.list(route + f'/{resource}?per_page=100', max_pages)
    output, seen = [], set()
    for row in rows:
        if resource == 'tabs':
            if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id']:
                raise CanvasError('Canvas returned invalid group navigation metadata')
            key = row['id']
            projected = {field: row[field] for field in ('id', 'label', 'type', 'html_url', 'position', 'visibility') if field in row}
            if row.get('hidden') or row.get('visibility') == 'none':
                continue
        elif resource == 'pages':
            if not isinstance(row, dict) or not isinstance(row.get('url'), str) or not row['url']:
                raise CanvasError('Canvas returned invalid group page metadata')
            key = row['url']
            _group_association(row, group_id)
            if not visible(row):
                continue
            projected = {field: row[field] for field in ('page_id', 'url', 'title', 'created_at', 'updated_at',
                                                        'published', 'front_page', 'html_url') if field in row}
        else:
            key = _id(row)
            if resource == 'folders':
                projected = folder(row, group_id, 'group')
            else:
                _group_association(row, group_id)
                fields = ('id', 'folder_id', 'display_name', 'filename', 'size', 'content-type', 'mime_class',
                          'created_at', 'updated_at', 'modified_at', 'hidden', 'hidden_for_user', 'locked',
                          'locked_for_user', 'lock_at', 'unlock_at')
                projected = {field: row[field] for field in fields if field in row}
        if key in seen:
            raise CanvasError('Canvas returned duplicate group content identifiers')
        seen.add(key)
        output.append(redact(projected))
    return {'context_type': 'group', 'group_id': int(group_id), 'group_name': context.get('name'),
            'resource': resource, 'items': output, 'complete_for_endpoint': True,
            'note': 'Authorized group endpoint only, not a complete inventory of every external tool or course resource. '
                    'No membership, read-marker, upload or content changes; Canvas may log content-access analytics.'}


def file_metadata(client, group_id, file_id):
    _number(file_id)
    route, _ = _context(client, group_id, 'group')
    row, _ = client.request(route + f'/files/{file_id}')
    if _id(row) != int(file_id):
        raise CanvasError('Canvas returned a different group file; refusing download')
    _group_association(row, group_id)
    if (row.get('hidden_for_user') or row.get('locked_for_user') or row.get('workflow_state') == 'deleted'):
        raise CanvasError('Group file is unavailable to this user')
    if not isinstance(row.get('url'), str) or not row['url']:
        raise CanvasError('Canvas did not provide a group-file download URL')
    return row
