"""Preview-first downloads of files linked from readable course content."""

import re
from pathlib import Path

from .client import CanvasError
from .discovery import linked_files
from .download import download


def safe_filename(file_id, name):
    leaf = str(name or 'file').replace('\\', '/').split('/')[-1]
    leaf = re.sub(r'[^A-Za-z0-9._-]+', '-', leaf).strip('.-_')[:120] or 'file'
    leaf = re.sub(r'-+(\.[A-Za-z0-9]{1,10})$', r'\1', leaf)
    return f'{file_id}-{leaf}'


def directory(path):
    target = Path(path).expanduser().resolve(strict=False)
    if not target.is_dir():
        raise CanvasError('Download directory must already exist')
    if any((parent / '.git').exists() for parent in (target, *target.parents)):
        raise CanvasError('Course files cannot be batch-downloaded inside a Git checkout')
    return target


def batch_download(client, course_id, target, max_pages, max_files, max_bytes,
                   all_pages=False, yes=False):
    target = directory(target)
    if max_files < 1 or max_bytes < 1:
        raise CanvasError('Batch file and byte limits must be positive')
    discovered = linked_files(client, course_id, max_pages, resolve=True, all_pages=all_pages)
    selected = [file for file in discovered['files'] if file.get('downloadable')]
    if len(selected) > max_files:
        raise CanvasError(f'{len(selected)} downloadable files exceed --max-files {max_files}; no files downloaded')
    planned = []
    for file in selected:
        filename = safe_filename(file['id'], file.get('display_name'))
        destination = target / filename
        if destination.exists() or destination.is_symlink():
            raise CanvasError(f'Destination already exists for file {file["id"]}; no files downloaded')
        planned.append({'id': file['id'], 'name': filename, 'size': file.get('size')})
    known_bytes = sum(item['size'] for item in planned if isinstance(item['size'], int))
    if known_bytes > max_bytes:
        raise CanvasError('Known file sizes exceed --max-bytes; no files downloaded')
    preview = {'dry_run': not yes, 'course_id': int(course_id), 'destination': str(target),
               'files': planned, 'known_bytes': known_bytes,
               'skipped_unavailable': len(discovered['files']) - len(selected),
               'skipped_sources': discovered['skipped_sources'],
               'max_bytes': max_bytes}
    if not yes:
        preview['next'] = 'Review filenames and limits, then repeat with --yes to download.'
        return preview
    saved, used = [], 0
    for item in planned:
        try:
            metadata, _ = client.request(f'/api/v1/courses/{course_id}/files/{item["id"]}')
            if (metadata.get('locked_for_user') or metadata.get('hidden_for_user') or
                    not metadata.get('url')):
                raise CanvasError('File became unavailable')
            remaining = max_bytes - used
            if remaining < 1 or (isinstance(metadata.get('size'), int) and metadata['size'] > remaining):
                raise CanvasError('Batch byte limit reached')
            result = download(metadata['url'], target / item['name'], remaining)
            used += result['bytes']
            saved.append({'id': item['id'], 'name': item['name'], 'bytes': result['bytes']})
        except CanvasError as error:
            raise CanvasError(f'Batch stopped after {len(saved)} successful downloads; those files remain. {error}') from None
    return {**preview, 'dry_run': False, 'saved': saved, 'bytes': used}
