"""Whitelisted own profiles and explicit, read-back-verified personal edits."""

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .client import CanvasError
from .writes import check_flags, confirmed, digest, own_id

FIELDS = ('name', 'short_name', 'sortable_name', 'title', 'bio', 'pronunciation', 'pronouns',
          'time_zone', 'locale', 'effective_locale')
EDITABLE = frozenset(FIELDS) - {'locale', 'effective_locale'}
NAMES = frozenset(('name', 'short_name', 'sortable_name'))
READ_NOTE = ('Own profile only. Bio and primary email are opt-in; login/SIS/LTI IDs, avatars, '
             'calendar feed secrets, service links and unknown fields are never printed. '
             'Missing fields are unreported, not proof that their features are disabled.')


def _project(record, *, include_bio=False, include_email=False):
    result = {'id': own_id(record)}
    for key in FIELDS + (('primary_email',) if include_email else ()):
        if key == 'bio' and not include_bio or key not in record:
            continue
        value = record[key]
        if value is not None and not isinstance(value, str):
            raise CanvasError('Canvas returned invalid own-profile metadata')
        result[key] = value
    return result


def _read(client):
    record, links = client.request('/api/v1/users/self/profile')
    if re.search(r'<[^>]+>;\s*rel="next"', links):
        raise CanvasError('Unexpected own-profile pagination; refusing incomplete state')
    own_id(record)
    return record


def read(client, *, include_bio=False, include_email=False):
    return {'origin': client.host, 'own_profile': _project(_read(client), include_bio=include_bio,
                                                         include_email=include_email),
            'bio_included': include_bio, 'email_included': include_email, 'note': READ_NOTE}


def _changes(changes):
    if not isinstance(changes, dict) or not changes or any(key not in EDITABLE for key in changes):
        raise CanvasError('Select supported profile fields only; no email, login, avatar, locale or account-status edits')
    result = {}
    for key, value in changes.items():
        if not isinstance(value, str):
            raise CanvasError('Profile fields must be text; use empty text only to clear optional fields')
        limit = 10000 if key == 'bio' else 255
        if len(value) > limit or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', value):
            raise CanvasError('Profile text exceeds local bounds or contains control characters')
        if key != 'bio':
            if any(char in value for char in '\t\r\n'):
                raise CanvasError('Only a bio may contain newlines or tabs')
            value = value.strip()
        if key in NAMES and not value:
            raise CanvasError('Profile names cannot be empty')
        if key == 'time_zone':
            try:
                if not value or value.startswith(('/', '.')) or '\\' in value:
                    raise ValueError
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError):
                raise CanvasError('Use an available IANA time zone, for example America/Los_Angeles') from None
        result[key] = value
    return dict(sorted(result.items()))


def change(client, changes, *, acknowledge_shared=False, yes=False, confirm=None):
    check_flags(yes, confirm)
    changes = _changes(changes)
    shared = any(key != 'time_zone' for key in changes)
    if shared and acknowledge_shared is not True:
        raise CanvasError('Names and profile text are shared with other Canvas users; add --acknowledge-shared-profile')
    record = _read(client)
    identity = {'origin': client.host, 'user_id': own_id(record)}
    current = _project(record, include_bio='bio' in changes)
    # Bind the full public profile revision without printing an unselected bio.
    revision = _project(record, include_bio=True)
    preview = {**identity, 'current_profile': current, 'profile_revision': digest(revision),
               'requested_fields': changes, 'shared_profile_change': shared,
               'method': 'PUT', 'route': '/api/v1/users/self',
               'body': {'user': changes, 'override_sis_stickiness': False},
               'effect': 'Change only the selected fields on your own Canvas user/profile. '
                         'Names are used in grading, discussions and messages; profile text may be visible to peers. '
                         'Time zone affects Canvas date displays, not assignment deadlines.',
               'warning': 'Institution permissions, feature settings and SIS-managed fields may block edits. '
                          'No SIS stickiness override is requested. Native name updates may derive other names. '
                          'This preview is not permission approval or an atomic lock. A batch may partially apply; '
                          'exact selected fields must be verified by a subsequent own-profile read. '
                          'No emails, logins, avatars, sessions, enrollment or schoolwork changes are requested.'}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    try:
        if own_id(response) != identity['user_id']:
            raise CanvasError('Profile acknowledgement mismatch')
        after = _project(_read(client), include_bio='bio' in changes)
        if after['id'] != identity['user_id']:
            raise CanvasError('Profile read-back account mismatch')
        for key, value in changes.items():
            actual = after.get(key)
            if actual != value and not (value == '' and key not in NAMES and actual is None):
                raise CanvasError('Selected field read-back mismatch')
    except CanvasError:
        raise CanvasError('Could not verify exact Canvas profile changes. Some edits may have applied; '
                          'check your Canvas profile before repeating. No automatic retries or raw response logging.') from None
    return {**identity, 'profile_changes': {key: after.get(key) for key in changes},
            'read_back_verified': True, 'shared_profile_change': shared,
            'note': 'Exact selected fields were verified in a subsequent own-profile GET. '
                    'This is not an atomic lock or a guarantee against later SIS/institution changes. '
                    'No email, login, avatar, enrollment, read-marker or schoolwork changes were requested.'}
