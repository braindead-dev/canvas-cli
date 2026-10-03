"""Native previous/next occurrence metadata, never implicit content navigation."""

import re
from urllib.parse import urlencode

from .client import CanvasError
from .group_content import _context, _id, _number, base
from .module_items import _item, _module_metadata

ASSET_TYPES = ('ModuleItem', 'File', 'Page', 'Discussion', 'Assignment', 'Quiz', 'ExternalTool')
NOTE = ('Native course sequence metadata, not a complete item inventory. Canvas returns at most ten '
        'asset occurrences; ten means more may exist. Quiz/discussion occurrences can reference their '
        'associated assignment. Use ModuleItem for one exact occurrence. Asset locks/completion are '
        'not probed; missing status is unknown. No content URL is followed, mastery path selected, '
        'view/done event or assessment attempt sent. Conditional-release evaluation may have native effects.')


def _asset(asset_type, asset_id):
    if asset_type not in ASSET_TYPES:
        raise CanvasError('Select a documented native module-sequence asset type')
    if asset_type != 'Page':
        return _number(asset_id)
    if (not isinstance(asset_id, str) or not asset_id or asset_id in ('.', '..') or
            len(asset_id) > 255 or any(char in asset_id for char in ('/', '\\', '?', '#')) or
            any(ord(char) < 32 or 0x7f <= ord(char) < 0xa0 or 0xd800 <= ord(char) < 0xe000 for char in asset_id)):
        raise CanvasError('Page sequence lookup needs one page URL slug, not an absolute URL, path or controls')
    return asset_id


def _node(row, modules, client, course_id):
    if row is None:
        return None
    module_id = _id(row, 'module_id')
    if module_id not in modules:
        raise CanvasError('Canvas returned a sequence item without its referenced module')
    projected = _item(row, str(module_id), client, course_id, require_details=False)
    # Sequence serialization does not include content_details or a student progression.
    # Do not turn their absence into a reported unlocked/incomplete status.
    projected.pop('content_lock_reported')
    projected['locked_for_user'] = None
    return projected


def _mastery(row, course_id, item_id, client):
    if row is None:
        return None
    if not isinstance(row, dict):
        raise CanvasError('Canvas returned malformed mastery-path metadata')
    result = {}
    for key in ('locked', 'awaiting_choice', 'still_processing', 'modules_tab_disabled'):
        if key in row:
            if type(row[key]) is not bool:
                raise CanvasError('Canvas returned malformed mastery-path flags')
            result[key] = row[key]
    if 'selected_set_id' in row:
        if row['selected_set_id'] is not None:
            _id(row, 'selected_set_id')
        result['selected_set_id'] = row['selected_set_id']
    if 'assignment_sets' in row:
        if not isinstance(row['assignment_sets'], list):
            raise CanvasError('Canvas returned malformed mastery-path sets')
        identifiers = [_id(item) for item in row['assignment_sets']]
        if len(set(identifiers)) != len(identifiers):
            raise CanvasError('Canvas returned duplicate mastery-path sets')
        result['assignment_set_ids'] = identifiers
    if result.get('awaiting_choice'):
        result['choose_html_url'] = client.host + f'/courses/{course_id}/modules/items/{item_id}/choose'
    return result


def _association(client, route, asset_type, asset_id, currents):
    associated = None
    if asset_type in ('Quiz', 'Discussion') and any(row['type'] == 'Assignment' for row in currents):
        resource = 'quizzes' if asset_type == 'Quiz' else 'discussion_topics'
        asset, _ = client.request(route + '/' + resource + '/' + asset_id)
        course_id = int(route.rsplit('/', 1)[1])
        if _id(asset) != int(asset_id) or 'course_id' in asset and _id(asset, 'course_id') != course_id:
            raise CanvasError('Canvas returned a different sequence source asset')
        associated = _id(asset, 'assignment_id')
    for row in currents:
        if asset_type == 'ModuleItem':
            matches = row['id'] == int(asset_id)
        elif asset_type == 'Page':
            matches = row['type'] == 'Page' and row.get('page_url') == asset_id
        else:
            matches = (row['type'] == asset_type and type(row.get('content_id')) is int and row['content_id'] == int(asset_id) or
                       row['type'] == 'Assignment' and associated is not None and
                       type(row.get('content_id')) is int and row['content_id'] == associated)
        if not matches:
            raise CanvasError('Canvas returned an occurrence of a different source asset')


def sequence(client, course_id, asset_type, asset_id):
    base(course_id, 'course')
    asset_id = _asset(asset_type, asset_id)
    route, context = _context(client, course_id, 'course')
    result, links = client.request(route + '/module_item_sequence?' + urlencode({'asset_type': asset_type, 'asset_id': asset_id}))
    if (not isinstance(result, dict) or not isinstance(result.get('items'), list) or
            not isinstance(result.get('modules'), list) or len(result['items']) > 10 or
            re.search(r'<[^>]+>;\s*rel="next"', links)):
        raise CanvasError('Canvas returned a malformed or unexpectedly paginated native sequence')
    modules = {}
    for row in result['modules']:
        identifier = _id(row)
        if identifier in modules or 'course_id' in row and _id(row, 'course_id') != int(course_id):
            raise CanvasError('Canvas returned duplicate or foreign sequence modules')
        modules[identifier] = _module_metadata(row)
    items = []
    for row in result['items']:
        if not isinstance(row, dict) or row.get('current') is None or any(key not in row for key in ('prev', 'next')):
            raise CanvasError('Canvas returned malformed sequence neighbors')
        node = {key: _node(row[key], modules, client, course_id) for key in ('prev', 'current', 'next')}
        node['mastery_path'] = _mastery(row.get('mastery_path'), course_id, node['current']['id'], client)
        items.append(node)
    currents = [row['current'] for row in items]
    if len({row['id'] for row in currents}) != len(currents) or asset_type == 'ModuleItem' and len(items) > 1:
        raise CanvasError('Canvas returned duplicate or ambiguous exact item occurrences')
    _association(client, route, asset_type, asset_id, currents)
    return {'course_id': int(course_id), 'course_name': context.get('name'), 'asset_type': asset_type,
            'asset_id': asset_id, 'module_sequence': items, 'modules': list(modules.values()),
            'native_occurrence_limit': 10, 'at_native_limit': len(items) == 10,
            'matched_occurrences': len(items), 'note': NOTE}
