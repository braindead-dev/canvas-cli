"""One-command private snapshot and field-level change summary."""

import hashlib
import secrets
from datetime import datetime, timezone
from pathlib import Path

from .client import CanvasError
from .page_revalidation import PageRevalidation
from .snapshot import capture, save_private
from .snapshot_diff import compare, read
from .writes import account


def sync_course(client, course_id, max_pages, directory, include_linked_files=False, *, incremental=False):
    if (not isinstance(course_id, str) or not course_id.isascii() or not course_id.isdecimal() or
            int(course_id) < 1 or str(int(course_id)) != course_id):
        raise CanvasError('Sync requires a positive numeric course ID')
    directory = Path(directory).expanduser().resolve(strict=False)
    if any((parent / '.git').exists() for parent in (directory, *directory.parents)):
        raise CanvasError('Raw course snapshots cannot be saved inside a Git checkout')
    if directory.exists() and not directory.is_dir():
        raise CanvasError('Snapshot destination must be a directory')
    identity = account(client)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    origin_key = hashlib.sha256(client.host.encode()).hexdigest()[:12]
    prefix = f'{origin_key}-user-{identity["user_id"]}-course-{course_id}-'
    previous_paths = sorted(directory.glob(prefix + '*.json'))
    previous = read(previous_paths[-1]) if previous_paths else None
    if previous and (previous.get('origin') != identity['origin']
                     or type(previous.get('viewer_user_id')) is not int
                     or previous['viewer_user_id'] != identity['user_id']
                     or type(previous.get('course_id')) is not int or str(previous['course_id']) != course_id):
        raise CanvasError('Latest stored snapshot is for a different origin, viewer or course')

    revalidation = PageRevalidation(previous) if incremental else None
    options = {'page_revalidation': revalidation} if incremental else {}
    current = capture(client, course_id, max_pages,
                      include_linked_files=include_linked_files, **options)
    if account(client) != identity:
        raise CanvasError('Canvas account changed during capture; no snapshot was saved')
    if (not isinstance(current, dict) or current.get('origin') != identity['origin'] or
            type(current.get('course_id')) is not int or str(current['course_id']) != course_id or
            'viewer_user_id' in current and (type(current['viewer_user_id']) is not int or
                                           current['viewer_user_id'] != identity['user_id'])):
        raise CanvasError('Capture context did not match the selected viewer/origin/course; no snapshot was saved')
    current = {**current, 'viewer_user_id': identity['user_id']}
    changes = compare(previous, current) if previous else None
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = directory / f'{prefix}{timestamp}-{secrets.token_hex(4)}.json'
    saved = save_private(destination, current)
    result = {
        **identity,
        'baseline': previous is None,
        'previous': str(previous_paths[-1]) if previous_paths else None,
        'saved': saved['saved'], 'complete': saved['complete'],
        'counts': saved['counts'], 'unavailable': saved['unavailable'],
        'diff': changes,
        'note': 'Private immutable snapshots are retained per origin, signed-in viewer and course. '
                'Identity is checked before and after capture; this is not an atomic permission/content lock. '
                'Legacy unscoped snapshots and other viewers are never selected as automatic baselines. '
                'Existing files are not migrated, renamed or removed; prune old files yourself when no longer needed.',
    }
    if revalidation is not None:
        result['revalidation'] = {**revalidation.stats,
                                  'validator_pages': len(revalidation.entries),
                                  'scope': 'page-bodies-only'}
    return result
