"""Shared account-bound previews for explicit, non-retried Canvas writes."""

import hashlib
import json

from .client import CanvasError


def own_id(profile):
    if not isinstance(profile, dict) or type(profile.get('id')) is not int or profile['id'] < 1:
        raise CanvasError('Canvas did not identify the signed-in user')
    return profile['id']


def account(client):
    profile, _ = client.request('/api/v1/users/self/profile')
    return {'origin': client.host, 'user_id': own_id(profile)}


def check_flags(yes, confirm):
    if bool(yes) != bool(confirm):
        raise CanvasError('Sending requires both --yes and --confirm from a prior preview')


def digest(preview):
    return hashlib.sha256(json.dumps(preview, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def confirmed(client, preview, yes=False, confirm=None):
    """The caller must re-read identity and destination to construct this fresh preview."""
    check_flags(yes, confirm)
    expected = digest(preview)
    if not yes:
        return {'dry_run': True, **preview, 'confirm': expected,
                'next': 'Review the account, destination and exact changes, then repeat with --yes --confirm DIGEST.'}
    if confirm != expected:
        raise CanvasError('Preview changed (account, destination or content); review a fresh preview')
    return client.request(preview['route'], preview['method'], preview.get('body'))[0]
