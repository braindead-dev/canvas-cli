"""Own-account authentication and private origin configuration."""

import getpass
import json
import os
import sys
from pathlib import Path

from .client import CanvasError, Client, origin
from .writes import account

# Keep the historical storage namespace so renaming the app does not strand
# existing keyring credentials, configuration, or private sync baselines.
SERVICE = 'canvas-pocket'


def config_path():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / SERVICE / 'config.json'


def secure_keyring():
    import keyring
    backend = keyring.get_keyring()
    # Fail closed rather than accepting a plaintext/fallback third-party backend.
    allowed = ('keyring.backends.macOS', 'keyring.backends.Windows',
               'keyring.backends.SecretService', 'keyring.backends.kwallet')
    if not type(backend).__module__.startswith(allowed):
        raise CanvasError('No supported OS keyring selected. Configure an OS backend or use CANVAS_TOKEN for this process.')
    return keyring


def load():
    try:
        configuration = json.loads(config_path().read_text())
        if not isinstance(configuration, dict) or not isinstance(configuration.get('origin'), str):
            raise ValueError('Invalid configuration shape')
        host = origin(configuration['origin'])
    except (OSError, ValueError, KeyError):
        raise CanvasError('Run canvas-cli auth login first, or set CANVAS_ORIGIN and CANVAS_TOKEN.') from None
    return host


def selected_origin():
    return origin(os.environ['CANVAS_ORIGIN']) if os.environ.get('CANVAS_ORIGIN') else load()


def connect():
    host = selected_origin()
    token = os.environ.get('CANVAS_TOKEN') or secure_keyring().get_password(SERVICE, host)
    if not token:
        raise CanvasError('No credential found. Run auth login again.')
    return Client(host, token)


def login(origin_value):
    host = origin(origin_value)
    if not sys.stdin.isatty():
        raise CanvasError('Login requires an interactive terminal with hidden token entry.')
    print(f'Personal development testing with your own account only. Create a token in {host}/profile/settings. Apps for other users require institution-approved OAuth.', file=sys.stderr)
    token = getpass.getpass('Canvas token (hidden): ').strip()
    if not token:
        raise CanvasError('Empty token')
    account(Client(host, token))
    secure_keyring().set_password(SERVICE, host, token)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        os.fchmod(f.fileno(), 0o600)
        json.dump({'origin': host}, f)
    return {'authenticated': True, 'storage': 'OS keyring'}


def logout():
    host = selected_origin()
    kr = secure_keyring()
    if kr.get_password(SERVICE, host):
        kr.delete_password(SERVICE, host)
    return {'local_credential_removed': True,
            'note': 'Revoke the token in Canvas to invalidate it. Environment tokens are not removed.'}
