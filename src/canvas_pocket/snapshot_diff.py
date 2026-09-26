"""Compare two local snapshots without printing full course content."""

import json
from pathlib import Path

from .client import CanvasError

FIELDS = {
    'assignments': ('name', 'description', 'due_at', 'unlock_at', 'lock_at',
                    'points_possible', 'submission_types', 'published'),
    'modules': ('name', 'position', 'unlock_at', 'state', 'published', 'items'),
    'pages': ('title', 'body', 'published', 'updated_at'),
    'announcements': ('title', 'message', 'updated_at', 'posted_at', 'published'),
    'discussions': ('title', 'message', 'updated_at', 'posted_at', 'published',
                    'assignment_id', 'lock_at', 'unlock_at'),
    'linked_files': ('display_name', 'size', 'updated_at', 'modified_at',
                     'downloadable', 'sources'),
}


def read(path):
    try:
        data = json.loads(Path(path).expanduser().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise CanvasError('Cannot read a valid JSON snapshot') from None
    if not isinstance(data, dict) or data.get('schema_version') != 1:
        raise CanvasError('Unsupported snapshot schema')
    return data


def key(kind, item):
    return item.get('url') if kind == 'pages' else item.get('id')


def visible_label(kind, item):
    return item.get('name') or item.get('title') or item.get('display_name') or str(key(kind, item))


def content(kind, item):
    if kind == 'modules':
        items = [{name: part.get(name) for name in ('id', 'title', 'type', 'position',
                                                   'content_id', 'page_url', 'locked_for_user')}
                 for part in item.get('items', [])]
        return {name: (items if name == 'items' else item.get(name)) for name in FIELDS[kind]}
    return {name: item.get(name) for name in FIELDS[kind]}


def compare(old, new):
    if old.get('origin') != new.get('origin') or old.get('course_id') != new.get('course_id'):
        raise CanvasError('Snapshots must have the same Canvas origin and course ID')
    course_fields = ('name', 'course_code', 'syllabus_body', 'start_at', 'end_at')
    course_changes = [field for field in course_fields
                      if old.get('course', {}).get(field) != new.get('course', {}).get(field)]
    changes = {}
    observed_changes = {}
    skipped = {}
    for kind, fields in FIELDS.items():
        missing_old = kind in old.get('unavailable', {}) or kind not in old
        missing_new = kind in new.get('unavailable', {}) or kind not in new
        if kind == 'modules':
            missing_old |= any(name.startswith('module ') for name in old.get('unavailable', {}))
            missing_new |= any(name.startswith('module ') for name in new.get('unavailable', {}))
        if missing_old or missing_new:
            skipped[kind] = 'incomplete in older or newer snapshot'
            if kind in ('pages', 'linked_files'):
                before = {key(kind, item): item for item in old.get(kind, []) if key(kind, item) is not None}
                after = {key(kind, item): item for item in new.get(kind, []) if key(kind, item) is not None}
                observed_changes[kind] = [
                    {'id': identity, 'title': visible_label(kind, after[identity]),
                     'fields': [field for field in fields
                                if content(kind, before[identity])[field] != content(kind, after[identity])[field]]}
                    for identity in sorted(before.keys() & after.keys(), key=str)
                    if content(kind, before[identity]) != content(kind, after[identity])
                ]
            continue
        before = {key(kind, item): item for item in old.get(kind, []) if key(kind, item) is not None}
        after = {key(kind, item): item for item in new.get(kind, []) if key(kind, item) is not None}
        added = sorted(after.keys() - before.keys(), key=str)
        removed = sorted(before.keys() - after.keys(), key=str)
        changed = sorted((identity for identity in before.keys() & after.keys()
                          if content(kind, before[identity]) != content(kind, after[identity])), key=str)
        changes[kind] = {
            'added': [{'id': identity, 'title': visible_label(kind, after[identity])} for identity in added],
            'removed': [{'id': identity, 'title': visible_label(kind, before[identity])} for identity in removed],
            'changed': [{'id': identity, 'title': visible_label(kind, after[identity]),
                         'fields': [field for field in fields
                                    if content(kind, before[identity])[field] != content(kind, after[identity])[field]]}
                        for identity in changed],
        }
    return {'origin': new['origin'], 'course_id': new['course_id'],
            'older_captured_at': old.get('captured_at'), 'newer_captured_at': new.get('captured_at'),
            'course_changed_fields': course_changes, 'changes': changes,
            'observed_changes': observed_changes, 'skipped': skipped}
