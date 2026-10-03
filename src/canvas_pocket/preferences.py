"""Own-user dashboard and interface preferences, with explicit field-only writes."""

import re

from .client import CanvasError
from .writes import account, check_flags, confirmed

SETTING_KEYS = (
    'manual_mark_as_read', 'collapse_global_nav', 'collapse_course_nav',
    'hide_dashcard_color_overlays', 'release_notes_badge_disabled',
    'comment_library_suggestions_enabled', 'elementary_dashboard_disabled',
    'default_to_block_editor', 'widget_dashboard_user_preference', 'widget_dashboard_dark_mode',
)


def _number(value):
    if (not isinstance(value, str) or not value.isascii() or not value.isdecimal() or
            int(value) < 1 or str(int(value)) != value):
        raise CanvasError('Expected a positive numeric context ID')
    return value


def _nickname(record, course_id=None):
    if (not isinstance(record, dict) or type(record.get('course_id')) is not int or record['course_id'] < 1 or
            (course_id is not None and str(record['course_id']) != course_id) or
            not isinstance(record.get('name'), str) or 'nickname' not in record or
            (record['nickname'] is not None and not isinstance(record['nickname'], str))):
        raise CanvasError('Canvas returned an invalid or different course nickname')
    return {key: record.get(key) for key in ('course_id', 'name', 'nickname')}


def nicknames(client, max_pages=100):
    rows = [_nickname(row) for row in client.list('/api/v1/users/self/course_nicknames?per_page=100', max_pages)]
    if len({row['course_id'] for row in rows}) != len(rows):
        raise CanvasError('Canvas returned duplicate nickname records')
    return rows


def nickname(client, course_id):
    _number(course_id)
    return _nickname(client.request(f'/api/v1/users/self/course_nicknames/{course_id}')[0], course_id)


def change_nickname(client, course_id=None, name=None, *, clear=False, reset=False,
                    max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    if reset:
        if course_id is not None or name is not None or clear:
            raise CanvasError('Nickname reset affects all own nicknames, not one course')
    else:
        _number(course_id)
        if clear:
            if name is not None:
                raise CanvasError('Nickname removal cannot combine with a new nickname')
        elif (not isinstance(name, str) or not name.strip() or len(name.strip()) >= 60 or
              any(ord(char) < 32 or ord(char) == 127 for char in name)):
            raise CanvasError('Nickname must be nonempty, shorter than 60 characters and without control characters')
    identity = account(client)
    route = '/api/v1/users/self/course_nicknames'
    if reset:
        current = sorted(nicknames(client, max_pages), key=lambda row: row['course_id'])
    else:
        route += f'/{course_id}'
        current = nickname(client, course_id)
        if clear and current['nickname'] is None:
            raise CanvasError('No nickname is stored for this course; there is nothing to remove')
    body = None if clear or reset else {'nickname': name.strip()}
    preview = {**identity, 'method': 'DELETE' if clear or reset else 'PUT', 'route': route,
               'body': body, 'current': current,
               'effect': ('Remove ALL your stored course nicknames.' if reset else
                          'Change only your nickname for this course, not the shared course name.'),
               'warning': 'Nicknames affect course names in your later API responses as well as selected Canvas views.'}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    if reset:
        if not isinstance(response, dict) or response.get('message') != 'OK':
            raise CanvasError('Nickname reset was not confirmed; verify Canvas before repeating')
        result = None
    else:
        try:
            result = _nickname(response, course_id)
        except CanvasError:
            raise CanvasError('Nickname response did not confirm the expected course; verify Canvas before repeating') from None
        if result['nickname'] != (None if clear else body['nickname']):
            raise CanvasError('Nickname response did not confirm the change; verify Canvas before repeating')
    return {'nickname_change': result, 'reset_all': bool(reset), 'acknowledged': True,
            'note': 'Only your own nickname preferences changed. Shared course names and enrollment are unchanged.'}


def _hex(value):
    if not isinstance(value, str) or not re.fullmatch(r'#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})', value):
        raise CanvasError('Color must be a three- or six-digit RGB hex code')
    return '#' + value.lstrip('#').lower()


def colors(client):
    record, _ = client.request('/api/v1/users/self/colors')
    if not isinstance(record, dict) or not isinstance(record.get('custom_colors'), dict):
        raise CanvasError('Canvas did not provide your custom color map')
    result = record['custom_colors']
    for asset, value in result.items():
        if not isinstance(asset, str):
            raise CanvasError('Canvas returned an invalid custom color context')
        _hex(value)
    return {'custom_colors': result}


def _asset(item_id, context_type):
    _number(item_id)
    if context_type not in ('course', 'group', 'user'):
        raise CanvasError('Color context must be course, group or user')
    return f'{context_type}_{item_id}'


def color(client, item_id, context_type='course'):
    asset = _asset(item_id, context_type)
    value = colors(client)['custom_colors'].get(asset)
    return {'asset_string': asset, 'hexcode': value,
            'note': 'Only saved custom colors are reported. An absent value does not identify the default UI color.'}


def change_color(client, item_id, hexcode, *, context_type='course', yes=False, confirm=None):
    check_flags(yes, confirm)
    asset = _asset(item_id, context_type)
    value = _hex(hexcode)
    identity = account(client)
    if context_type == 'user':
        if int(item_id) != identity['user_id']:
            raise CanvasError('User color changes are restricted to your own personal calendar')
        target = {'id': identity['user_id'], 'name': 'Your personal calendar'}
    else:
        target, _ = client.request(f'/api/v1/{context_type}s/{item_id}')
        if (not isinstance(target, dict) or type(target.get('id')) is not int or str(target['id']) != item_id):
            raise CanvasError('Canvas returned a different color destination')
        target = {key: target.get(key) for key in ('id', 'name')}
    current = color(client, item_id, context_type)
    preview = {**identity, 'method': 'PUT', 'route': f'/api/v1/users/self/colors/{asset}',
               'body': {'hexcode': value}, 'target': target, 'current': current,
               'effect': 'Change only your saved display color for this context. Other users and enrollment are unaffected.'}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        matches = isinstance(response, dict) and _hex(response.get('hexcode')) == value
    except CanvasError:
        matches = False
    if not matches:
        raise CanvasError('Color response did not confirm the requested value; verify Canvas before repeating')
    return {'color_change': {'asset_string': asset, 'hexcode': response['hexcode']}, 'acknowledged': True,
            'note': 'Only your own custom display color changed. Other users and enrollment are unchanged.'}


def _settings(record):
    if not isinstance(record, dict):
        raise CanvasError('Canvas returned invalid own-user settings')
    visible = {key: record[key] for key in SETTING_KEYS if key in record}
    if any(type(value) is not bool for value in visible.values()):
        raise CanvasError('Canvas returned a non-boolean display setting')
    return {'settings': visible, 'unreported_keys': [key for key in SETTING_KEYS if key not in record]}


def settings(client):
    # Never request mobile_settings: it can include service keys and telemetry configuration.
    return _settings(client.request('/api/v1/users/self/settings')[0])


def setting_pairs(values):
    """Parse repeated exact KEY=true|false options without accepting arbitrary user fields."""
    changes = {}
    for value in values:
        if not isinstance(value, str) or value.count('=') != 1:
            raise CanvasError('Each setting must be KEY=true or KEY=false')
        key, literal = value.split('=')
        if key not in SETTING_KEYS or literal not in ('true', 'false') or key in changes:
            raise CanvasError('Setting keys must be supported, unique and use exactly true or false')
        changes[key] = literal == 'true'
    return changes


def change_settings(client, changes, *, yes=False, confirm=None):
    check_flags(yes, confirm)
    if (not isinstance(changes, dict) or not changes or
            any(key not in SETTING_KEYS or type(value) is not bool for key, value in changes.items())):
        raise CanvasError('Provide at least one supported boolean setting')
    identity = account(client)
    current = settings(client)
    if any(key not in current['settings'] for key in changes):
        raise CanvasError('A requested setting was not reported by this Canvas deployment; it will not be guessed')
    preview = {**identity, 'method': 'PUT', 'route': '/api/v1/users/self/settings',
               'body': dict(changes), 'current': current,
               'effect': 'Change only the specified own-user interface preferences.',
               'warning': 'manual_mark_as_read affects future browser discussion read behavior, not existing markers. '
                          'Institution features may override the visible effect of some preferences.'}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        result = _settings(response)
        matches = all(result['settings'].get(key) is value for key, value in changes.items())
    except CanvasError:
        matches = False
    if not matches:
        raise CanvasError('Settings response did not confirm the requested values; verify Canvas before repeating')
    return {'settings_change': dict(changes), 'acknowledged': True,
            'note': 'Only specified own-user preferences were sent. Existing read markers and course content are unchanged.'}


def _position(value):
    if isinstance(value, str) and re.fullmatch(r'[+-]?[0-9]+', value):
        value = int(value)
    if type(value) is not int or abs(value) > 1000:
        raise CanvasError('Dashboard position must be an integer between -1000 and 1000')
    return value


def _asset_parts(asset):
    if not isinstance(asset, str) or not re.fullmatch(r'(?:course|group|user)_[1-9][0-9]*', asset):
        raise CanvasError('Dashboard context must be course_ID, group_ID or your own user_ID')
    context, item_id = asset.split('_', 1)
    return context, item_id


def _positions(record):
    if not isinstance(record, dict) or not isinstance(record.get('dashboard_positions'), dict):
        raise CanvasError('Canvas returned an invalid dashboard position map')
    mapping = record['dashboard_positions']
    for asset, value in mapping.items():
        if not isinstance(asset, str):
            raise CanvasError('Canvas returned an invalid dashboard context')
        _position(value)
    return {'dashboard_positions': dict(mapping)}


def positions(client):
    return _positions(client.request('/api/v1/users/self/dashboard_positions')[0])


def ordered_positions(assets):
    if not isinstance(assets, (list, tuple)) or not assets or len(assets) > 1001:
        raise CanvasError('Provide between one and 1001 dashboard contexts in desired order')
    for asset in assets:
        _asset_parts(asset)
    if len(set(assets)) != len(assets):
        raise CanvasError('Dashboard ordering cannot repeat a context')
    return {asset: index for index, asset in enumerate(assets)}


def change_positions(client, changes, *, yes=False, confirm=None):
    check_flags(yes, confirm)
    if not isinstance(changes, dict) or not changes:
        raise CanvasError('Provide at least one dashboard position')
    body = {}
    for asset, value in changes.items():
        _asset_parts(asset)
        body[asset] = _position(value)
    identity = account(client)
    targets = []
    for asset in body:
        context, item = _asset_parts(asset)
        if context == 'user':
            if int(item) != identity['user_id']:
                raise CanvasError('User dashboard preferences are restricted to your own user ID')
            target = {'id': identity['user_id'], 'name': 'Your personal context'}
        else:
            target, _ = client.request(f'/api/v1/{context}s/{item}')
            if not isinstance(target, dict) or type(target.get('id')) is not int or str(target['id']) != item:
                raise CanvasError('Canvas returned a different dashboard destination')
            target = {key: target.get(key) for key in ('id', 'name')}
        targets.append({'asset_string': asset, **target})
    current = positions(client)
    preview = {**identity, 'method': 'PUT', 'route': '/api/v1/users/self/dashboard_positions',
               'body': {'dashboard_positions': body}, 'current': current, 'targets': targets,
               'effect': 'Merge only these positions into your own saved dashboard order.',
               'warning': 'Unspecified saved positions remain. Equal positions can leave UI ordering ambiguous; '
                          'this does not change favorites or guarantee a card is visible.'}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        result = _positions(response)['dashboard_positions']
        matches = all(asset in result and _position(result[asset]) == value for asset, value in body.items())
    except CanvasError:
        matches = False
    if not matches:
        raise CanvasError('Dashboard response did not confirm the requested positions; verify Canvas before repeating')
    return {'positions_change': body, 'acknowledged': True,
            'note': 'Only requested own dashboard positions were sent. Favorites, enrollment and course content are unchanged.'}
