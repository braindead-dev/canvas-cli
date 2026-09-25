import argparse
import getpass
import html
import json
import os
from pathlib import Path
import sys

from .client import CanvasError, Client, origin

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
        host = origin(json.loads(config_path().read_text())['origin'])
    except (OSError, ValueError, KeyError):
        raise CanvasError('Run canvas-pocket auth login first, or set CANVAS_ORIGIN and CANVAS_TOKEN.') from None
    return host


def identifier(value):
    if not value.isdecimal() or int(value) < 1:
        raise argparse.ArgumentTypeError('Expected a positive numeric ID')
    return value


def parser():
    p = argparse.ArgumentParser(description='Canvas API CLI. JSON output may contain private academic data.')
    p.add_argument('--max-pages', type=int, default=100)
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('auth').add_subparsers(dest='action', required=True)
    a.add_parser('login').add_argument('--origin', required=True)
    a.add_parser('status')
    a.add_parser('logout')
    sub.add_parser('courses')
    sub.add_parser('me')
    for name in ('assignments', 'modules', 'pages', 'files', 'discussions', 'announcements', 'syllabus'):
        sub.add_parser(name).add_argument('course', type=identifier)
    for name in ('entries', 'replies', 'post'):
        s = sub.add_parser(name)
        s.add_argument('course', type=identifier)
        s.add_argument('topic', type=identifier)
        if name == 'replies':
            s.add_argument('entry', type=identifier)
        if name == 'post':
            s.add_argument('--reply-to', type=identifier)
            s.add_argument('--message-file', required=True, type=Path)
            s.add_argument('--yes', action='store_true', help='Explicitly authorize this post')
    return p


def run(args):
    if args.max_pages < 1:
        raise CanvasError('--max-pages must be positive')
    if args.command == 'auth' and args.action == 'login':
        host = origin(args.origin)
        if not sys.stdin.isatty():
            raise CanvasError('Login requires an interactive terminal with hidden token entry.')
        print(f'Create a personal access token in {host}/profile/settings. Institutional policy may disable tokens.', file=sys.stderr)
        token = getpass.getpass('Canvas token (hidden): ').strip()
        if not token:
            raise CanvasError('Empty token')
        Client(host, token).request('/api/v1/users/self/profile')
        secure_keyring().set_password(SERVICE, host, token)
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            os.fchmod(f.fileno(), 0o600)
            json.dump({'origin': host}, f)
        return {'authenticated': True, 'storage': 'OS keyring'}
    host = origin(os.environ['CANVAS_ORIGIN']) if os.environ.get('CANVAS_ORIGIN') else load()
    if args.command == 'auth' and args.action == 'logout':
        kr = secure_keyring()
        if kr.get_password(SERVICE, host):
            kr.delete_password(SERVICE, host)
        return {'local_credential_removed': True, 'note': 'Revoke the token in Canvas to invalidate it. Environment tokens are not removed.'}
    token = os.environ.get('CANVAS_TOKEN') or secure_keyring().get_password(SERVICE, host)
    if not token:
        raise CanvasError('No credential found. Run auth login again.')
    client = Client(host, token)
    if args.command in ('auth', 'me'):
        data, _ = client.request('/api/v1/users/self/profile')
        return {'authenticated': True} if args.command == 'auth' else data
    if args.command == 'courses':
        return client.list('/api/v1/courses?per_page=100', args.max_pages)
    base = f'/api/v1/courses/{args.course}'
    if args.command == 'syllabus':
        return client.request(base + '?include[]=syllabus_body')[0]
    if args.command in ('entries', 'replies', 'post'):
        route = base + f'/discussion_topics/{args.topic}/entries'
        if args.command == 'replies':
            route += f'/{args.entry}/replies'
        if args.command == 'post':
            if args.reply_to:
                route += f'/{args.reply_to}/replies'
            message = args.message_file.read_text(encoding='utf-8')
            if not message.strip():
                raise CanvasError('Empty message refused')
            # Plain text input, escaped before Canvas renders it as HTML.
            body = {'message': '<p>' + html.escape(message).replace('\n', '<br>') + '</p>'}
            if not args.yes:
                return {'dry_run': True, 'method': 'POST', 'origin': host, 'path': route, 'body': body,
                        'next': 'Review the exact destination and body, then repeat with --yes to publish.'}
            return client.request(route, 'POST', body)[0]
        return client.list(route + '?per_page=100', args.max_pages)
    resource = {'discussions': 'discussion_topics', 'announcements': 'discussion_topics'}.get(args.command, args.command)
    route = base + '/' + resource + '?per_page=100'
    if args.command == 'announcements':
        route += '&only_announcements=true'
    return client.list(route, args.max_pages)


def main():
    try:
        print(json.dumps(run(parser().parse_args()), indent=2))
    except CanvasError as e:
        print(f'Error: {e}', file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print('Error: local file/configuration operation failed; no private contents logged.', file=sys.stderr)
        return 1
    except Exception:
        print('Error: credential backend or operation failed; no sensitive diagnostic output logged.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
