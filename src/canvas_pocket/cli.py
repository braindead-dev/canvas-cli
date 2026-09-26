import argparse
import getpass
import hashlib
import html
import json
import os
import re
from pathlib import Path
from urllib.parse import quote, urlencode
import sys
from datetime import date, datetime, timedelta, timezone

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


def calendar_date(value):
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError
        date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError('Expected a date in YYYY-MM-DD format') from None
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
    sub.add_parser('favorites', help='Your favorite courses')
    sub.add_parser('groups', help='Your active Canvas groups')
    group = sub.add_parser('group', help='One visible group')
    group.add_argument('group', type=identifier)
    course_groups = sub.add_parser('course-groups', help='Visible groups in a course')
    course_groups.add_argument('course', type=identifier)
    inbox = sub.add_parser('inbox', help='List Canvas Inbox conversations')
    inbox.add_argument('--scope', choices=('unread', 'starred', 'archived', 'sent'))
    inbox.add_argument('--course', type=identifier, help='Filter to a course context')
    conversation = sub.add_parser('conversation', help='Read one Inbox thread without marking it read')
    conversation.add_argument('conversation', type=identifier)
    reply = sub.add_parser('inbox-reply', help='Preview an Inbox reply; sending requires a matching digest')
    reply.add_argument('conversation', type=identifier)
    reply.add_argument('--message-file', required=True, type=Path)
    reply.add_argument('--confirm', help='Digest returned by the preview')
    reply.add_argument('--yes', action='store_true', help='Send only if --confirm matches the fresh preview')
    people = sub.add_parser('recipients', help='Find individual users Canvas permits you to message')
    match = people.add_mutually_exclusive_group(required=True)
    match.add_argument('--search', help='Search name or other permitted recipient text')
    match.add_argument('--user-id', type=identifier, help='Check one numeric user ID')
    people.add_argument('--course', type=identifier, help='Limit a text search to one course')
    compose = sub.add_parser('inbox-compose', help='Preview a new one-recipient Canvas Inbox message')
    compose.add_argument('--recipient', type=identifier, required=True, help='Numeric Canvas user ID')
    compose.add_argument('--subject', required=True)
    compose.add_argument('--message-file', required=True, type=Path)
    compose.add_argument('--course', type=identifier, help='Set course conversation context')
    compose.add_argument('--confirm', help='Digest returned by the preview')
    compose.add_argument('--yes', action='store_true', help='Send only if --confirm matches the fresh preview')
    sub.add_parser('todo', help='Your Canvas to-do items')
    sub.add_parser('upcoming', help='Upcoming assignments and events')
    calendar = sub.add_parser('calendar', help='Events or assignments in a date window')
    calendar.add_argument('--start', type=calendar_date, help='First date (YYYY-MM-DD); default today')
    calendar.add_argument('--end', type=calendar_date, help='Last date (YYYY-MM-DD); default 13 days after start')
    calendar.add_argument('--type', choices=('event', 'assignment', 'sub_assignment'), default='event')
    calendar.add_argument('--course', type=identifier, action='append', default=[], help='Include a course calendar; repeatable')
    calendar.add_argument('--active', action='store_true', help='Include all active course calendars')
    calendar.add_argument('--personal', action='store_true', help='Include your personal calendar with selected courses')
    sub.add_parser('overview', help='Active courses, upcoming work, and to-do items')
    due = sub.add_parser('deadlines', help='Assignment deadlines across active courses')
    due.add_argument('--days', type=int, default=14, help='Look ahead this many days; default 14')
    due.add_argument('--course', type=identifier, help='Limit to one course')
    work = sub.add_parser('work', help='Assignments with your Canvas submission status')
    work.add_argument('--course', type=identifier, help='Limit to one course')
    work.add_argument('--days', type=int, help='Show only work due in the next N days; default is all work')
    work.add_argument('--status', choices=('unknown', 'unsubmitted', 'submitted', 'graded',
                                           'pending_review', 'missing', 'excused'))
    news = sub.add_parser('news', help='Recent announcements across active or selected courses')
    news.add_argument('--days', type=int, default=14)
    news.add_argument('--course', type=identifier, action='append', help='Limit to a course; repeatable')
    linked = sub.add_parser('linked-files', help='Find file links in accessible course content')
    linked.add_argument('course', type=identifier)
    linked.add_argument('--quick', action='store_true', help='Skip per-file metadata checks for a faster link index')
    linked.add_argument('--all-pages', action='store_true', help='Also scan listed published pages outside modules')
    sub.add_parser('capabilities', help='Discover commands without logging in')
    snap = sub.add_parser('snapshot', help='Save a private, read-only course snapshot outside Git')
    snap.add_argument('course', type=identifier)
    snap.add_argument('--output', required=True, type=Path)
    difference = sub.add_parser('snapshot-diff', help='Compare two local snapshots without Canvas login')
    difference.add_argument('older', type=Path)
    difference.add_argument('newer', type=Path)
    markdown = sub.add_parser('snapshot-markdown', help='Render a private snapshot as readable Markdown, offline')
    markdown.add_argument('snapshot', type=Path)
    markdown.add_argument('--output', required=True, type=Path)
    s = sub.add_parser('download', help='Download one accessible course file without overwriting')
    s.add_argument('course', type=identifier)
    s.add_argument('file', type=identifier)
    s.add_argument('--output', required=True, type=Path)
    s.add_argument('--max-bytes', type=int, default=100 * 1024 * 1024)
    batch = sub.add_parser('download-linked', help='Preview or download files linked in readable course content')
    batch.add_argument('course', type=identifier)
    batch.add_argument('--directory', required=True, type=Path)
    batch.add_argument('--all-pages', action='store_true')
    batch.add_argument('--max-files', type=int, default=20)
    batch.add_argument('--max-bytes', type=int, default=250 * 1024 * 1024)
    batch.add_argument('--yes', action='store_true', help='Download after reviewing a preview')
    for name in ('assignment', 'page', 'module-items'):
        s = sub.add_parser(name, help='Read one resource or list module items')
        s.add_argument('course', type=identifier)
        s.add_argument('item', type=str if name == 'page' else identifier)
    submission = sub.add_parser('submission', help='Read your own assignment submission and feedback')
    submission.add_argument('course', type=identifier)
    submission.add_argument('assignment', type=identifier)
    for name, file_flag in (('submit-url', '--url-file'), ('submit-text', '--text-file')):
        submit = sub.add_parser(name, help='Preview an assignment submission before explicit confirmation')
        submit.add_argument('course', type=identifier)
        submit.add_argument('assignment', type=identifier)
        submit.add_argument(file_flag, required=True, type=Path)
        submit.add_argument('--confirm', help='Digest returned by the preview')
        submit.add_argument('--yes', action='store_true', help='Submit only if the fresh preview matches --confirm')
    grades = sub.add_parser('grades', help='Read only your own course enrollment and visible grade')
    grades.add_argument('course', type=identifier)
    for name in ('folders', 'sections', 'outline'):
        sub.add_parser(name).add_argument('course', type=identifier)
    for name in ('folder', 'folder-files', 'folder-folders'):
        sub.add_parser(name).add_argument('folder', type=identifier)
    topic = sub.add_parser('topic', help='Read one discussion topic')
    topic.add_argument('course', type=identifier)
    topic.add_argument('topic', type=identifier)
    for name in ('quiz', 'rubric', 'assignment-group'):
        resource = sub.add_parser(name, help=f'Read one {name} without starting or changing it')
        resource.add_argument('course', type=identifier)
        resource.add_argument('item', type=identifier)
    new_quiz = sub.add_parser('new-quiz', help='Read New Quiz metadata without starting an attempt')
    new_quiz.add_argument('course', type=identifier)
    new_quiz.add_argument('assignment', type=identifier)
    s = sub.add_parser('get', help='Advanced read-only Canvas API request')
    s.add_argument('path', help='An /api/v1/ path, including optional query parameters')
    s.add_argument('--paginate', action='store_true')
    for name in ('assignments', 'assignment-groups', 'modules', 'pages', 'files',
                 'discussions', 'announcements', 'syllabus', 'quizzes', 'rubrics',
                 'new-quizzes'):
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
        return {'read': ['courses', 'me', 'favorites', 'groups', 'group', 'course-groups', 'inbox', 'conversation (no read-state change)', 'recipients', 'todo', 'upcoming', 'calendar', 'overview', 'deadlines', 'work', 'news', 'linked-files', 'assignments', 'assignment', 'assignment-groups', 'assignment-group', 'submission', 'grades', 'syllabus', 'modules', 'module-items', 'outline', 'pages', 'page', 'files', 'folders', 'folder-files', 'sections', 'announcements', 'discussions', 'topic', 'entries', 'replies', 'quizzes (metadata only)', 'quiz (metadata only)', 'new-quizzes (metadata only)', 'new-quiz (metadata only)', 'rubrics', 'rubric', 'get', 'snapshot-diff (offline)'], 'local_write': ['snapshot (private local file)', 'snapshot-markdown (private local file, offline)', 'download', 'download-linked (preview unless --yes)'], 'canvas_write': ['post (preview unless --yes)', 'inbox-reply (preview and matching digest required)', 'inbox-compose (one person, preview and matching digest required)', 'submit-url/submit-text (preview and matching digest required)'], 'auth': ['login', 'status', 'logout'], 'format': 'JSON', 'limitations': ['No quiz attempts', 'No file uploads', 'No OAuth browser consent yet']}
    if args.command == 'snapshot-diff':
        from .snapshot_diff import compare, read
        return compare(read(args.older), read(args.newer))
    if args.command == 'snapshot-markdown':
        from .markdown import render, save
        from .snapshot_diff import read
        return save(args.output, render(read(args.snapshot)))
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
        return linked_files(client, args.course, args.max_pages, resolve=not args.quick,
                            all_pages=args.all_pages)
    if args.command == 'download-linked':
        from .batch import batch_download
        return batch_download(client, args.course, args.directory, args.max_pages,
                              args.max_files, args.max_bytes, args.all_pages, args.yes)
    if args.command == 'snapshot':
        from .snapshot import capture, save_private, validate_destination
        output = validate_destination(args.output)
        return save_private(output, capture(client, args.course, args.max_pages))
    if args.command in ('submit-url', 'submit-text'):
        from .submit import submit
        source = args.url_file if args.command == 'submit-url' else args.text_file
        content = source.read_text(encoding='utf-8')
        submission_type = 'online_url' if args.command == 'submit-url' else 'online_text_entry'
        return submit(client, args.course, args.assignment, submission_type, content,
                      args.yes, args.confirm)
    if args.command == 'deadlines':
        from .planning import deadlines
        if args.days < 1:
            raise CanvasError('--days must be positive')
        return deadlines(client, args.max_pages, args.days, args.course)
    if args.command == 'work':
        from .planning import work
        if args.days is not None and args.days < 1:
            raise CanvasError('--days must be positive')
        return work(client, args.max_pages, args.course, args.days, args.status)
    if args.command == 'news':
        from .news import announcement_feed
        if args.days < 1:
            raise CanvasError('--days must be positive')
        return announcement_feed(client, args.max_pages, args.days, args.course)
    if args.command == 'get':
        if not args.path.startswith('/api/v1/'):
            raise CanvasError('get requires an /api/v1/ path')
        return client.list(args.path, args.max_pages) if args.paginate else client.request(args.path)[0]
    if args.command in ('new-quizzes', 'new-quiz'):
        route = f'/api/quiz/v1/courses/{args.course}/quizzes'
        if args.command == 'new-quiz':
            return client.request(route + f'/{args.assignment}')[0]
        return client.list(route + '?per_page=100', args.max_pages)
    if args.command == 'calendar':
        start = args.start or date.today().isoformat()
        end = args.end or (date.fromisoformat(start) + timedelta(days=13)).isoformat()
        if end < start:
            raise CanvasError('--end must not precede --start')
        contexts = [f'course_{number}' for number in args.course]
        if args.active:
            courses = client.list('/api/v1/courses?enrollment_state=active&per_page=100', args.max_pages)
            contexts += [f"course_{course['id']}" for course in courses if course.get('id')]
        if args.personal:
            profile = client.request('/api/v1/users/self/profile')[0]
            contexts.append(f"user_{profile['id']}")
        contexts = list(dict.fromkeys(contexts))
        if len(contexts) > 10:
            raise CanvasError('Canvas calendar supports at most 10 contexts; select courses explicitly')
        query = [('type', args.type), ('start_date', start), ('end_date', end), ('per_page', '100')]
        query += [('context_codes[]', context) for context in contexts]
        return client.list('/api/v1/calendar_events?' + urlencode(query), args.max_pages)
    if args.command == 'todo':
        return client.list('/api/v1/users/self/todo?per_page=100', args.max_pages)
    if args.command == 'favorites':
        return client.list('/api/v1/users/self/favorites/courses?per_page=100', args.max_pages)
    if args.command == 'groups':
        return client.list('/api/v1/users/self/groups?per_page=100', args.max_pages)
    if args.command == 'group':
        return client.request(f'/api/v1/groups/{args.group}')[0]
    if args.command == 'course-groups':
        return client.list(f'/api/v1/courses/{args.course}/groups?per_page=100', args.max_pages)
    if args.command == 'inbox':
        query = [('per_page', '100')]
        if args.scope:
            query.append(('scope', args.scope))
        if args.course:
            query.append(('filter[]', f'course_{args.course}'))
        return client.list('/api/v1/conversations?' + urlencode(query), args.max_pages)
    if args.command == 'recipients':
        from .messaging import recipients
        return recipients(client, args.max_pages, args.search, args.user_id, args.course)
    if args.command == 'inbox-compose':
        from .messaging import compose
        message = args.message_file.read_text(encoding='utf-8')
        return compose(client, args.max_pages, args.recipient, args.subject, message,
                       args.course, args.yes, args.confirm)
    if args.command == 'conversation':
        return client.request(f'/api/v1/conversations/{args.conversation}?auto_mark_as_read=false')[0]
    if args.command == 'inbox-reply':
        if bool(args.confirm) != bool(args.yes):
            raise CanvasError('Sending requires both --yes and --confirm from a prior preview')
        conversation = client.request(
            f'/api/v1/conversations/{args.conversation}?auto_mark_as_read=false')[0]
        if str(conversation.get('id')) != args.conversation:
            raise CanvasError('Canvas returned a different conversation; refusing to send')
        participants = conversation.get('participants')
        if not isinstance(participants, list) or not participants:
            raise CanvasError('Canvas did not identify thread participants; refusing to send')
        message = args.message_file.read_text(encoding='utf-8')
        if not message.strip():
            raise CanvasError('Empty message refused')
        route = f'/api/v1/conversations/{args.conversation}/add_message'
        body = {'body': message}
        preview = {'conversation_id': args.conversation, 'subject': conversation.get('subject'),
                   'participants': participants, 'audience': conversation.get('audience'),
                   'route': route, 'body': body}
        digest = hashlib.sha256(json.dumps(preview, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if not args.yes:
            return {'dry_run': True, **preview, 'confirm': digest,
                    'next': 'Review participants and body, then repeat with --yes --confirm DIGEST to send.'}
        if args.confirm != digest:
            raise CanvasError('Preview changed (thread or message); review a fresh preview before sending')
        return client.request(route, 'POST', body)[0]
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
    if args.command in ('folder', 'folder-files', 'folder-folders'):
        route = f'/api/v1/folders/{args.folder}'
        return (client.request(route)[0] if args.command == 'folder' else
                client.list(route + ('/files' if args.command == 'folder-files' else '/folders') + '?per_page=100', args.max_pages))
    base = f'/api/v1/courses/{args.course}'
    if args.command == 'grades':
        profile = client.request('/api/v1/users/self/profile')[0]
        user_id = profile['id']
        enrollments = client.list(base + f'/enrollments?user_id={user_id}&per_page=100', args.max_pages)
        if any(enrollment.get('user_id') != user_id or str(enrollment.get('course_id')) != args.course
               for enrollment in enrollments):
            raise CanvasError('Canvas returned enrollment data outside the requested user/course; refusing output')
        return enrollments
    if args.command == 'folders':
        return client.list(base + '/folders?per_page=100', args.max_pages)
    if args.command == 'sections':
        return client.list(base + '/sections?per_page=100', args.max_pages)
    if args.command == 'outline':
        modules = client.list(base + '/modules?per_page=100', args.max_pages)
        return [{'id': module.get('id'), 'name': module.get('name'),
                 'position': module.get('position'), 'state': module.get('state'),
                 'unlock_at': module.get('unlock_at'), 'completed_at': module.get('completed_at'),
                 'items': client.list(base + f"/modules/{module['id']}/items?per_page=100", args.max_pages)}
                for module in modules]
    if args.command == 'topic':
        return client.request(base + f'/discussion_topics/{args.topic}')[0]
    if args.command in ('quiz', 'rubric', 'assignment-group'):
        resource = {'quiz': 'quizzes', 'rubric': 'rubrics',
                    'assignment-group': 'assignment_groups'}[args.command]
        return client.request(base + f'/{resource}/{args.item}')[0]
    if args.command == 'submission':
        return client.request(base + f'/assignments/{args.assignment}/submissions/self?include[]=submission_comments&include[]=rubric_assessment')[0]
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
    resource = {'discussions': 'discussion_topics', 'announcements': 'discussion_topics',
                'assignment-groups': 'assignment_groups'}.get(args.command, args.command)
    route = base + '/' + resource + '?per_page=100'
    if args.command == 'announcements':
        route += '&only_announcements=true'
    return client.list(route, args.max_pages)


def brief(data):
    """Small human index. JSON remains the complete representation."""
    if isinstance(data, list):
        if not data:
            return 'No items.'
        if all(isinstance(item, dict) and 'items' in item and 'name' in item for item in data):
            return '\n\n'.join(
                f"{module['name']}" +
                ''.join(f"\n  {item.get('id', '')}  {item.get('title', 'item')}"
                        for item in module['items'])
                for module in data)
        if all(isinstance(item, dict) and 'course_id' in item and 'grades' in item for item in data):
            return '\n'.join(
                f"Course {item['course_id']}: " +
                (f"{item['grades'].get('current_grade') or item['grades'].get('current_score')}"
                 if item.get('grades') and (item['grades'].get('current_grade') is not None or
                                            item['grades'].get('current_score') is not None)
                 else 'grade not visible')
                for item in data)
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
            if item.get('downloadable') is False:
                detail = 'not downloadable'
            elif item.get('metadata_not_checked'):
                detail = 'availability not checked'
            lines.append('  '.join(str(x) for x in (number, label, detail) if x != ''))
        return '\n'.join(lines)
    if isinstance(data, dict) and all(k in data for k in ('courses', 'upcoming', 'todo')):
        lines = [(title, data[key]) for title, key in
                 [('Active courses', 'courses'), ('Upcoming', 'upcoming'), ('To do', 'todo')]]
        if 'deadlines' in data:
            lines.append(('Deadlines (next 14 days)', data['deadlines']))
        return '\n\n'.join(f'{title}\n{brief(values)}' for title, values in lines)
    if isinstance(data, dict) and 'assignments' in data and 'unavailable_courses' in data:
        if 'status_filter' in data:
            result = ('\n'.join(
                f"{item.get('course_name') or item['course_id']}: "
                f"{item.get('name') or item.get('assignment_id')} "
                f"[{item['status']}]"
                + (f"  due {item['due_at']}" if item.get('due_at') else '  no due date')
                for item in data['assignments']) or 'No assignments.')
        else:
            result = brief(data['assignments'])
        if data['unavailable_courses']:
            result += f"\nAssignments unavailable for {len(data['unavailable_courses'])} course(s); see JSON for details."
        return result
    if isinstance(data, dict) and 'announcements' in data and 'unavailable_courses' in data:
        result = ('\n'.join(
            f"{item.get('course_name') or item.get('context_code') or item.get('course_id')}: "
            f"{item.get('title') or item.get('id')}  "
            f"{item.get('posted_at') or item.get('created_at') or ''}"
            for item in data['announcements']) or 'No announcements.')
        if data['unavailable_courses']:
            result += f"\nAnnouncements unavailable for {len(data['unavailable_courses'])} course(s); see JSON for details."
        return result
    if isinstance(data, dict) and 'files' in data and 'skipped_sources' in data:
        result = brief(data['files'])
        if data['skipped_sources']:
            result += f"\nSkipped {len(data['skipped_sources'])} source(s); see JSON for details."
        return result
    if isinstance(data, dict) and 'assignment_id' in data and 'workflow_state' in data:
        fields = [('Status', data.get('workflow_state')),
                  ('Submitted', data.get('submitted_at')),
                  ('Grade', data.get('grade')),
                  ('Late', data.get('late')),
                  ('Missing', data.get('missing')),
                  ('Comments', len(data.get('submission_comments') or []))]
        return '\n'.join(f'{name}: {value}' for name, value in fields if value is not None)
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
