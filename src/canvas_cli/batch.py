"""Preview-first downloads of files linked from readable course content."""

import hashlib
import json
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
                   all_pages=False, yes=False, confirm=None, file_ids=None):
    if bool(yes) != bool(confirm):
        raise CanvasError('Batch download requires both --yes and --confirm from a prior preview')
    target = directory(target)
    if max_files < 1 or max_bytes < 1:
        raise CanvasError('Batch file and byte limits must be positive')
    discovered = linked_files(client, course_id, max_pages, resolve=True, all_pages=all_pages)
    requested = sorted({str(file_id) for file_id in (file_ids or [])}, key=int)
    if requested:
        found = {str(file['id']): file for file in discovered['files']}
        missing = [file_id for file_id in requested if file_id not in found]
        if missing:
            raise CanvasError(f'Selected file ID(s) not discovered: {", ".join(missing)}')
        unavailable = [file_id for file_id in requested if not found[file_id].get('downloadable')]
        if unavailable:
            raise CanvasError(f'Selected file ID(s) not downloadable: {", ".join(unavailable)}')
        selected = [found[file_id] for file_id in requested]
    else:
        selected = [file for file in discovered['files'] if file.get('downloadable')]
    planned = []
    for file in selected:
        filename = safe_filename(file['id'], file.get('display_name'))
        destination = target / filename
        if destination.exists() or destination.is_symlink():
            raise CanvasError(f'Destination already exists for file {file["id"]}; no files downloaded')
        planned.append({'id': file['id'], 'name': filename, 'size': file.get('size'),
                        'updated_at': file.get('updated_at'),
                        'modified_at': file.get('modified_at')})
    known_bytes = sum(item['size'] for item in planned if isinstance(item['size'], int))
    limit_issues = []
    if len(planned) > max_files:
        limit_issues.append(f'{len(planned)} downloadable files exceed --max-files {max_files}')
    if known_bytes > max_bytes:
        limit_issues.append(f'{known_bytes} known bytes exceed --max-bytes {max_bytes}')
    plan = {'course_id': int(course_id), 'destination': str(target),
            'files': planned, 'known_bytes': known_bytes,
            'skipped_unavailable': sum(not file.get('downloadable') for file in discovered['files']),
            'not_selected': (sum(bool(file.get('downloadable')) for file in discovered['files'])
                             - len(selected)),
            'selected_file_ids': requested,
            'discovered_file_count': len(discovered['files']),
            'skipped_sources': discovered['skipped_sources'],
            'max_files': max_files, 'max_bytes': max_bytes,
            'max_pages': max_pages, 'all_pages': all_pages,
            'within_limits': not limit_issues, 'limit_issues': limit_issues}
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    preview = {'dry_run': not yes, **plan, 'confirm': digest}
    if not yes:
        preview['next'] = ('Increase the listed limits and review a fresh preview before --yes.'
                           if limit_issues else
                           'Review filenames and limits, then repeat with --yes --confirm DIGEST to download.')
        return preview
    if confirm != digest:
        raise CanvasError('Download preview changed; review a fresh preview before downloading')
    if limit_issues:
        raise CanvasError('; '.join(limit_issues) + '; no files downloaded')
    saved, used = [], 0
    for item in planned:
        try:
            metadata, _ = client.request(f'/api/v1/courses/{course_id}/files/{item["id"]}')
            if not isinstance(metadata, dict) or str(metadata.get('id')) != str(item['id']):
                raise CanvasError('Canvas returned a different file')
            if (metadata.get('locked_for_user') or metadata.get('hidden_for_user') or
                    not metadata.get('url')):
                raise CanvasError('File became unavailable')
            if (safe_filename(item['id'], metadata.get('display_name')) != item['name'] or
                    metadata.get('size') != item['size'] or
                    metadata.get('updated_at') != item['updated_at'] or
                    metadata.get('modified_at') != item['modified_at']):
                raise CanvasError('File metadata changed after preview; no download attempted for this file')
            remaining = max_bytes - used
            if remaining < 1 or (isinstance(metadata.get('size'), int) and metadata['size'] > remaining):
                raise CanvasError('Batch byte limit reached')
            result = download(metadata['url'], target / item['name'], remaining,
                              expected_bytes=item['size'])
            used += result['bytes']
            saved.append({'id': item['id'], 'name': item['name'], 'bytes': result['bytes']})
        except CanvasError as error:
            raise CanvasError(f'Batch stopped after {len(saved)} successful downloads; those files remain. {error}') from None
    return {**preview, 'dry_run': False, 'saved': saved, 'bytes': used}
