"""One-command private snapshot and field-level change summary."""

import hashlib
import secrets
from datetime import datetime, timezone
from pathlib import Path

from .client import CanvasError
from .snapshot import capture, save_private
from .snapshot_diff import compare, read


def sync_course(client, course_id, max_pages, directory):
    directory = Path(directory).expanduser().resolve(strict=False)
    if any((parent / '.git').exists() for parent in (directory, *directory.parents)):
        raise CanvasError('Raw course snapshots cannot be saved inside a Git checkout')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not directory.is_dir():
        raise CanvasError('Snapshot destination must be a directory')

    origin_key = hashlib.sha256(client.host.encode()).hexdigest()[:12]
    prefix = f'{origin_key}-course-{course_id}-'
    previous_paths = sorted(directory.glob(prefix + '*.json'))
    previous = read(previous_paths[-1]) if previous_paths else None
    if previous and (previous.get('origin') != client.host
                     or str(previous.get('course_id')) != str(course_id)):
        raise CanvasError('Latest stored snapshot is for a different origin or course')

    current = capture(client, course_id, max_pages)
    changes = compare(previous, current) if previous else None
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = directory / f'{prefix}{timestamp}-{secrets.token_hex(4)}.json'
    saved = save_private(destination, current)
    return {
        'baseline': previous is None,
        'previous': str(previous_paths[-1]) if previous_paths else None,
        'saved': saved['saved'], 'complete': saved['complete'],
        'counts': saved['counts'], 'unavailable': saved['unavailable'],
        'diff': changes,
        'note': 'Private immutable snapshots are retained; prune old files yourself when no longer needed.',
    }
