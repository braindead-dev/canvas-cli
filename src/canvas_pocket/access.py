"""Ask Canvas about exact own context rights, never infer an admin role."""

import re
from urllib.parse import urlencode

from .client import CanvasError
from .group_content import _context


def _names(names):
    if (not isinstance(names, (list, tuple)) or not 1 <= len(names) <= 50 or
            any(not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', name) for name in names) or
            len(set(names)) != len(names)):
        raise CanvasError('Select 1–50 distinct native permission keys, using lowercase letters, digits and underscores')
    return sorted(names)


def query(client, route, names):
    requested = _names(names)
    response, links = client.request(route + '/permissions?' + urlencode([('permissions[]', name) for name in requested]))
    if (not isinstance(response, dict) or any(type(response.get(name)) is not bool for name in requested) or
            re.search(r'<[^>]+>;\s*rel="next"', links)):
        raise CanvasError('Canvas did not return explicit booleans for all requested permission keys')
    return {name: response[name] for name in requested}


def read(client, context_id, context_type='course', *, names=()):
    requested = _names(names)
    if context_type not in ('course', 'group'):
        raise CanvasError('Permission context must be course or group')
    route, context = _context(client, context_id, context_type)
    permissions = query(client, route, requested)
    return {'context_type': context_type, f'{context_type}_id': int(context_id), 'context_name': context.get('name'),
            'permissions': permissions,
            'note': 'Current native rights for this signed-in user and the exact requested keys only. '
                    'False can mean denied, unsupported or feature-disabled; it does not diagnose why. '
                    'Rights may change and do not guarantee that a future write succeeds. '
                    'No permission, enrollment, membership or role changes requested.'}
