import argparse
import getpass
import html
import json
import os
from pathlib import Path
from urllib.parse import quote
import sys
from datetime import datetime, timezone

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
    p.add_argument('--format', choices=('json', 'brief'), default='json', help='Output format; JSON is complete')
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('auth').add_subparsers(dest='action', required=True)
    login = a.add_parser('login', help='Personal development testing with your own account')
    login.add_argument('--origin', required=True)
    a.add_parser('status')
    a.add_parser('logout')
    courses = sub.add_parser('courses')
    courses.add_argument('--active', action='store_true', help='Only current active enrollments')
    sub.add_parser('me')
    sub.add_parser('todo', help='Your Canvas to-do items')
    sub.add_parser('upcoming', help='Upcoming assignments and events')
    sub.add_parser('overview', help='Active courses, upcoming work, and to-do items')
    due = sub.add_parser('deadlines', help='Assignment deadlines across active courses')
    due.add_argument('--days', type=int, default=14, help='Look ahead this many days; default 14')
    due.add_argument('--course', type=identifier, help='Limit to one course')
    linked = sub.add_parser('linked-files', help='Find file links in accessible course content')
    linked.add_argument('course', type=identifier)
    sub.add_parser('capabilities', help='Discover commands without logging in')
    s = sub.add_parser('download', help='Download one accessible course file without overwriting')
    s.add_argument('course', type=identifier)
    s.add_argument('file', type=identifier)
    s.add_argument('--output', required=True, type=Path)
    s.add_argument('--max-bytes', type=int, default=100 * 1024 * 1024)
    for name in ('assignment', 'page', 'module-items'):
        s = sub.add_parser(name, help='Read one resource or list module items')
        s.add_argument('course', type=identifier)
        s.add_argument('item', type=str if name == 'page' else identifier)
    s = sub.add_parser('get', help='Advanced read-only Canvas API request')
    s.add_argument('path', help='An /api/v1/ path, including optional query parameters')
    s.add_argument('--paginate', action='store_true')
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
    if args.command == 'capabilities':
        return {'read': ['courses', 'me', 'todo', 'upcoming', 'overview', 'deadlines', 'linked-files', 'assignments', 'assignment', 'syllabus', 'modules', 'module-items', 'pages', 'page', 'files', 'announcements', 'discussions', 'entries', 'replies', 'get'], 'write': ['post (preview unless --yes)'], 'auth': ['login', 'status', 'logout'], 'format': 'JSON', 'limitations': ['No quiz attempts or submissions', 'No file uploads', 'No OAuth browser consent yet']}
    if args.command == 'auth' and args.action == 'login':
        host = origin(args.origin)
        if not sys.stdin.isatty():
            raise CanvasError('Login requires an interactive terminal with hidden token entry.')
        print(f'Personal development testing with your own account only. Create a token in {host}/profile/settings. Apps for other users require institution-approved OAuth.', file=sys.stderr)
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
    if args.command == 'linked-files':
        from .discovery import linked_files
        return linked_files(client, args.course, args.max_pages)
    if args.command == 'deadlines':
        from .planning import deadlines
        if args.days < 1:
            raise CanvasError('--days must be positive')
        return deadlines(client, args.max_pages, args.days, args.course)
    if args.command == 'get':
        if not args.path.startswith('/api/v1/'):
            raise CanvasError('get requires an /api/v1/ path')
        return client.list(args.path, args.max_pages) if args.paginate else client.request(args.path)[0]
    if args.command == 'todo':
        return client.list('/api/v1/users/self/todo?per_page=100', args.max_pages)
    if args.command == 'upcoming':
        return client.list('/api/v1/users/self/upcoming_events?per_page=100', args.max_pages)
    if args.command == 'overview':
        from .planning import deadlines
        courses = client.list('/api/v1/courses?enrollment_state=active&per_page=100', args.max_pages)
        upcoming = client.list('/api/v1/users/self/upcoming_events?per_page=100', args.max_pages)
        todo = client.list('/api/v1/users/self/todo?per_page=100', args.max_pages)
        return {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'courses': [{'id': c.get('id'), 'name': c.get('name'), 'course_code': c.get('course_code'),
                         'workflow_state': c.get('workflow_state')} for c in courses],
            'upcoming': upcoming, 'todo': todo,
            'deadlines': deadlines(client, args.max_pages, 14, courses=courses),
        }
    if args.command in ('auth', 'me'):
        data, _ = client.request('/api/v1/users/self/profile')
        return {'authenticated': True} if args.command == 'auth' else data
    if args.command == 'courses':
        route = '/api/v1/courses?per_page=100'
        if args.active:
            route += '&enrollment_state=active'
        return client.list(route, args.max_pages)
    base = f'/api/v1/courses/{args.course}'
    if args.command == 'download':
        from .download import download
        metadata = client.request(base + f'/files/{args.file}')[0]
        if metadata.get('locked_for_user') or metadata.get('hidden_for_user'):
            raise CanvasError('File is unavailable to this user')
        if not metadata.get('url'):
            raise CanvasError('Canvas did not provide a download URL')
        return download(metadata['url'], args.output, args.max_bytes)
    if args.command in ('assignment', 'page', 'module-items'):
        item = quote(args.item, safe='')
        if args.command == 'module-items':
            return client.list(base + f'/modules/{item}/items?per_page=100', args.max_pages)
        resource = 'assignments' if args.command == 'assignment' else 'pages'
        return client.request(base + f'/{resource}/{item}')[0]
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


def brief(data):
    """Small human index. JSON remains the complete representation."""
    if isinstance(data, list):
        if not data:
            return 'No items.'
        lines = []
        for item in data:
            if not isinstance(item, dict):
                lines.append(str(item))
                continue
            number = item.get('id') or item.get('assignment_id') or ''
            label = (item.get('course_code') or item.get('name') or item.get('title')
                     or item.get('display_name') or item.get('filename') or item.get('type') or 'item')
            if item.get('course_code') and item.get('name') and item['name'] != item['course_code']:
                label += f" — {item['name']}"
            elif item.get('course_name') and item.get('name'):
                label = f"{item['course_name']}: {item['name']}"
            detail = item.get('due_at') or item.get('start_at') or item.get('workflow_state') or ''
            lines.append('  '.join(str(x) for x in (number, label, detail) if x != ''))
        return '\n'.join(lines)
    if isinstance(data, dict) and all(k in data for k in ('courses', 'upcoming', 'todo')):
        lines = [(title, data[key]) for title, key in
                 [('Active courses', 'courses'), ('Upcoming', 'upcoming'), ('To do', 'todo')]]
        if 'deadlines' in data:
            lines.append(('Deadlines (next 14 days)', data['deadlines']))
        return '\n\n'.join(f'{title}\n{brief(values)}' for title, values in lines)
    if isinstance(data, dict) and 'assignments' in data and 'unavailable_courses' in data:
        result = brief(data['assignments'])
        if data['unavailable_courses']:
            result += f"\nAssignments unavailable for {len(data['unavailable_courses'])} course(s); see JSON for details."
        return result
    if isinstance(data, dict) and 'files' in data and 'skipped_sources' in data:
        result = brief(data['files'])
        if data['skipped_sources']:
            result += f"\nSkipped {len(data['skipped_sources'])} source(s); see JSON for details."
        return result
    return json.dumps(data, indent=2)


def main():
    try:
        args = parser().parse_args()
        data = run(args)
        print(brief(data) if args.format == 'brief' else json.dumps(data, indent=2))
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
