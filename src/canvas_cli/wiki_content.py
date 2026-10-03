"""Shared native wiki metadata and private content fingerprints, not write policy."""

from .client import CanvasError
from .events import timestamp
from .group_content import _id
from .writes import digest

PAGE_FIELDS = ('page_id', 'url', 'title', 'editing_roles', 'published', 'front_page', 'updated_at', 'publish_at')


def _metadata(row, page_id=None):
    identifier = _id(row, 'page_id')
    if page_id is not None and identifier != int(page_id):
        raise CanvasError('Canvas returned a different page ID')
    if (any(not isinstance(row.get(key), str) or not row[key] for key in ('url', 'title', 'editing_roles', 'updated_at')) or
            any(type(row.get(key)) is not bool for key in ('published', 'front_page')) or
            row.get('workflow_state') == 'deleted' or row.get('hidden_for_user') or row.get('locked_for_user')):
        raise CanvasError('Canvas returned an unavailable or malformed page')
    timestamp(row['updated_at'])
    if row.get('publish_at') is not None:
        timestamp(row['publish_at'])
    return {key: row.get(key) for key in PAGE_FIELDS}


def _html(row):
    if 'body' not in row or row['body'] is not None and not isinstance(row['body'], str):
        raise CanvasError('Canvas did not return readable page HTML')
    return row['body'] if row['body'] is not None else ''  # Native nil represents an unedited empty RCE page.


def _inventory(client, route, max_pages):
    rows = [_metadata(row) for row in client.list(route + '/pages?per_page=100', max_pages)]
    if len({row['page_id'] for row in rows}) != len(rows) or sum(row['front_page'] for row in rows) > 1:
        raise CanvasError('Canvas returned an ambiguous page/front-page inventory')
    return sorted(rows, key=lambda row: row['page_id'])


def _assignment(row, item, context_type):
    if row is None:
        return None
    _id(row)
    if (context_type != 'course' or type(row.get('course_id')) is not int or row['course_id'] != int(item) or
            not isinstance(row.get('name'), str) or not row['name'] or type(row.get('published')) is not bool or
            not isinstance(row.get('submission_types'), list) or not row['submission_types'] or
            any(not isinstance(value, str) for value in row['submission_types']) or
            len(set(row['submission_types'])) != len(row['submission_types']) or
            'wiki_page' not in row['submission_types'] or
            row.get('workflow_state') is not None and not isinstance(row['workflow_state'], str) or
            row.get('workflow_state') == 'deleted'):
        raise CanvasError('Canvas returned an invalid or foreign linked wiki assignment')
    timestamp(row.get('updated_at'))
    return {key: row.get(key) for key in ('id', 'course_id', 'name', 'submission_types', 'published', 'updated_at', 'workflow_state')}


def _content(row):
    editor = row.get('editor')
    if editor not in (None, 'rce', 'block_editor', 'block_content_editor'):
        raise CanvasError('Canvas returned an unknown native wiki editor')
    blocks, external = row.get('block_editor_attributes'), row.get('block_editor_data')
    if blocks is not None and external is not None:
        raise CanvasError('Canvas returned ambiguous native wiki content')
    block_id = None
    if blocks is not None:
        if not isinstance(blocks, dict) or 'blocks' not in blocks:
            raise CanvasError('Canvas did not return readable native block content')
        block_id = _id(blocks)
        payload = {'editor': editor, 'block_editor_attributes': blocks}
        comparable = {'kind': 'blocks', 'version': blocks.get('version'), 'blocks': blocks['blocks']}
    elif external is not None:
        if not isinstance(external, (dict, list, str)):
            raise CanvasError('Canvas did not return readable native external block content')
        payload = {'editor': editor, 'block_editor_data': external}
        comparable = {'kind': 'external', 'data': external}
    else:
        payload = {'editor': editor, 'body': _html(row)}
        comparable = {'kind': 'html', 'body': payload['body']}
    # Copies allocate a new block ID; equality never strips IDs from the source/preflight fingerprint.
    return {'kind': comparable['kind'], 'fingerprint': digest(payload),
            'copy_fingerprint': digest(comparable), 'block_id': block_id}
