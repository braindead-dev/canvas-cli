import argparse
import getpass
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode

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
    return str(int(value))


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
    own_profile = sub.add_parser('profile', help='Read whitelisted own-profile metadata, not secret feed or login fields')
    own_profile.add_argument('--include-bio', action='store_true', help='Opt in to your own biography text')
    own_profile.add_argument('--include-email', action='store_true', help='Opt in to your own primary email address')
    own_profile = sub.add_parser('profile-set', help='Preview selected own-profile edits with explicit shared-audience acknowledgement')
    for field in ('name', 'short-name', 'sortable-name', 'title', 'pronunciation', 'pronouns'):
        own_profile.add_argument('--' + field, help='Selected profile text; empty clears optional fields, not names')
    own_profile.add_argument('--bio-file', type=Path, help='UTF-8 biography file; empty file clears, local limit 10000 characters')
    own_profile.add_argument('--timezone', help='IANA time zone; changes date display, not deadlines')
    own_profile.add_argument('--acknowledge-shared-profile', action='store_true',
                             help='Required for names/profile text visible to peers and graders')
    own_profile.add_argument('--confirm', help='Digest returned by the preview')
    own_profile.add_argument('--yes', action='store_true', help='Execute only if the fresh preview matches --confirm')
    favorites = sub.add_parser('favorites', help='Displayed favorite courses/groups, which may be Canvas defaults')
    favorites.add_argument('--context', choices=('course', 'group'), default='course')
    for name in ('favorite-add', 'favorite-remove', 'favorites-reset'):
        favorite = sub.add_parser(name, help='Preview a change to your own dashboard favorites')
        if name != 'favorites-reset':
            favorite.add_argument('item', type=identifier, help='Numeric course or group ID')
        favorite.add_argument('--context', choices=('course', 'group'), default='course')
        favorite.add_argument('--confirm', help='Digest returned by the preview')
        favorite.add_argument('--yes', action='store_true', help='Apply only if --confirm matches the fresh preview')
    sub.add_parser('nicknames', help='List your saved course nicknames')
    nickname = sub.add_parser('nickname', help='Read your nickname and the actual course name')
    nickname.add_argument('course', type=identifier)
    for name in ('nickname-set', 'nickname-clear', 'nicknames-reset'):
        preference = sub.add_parser(name, help='Preview own course nickname changes, never rename a shared course')
        if name != 'nicknames-reset':
            preference.add_argument('course', type=identifier)
        if name == 'nickname-set':
            preference.add_argument('--name', required=True, help='Nonempty nickname shorter than 60 characters')
        preference.add_argument('--confirm', help='Digest returned by the preview')
        preference.add_argument('--yes', action='store_true')
    sub.add_parser('colors', help='Read your saved custom calendar/dashboard colors')
    for name in ('color', 'color-set'):
        preference = sub.add_parser(name, help='Read or preview your own color for an explicit context')
        preference.add_argument('item', type=identifier, help='Numeric course, group or own user ID')
        preference.add_argument('--context', choices=('course', 'group', 'user'), default='course')
        if name == 'color-set':
            preference.add_argument('--hex', required=True, help='Three- or six-digit RGB code, optionally prefixed with #')
            preference.add_argument('--confirm', help='Digest returned by the preview')
            preference.add_argument('--yes', action='store_true')
    sub.add_parser('settings', help='Read supported own-user interface settings, not mobile keys')
    preference = sub.add_parser('settings-set', help='Preview only explicitly selected boolean interface preferences')
    preference.add_argument('--set', dest='changes', action='append', required=True, metavar='KEY=true|false',
                            help='Repeat for several distinct settings; use settings to see reported keys')
    preference.add_argument('--confirm', help='Digest returned by the preview')
    preference.add_argument('--yes', action='store_true')
    channels = sub.add_parser('channels', help='List your own communication-channel metadata, not contact addresses by default')
    channels.add_argument('--include-addresses', action='store_true', help='Opt in to own email/SMS addresses; never push tokens')
    notifications = sub.add_parser('notification-preferences', help='Read own-channel frequencies; Canvas may materialize defaults')
    notifications.add_argument('channel', type=identifier, help='Numeric channel ID from channels')
    notifications.add_argument('--category', help='Exact reported category key; filter after reading the full inventory')
    notifications = sub.add_parser('notification-preferences-set', help='Preview specific own-channel frequency changes')
    notifications.add_argument('channel', type=identifier, help='Numeric channel ID from channels')
    notifications.add_argument('--set', dest='changes', action='append', required=True, metavar='NOTIFICATION=FREQUENCY',
                               help='Repeat exact notification keys with immediately, daily, weekly or never')
    notifications.add_argument('--confirm', help='Digest returned by the preview')
    notifications.add_argument('--yes', action='store_true')
    sub.add_parser('dashboard-positions', help='Read saved own dashboard positions, not a complete visible card inventory')
    for name in ('dashboard-position-set', 'dashboard-order'):
        preference = sub.add_parser(name, help='Preview own dashboard position changes without changing favorites')
        if name == 'dashboard-position-set':
            preference.add_argument('item', type=identifier)
            preference.add_argument('--context', choices=('course', 'group', 'user'), default='course')
            preference.add_argument('--position', required=True, type=int, help='Saved position from -1000 through 1000')
        else:
            preference.add_argument('assets', nargs='+', metavar='CONTEXT_ID',
                                    help='Explicit course_ID/group_ID/own user_ID values in desired order; unspecified values remain')
        preference.add_argument('--confirm', help='Digest returned by the preview')
        preference.add_argument('--yes', action='store_true')
    for name in ('activity', 'activity-summary'):
        stream = sub.add_parser(name, help='Read own notifications, not a complete coursework inventory')
        stream.add_argument('--course', type=identifier, help='Use the authorized course-specific feed')
        stream.add_argument('--active', action='store_true', help='Global feed: only active courses')
        if name == 'activity':
            stream.add_argument('--type', help='Exact native type, e.g. AssessmentRequest; filter after full pagination')
            stream.add_argument('--include-content', action='store_true', help='Opt in to cached bodies; initial-post restrictions still apply')
    for name in ('activity-dismiss', 'activity-dismiss-all'):
        stream = sub.add_parser(name, help='Preview hiding own notifications, never delete underlying content')
        if name == 'activity-dismiss':
            stream.add_argument('item', type=identifier, help='Activity ID, not an assignment or conversation ID')
        else:
            stream.add_argument('--all', dest='all_items', action='store_true', required=True,
                                help='Acknowledge hiding ALL your notifications, not just the current page')
        stream.add_argument('--confirm', help='Digest returned by the preview')
        stream.add_argument('--yes', action='store_true')
    sub.add_parser('groups', help='Your active Canvas groups')
    group = sub.add_parser('group', help='One visible group')
    group.add_argument('group', type=identifier)
    course_groups = sub.add_parser('course-groups', help='Visible groups in a course')
    course_groups.add_argument('course', type=identifier)
    from .enrollments import STATES, TYPES
    enrollments = sub.add_parser('enrollments', help='Paginated own Canvas membership metadata, not official university registration')
    enrollments.add_argument('--type', dest='types', choices=TYPES, action='append', default=[])
    enrollments.add_argument('--state', dest='states', choices=STATES, action='append', default=[])
    enrollments.add_argument('--course', type=identifier, action='append', default=[], help='Local course filter after full own pagination')
    enrollments.add_argument('--term', type=identifier, help='Native numeric enrollment-term ID, never a SIS ID')
    for name in ('enrollment-accept', 'enrollment-reject'):
        invitation = sub.add_parser(name, help='Preview responding only to an exact pending own Canvas invitation')
        invitation.add_argument('course', type=identifier)
        invitation.add_argument('enrollment', type=identifier)
        invitation.add_argument('--acknowledge-canvas-enrollment', action='store_true', required=True,
                                help='Acknowledge a Canvas membership/access change, not official university registration')
        invitation.add_argument('--confirm', help='Digest returned by the preview')
        invitation.add_argument('--yes', action='store_true')
    permissions = sub.add_parser('permissions', help='Read exact own native context rights, not an admin-role inference')
    permissions.add_argument('context_id', type=identifier)
    permissions.add_argument('--context', choices=('course', 'group'), default='course')
    permissions.add_argument('--permission', dest='permissions', action='append', required=True,
                             help='Repeat for exact native keys, e.g. read_roster or join; false does not diagnose why')
    categories = sub.add_parser('group-categories', help='List authorized course group-set metadata, not member allocations')
    categories.add_argument('course', type=identifier)
    categories.add_argument('--collaboration-state', choices=('collaborative', 'non_collaborative', 'all'), default='collaborative')
    for name in ('group-category', 'category-groups'):
        categories = sub.add_parser(name, help='Read a course-verified group set or its paginated group metadata')
        categories.add_argument('course', type=identifier)
        categories.add_argument('category', type=identifier)
    for name in ('course-users', 'group-users'):
        roster = sub.add_parser(name, help='Fully paginate an authorized roster; metadata only by default')
        roster.add_argument('context_id', type=identifier)
        roster.add_argument('--search', help='Native partial name/full ID search, at least two characters')
        roster.add_argument('--include-email', action='store_true', help='Print email only if authorized and returned; never SIS/login IDs')
        if name == 'course-users':
            from .roster import ENROLLMENT_STATES, ENROLLMENT_TYPES
            roster.add_argument('--enrollment-type', choices=ENROLLMENT_TYPES, action='append', default=[])
            roster.add_argument('--enrollment-state', choices=ENROLLMENT_STATES, action='append', default=[])
            roster.add_argument('--section', type=identifier, action='append', default=[])
            roster.add_argument('--include-enrollments', action='store_true', help='Include scoped enrollment metadata, never grades')
        else:
            roster.add_argument('--exclude-inactive', action=argparse.BooleanOptionalAction, default=None,
                                help='Explicit native inactive-user filter; omitted preserves the native default')
    membership = sub.add_parser('group-membership', help='Your active membership/request/invitation only, with complete pagination')
    membership.add_argument('group', type=identifier)
    for name in ('group-join', 'group-leave'):
        membership = sub.add_parser(name, help='Preview only your student-organized/community membership change')
        membership.add_argument('group', type=identifier)
        membership.add_argument('--confirm', help='Digest returned by the preview')
        membership.add_argument('--yes', action='store_true')
    doctor = sub.add_parser('doctor', help='Read-only course API reachability check without content output')
    doctor.add_argument('course', type=identifier)
    finder = sub.add_parser('find', help='Search visible titles across several areas of one course')
    finder.add_argument('course', type=identifier)
    finder.add_argument('--query', required=True)
    finder.add_argument('--area', choices=('assignments', 'discussions', 'pages', 'files', 'modules'))
    my_files = sub.add_parser('my-files', help='List your personal Canvas files')
    my_files.add_argument('--search', help='Filter by partial filename')
    file_info = sub.add_parser('file-info', help='Get one accessible Canvas file record')
    file_info.add_argument('file', type=identifier)
    inbox = sub.add_parser('inbox', help='List Canvas Inbox conversations')
    inbox.add_argument('--scope', choices=('unread', 'starred', 'archived', 'sent'))
    inbox.add_argument('--course', type=identifier, help='Filter to a course context')
    conversation = sub.add_parser('conversation', help='Read one Inbox thread without marking it read')
    conversation.add_argument('conversation', type=identifier)
    edit_inbox = sub.add_parser('inbox-edit', help='Preview own-thread read/archive/star/subscription changes')
    edit_inbox.add_argument('conversation', type=identifier)
    edit_inbox.add_argument('--state', choices=('read', 'unread', 'archived'))
    edit_inbox.add_argument('--starred', action=argparse.BooleanOptionalAction, default=None)
    edit_inbox.add_argument('--subscribed', action=argparse.BooleanOptionalAction, default=None,
                            help='Only for a confirmed group conversation')
    edit_inbox.add_argument('--yes', action='store_true')
    edit_inbox.add_argument('--confirm', help='Digest returned by the preview')
    delete_inbox = sub.add_parser('inbox-delete', help='Preview removing all thread messages from your own view')
    delete_inbox.add_argument('conversation', type=identifier)
    delete_inbox.add_argument('--permanent', action='store_true', help='Acknowledge no CLI restore; archive preserves messages')
    delete_inbox.add_argument('--yes', action='store_true')
    delete_inbox.add_argument('--confirm', help='Digest returned by the preview')
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
    planner = sub.add_parser('planner', help='Your paginated planner items, including personal tasks')
    planner.add_argument('--start', type=calendar_date)
    planner.add_argument('--end', type=calendar_date)
    planner.add_argument('--course', type=identifier, action='append', default=[])
    planner.add_argument('--group', type=identifier, action='append', default=[])
    planner.add_argument('--filter', choices=('new_activity', 'incomplete_items', 'complete_items'))
    notes = sub.add_parser('planner-notes', help='Your personal planner notes without changing completion')
    notes.add_argument('--start', type=calendar_date)
    notes.add_argument('--end', type=calendar_date)
    notes.add_argument('--course', type=identifier, action='append', default=[])
    notes.add_argument('--personal', action='store_true', help='Include notes not associated with a course')
    sub.add_parser('planner-note', help='Read one of your planner notes').add_argument('note', type=identifier)
    sub.add_parser('planner-overrides', help='Your planner visibility/completion overrides')
    sub.add_parser('planner-override', help='Read one of your planner overrides').add_argument('override', type=identifier)
    from .overrides import TYPE_NAMES
    for name, creating in (('planner-override-create', True), ('planner-override-edit', False)):
        override = sub.add_parser(name, help='Preview changing personal planner checkboxes, not submitting work')
        if creating:
            override.add_argument('type', choices=tuple(TYPE_NAMES), help='Exact type from planner output')
            override.add_argument('item', type=identifier, help='Plannable ID, not a module-item or assignment alias')
            override.add_argument('--start', type=calendar_date, help='Window containing the visible planner item')
            override.add_argument('--end', type=calendar_date)
        else:
            override.add_argument('override', type=identifier)
        override.add_argument('--complete', action=argparse.BooleanOptionalAction, default=None)
        override.add_argument('--dismiss', action=argparse.BooleanOptionalAction, default=None,
                              help='Control appearance in planner opportunities, not assignment availability')
        override.add_argument('--allow-module-progress', action='store_true',
                              help='Acknowledge Canvas may sync course module mark-done requirements')
        override.add_argument('--yes', action='store_true')
        override.add_argument('--confirm')
    delete_override = sub.add_parser('planner-override-delete', help='Preview removing a planner override, not its assignment')
    delete_override.add_argument('override', type=identifier)
    delete_override.add_argument('--yes', action='store_true')
    delete_override.add_argument('--confirm')
    task = sub.add_parser('task-create', help='Preview creating a personal Canvas planner note')
    task.add_argument('--title', required=True)
    task.add_argument('--date', required=True, type=calendar_date)
    task.add_argument('--details-file', type=Path, help='Optional plain UTF-8 note details')
    task.add_argument('--course', type=identifier)
    task.add_argument('--confirm')
    task.add_argument('--yes', action='store_true', help='Create only with a matching preview digest')
    edit_task = sub.add_parser('task-edit', help='Preview changes to one personal planner note')
    edit_task.add_argument('note', type=identifier)
    edit_task.add_argument('--title')
    edit_task.add_argument('--date', type=calendar_date)
    edit_task.add_argument('--details-file', type=Path, help='Plain UTF-8 details; an empty file clears details')
    course_change = edit_task.add_mutually_exclusive_group()
    course_change.add_argument('--course', type=identifier)
    course_change.add_argument('--clear-course', action='store_true')
    edit_task.add_argument('--yes', action='store_true')
    edit_task.add_argument('--confirm')
    remove_task = sub.add_parser('task-delete', help='Preview removing one personal planner note, not an assignment')
    remove_task.add_argument('note', type=identifier)
    remove_task.add_argument('--yes', action='store_true')
    remove_task.add_argument('--confirm')
    progress = sub.add_parser('module-progress', help='Read visible module requirements and completion status')
    progress.add_argument('course', type=identifier)
    exports = sub.add_parser('exports', help='List authorized course export jobs without signed download URLs')
    exports.add_argument('course', type=identifier)
    export_status = sub.add_parser('export-status', help='Read one export job without creating a new job')
    export_status.add_argument('course', type=identifier)
    export_status.add_argument('export', type=identifier)
    export_status.add_argument('--progress', action='store_true', help='Also read the linked same-origin progress job')
    export_create = sub.add_parser('export-create', help='Preview starting an asynchronous course export, if authorized')
    export_create.add_argument('course', type=identifier)
    export_create.add_argument('--type', choices=('zip', 'common_cartridge'), default='zip')
    export_create.add_argument('--select', nargs=2, action='append', default=[], metavar=('RESOURCE', 'ID'),
                               help='Select a documented resource type and positive ID; repeatable')
    export_create.add_argument('--skip-notifications', action='store_true')
    export_create.add_argument('--yes', action='store_true')
    export_create.add_argument('--confirm')
    export_download = sub.add_parser('export-download', help='Privately download an already completed authorized export')
    export_download.add_argument('course', type=identifier)
    export_download.add_argument('export', type=identifier)
    export_download.add_argument('--output', required=True, type=Path)
    export_download.add_argument('--max-bytes', type=int, default=100 * 1024 * 1024)
    calendar = sub.add_parser('calendar', help='Events or assignments in a date window')
    calendar.add_argument('--start', type=calendar_date, help='First date (YYYY-MM-DD); default today')
    calendar.add_argument('--end', type=calendar_date, help='Last date (YYYY-MM-DD); default 13 days after start')
    calendar.add_argument('--type', choices=('event', 'assignment', 'sub_assignment'), default='event')
    calendar.add_argument('--course', type=identifier, action='append', default=[], help='Include a course calendar; repeatable')
    calendar.add_argument('--group', type=identifier, action='append', default=[], help='Include a group calendar; repeatable')
    calendar.add_argument('--active', action='store_true', help='Include all active course calendars')
    calendar.add_argument('--personal', action='store_true', help='Include your personal calendar with selected courses')
    undated = calendar.add_mutually_exclusive_group()
    undated.add_argument('--undated', action='store_true', help='Only undated items; cannot combine with dates')
    undated.add_argument('--all', action='store_true', help='All dated and undated items; cannot combine with dates')
    sub.add_parser('event', help='Read one calendar event without changing it').add_argument('event', type=identifier)
    for name, creating in (('event-create', True), ('event-edit', False)):
        event = sub.add_parser(name, help='Preview creating or editing a personal calendar event')
        if not creating:
            event.add_argument('event', type=identifier)
        event.add_argument('--title', required=creating)
        event.add_argument('--start', help='ISO timestamp with seconds and an explicit UTC offset or Z')
        event.add_argument('--end', help='ISO timestamp with seconds and an explicit UTC offset or Z')
        event.add_argument('--date', type=calendar_date, help='One all-day date instead of --start/--end')
        event.add_argument('--timezone', help='IANA time zone; required with --date')
        event.add_argument('--details-file', type=Path, help='Plain UTF-8 text; empty file clears details')
        event.add_argument('--location')
        event.add_argument('--address')
        event.add_argument('--yes', action='store_true')
        event.add_argument('--confirm', help='Digest returned by the account-bound preview')
    remove_event = sub.add_parser('event-delete', help='Preview removing one personal calendar event occurrence')
    remove_event.add_argument('event', type=identifier)
    remove_event.add_argument('--reason', help='Optional cancellation reason shown in the preview')
    remove_event.add_argument('--yes', action='store_true')
    remove_event.add_argument('--confirm')
    sub.add_parser('overview', help='Active courses, upcoming work, and to-do items')
    due = sub.add_parser('deadlines', help='Assignment deadlines across active courses')
    due.add_argument('--days', type=int, default=14, help='Look ahead this many days; default 14')
    due.add_argument('--course', type=identifier, help='Limit to one course')
    work = sub.add_parser('work', help='Assignments with your Canvas submission status')
    work.add_argument('--course', type=identifier, help='Limit to one course')
    work.add_argument('--days', type=int, help='Show only work due in the next N days; default is all work')
    work.add_argument('--status', choices=('unknown', 'unsubmitted', 'submitted', 'graded',
                                           'pending_review', 'missing', 'excused'))
    missing = sub.add_parser('missing', help="Read Canvas's own native missing-submission list")
    missing.add_argument('--course', type=identifier, action='append', help='Limit to a course; repeatable')
    missing.add_argument('--submittable', action='store_true', help='Native filter: omit locked assignments')
    missing.add_argument('--current-grading-period', action='store_true', help='Native current-grading-period filter')
    missing.add_argument('--include-planner', action='store_true', help='Include own planner markers, not submission proof')
    missing.add_argument('--timezone', default='local', help='IANA time zone; default is system local time')
    agenda = sub.add_parser('agenda', help='Unfinished dated work in local time, with undated-item coverage')
    agenda.add_argument('--days', type=int, default=14, help='Look ahead this many days; default 14')
    agenda.add_argument('--course', type=identifier, action='append', default=[],
                        help='Limit to a course; repeatable')
    agenda.add_argument('--timezone', default='local', help='IANA time zone; default is system local time')
    agenda.add_argument('--include-undated', action='store_true',
                        help='List undated visible items separately; not necessarily actionable')
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
    snap.add_argument('--include-linked-files', action='store_true',
                      help='Also index files referenced by readable course content')
    sync = sub.add_parser('sync', help='Save a private course snapshot and compare with the previous one')
    sync.add_argument('course', type=identifier)
    sync.add_argument('--directory', type=Path,
                      help='Private snapshot directory; defaults to the app config directory')
    sync.add_argument('--include-linked-files', action='store_true',
                      help='Also index files referenced by readable course content')
    difference = sub.add_parser('snapshot-diff', help='Compare two local snapshots without Canvas login')
    difference.add_argument('older', type=Path)
    difference.add_argument('newer', type=Path)
    snapshot_search = sub.add_parser('snapshot-search', help='Search a local private course snapshot offline')
    snapshot_search.add_argument('snapshot', type=Path)
    snapshot_search.add_argument('--query', required=True)
    snapshot_search.add_argument('--limit', type=int, default=20)
    markdown = sub.add_parser('snapshot-markdown', help='Render a private snapshot as readable Markdown, offline')
    markdown.add_argument('snapshot', type=Path)
    markdown.add_argument('--output', required=True, type=Path)
    s = sub.add_parser('download', help='Download one accessible course/group file without overwriting')
    s.add_argument('course', type=identifier, metavar='CONTEXT_ID')
    s.add_argument('--context', choices=('course', 'group'), default='course')
    s.add_argument('file', type=identifier)
    s.add_argument('--output', required=True, type=Path)
    s.add_argument('--max-bytes', type=int, default=100 * 1024 * 1024)
    batch = sub.add_parser('download-linked', help='Preview or download files linked in readable course content')
    batch.add_argument('course', type=identifier)
    batch.add_argument('--directory', required=True, type=Path)
    batch.add_argument('--all-pages', action='store_true')
    batch.add_argument('--file', type=identifier, action='append', default=[],
                       help='Download only this discovered file ID; repeatable')
    batch.add_argument('--max-files', type=int, default=20)
    batch.add_argument('--max-bytes', type=int, default=250 * 1024 * 1024)
    batch.add_argument('--confirm', help='Digest returned by the preview')
    batch.add_argument('--yes', action='store_true', help='Download after reviewing a preview')
    personal_upload = sub.add_parser('upload-personal', help='Preview uploading a file to your Canvas Files')
    personal_upload.add_argument('--file', required=True, type=Path)
    personal_upload.add_argument('--folder', type=identifier, help='Existing own folder ID; preview verifies its context')
    personal_upload.add_argument('--max-bytes', type=int, default=25 * 1024 * 1024)
    personal_upload.add_argument('--confirm', help='Digest returned by the preview')
    personal_upload.add_argument('--yes', action='store_true', help='Upload only with a matching preview digest')
    assignment_upload = sub.add_parser('upload-assignment-file', help='Upload a file for an assignment without submitting it')
    assignment_upload.add_argument('course', type=identifier)
    assignment_upload.add_argument('assignment', type=identifier)
    assignment_upload.add_argument('--file', required=True, type=Path)
    assignment_upload.add_argument('--max-bytes', type=int, default=25 * 1024 * 1024)
    assignment_upload.add_argument('--confirm', help='Digest returned by the preview')
    assignment_upload.add_argument('--yes', action='store_true', help='Upload only with a matching preview digest')
    context_upload = sub.add_parser('upload-context', help='Preview a shared course/group file upload, not an assignment submission')
    context_upload.add_argument('context_id', type=identifier)
    context_upload.add_argument('--context', required=True, choices=('course', 'group'))
    context_upload.add_argument('--folder', type=identifier, help='Existing folder ID; otherwise the exact context root')
    context_upload.add_argument('--file', required=True, type=Path)
    context_upload.add_argument('--max-bytes', type=int, default=25 * 1024 * 1024)
    context_upload.add_argument('--confirm', help='Digest returned by the preview')
    context_upload.add_argument('--yes', action='store_true', help='Upload only with a matching account/file/folder preview')
    for name in ('assignment', 'page', 'module-items'):
        s = sub.add_parser(name, help='Read one resource or list module items')
        s.add_argument('course', type=identifier, metavar='CONTEXT_ID' if name == 'page' else None)
        s.add_argument('item', type=str if name == 'page' else identifier)
        if name == 'page':
            s.add_argument('--context', choices=('course', 'group'), default='course')
    submission = sub.add_parser('submission', help='Read your own assignment submission and feedback')
    submission.add_argument('course', type=identifier)
    submission.add_argument('assignment', type=identifier)
    submissions = sub.add_parser('submissions', help='Read only your own course submission records, with opt-in history')
    submissions.add_argument('course', type=identifier)
    submissions.add_argument('--assignment', type=identifier, action='append', help='Limit to an assignment; repeatable')
    submissions.add_argument('--state', choices=('submitted', 'unsubmitted', 'graded', 'pending_review'))
    submissions.add_argument('--include-history', action='store_true')
    submissions.add_argument('--include-comments', action='store_true', help='Comment metadata; bodies require --include-content')
    submissions.add_argument('--include-rubric', action='store_true', help='Native indexed rubric points/rating IDs; text requires --include-content')
    submissions.add_argument('--include-content', action='store_true', help='Opt in to private bodies, attachment links and feedback text')
    feedback = sub.add_parser('feedback', help='Own reported grades/comments/rubric results, not submitted answers or a completion checklist')
    feedback.add_argument('course', type=identifier)
    feedback.add_argument('--assignment', type=identifier, action='append', help='Limit to an assignment; repeatable')
    feedback.add_argument('--include-text', action='store_true', help='Opt in to feedback text only, never submitted answers or attachment links')
    feedback.add_argument('--since', help='Reported timestamps since ISO time with seconds and explicit offset; unknown dates stay included')
    feedback.add_argument('--timezone', default='local', help='local or an IANA display time zone')
    peer_reviews = sub.add_parser('peer-reviews', help='Read reviews of your submission, not a complete list of reviews you owe')
    peer_reviews.add_argument('course', type=identifier)
    peer_reviews.add_argument('assignment', type=identifier)
    peer_reviews.add_argument('--scope', choices=('received', 'visible'), default='received',
                              help='Received filters to your work; visible includes other records only if Canvas permits')
    peer_reviews.add_argument('--include-comments', action='store_true', help='Include native submission comments, which may repeat')
    peer_reviews.add_argument('--include-users', action='store_true', help='Include permitted user associations; anonymous identities stay hidden')
    feedback = sub.add_parser('submission-comment', help='Preview a comment on your own submission, without grading')
    feedback.add_argument('course', type=identifier)
    feedback.add_argument('assignment', type=identifier)
    feedback.add_argument('--message-file', required=True, type=Path)
    feedback.add_argument('--attempt', type=int, help='Attach to a confirmed submission attempt')
    feedback.add_argument('--group-comment', action='store_true', help='Explicitly send to the submission group')
    feedback.add_argument('--yes', action='store_true')
    feedback.add_argument('--confirm')
    for name, file_flag in (('submit-url', '--url-file'), ('submit-text', '--text-file')):
        submit = sub.add_parser(name, help='Preview an assignment submission before explicit confirmation')
        submit.add_argument('course', type=identifier)
        submit.add_argument('assignment', type=identifier)
        submit.add_argument(file_flag, required=True, type=Path)
        submit.add_argument('--confirm', help='Digest returned by the preview')
        submit.add_argument('--yes', action='store_true', help='Submit only if the fresh preview matches --confirm')
    file_submit = sub.add_parser('submit-file', help='Preview submitting one or more previously uploaded Canvas file IDs')
    file_submit.add_argument('course', type=identifier)
    file_submit.add_argument('assignment', type=identifier)
    file_submit.add_argument('file', type=identifier, nargs='+')
    file_submit.add_argument('--confirm', help='Digest returned by the preview')
    file_submit.add_argument('--yes', action='store_true', help='Submit only if the fresh preview matches --confirm')
    grades = sub.add_parser('grades', help='Read only your own course enrollment and visible grade')
    grades.add_argument('course', type=identifier)
    for name in ('folders', 'sections', 'outline', 'tabs', 'front-page'):
        content = sub.add_parser(name)
        content.add_argument('course', type=identifier,
                             metavar='CONTEXT_ID' if name in ('folders', 'tabs', 'front-page') else None)
        if name in ('folders', 'tabs', 'front-page'):
            content.add_argument('--context', choices=('course', 'group'), default='course')
    for name in ('root-folder', 'file-quota', 'folder-path'):
        descriptions = {'root-folder': 'GET native root folder metadata; Canvas may create a missing root',
                        'file-quota': 'Read native storage quota and used bytes, not upload permission',
                        'folder-path': 'GET an existing relative folder hierarchy; Canvas may create a missing root'}
        content = sub.add_parser(name, help=descriptions[name])
        content.add_argument('context_id', type=identifier)
        content.add_argument('--context', choices=('course', 'group', 'user'), default='course',
                             help='User context requires your own numeric ID; no other-user reads')
        if name == 'folder-path':
            content.add_argument('--path', default='', help='Relative folder path, e.g. Week 1/Readings; empty means root')
    sub.add_parser('my-folders', help='List your paginated personal Canvas folders')
    sub.add_parser('my-root', help='GET your personal root folder ID; Canvas may create a missing root')
    personal_folder = sub.add_parser('my-folder-create', help='Preview one subfolder in your personal Canvas files')
    personal_folder.add_argument('parent', type=identifier)
    personal_folder.add_argument('--name', required=True)
    personal_folder.add_argument('--yes', action='store_true')
    personal_folder.add_argument('--confirm')
    for name in ('my-folder-edit', 'my-folder-delete'):
        s = sub.add_parser(name, help='Preview a personal folder change; deletion requires an empty non-root folder')
        s.add_argument('folder', type=identifier)
        if name == 'my-folder-edit':
            s.add_argument('--name')
            s.add_argument('--parent', type=identifier)
        s.add_argument('--yes', action='store_true')
        s.add_argument('--confirm')
    for name in ('my-file-edit', 'my-file-copy', 'my-file-delete'):
        s = sub.add_parser(name, help='Preview organizing a personal Canvas file without overwriting or sharing')
        s.add_argument('file', type=identifier)
        if name != 'my-file-delete':
            s.add_argument('--folder', type=identifier, required=name == 'my-file-copy')
        if name == 'my-file-edit':
            s.add_argument('--name')
        if name == 'my-file-delete':
            s.add_argument('--permanent', action='store_true', help='Acknowledge irreversible file destruction')
        s.add_argument('--yes', action='store_true')
        s.add_argument('--confirm')
    for name in ('folder', 'folder-files', 'folder-folders'):
        sub.add_parser(name).add_argument('folder', type=identifier)
    topic = sub.add_parser('topic', help='Read one discussion topic')
    topic.add_argument('course', type=identifier, metavar='CONTEXT_ID')
    topic.add_argument('--context', choices=('course', 'group'), default='course')
    topic.add_argument('topic', type=identifier)
    thread = sub.add_parser('thread', help='Read visible discussion entries and their paginated replies')
    thread.add_argument('course', type=identifier, metavar='CONTEXT_ID')
    thread.add_argument('--context', choices=('course', 'group'), default='course')
    thread.add_argument('topic', type=identifier)
    for name in ('quiz', 'rubric', 'assignment-group'):
        resource = sub.add_parser(name, help=f'Read one {name} without starting or changing it')
        resource.add_argument('course', type=identifier)
        resource.add_argument('item', type=identifier)
    new_quiz = sub.add_parser('new-quiz', help='Read New Quiz metadata without starting an attempt')
    new_quiz.add_argument('course', type=identifier)
    new_quiz.add_argument('assignment', type=identifier)
    s = sub.add_parser('get', help='Advanced Canvas GET; some native endpoints have server-side effects')
    s.add_argument('path', help='An /api/v1/ path, including optional query parameters')
    s.add_argument('--paginate', action='store_true')
    for name in ('assignments', 'assignment-groups', 'modules', 'pages', 'files',
                 'discussions', 'announcements', 'syllabus', 'quizzes', 'rubrics',
                 'new-quizzes'):
        listing = sub.add_parser(name)
        listing.add_argument('course', type=identifier,
                             metavar='CONTEXT_ID' if name in ('discussions', 'announcements', 'files', 'pages') else None)
        if name in ('discussions', 'announcements', 'files', 'pages'):
            listing.add_argument('--context', choices=('course', 'group'), default='course')
        if name == 'pages':
            listing.add_argument('--best-effort', action='store_true',
                                 help='Show readable module pages when Canvas denies the pages list; reports incomplete coverage')
        if name == 'files':
            listing.add_argument('--best-effort', action='store_true',
                                 help='Use linked course content when Canvas denies the Files list; reports incomplete coverage')
            listing.add_argument('--quick', action='store_true',
                                 help='Skip file metadata checks in best-effort fallback')
            listing.add_argument('--all-pages', action='store_true',
                                 help='Scan listed published pages in best-effort fallback')
    for name in ('entries', 'replies', 'post'):
        s = sub.add_parser(name)
        s.add_argument('course', type=identifier, metavar='CONTEXT_ID')
        s.add_argument('--context', choices=('course', 'group'), default='course')
        s.add_argument('topic', type=identifier)
        if name == 'replies':
            s.add_argument('entry', type=identifier)
        if name == 'post':
            s.add_argument('--reply-to', type=identifier)
            s.add_argument('--message-file', required=True, type=Path)
            s.add_argument('--confirm', help='Digest returned by the preview')
            s.add_argument('--yes', action='store_true', help='Post only if the fresh preview matches --confirm')
    for name in ('entry', 'entry-edit', 'entry-delete'):
        s = sub.add_parser(name, help='Read one visible discussion entry' if name == 'entry' else
                           'Preview editing or deleting one of your own discussion entries')
        s.add_argument('course', type=identifier, metavar='CONTEXT_ID')
        s.add_argument('topic', type=identifier)
        s.add_argument('entry', type=identifier)
        s.add_argument('--context', choices=('course', 'group'), default='course')
        if name == 'entry-edit':
            s.add_argument('--message-file', required=True, type=Path)
            s.add_argument('--remove-attachment', action='store_true',
                           help='Acknowledge that Canvas text edits remove the existing attachment')
        if name != 'entry':
            s.add_argument('--confirm', help='Digest returned by the preview')
            s.add_argument('--yes', action='store_true', help='Execute only if the fresh preview matches --confirm')
    ratings = sub.add_parser('topic-ratings', help='Read only your own discussion likes without cached bodies')
    ratings.add_argument('course', type=identifier, help='Course or group ID, selected by --context')
    ratings.add_argument('topic', type=identifier)
    ratings.add_argument('--context', choices=('course', 'group'), default='course')
    rate = sub.add_parser('entry-rate', help='Preview setting your own like, not a grade or read marker')
    rate.add_argument('course', type=identifier, help='Course or group ID, selected by --context')
    rate.add_argument('topic', type=identifier)
    rate.add_argument('entry', type=identifier)
    rate.add_argument('--rating', required=True, type=int, choices=(0, 1), help='1 likes; 0 removes your like')
    rate.add_argument('--context', choices=('course', 'group'), default='course')
    rate.add_argument('--yes', action='store_true')
    rate.add_argument('--confirm')
    for name in ('topic-subscribe', 'topic-unsubscribe', 'topic-mark-read', 'topic-mark-unread',
                 'entry-mark-read', 'entry-mark-unread'):
        s = sub.add_parser(name, help='Preview changing only your discussion subscription or read marker')
        s.add_argument('course', type=identifier, metavar='CONTEXT_ID')
        s.add_argument('topic', type=identifier)
        s.add_argument('--context', choices=('course', 'group'), default='course')
        if name.startswith('entry-'):
            s.add_argument('entry', type=identifier)
            s.add_argument('--forced-read-state', action=argparse.BooleanOptionalAction,
                           help='Explicitly set or clear the manual read-marker override; omitted leaves it unchanged')
        s.add_argument('--confirm', help='Digest returned by the preview')
        s.add_argument('--yes', action='store_true', help='Execute only if the fresh preview matches --confirm')
    schema_command = sub.add_parser('schema', help='Offline machine-readable argument and safety catalog from the actual parser')
    schema_command.add_argument('--search', help='Find command schemas by name, description or safety category')
    help_command = sub.add_parser('help', help='Search commands or show exact options without authenticating')
    help_command.add_argument('topic', nargs='?', choices=sorted(sub.choices))
    help_command.add_argument('--search', help='Find commands by name, description or safety category')
    schema_command.add_argument('topic', nargs='?', choices=sorted(sub.choices))
    # SUPPRESS preserves a root-level value when the subcommand omits the option.
    for command_parser in (*sub.choices.values(), *a.choices.values()):
        command_parser.add_argument('--format', choices=('json', 'brief'),
                                    default=argparse.SUPPRESS,
                                    help='Output format (also accepted before the command)')
        command_parser.add_argument('--max-pages', type=int, default=argparse.SUPPRESS,
                                    help='Pagination cap (also accepted before the command)')
    return p


def run(args):
    if args.max_pages < 1:
        raise CanvasError('--max-pages must be positive')
    if args.command == 'help':
        from .navigation import command_help
        return command_help(parser(), args.topic, args.search)
    if args.command == 'schema':
        from .navigation import command_schema
        return command_schema(parser(), args.topic, args.search)
    if args.command == 'capabilities':
        from .capabilities import describe
        return describe()
    if args.command == 'snapshot-diff':
        from .snapshot_diff import compare, read
        return compare(read(args.older), read(args.newer))
    if args.command == 'snapshot-search':
        from .snapshot_diff import read
        from .snapshot_search import search
        return search(read(args.snapshot), args.query, args.limit)
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
    if args.command in ('profile', 'profile-set'):
        from . import profile
        if args.command == 'profile':
            return profile.read(client, include_bio=args.include_bio, include_email=args.include_email)
        changes = {key: getattr(args, key) for key in ('name', 'short_name', 'sortable_name', 'title',
                                                      'pronunciation', 'pronouns') if getattr(args, key) is not None}
        if args.bio_file is not None:
            # Bound memory before parsing; re-read for every preview/confirmation invocation.
            with args.bio_file.open('rb') as source:
                content = source.read(40001)
            if len(content) > 40000:
                raise CanvasError('Biography file exceeds local UTF-8 size bounds')
            try:
                changes['bio'] = content.decode('utf-8')
            except UnicodeError:
                raise CanvasError('Biography file must be UTF-8 text') from None
        if args.timezone is not None:
            changes['time_zone'] = args.timezone
        return profile.change(client, changes, acknowledge_shared=args.acknowledge_shared_profile,
                              yes=args.yes, confirm=args.confirm)
    if args.command in ('event', 'event-create', 'event-edit', 'event-delete'):
        from . import events
        if args.command == 'event':
            return events.read(client, args.event)
        if args.command == 'event-delete':
            return events.change(client, args.event, delete=True, cancel_reason=args.reason,
                                 yes=args.yes, confirm=args.confirm)
        details = args.details_file.read_text(encoding='utf-8') if args.details_file else None
        options = dict(title=args.title, start=args.start, end=args.end, day=args.date,
                       time_zone=args.timezone, details=details, location=args.location,
                       address=args.address, yes=args.yes, confirm=args.confirm)
        if args.command == 'event-create':
            return events.create(client, **options)
        return events.change(client, args.event, **options)
    if args.command == 'planner':
        from .planner import items
        return items(client, args.max_pages, args.start, args.end, args.course,
                     args.group, args.filter)
    if args.command == 'planner-notes':
        from .planner import notes
        return notes(client, args.max_pages, args.start, args.end, args.course, args.personal)
    if args.command == 'planner-note':
        note = client.request(f'/api/v1/planner_notes/{args.note}')[0]
        if not isinstance(note, dict) or str(note.get('id')) != args.note:
            raise CanvasError('Canvas returned a different planner note')
        return note
    if args.command == 'planner-overrides':
        return client.list('/api/v1/planner/overrides?per_page=100', args.max_pages)
    if args.command in ('planner-override', 'planner-override-create', 'planner-override-edit', 'planner-override-delete'):
        from . import overrides
        if args.command == 'planner-override':
            return overrides.read(client, args.override)
        if args.command == 'planner-override-delete':
            return overrides.change(client, args.override, delete=True, yes=args.yes, confirm=args.confirm)
        options = dict(marked_complete=args.complete, dismissed=args.dismiss,
                       allow_module_progress=args.allow_module_progress, yes=args.yes, confirm=args.confirm)
        if args.command == 'planner-override-create':
            return overrides.create(client, args.type, args.item, args.max_pages,
                                    start=args.start, end=args.end, **options)
        return overrides.change(client, args.override, **options)
    if args.command == 'task-create':
        from .planner import create_note
        details = args.details_file.read_text(encoding='utf-8') if args.details_file else ''
        return create_note(client, args.title, args.date, details, args.course, args.yes, args.confirm)
    if args.command == 'task-edit':
        from .planner import change_note
        details = args.details_file.read_text(encoding='utf-8') if args.details_file else None
        return change_note(client, args.note, args.title, args.date, details,
                           args.course, args.clear_course, yes=args.yes, confirm=args.confirm)
    if args.command == 'task-delete':
        from .planner import change_note
        return change_note(client, args.note, delete=True, yes=args.yes, confirm=args.confirm)
    if args.command == 'module-progress':
        from .progress import module_progress
        return module_progress(client, args.course, args.max_pages)
    if args.command in ('exports', 'export-status', 'export-create', 'export-download'):
        from . import content_exports
        if args.command == 'exports':
            return content_exports.list_exports(client, args.course, args.max_pages)
        if args.command == 'export-status':
            return content_exports.status(client, args.course, args.export, args.progress)
        if args.command == 'export-create':
            return content_exports.create(client, args.course, args.type, args.select,
                                          args.skip_notifications, args.yes, args.confirm)
        return content_exports.download_export(client, args.course, args.export,
                                               args.output, args.max_bytes)
    if args.command == 'linked-files':
        from .discovery import linked_files
        return linked_files(client, args.course, args.max_pages, resolve=not args.quick,
                            all_pages=args.all_pages)
    if args.command == 'download-linked':
        from .batch import batch_download
        return batch_download(client, args.course, args.directory, args.max_pages,
                              args.max_files, args.max_bytes, args.all_pages, args.yes,
                              args.confirm, args.file)
    if args.command == 'snapshot':
        from .snapshot import capture, save_private, validate_destination
        output = validate_destination(args.output)
        return save_private(output, capture(client, args.course, args.max_pages,
                                            include_linked_files=args.include_linked_files))
    if args.command == 'sync':
        from .sync import sync_course
        directory = args.directory or config_path().parent / 'snapshots'
        return sync_course(client, args.course, args.max_pages, directory,
                           include_linked_files=args.include_linked_files)
    if args.command in ('upload-personal', 'upload-assignment-file', 'upload-context'):
        from .upload import upload
        return upload(client, args.file, args.max_bytes,
                      args.course if args.command == 'upload-assignment-file' else None,
                      args.assignment if args.command == 'upload-assignment-file' else None,
                      args.yes, args.confirm,
                      context_type=args.context if args.command == 'upload-context' else None,
                      context_id=args.context_id if args.command == 'upload-context' else None,
                      folder_id=getattr(args, 'folder', None))
    if args.command in ('submit-url', 'submit-text'):
        from .submit import submit
        source = args.url_file if args.command == 'submit-url' else args.text_file
        content = source.read_text(encoding='utf-8')
        submission_type = 'online_url' if args.command == 'submit-url' else 'online_text_entry'
        return submit(client, args.course, args.assignment, submission_type, content,
                      args.yes, args.confirm)
    if args.command == 'submit-file':
        from .submit import submit_file
        return submit_file(client, args.course, args.assignment, args.file,
                           args.yes, args.confirm)
    if args.command == 'submission-comment':
        from .feedback import comment
        return comment(client, args.course, args.assignment,
                       args.message_file.read_text(encoding='utf-8'), args.attempt,
                       args.group_comment, args.yes, args.confirm)
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
    if args.command == 'agenda':
        from .planning import agenda
        return agenda(client, args.max_pages, args.days, time_zone=args.timezone,
                      include_undated=args.include_undated, course_ids=args.course)
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
        from .planner import window
        from .writes import own_id
        if (args.all or args.undated) and (args.start or args.end):
            raise CanvasError('--all/--undated cannot combine with --start/--end; those dates would be ignored')
        query = [('type', args.type)]
        if args.all or args.undated:
            query.append(('all_events' if args.all else 'undated', 'true'))
        else:
            start, end = window(args.start, args.end)
            query += [('start_date', start), ('end_date', end)]
        query.append(('per_page', '100'))
        contexts = [f'course_{number}' for number in args.course] + [f'group_{number}' for number in args.group]
        if args.active:
            courses = client.list('/api/v1/courses?enrollment_state=active&per_page=100', args.max_pages)
            contexts += [f"course_{course['id']}" for course in courses if course.get('id')]
        if args.personal:
            profile = client.request('/api/v1/users/self/profile')[0]
            contexts.append(f'user_{own_id(profile)}')
        contexts = list(dict.fromkeys(contexts))
        if len(contexts) > 10:
            raise CanvasError('Canvas calendar supports at most 10 contexts; select courses explicitly')
        query += [('context_codes[]', context) for context in contexts]
        return client.list('/api/v1/calendar_events?' + urlencode(query), args.max_pages)
    if args.command == 'todo':
        return client.list('/api/v1/users/self/todo?per_page=100', args.max_pages)
    if args.command == 'favorites':
        from .favorites import listing
        return listing(client, args.max_pages, args.context)
    if args.command in ('favorite-add', 'favorite-remove', 'favorites-reset'):
        from .favorites import change
        return change(client, args.command.rsplit('-', 1)[1], getattr(args, 'item', None),
                      context_type=args.context, max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command in ('nicknames', 'nickname', 'nickname-set', 'nickname-clear', 'nicknames-reset'):
        from . import preferences
        if args.command == 'nicknames':
            return preferences.nicknames(client, args.max_pages)
        if args.command == 'nickname':
            return preferences.nickname(client, args.course)
        return preferences.change_nickname(client, getattr(args, 'course', None), getattr(args, 'name', None),
                                           clear=args.command == 'nickname-clear', reset=args.command == 'nicknames-reset',
                                           max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command in ('colors', 'color', 'color-set'):
        from . import preferences
        if args.command == 'colors':
            return preferences.colors(client)
        if args.command == 'color':
            return preferences.color(client, args.item, args.context)
        return preferences.change_color(client, args.item, args.hex, context_type=args.context,
                                        yes=args.yes, confirm=args.confirm)
    if args.command in ('settings', 'settings-set'):
        from . import preferences
        if args.command == 'settings':
            return preferences.settings(client)
        return preferences.change_settings(client, preferences.setting_pairs(args.changes),
                                           yes=args.yes, confirm=args.confirm)
    if args.command in ('channels', 'notification-preferences', 'notification-preferences-set'):
        from . import notifications
        if args.command == 'channels':
            return notifications.channels(client, args.max_pages, include_addresses=args.include_addresses)
        if args.command == 'notification-preferences':
            return notifications.preferences(client, args.channel, args.max_pages, category=args.category)
        return notifications.change(client, args.channel, notifications.pairs(args.changes),
                                    max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command in ('dashboard-positions', 'dashboard-position-set', 'dashboard-order'):
        from . import preferences
        if args.command == 'dashboard-positions':
            return preferences.positions(client)
        changes = ({f'{args.context}_{args.item}': args.position} if args.command == 'dashboard-position-set' else
                   preferences.ordered_positions(args.assets))
        return preferences.change_positions(client, changes, yes=args.yes, confirm=args.confirm)
    if args.command in ('activity', 'activity-summary', 'activity-dismiss', 'activity-dismiss-all'):
        from . import activity
        if args.command == 'activity':
            return activity.feed(client, args.max_pages, course_id=args.course, active=args.active,
                                 type_filter=args.type, include_content=args.include_content)
        if args.command == 'activity-summary':
            return activity.summary(client, course_id=args.course, active=args.active)
        return activity.dismiss(client, getattr(args, 'item', None), all_items=args.command == 'activity-dismiss-all',
                                max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command == 'missing':
        from .missing import read
        return read(client, args.max_pages, course_ids=args.course, submittable=args.submittable,
                    current_grading_period=args.current_grading_period, include_planner=args.include_planner,
                    time_zone=args.timezone)
    if args.command == 'groups':
        return client.list('/api/v1/users/self/groups?per_page=100', args.max_pages)
    if args.command == 'group':
        return client.request(f'/api/v1/groups/{args.group}')[0]
    if args.command == 'course-groups':
        return client.list(f'/api/v1/courses/{args.course}/groups?per_page=100', args.max_pages)
    if args.command == 'enrollments':
        from .enrollments import read
        return read(client, args.max_pages, types=args.types, states=args.states, courses=args.course, term=args.term)
    if args.command in ('enrollment-accept', 'enrollment-reject'):
        from .enrollments import respond
        return respond(client, args.course, args.enrollment, args.command.split('-')[1],
                       acknowledge=args.acknowledge_canvas_enrollment, max_pages=args.max_pages,
                       yes=args.yes, confirm=args.confirm)
    if args.command == 'permissions':
        from .access import read
        return read(client, args.context_id, args.context, names=args.permissions)
    if args.command in ('group-categories', 'group-category', 'category-groups'):
        from . import group_categories
        if args.command == 'group-categories':
            return group_categories.listing(client, args.course, args.max_pages, collaboration_state=args.collaboration_state)
        if args.command == 'group-category':
            return group_categories.read(client, args.course, args.category)
        return group_categories.groups(client, args.course, args.category, args.max_pages)
    if args.command in ('course-users', 'group-users'):
        from .roster import listing
        return listing(client, args.context_id, 'course' if args.command == 'course-users' else 'group', args.max_pages,
                       search=args.search, include_email=args.include_email,
                       enrollment_types=getattr(args, 'enrollment_type', ()),
                       enrollment_states=getattr(args, 'enrollment_state', ()),
                       sections=getattr(args, 'section', ()),
                       include_enrollments=getattr(args, 'include_enrollments', False),
                       exclude_inactive=getattr(args, 'exclude_inactive', None))
    if args.command == 'group-membership':
        from .group_membership import read
        return read(client, args.group, args.max_pages)
    if args.command in ('group-join', 'group-leave'):
        from .group_membership import change
        return change(client, args.group, args.command.split('-')[1], max_pages=args.max_pages,
                      yes=args.yes, confirm=args.confirm)
    if args.command == 'doctor':
        from .doctor import course_doctor
        return course_doctor(client, args.course)
    if args.command == 'find':
        from .find import find
        return find(client, args.course, args.query, args.max_pages, args.area)
    if args.command == 'my-files':
        route = '/api/v1/users/self/files?per_page=100'
        if args.search:
            route += '&' + urlencode({'search_term': args.search})
        return client.list(route, args.max_pages)
    if args.command == 'file-info':
        data = client.request(f'/api/v1/files/{args.file}')[0]
        if not isinstance(data, dict) or str(data.get('id')) != args.file:
            raise CanvasError('Canvas returned a different file; refusing output')
        return data
    if args.command == 'folder-path':
        from .group_content import resolve_folder_path
        return resolve_folder_path(client, args.context_id, args.context, args.path)
    if args.command in ('root-folder', 'file-quota'):
        from .group_content import quota, root
        return (root if args.command == 'root-folder' else quota)(client, args.context_id, args.context)
    if args.command in ('files', 'folders', 'pages', 'page', 'tabs', 'front-page') and args.context == 'group':
        from . import group_content
        if any(getattr(args, key, False) for key in ('best_effort', 'quick', 'all_pages')):
            raise CanvasError('Course module/linked-content fallbacks do not apply to group spaces; use the native group listing')
        if args.command in ('page', 'front-page'):
            return group_content.page(client, args.course, getattr(args, 'item', None))
        return group_content.listing(client, args.course, args.command, args.max_pages)
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
    if args.command in ('inbox-edit', 'inbox-delete'):
        from .inbox import change
        return change(client, args.conversation, state=getattr(args, 'state', None),
                      starred=getattr(args, 'starred', None), subscribed=getattr(args, 'subscribed', None),
                      delete=args.command == 'inbox-delete', permanent=getattr(args, 'permanent', False),
                      yes=args.yes, confirm=args.confirm)
    if args.command == 'inbox-reply':
        from .messaging import reply
        return reply(client, args.conversation, args.message_file.read_text(encoding='utf-8'),
                     args.yes, args.confirm)
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
    if args.command in ('my-folders', 'my-root'):
        from .personal_files import folders
        return folders(client, args.max_pages, root=args.command == 'my-root')
    if args.command == 'my-folder-create':
        from .personal_files import create_folder
        return create_folder(client, args.parent, args.name, max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command in ('my-folder-edit', 'my-folder-delete'):
        from .personal_files import change_folder
        return change_folder(client, args.folder, name=getattr(args, 'name', None),
                             destination=getattr(args, 'parent', None), delete=args.command == 'my-folder-delete',
                             max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command in ('my-file-edit', 'my-file-copy', 'my-file-delete'):
        from .personal_files import change_file
        return change_file(client, args.file, name=getattr(args, 'name', None),
                           destination=getattr(args, 'folder', None), delete=args.command == 'my-file-delete',
                           permanent=getattr(args, 'permanent', False), copy=args.command == 'my-file-copy',
                           yes=args.yes, confirm=args.confirm)
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
    if args.command == 'tabs':
        tabs = client.list(base + '/tabs?per_page=100', args.max_pages)
        return [{key: tab.get(key) for key in ('id', 'label', 'html_url', 'position', 'visibility')}
                for tab in tabs if isinstance(tab, dict) and not tab.get('hidden')]
    if args.command == 'front-page':
        page = client.request(base + '/front_page')[0]
        if not isinstance(page, dict) or page.get('published') is False or page.get('locked_for_user'):
            raise CanvasError('Course front page is not readable to this user')
        return page
    if args.command == 'pages' and args.best_effort:
        from .pages import page_index
        return page_index(client, args.course, args.max_pages)
    if args.command == 'files':
        if (args.quick or args.all_pages) and not args.best_effort:
            raise CanvasError('--quick and --all-pages require --best-effort')
        if args.best_effort:
            from .discovery import file_index
            return file_index(client, args.course, args.max_pages,
                              resolve=not args.quick, all_pages=args.all_pages)
    if args.command == 'outline':
        modules = client.list(base + '/modules?per_page=100', args.max_pages)
        return [{'id': module.get('id'), 'name': module.get('name'),
                 'position': module.get('position'), 'state': module.get('state'),
                 'unlock_at': module.get('unlock_at'), 'completed_at': module.get('completed_at'),
                 'items': client.list(base + f"/modules/{module['id']}/items?per_page=100", args.max_pages)}
                for module in modules]
    if args.command == 'topic':
        from .contexts import read_topic
        return read_topic(client, args.course, args.topic, args.context)
    if args.command == 'thread':
        from .thread import read_thread
        return read_thread(client, args.course, args.topic, args.max_pages, args.context)
    if args.command in ('entry', 'entry-edit', 'entry-delete'):
        from .discussion import change_entry, entry
        if args.command == 'entry':
            return entry(client, args.course, args.topic, args.entry, args.max_pages, args.context)
        return change_entry(client, args.course, args.topic, args.entry,
                            args.message_file.read_text(encoding='utf-8') if args.command == 'entry-edit' else None,
                            delete=args.command == 'entry-delete',
                            remove_attachment=getattr(args, 'remove_attachment', False),
                            max_pages=args.max_pages, context_type=args.context, yes=args.yes, confirm=args.confirm)
    if args.command in ('topic-subscribe', 'topic-unsubscribe', 'topic-mark-read', 'topic-mark-unread',
                        'entry-mark-read', 'entry-mark-unread'):
        from .discussion import state
        return state(client, args.course, args.topic, args.command.rsplit('-', 1)[1],
                     entry_id=getattr(args, 'entry', None), forced=getattr(args, 'forced_read_state', None),
                     max_pages=args.max_pages, context_type=args.context, yes=args.yes, confirm=args.confirm)
    if args.command in ('topic-ratings', 'entry-rate'):
        from . import ratings
        if args.command == 'topic-ratings':
            return ratings.read(client, args.course, args.topic, args.context)
        return ratings.change(client, args.course, args.topic, args.entry, args.rating,
                              context_type=args.context, max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command in ('quiz', 'rubric', 'assignment-group'):
        resource = {'quiz': 'quizzes', 'rubric': 'rubrics',
                    'assignment-group': 'assignment_groups'}[args.command]
        return client.request(base + f'/{resource}/{args.item}')[0]
    if args.command == 'submission':
        return client.request(base + f'/assignments/{args.assignment}/submissions/self?include[]=submission_comments&include[]=rubric_assessment')[0]
    if args.command == 'submissions':
        from .submissions import read
        return read(client, args.course, args.max_pages, assignment_ids=args.assignment, state=args.state,
                    include_history=args.include_history, include_comments=args.include_comments,
                    include_content=args.include_content, include_rubric=args.include_rubric)
    if args.command == 'feedback':
        from .feedback_read import read
        return read(client, args.course, args.max_pages, assignment_ids=args.assignment, include_text=args.include_text,
                    since=args.since, time_zone=args.timezone)
    if args.command == 'peer-reviews':
        from .peer_reviews import read
        return read(client, args.course, args.assignment, args.max_pages, scope=args.scope,
                    comments=args.include_comments, users=args.include_users)
    if args.command == 'download':
        from .download import download
        if args.context == 'group':
            from .group_content import file_metadata
            metadata = file_metadata(client, args.course, args.file)
        else:
            metadata = client.request(base + f'/files/{args.file}')[0]
        if not isinstance(metadata, dict) or str(metadata.get('id')) != args.file:
            raise CanvasError('Canvas returned a different file; refusing download')
        if metadata.get('locked_for_user') or metadata.get('hidden_for_user'):
            raise CanvasError('File is unavailable to this user')
        if not metadata.get('url'):
            raise CanvasError('Canvas did not provide a download URL')
        return download(metadata['url'], args.output, args.max_bytes,
                        expected_bytes=metadata.get('size'))
    if args.command in ('assignment', 'page', 'module-items'):
        item = quote(args.item, safe='')
        if args.command == 'module-items':
            return client.list(base + f'/modules/{item}/items?per_page=100', args.max_pages)
        resource = 'assignments' if args.command == 'assignment' else 'pages'
        return client.request(base + f'/{resource}/{item}')[0]
    if args.command == 'syllabus':
        return client.request(base + '?include[]=syllabus_body')[0]
    if args.command in ('entries', 'replies', 'post'):
        from .contexts import discussion_base, read_topic
        route = discussion_base(args.course, args.topic, args.context) + '/entries'
        if args.command == 'replies':
            route += f'/{args.entry}/replies'
        if args.command == 'post':
            from .discussion import post
            message = args.message_file.read_text(encoding='utf-8')
            return post(client, args.course, args.topic, args.reply_to, message,
                        args.yes, args.confirm, args.context)
        read_topic(client, args.course, args.topic, args.context, require_entries=True)
        return client.list(route + '?per_page=100', args.max_pages)
    resource = {'discussions': 'discussion_topics', 'announcements': 'discussion_topics',
                'assignment-groups': 'assignment_groups'}.get(args.command, args.command)
    route = base + '/' + resource + '?per_page=100'
    if args.command in ('discussions', 'announcements') and args.context == 'group':
        from .contexts import discussion_base
        route = discussion_base(args.course, context_type=args.context) + '?per_page=100'
    if args.command == 'announcements':
        route += '&only_announcements=true'
    return client.list(route, args.max_pages)


def brief(data):
    """Small human index. JSON remains the complete representation."""
    if isinstance(data, dict) and 'help_text' in data:
        return f"{data['safety']}\n\n{data['help_text'].rstrip()}"
    if isinstance(data, dict) and 'schema_version' in data and 'commands' in data:
        lines = [f"Pocket parser schema v{data['schema_version']} (JSON has full argument details)"]
        for command in data['commands']:
            lines.append(f"{command['command']} | {command['safety']}")
            lines.extend('  ' + (' / '.join(argument['flags']) or argument['destination']) +
                         (' (required)' if argument['required'] else '') for argument in command['arguments'])
            for selector in command.get('subcommand_selectors', []):
                lines.append('  subcommands: ' + ', '.join(selector['commands']))
        if not data['commands']:
            lines.append('No matching commands.')
        lines.append(data['note'])
        return '\n'.join(lines)
    if isinstance(data, dict) and 'command_index' in data:
        lines = []
        for category, commands in data['command_index'].items():
            lines.append(category)
            lines.extend(f"  {item['command']}  {item['description']}" for item in commands)
            lines.append('')
        if not data['command_index']:
            lines.append('No matching commands. Try help without --search.')
        lines.append(data['note'])
        return '\n'.join(lines)
    if isinstance(data, dict) and 'permissions' in data and 'context_type' in data:
        return (f"Native permissions ({data['context_type']} {data[data['context_type'] + '_id']})\n" +
                '\n'.join(f"{key}: {str(value).lower()}" for key, value in data['permissions'].items()) + f"\n{data['note']}")
    if isinstance(data, dict) and ('own_profile' in data or 'profile_changes' in data):
        record = data.get('own_profile', data.get('profile_changes'))
        lines = ['Own Canvas profile' if 'own_profile' in data else 'Selected profile fields verified by read-back']
        lines.extend(f'{key}: {value if value is not None else "(unset)"}' for key, value in record.items())
        lines.append(data['note'])
        return '\n'.join(lines)
    if isinstance(data, dict) and 'enrollments' in data and 'user_id' in data:
        lines = ['Own Canvas enrollments (not official university registration)']
        for row in data['enrollments']:
            lines.append(f"{row['id']} | course {row['course_id']} | {row.get('type') or 'unknown role'} | "
                         f"{row.get('enrollment_state') or 'unknown state'}" +
                         (f" | section {row['course_section_id']}" if 'course_section_id' in row else ''))
        lines.append(data['note'])
        return '\n'.join(lines)
    if isinstance(data, dict) and 'invitation_response' in data:
        return f"Canvas invitation {data['enrollment_id']} (course {data['course_id']}): {data['invitation_response']} acknowledged\n{data['note']}"
    if isinstance(data, dict) and ('group_categories' in data or 'group_category' in data):
        categories = data.get('group_categories', [data.get('group_category')])
        lines = [f"Course {data['course_id']} group-set metadata"]
        for row in categories:
            signup = (row['self_signup'] or 'disabled') if 'self_signup' in row else 'unknown'
            lines.append(f"{row['id']} | {row.get('name') or '(unnamed)'} | self-signup {signup}")
        if 'category_groups' in data:
            lines.extend(f"  {row['id']} | {row.get('name') or '(unnamed)'} | native count {row.get('members_count', 'unknown')}"
                         for row in data['category_groups'])
        lines.append(data['note'])
        return '\n'.join(lines)
    if isinstance(data, dict) and 'returned_user_count' in data and 'users' in data:
        lines = [f"Visible roster ({data['context_type']} {data[data['context_type'] + '_id']}): {data['returned_user_count']} returned"]
        for row in data['users']:
            lines.append(f"{row['id']} | {row.get('name') or row.get('short_name') or '(name unavailable)'}" +
                         (f" | {row['email']}" if row.get('email') is not None else ''))
            for enrollment in row.get('enrollments', []):
                lines.append(f"  {enrollment.get('type') or 'unknown role'} | {enrollment.get('enrollment_state') or 'unknown state'}" +
                             (f" | section {enrollment['course_section_id']}" if 'course_section_id' in enrollment else ''))
        lines.append(data['note'])
        return '\n'.join(lines)
    if isinstance(data, dict) and 'membership' in data:
        item = data['membership']
        state = item['workflow_state'] if item else 'no active record returned'
        return f"Own group membership ({data['group_id']}): {state}\n{data['note']}"
    if isinstance(data, dict) and data.get('context_type') == 'group' and 'resource' in data and 'items' in data:
        return (f"Group {data['group_id']} {data['resource']}: {data.get('group_name') or '(unnamed)'}\n" +
                brief(data['items']) + f"\n{data['note']}")
    if isinstance(data, dict) and 'quota_bytes' in data:
        return (f"Storage ({data['context_type']} {data[data['context_type'] + '_id']}): "
                f"{data['used_bytes']} / {data['quota_bytes']} bytes; {data['remaining_bytes']} remaining" +
                (' (over quota)' if data['over_quota'] else '') + f"\n{data['note']}")
    if isinstance(data, dict) and 'root_folder' in data:
        row = data['root_folder']
        return f"Root ({data['context_type']} {data[data['context_type'] + '_id']}): {row['id']} {row.get('name') or ''}\n{data['note']}"
    if isinstance(data, dict) and 'calendar_event' in data:
        event = data['calendar_event']
        when = (event.get('all_day_date') or event.get('start_at')) if event.get('all_day') else event.get('start_at')
        return (f"Event {event['id']} [{event.get('workflow_state') or 'unknown'}] {event.get('title') or 'Untitled'}\n"
                f"{when or 'Undated'}" + (' (all day)' if event.get('all_day') else f" to {event.get('end_at') or 'unknown'}") +
                f"\n{data['note']}")
    if isinstance(data, dict) and 'discussion_state' in data:
        state = data['discussion_state']
        return (f"Discussion {state['topic_id']}: {state['action']}" +
                (f" (entry {state['entry_id']})" if state.get('entry_id') else '') + f"\n{data['note']}")
    if isinstance(data, dict) and 'favorite_change' in data:
        change = data['favorite_change']
        target = change.get('target')
        return (f"Favorites ({change['context_type']}): {change['action']}" +
                (f" {target['id']} {target.get('name') or ''}" if target else '') + f"\n{data['note']}")
    if isinstance(data, dict) and 'inbox_change' in data:
        thread = data['inbox_change']
        action = 'removed from your view' if data['deleted_from_own_view'] else thread['workflow_state']
        return f"Inbox {thread['id']}: {action}\nStarred: {thread['starred']}; subscribed: {thread['subscribed']}\n{data['note']}"
    if isinstance(data, dict) and 'nickname_change' in data:
        record = data['nickname_change']
        return (f"Nickname {record['course_id']}: {record['nickname'] or '(cleared)'}" if record else
                'All own course nicknames cleared.') + f"\n{data['note']}"
    if isinstance(data, dict) and 'color_change' in data:
        record = data['color_change']
        return f"Color {record['asset_string']}: {record['hexcode']}\n{data['note']}"
    if isinstance(data, dict) and ('settings_change' in data or 'positions_change' in data):
        changes = data.get('settings_change', data.get('positions_change'))
        return '\n'.join(f'{key}: {value}' for key, value in changes.items()) + f"\n{data['note']}"
    if isinstance(data, dict) and 'communication_channels' in data:
        lines = ['Own communication channels']
        for row in data['communication_channels']:
            lines.append(f"{row['id']} | {row['type']} | {row['workflow_state']} | position {row.get('position', 'unknown')}" +
                         (f" | {row['address']}" if row.get('address') is not None else ''))
        lines.append(data['note'])
        return '\n'.join(lines)
    if isinstance(data, dict) and ('notification_preferences' in data or 'notification_changes' in data):
        channel = data['channel']
        lines = [f"Notification {'changes' if 'notification_changes' in data else 'preferences'}: "
                 f"channel {channel['id']} ({channel['type']}, {channel['workflow_state']})"]
        for row in data.get('notification_changes', data.get('notification_preferences')):
            lines.append(f"{row['notification']} | {row['frequency']} | {row['category'] or 'category unknown'}")
        lines.append(data['note'])
        return '\n'.join(lines)
    if isinstance(data, dict) and 'activity_hidden' in data:
        record = data['activity_hidden']
        return f"Activity hide acknowledged: {'all items' if record['all_items'] else record['item_id']}\n{data['note']}"
    if isinstance(data, dict) and 'missing_assignments' in data:
        lines = ['Native missing submissions (own account)']
        for row in data['missing_assignments']:
            lines.append(f"{row['course_id']}/{row['id']} | {row['due_display']} | {row.get('name') or '(untitled)'}")
            if row.get('locked_for_user') is True:
                lines.append('  Locked for this user; do not assume a late submission is possible.')
            if row.get('planner_override'):
                lines.append('  Planner marker present; missing submission remains listed by Canvas.')
            if row.get('html_url'):
                lines.append('  ' + row['html_url'])
        lines.append(data['note'])
        return '\n'.join(lines)
    if isinstance(data, dict) and 'own_entry_ratings' in data:
        lines = [f"Own ratings: {data.get('topic_title') or data['topic_id']}"]
        if not data['ratings_enabled']:
            lines.append('Ratings disabled.')
        for key, rating in data['own_entry_ratings'].items():
            lines.append(f"{key}: {'liked' if rating == 1 else 'like removed'}")
        lines.append(data['note'])
        return '\n'.join(lines)
    if isinstance(data, dict) and 'discussion_rating' in data:
        row = data['discussion_rating']
        return f"Entry {row['entry_id']}: {'liked' if row['rating'] == 1 else 'like removed'}\n{data['note']}"
    if isinstance(data, dict) and 'submissions' in data:
        lines = [f"Own submissions: course {data['course_id']}"]
        for row in data['submissions']:
            assignment = row.get('assignment') or {}
            lines.append(f"{row['assignment_id']} | {assignment.get('name') or '(unknown title)'} | "
                         f"{row.get('workflow_state') or 'unknown'} | attempt {row.get('attempt', 'unknown')}")
            if row.get('grade_matches_current_submission') is False:
                lines.append('  Grade does not match the current submission attempt.')
        lines.append(data['note'])
        return '\n'.join(lines)
    if isinstance(data, dict) and 'feedback' in data:
        lines = [f"Own reported feedback: course {data['course_id']}"]
        for row in data['feedback']:
            lines.append(f"{row['assignment_id']} | {row.get('assignment_name') or '(unknown title)'} | "
                         f"{row.get('latest_feedback_display') or 'date unknown'}")
            if row.get('redo_request') is True:
                lines.append('  Native reassignment flag is set; check the instructor instructions.')
            if row['grade_applicability'] == 'earlier_attempt':
                lines.append('  Grade does not match the current attempt.')
            if row.get('grade') is not None or row.get('score') is not None:
                lines.append(f"  Grade {row.get('grade', 'unknown')}; score {row.get('score', 'unknown')} / "
                             f"{row.get('points_possible') if row.get('points_possible') is not None else 'unknown'}")
            lines.append(f"  Comments: {row['comment_count'] if row['comment_count'] is not None else 'unknown'}; "
                         f"rubric criteria: {len(row['rubric_assessment']) if row['rubric_assessment'] is not None else 'unknown'}")
            for comment in row['comments']:
                if comment.get('comment') is not None:
                    lines.append('  ' + comment['comment'])
            for criterion, assessment in (row['rubric_assessment'] or {}).items():
                lines.append(f"  Criterion {criterion}: {assessment.get('points', 'unknown')} points" +
                             (f"; {assessment['comments']}" if assessment.get('comments') is not None else ''))
            if row['timestamp_coverage_uncertain']:
                lines.append('  Some feedback timestamps are unknown.')
            if row.get('assignment_url'):
                lines.append('  ' + row['assignment_url'])
        if not data['feedback']:
            lines.append('No feedback reported for these filters; this is not proof of completed coursework.')
        lines.append(data['note'])
        return '\n'.join(lines)
    if isinstance(data, dict) and 'activity_summary' in data:
        return '\n'.join(f"{row['type']}" + (f" ({row['notification_category']})" if row.get('notification_category') else '') +
                         f": {row['unread_count']} unread / {row['count']} notifications"
                         for row in data['activity_summary']) + f"\n{data['note']}"
    if isinstance(data, dict) and 'activity' in data:
        lines = [f"Activity: {data['scope']}"]
        for row in data['activity']:
            marker = 'unread' if row.get('read_state') is False else 'read' if row.get('read_state') is True else 'unknown'
            lines.append(f"{row['id']} | {row['type']} | {marker} | {row.get('title') or '(untitled)'}")
            if row.get('html_url'):
                lines.append('  ' + row['html_url'])
        lines.append(data['note'])
        return '\n'.join(lines)
    if isinstance(data, dict) and 'peer_reviews' in data:
        lines = [f"Peer reviews: {data.get('assignment_name') or data['assignment_id']} ({data['scope']})"]
        for review in data['peer_reviews']:
            assessor = review.get('assessor_id')
            lines.append(f"{review['id']}  {review.get('workflow_state') or 'unknown'}  "
                         f"owner {review['user_id']}; assessor {assessor if assessor is not None else 'hidden/unknown'}")
        if not data['peer_reviews']:
            lines.append('No reviews returned in this scope; this does not prove there are no reviews you owe.')
        lines.append(data['note'])
        return '\n'.join(lines)
    if isinstance(data, dict) and 'personal_file' in data:
        file = data['personal_file']
        return f"File {file['id']}: {file.get('display_name') or 'Untitled'}\n{data['note']}"
    if isinstance(data, dict) and 'personal_folder' in data:
        folder = data['personal_folder']
        return f"Folder {folder['id']}: {folder['name']}\n{data['note']}"
    if isinstance(data, dict) and 'entry' in data and 'note' in data:
        return f"Entry {data['entry']['id']} updated.\n{data['note']}"
    if isinstance(data, dict) and data.get('deleted') and 'entry_id' in data:
        return f"Entry {data['entry_id']} deleted.\n{data['note']}"
    if isinstance(data, dict) and 'planner_override' in data:
        override = data['planner_override']
        return (f"Planner override {override['id']} for {override['plannable_type']} {override['plannable_id']}\n"
                f"Marked complete: {override['marked_complete']}; dismissed: {override['dismissed']}\n{data['note']}")
    if isinstance(data, dict) and 'export' in data and isinstance(data['export'], dict):
        job = data['export']
        lines = [f"Export {job['id']} [{job.get('workflow_state') or 'unknown'}] "
                 f"{job.get('export_type') or 'type unknown'}",
                 f"Download available: {'yes' if job['download_available'] else 'no'}"]
        if data.get('progress'):
            progress = data['progress']
            lines.append(f"Progress {progress['id']} [{progress.get('workflow_state') or 'unknown'}] "
                         f"{progress.get('completion')}% reported")
        if data.get('note'):
            lines.append(data['note'])
        return '\n'.join(lines)
    if isinstance(data, dict) and 'planner_window' in data and 'items' in data:
        window = data['planner_window']
        lines = [f"Planner {window['start']} through {window['end']}"]
        for item in data['items']:
            content = item.get('plannable') or {}
            override = item.get('planner_override') or {}
            label = content.get('title') or content.get('name') or item.get('plannable_id')
            when = item.get('plannable_date') or content.get('todo_date') or content.get('due_at') or 'undated'
            status = ' [planner marked complete]' if override.get('marked_complete') is True else ''
            lines.append(f"{when}  {item.get('plannable_type', 'item')}: {label}{status}")
        if not data['items']:
            lines.append('No planner items in this window; other course requirements may still exist.')
        return '\n'.join(lines)
    if isinstance(data, dict) and 'module_progress' in data:
        lines = [f"Module progress for course {data['course_id']}"]
        for module in data['module_progress']:
            lines.append(f"{module['id']}  {module.get('name') or 'Module'} [{module.get('state') or 'unknown'}]")
            counts = module['requirements']
            if counts is None:
                lines.append('  Item requirements unavailable; see JSON for details.')
                continue
            rule = module.get('requirement_type') or 'not reported'
            lines.append(f"  {counts['completed']}/{counts['required']} visible requirements completed; "
                         f"{counts['unknown']} unknown; rule: {rule}")
            for item in module['items']:
                locked = ', locked' if item['locked_for_user'] else ''
                lines.append(f"  {item['id']}  {item.get('title') or 'Item'} [{item['completion']}{locked}]")
        if not data['complete']:
            lines.append('Some module item inventories were not read; coverage is partial.')
        return '\n'.join(lines)
    if isinstance(data, dict) and 'priority_basis' in data and 'items' in data:
        lines = [f"Agenda ({data['time_zone']}; next {data['window_days']} days)"]
        for item in data['items']:
            note = f"{item['urgency']}, {item['status']}"
            if item['availability'] not in ('not_specified', 'within_window'):
                note += f", {item['availability']}"
            lines.append(f"{item['due_display']}  {item.get('course_name') or item['course_id']}: "
                         f"{item.get('name') or item['assignment_id']}  [{note}]")
            if item.get('html_url'):
                lines.append(f"  {item['html_url']}")
        if not data['items']:
            lines.append('No unfinished dated assignments in this window.')
        if data['undated_count']:
            line = f"{data['undated_count']} undated visible item(s) are not deadlines."
            if data['undated'] is None:
                line += ' Use --include-undated to inspect them.'
            lines.append(line)
        if data['undated']:
            lines.append('Undated visible items (check course instructions):')
            lines.extend(f"  {item.get('course_name') or item['course_id']}: "
                         f"{item.get('name') or item['assignment_id']} [{item['status']}]"
                         for item in data['undated'])
        if data['unavailable_courses']:
            lines.append(f"Assignments unavailable for {len(data['unavailable_courses'])} "
                         'course(s); see JSON for details.')
        return '\n'.join(lines)
    if isinstance(data, dict) and all(key in data for key in
                                       ('read', 'local_write', 'canvas_write', 'auth', 'limitations')):
        sections = (('Read-only', 'read'), ('Local writes', 'local_write'),
                    ('Canvas writes', 'canvas_write'), ('Authentication', 'auth'),
                    ('Limitations', 'limitations'))
        return '\n\n'.join(f'{title} ({len(data[key])})\n' +
                           '\n'.join(f'  {item}' for item in data[key])
                           for title, key in sections)
    if isinstance(data, dict) and 'topic_id' in data and 'entries' in data and 'unavailable' in data:
        lines = [f"{data.get('title') or 'Discussion'}: {len(data['entries'])} top-level entry(s)."]
        for entry in data['entries']:
            lines.append(f"  {entry['id']}  {entry.get('user_name') or 'Unknown author'}  "
                         f"{len(entry['replies'])} repl{'y' if len(entry['replies']) == 1 else 'ies'}"
                         + (' (partial)' if not entry['replies_complete'] else ''))
        if not data['complete']:
            lines.append('Some replies were unavailable; see JSON for details.')
        return '\n'.join(lines)
    if isinstance(data, dict) and 'baseline' in data and 'saved' in data and 'counts' in data:
        lines = [f"Saved private snapshot: {data['saved']}"]
        if data['baseline']:
            lines.append('Baseline created; no earlier snapshot to compare.')
        else:
            diff = data['diff']
            count = len(diff['course_changed_fields']) + sum(
                len(group[key]) for group in diff['changes'].values()
                for key in ('added', 'removed', 'changed'))
            observed = sum(len(items) for items in diff['observed_changes'].values())
            lines.append(f'{count} change(s) in fully covered resources; '
                         f'{observed} change(s) observed in partial resources.')
            if diff['skipped']:
                lines.append('Some resource inventories were incomplete; see JSON for details.')
        return '\n'.join(lines)
    if isinstance(data, dict) and 'pages' in data and 'source' in data and 'complete' in data:
        lines = [f"{len(data['pages'])} readable page(s) in course {data['course_id']}."]
        lines.extend(f"{page.get('url')}: {page.get('title') or 'Untitled'}" for page in data['pages'])
        if not data['complete']:
            lines.append('Partial coverage: only pages linked from visible modules. See JSON for unavailable resources.')
        return '\n'.join(lines)
    if isinstance(data, dict) and 'files' in data and 'source' in data and 'complete' in data:
        lines = [f"{len(data['files'])} file(s) in course {data['course_id']}", brief(data['files'])]
        if not data['complete']:
            lines.append('Partial coverage: files linked from readable course content only.')
        if data['skipped_sources']:
            lines.append(f"Skipped {len(data['skipped_sources'])} source(s); see JSON for details.")
        return '\n'.join(lines)
    if isinstance(data, dict) and 'coverage' in data and 'results' in data:
        lines = [f"{len(data['results'])} result(s) in course {data['course_id']}."]
        for item in data['results']:
            suffix = f"  due {item['due_at']}" if item.get('due_at') else ''
            lines.append(f"{item['area']} {item['id']}: {item['title']}{suffix}")
        if not data.get('complete'):
            missing = ', '.join(area for area, status in data['coverage'].items()
                                if status != 'searched')
            lines.append(f'Coverage incomplete: {missing}. See JSON for details.')
        return '\n'.join(lines)
    if isinstance(data, dict) and 'shown' in data and 'total_matches' in data:
        lines = [f"{data['total_matches']} match(es) in snapshot; showing {len(data['shown'])}."]
        if not data.get('snapshot_complete'):
            lines.append('Snapshot incomplete; more matches may exist in Canvas.')
        for item in data['shown']:
            lines.append(f"{item['kind']} {item['id']}: {item['title']}")
            if item.get('snippet'):
                lines.append(f"  {item['snippet']}")
        return '\n'.join(lines)
    if isinstance(data, list):
        if not data:
            return 'No items.'
        if all(isinstance(item, dict) and 'label' in item and 'html_url' in item for item in data):
            return '\n'.join(f"{item.get('label') or item.get('id') or 'Untitled'}  "
                             f"{item.get('html_url') or ''}" for item in data)
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
    except Exception:  # noqa: BLE001 - suppress backend diagnostics that may contain credentials
        print('Error: credential backend or operation failed; no sensitive diagnostic output logged.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
