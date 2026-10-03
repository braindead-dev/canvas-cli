"""Account-bound personal file organization, without sharing or overwrite controls."""

from .client import CanvasError
from .group_content import ROOT_NOTE
from .writes import account, check_flags, confirmed, digest


def _id(value):
    if not isinstance(value, str) or not value.isdecimal() or int(value) < 1 or str(int(value)) != value:
        raise CanvasError('Expected a canonical positive file or folder ID')
    return value


def _name(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 255 or value in ('.', '..') or
            any(char in '/\\' or ord(char) < 32 or ord(char) == 127 for char in value)):
        raise CanvasError('Use one nonempty name of at most 255 characters, without path separators or controls')
    return value


def _folder_record(record, user_id, folder_id=None, *, allow_deleted=False):
    if (not isinstance(record, dict) or type(record.get('id')) is not int or record['id'] < 1 or
            folder_id is not None and str(record['id']) != folder_id or
            record.get('context_type') != 'User' or type(record.get('context_id')) is not int or
            record['context_id'] != user_id or record.get('for_submissions') or
            record.get('hidden_for_user') or record.get('locked_for_user') or
            not allow_deleted and record.get('workflow_state') == 'deleted'):
        raise CanvasError('Only your own accessible personal folders, excluding submission folders, are supported')
    return {key: record.get(key) for key in ('id', 'context_type', 'context_id', 'name', 'full_name',
             'parent_folder_id', 'updated_at', 'files_count', 'folders_count', 'locked', 'hidden')}


def _folder(client, folder_id, user_id):
    return _folder_record(client.request(f'/api/v1/folders/{_id(folder_id)}')[0], user_id, folder_id)


def _file(client, file_id):
    record, _ = client.request(f'/api/v1/files/{_id(file_id)}')
    if (not isinstance(record, dict) or type(record.get('id')) is not int or str(record['id']) != file_id or
            type(record.get('size')) is not int or record['size'] < 0 or record.get('locked_for_user') or
            record.get('hidden_for_user') or record.get('workflow_state') == 'deleted'):
        raise CanvasError('Canvas did not return the exact accessible file with valid size metadata')
    return {key: record.get(key) for key in ('id', 'folder_id', 'display_name', 'filename', 'size',
             'created_at', 'updated_at', 'modified_at', 'locked', 'hidden', 'content-type')}, digest({'uuid': record.get('uuid')})


def folders(client, max_pages=100, root=False):
    identity = account(client)
    if root:
        record, _ = client.request('/api/v1/users/self/folders/root')
        return {**_folder_record(record, identity['user_id']), 'note': ROOT_NOTE}
    rows = client.list('/api/v1/users/self/folders?per_page=100', max_pages)
    # Submission folders can appear in the inventory but must never be used as mutation targets.
    return rows


def change_file(client, file_id, *, name=None, destination=None, delete=False, permanent=False,
                copy=False, yes=False, confirm=None):
    check_flags(yes, confirm)
    _id(file_id)
    if name is not None:
        _name(name)
    if destination is not None:
        _id(destination)
    if delete:
        if not permanent or name is not None or destination is not None or copy:
            raise CanvasError('Personal file deletion requires --permanent and cannot be combined with edits')
    elif permanent or (copy and (destination is None or name is not None)) or (not copy and name is None and destination is None):
        raise CanvasError('Specify a filename and/or destination; copying requires only a destination folder')
    identity = account(client)
    current, fingerprint = _file(client, file_id)
    source = None
    if not copy:
        if type(current.get('folder_id')) is not int or current['folder_id'] < 1:
            raise CanvasError('Canvas did not identify the source file folder')
        source = _folder(client, str(current['folder_id']), identity['user_id'])
    target = _folder(client, destination, identity['user_id']) if destination is not None else source
    if copy:
        method, route = 'POST', f'/api/v1/folders/{destination}/copy_file'
        body = {'source_file_id': file_id, 'on_duplicate': 'rename'}
        effect = 'Creates a personal copy of this readable file. A collision is renamed, never overwritten.'
    elif delete:
        method, route, body = 'DELETE', f'/api/v1/files/{file_id}', None
        effect = 'Permanently removes this personal file. Canvas documents this as irreversible; links can break.'
    else:
        method, route, body = 'PUT', f'/api/v1/files/{file_id}', {'on_duplicate': 'rename'}
        if name is not None: body['name'] = name
        if destination is not None: body['parent_folder_id'] = destination
        effect = 'Changes only name/location. A collision is renamed, never overwritten; links may be affected.'
    preview = {**identity, 'file_id': file_id, 'file': current, 'file_fingerprint': fingerprint,
               'source_folder': source, 'destination_folder': target, 'method': method,
               'route': route, 'body': body, 'permanent': permanent, 'effect': effect}
    result = confirmed(client, preview, yes, confirm)
    if not yes: return result
    if (not isinstance(result, dict) or type(result.get('id')) is not int or result['id'] < 1 or
            not copy and str(result['id']) != file_id or copy and str(result['id']) == file_id or
            type(result.get('size')) is not int or result['size'] < 0 or
            not delete and (type(result.get('folder_id')) is not int or result['folder_id'] != target['id'])):
        raise CanvasError('Unexpected file acknowledgement; verify in Canvas before repeating the write. No automatic retries.')
    public = {key: result.get(key) for key in ('id', 'folder_id', 'display_name', 'filename', 'size', 'updated_at')}
    return {'personal_file': public, 'deleted': delete, 'copied': copy,
            'note': 'Canvas acknowledged the file operation. ' + effect}


def create_folder(client, parent, name, *, max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    _id(parent); _name(name)
    identity = account(client)
    target = _folder(client, parent, identity['user_id'])
    siblings = client.list(f'/api/v1/folders/{parent}/folders?per_page=100', max_pages)
    if any(not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] < 1 for row in siblings):
        raise CanvasError('Canvas returned malformed sibling folder metadata')
    if any(row.get('name') == name for row in siblings):
        raise CanvasError('A folder with this name already exists; choose another name')
    preview = {**identity, 'parent_folder': target,
               'siblings_digest': digest(sorted((row['id'], row.get('name')) for row in siblings)),
               'method': 'POST', 'route': f'/api/v1/folders/{parent}/folders', 'body': {'name': name},
               'effect': 'Creates one personal subfolder without changing sharing or existing contents.'}
    result = confirmed(client, preview, yes, confirm)
    if not yes: return result
    try:
        created = _folder_record(result, identity['user_id'])
    except CanvasError:
        raise CanvasError('Unexpected folder acknowledgement; verify in Canvas before repeating the write') from None
    if (created['id'] == target['id'] or type(created['parent_folder_id']) is not int or
            created['parent_folder_id'] != target['id'] or created['name'] != name):
        raise CanvasError('Unexpected new folder destination/name; verify in Canvas before retrying')
    return {'personal_folder': created, 'note': 'Canvas returned the new personal folder.'}


def change_folder(client, folder_id, *, name=None, destination=None, delete=False,
                  max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    _id(folder_id)
    if name is not None: _name(name)
    if destination is not None: _id(destination)
    if delete and (name is not None or destination is not None) or not delete and name is None and destination is None:
        raise CanvasError('Specify a folder name/location change or empty-folder deletion, not both')
    identity = account(client)
    current = _folder(client, folder_id, identity['user_id'])
    if type(current.get('parent_folder_id')) is not int or current['parent_folder_id'] < 1:
        raise CanvasError('The personal root folder cannot be edited or deleted')
    base = f'/api/v1/folders/{folder_id}'
    before = {'folder': current}
    target = None
    if delete:
        children = client.list(base + '/folders?per_page=100', max_pages)
        files = client.list(base + '/files?per_page=100', max_pages)
        if children or files or current.get('files_count', 0) or current.get('folders_count', 0):
            raise CanvasError('Only empty personal folders can be deleted; recursive force deletion is not enabled')
        before.update(children=children, files=files)
        body = None  # Canvas rejects nonempty folders unless force="true"; never send that override.
        effect = 'Removes only this empty personal folder. No force flag or recursive deletion is sent.'
    else:
        target_id = destination or str(current['parent_folder_id'])
        ancestors, seen = [], set()
        ancestor = target_id
        for _ in range(100):
            if ancestor == folder_id:
                raise CanvasError('A folder cannot be moved into itself or its descendants')
            if ancestor in seen:
                raise CanvasError('Canvas returned a folder ancestry cycle')
            seen.add(ancestor)
            record = _folder(client, ancestor, identity['user_id'])
            ancestors.append(record)
            parent = record.get('parent_folder_id')
            if parent is None: break
            if type(parent) is not int or parent < 1:
                raise CanvasError('Canvas returned malformed folder ancestry')
            ancestor = str(parent)
        else:
            raise CanvasError('Folder ancestry limit reached; no change sent')
        target = ancestors[0]
        siblings = client.list(f'/api/v1/folders/{target_id}/folders?per_page=100', max_pages)
        if any(not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] < 1 for row in siblings):
            raise CanvasError('Canvas returned malformed sibling folder metadata')
        intended_name = name if name is not None else current['name']
        if any(row['id'] != current['id'] and row.get('name') == intended_name for row in siblings):
            raise CanvasError('A same-named folder already exists at the destination; choose another name')
        before.update(ancestors=ancestors,
                      siblings_digest=digest(sorted((row['id'], row.get('name')) for row in siblings)))
        body = {}
        if name is not None: body['name'] = name
        if destination is not None: body['parent_folder_id'] = destination
        effect = 'Changes only this personal folder name/location. Existing contents move with it; inherited access can change.'
    preview = {**identity, 'folder_id': folder_id, 'before': before, 'destination_folder': target,
               'method': 'DELETE' if delete else 'PUT', 'route': base, 'body': body, 'effect': effect}
    result = confirmed(client, preview, yes, confirm)
    if not yes: return result
    try:
        changed = _folder_record(result, identity['user_id'], folder_id, allow_deleted=delete)
    except CanvasError:
        raise CanvasError('Unexpected folder acknowledgement; verify in Canvas before repeating the write') from None
    if not delete and (type(changed['parent_folder_id']) is not int or changed['parent_folder_id'] != target['id'] or
                       name is not None and changed['name'] != name):
        raise CanvasError('Unexpected folder destination/name; verify in Canvas before repeating the write')
    return {'personal_folder': changed, 'deleted': delete, 'note': 'Canvas acknowledged the folder operation. ' + effect}
