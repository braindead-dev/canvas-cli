"""Command syntax only; no credentials or network setup."""

import argparse
import re
from datetime import date
from pathlib import Path


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


def _confirmation(command):
    """One execution contract for every preview-first write command."""
    command.add_argument('--confirm', help='Digest returned by the fresh preview')
    command.add_argument('--yes', action='store_true', help='Execute only if --confirm matches the fresh preview')


def parser():
    p = argparse.ArgumentParser(prog='canvas', description='Canvas API CLI. JSON output may contain private academic data.')
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
    _confirmation(own_profile)
    favorites = sub.add_parser('favorites', help='Displayed favorite courses/groups, which may be Canvas defaults')
    favorites.add_argument('--context', choices=('course', 'group'), default='course')
    for name in ('favorite-add', 'favorite-remove', 'favorites-reset'):
        favorite = sub.add_parser(name, help='Preview a change to your own dashboard favorites')
        if name != 'favorites-reset':
            favorite.add_argument('item', type=identifier, help='Numeric course or group ID')
        favorite.add_argument('--context', choices=('course', 'group'), default='course')
        _confirmation(favorite)
    sub.add_parser('nicknames', help='List your saved course nicknames')
    nickname = sub.add_parser('nickname', help='Read your nickname and the actual course name')
    nickname.add_argument('course', type=identifier)
    for name in ('nickname-set', 'nickname-clear', 'nicknames-reset'):
        preference = sub.add_parser(name, help='Preview own course nickname changes, never rename a shared course')
        if name != 'nicknames-reset':
            preference.add_argument('course', type=identifier)
        if name == 'nickname-set':
            preference.add_argument('--name', required=True, help='Nonempty nickname shorter than 60 characters')
        _confirmation(preference)
    sub.add_parser('colors', help='Read your saved custom calendar/dashboard colors')
    for name in ('color', 'color-set'):
        preference = sub.add_parser(name, help='Read or preview your own color for an explicit context')
        preference.add_argument('item', type=identifier, help='Numeric course, group or own user ID')
        preference.add_argument('--context', choices=('course', 'group', 'user'), default='course')
        if name == 'color-set':
            preference.add_argument('--hex', required=True, help='Three- or six-digit RGB code, optionally prefixed with #')
            _confirmation(preference)
    sub.add_parser('settings', help='Read supported own-user interface settings, not mobile keys')
    preference = sub.add_parser('settings-set', help='Preview only explicitly selected boolean interface preferences')
    preference.add_argument('--set', dest='changes', action='append', required=True, metavar='KEY=true|false',
                            help='Repeat for several distinct settings; use settings to see reported keys')
    _confirmation(preference)
    channels = sub.add_parser('channels', help='List your own communication-channel metadata, not contact addresses by default')
    channels.add_argument('--include-addresses', action='store_true', help='Opt in to own email/SMS addresses; never push tokens')
    channel = sub.add_parser('channel-create', help='Preview adding one own email/SMS contact with native confirmation')
    channel.add_argument('--type', dest='channel_type', required=True, choices=('email', 'sms'))
    channel.add_argument('--address-file', type=Path, required=True, help='Bounded UTF-8 contact address, not a command-line address/token')
    channel.add_argument('--acknowledge-contact-message', action='store_true', help='Acknowledge a native confirmation message to this contact')
    _confirmation(channel)
    channel = sub.add_parser('channel-delete', help='Preview retiring one exact own channel, including possible primary-email/alert effects')
    channel.add_argument('channel', type=identifier)
    channel.add_argument('--acknowledge-contact-removal', action='store_true', help='Acknowledge lost alerts, possible primary/recovery email and device-notification effects')
    _confirmation(channel)
    notifications = sub.add_parser('notification-preferences', help='Read own-channel frequencies; Canvas may materialize defaults')
    notifications.add_argument('channel', type=identifier, help='Numeric channel ID from channels')
    notifications.add_argument('--category', help='Exact reported category key; filter after reading the full inventory')
    notifications = sub.add_parser('notification-preferences-set', help='Preview specific own-channel frequency changes')
    notifications.add_argument('channel', type=identifier, help='Numeric channel ID from channels')
    notifications.add_argument('--set', dest='changes', action='append', required=True, metavar='NOTIFICATION=FREQUENCY',
                               help='Repeat exact notification keys with immediately, daily, weekly or never')
    _confirmation(notifications)
    notifications = sub.add_parser('notification-category-set', help='Preview exact reported notification keys in one own-channel category')
    notifications.add_argument('channel', type=identifier, help='Numeric channel ID from channels')
    notifications.add_argument('--category', required=True, help='Exact category key reported by notification-preferences')
    notifications.add_argument('--frequency', required=True, choices=('immediately', 'daily', 'weekly', 'never'))
    _confirmation(notifications)
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
        _confirmation(preference)
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
        _confirmation(stream)
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
        _confirmation(invitation)
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
        _confirmation(membership)
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
    _confirmation(edit_inbox)
    delete_inbox = sub.add_parser('inbox-delete', help='Preview removing all thread messages from your own view')
    delete_inbox.add_argument('conversation', type=identifier)
    delete_inbox.add_argument('--permanent', action='store_true', help='Acknowledge no CLI restore; archive preserves messages')
    _confirmation(delete_inbox)
    reply = sub.add_parser('inbox-reply', help='Preview an Inbox reply; sending requires a matching digest')
    reply.add_argument('conversation', type=identifier)
    reply.add_argument('--message-file', required=True, type=Path)
    _confirmation(reply)
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
    _confirmation(compose)
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
        _confirmation(override)
    delete_override = sub.add_parser('planner-override-delete', help='Preview removing a planner override, not its assignment')
    delete_override.add_argument('override', type=identifier)
    _confirmation(delete_override)
    task = sub.add_parser('task-create', help='Preview creating a personal Canvas planner note')
    task.add_argument('--title', required=True)
    task.add_argument('--date', required=True, type=calendar_date)
    task.add_argument('--details-file', type=Path, help='Optional plain UTF-8 note details')
    task.add_argument('--course', type=identifier)
    _confirmation(task)
    edit_task = sub.add_parser('task-edit', help='Preview changes to one personal planner note')
    edit_task.add_argument('note', type=identifier)
    edit_task.add_argument('--title')
    edit_task.add_argument('--date', type=calendar_date)
    edit_task.add_argument('--details-file', type=Path, help='Plain UTF-8 details; an empty file clears details')
    course_change = edit_task.add_mutually_exclusive_group()
    course_change.add_argument('--course', type=identifier)
    course_change.add_argument('--clear-course', action='store_true')
    _confirmation(edit_task)
    remove_task = sub.add_parser('task-delete', help='Preview removing one personal planner note, not an assignment')
    remove_task.add_argument('note', type=identifier)
    _confirmation(remove_task)
    progress = sub.add_parser('module-progress', help='Read visible module requirements and completion status')
    progress.add_argument('course', type=identifier)
    sequence = sub.add_parser('module-sequence', help='Native previous/next asset occurrences, at most ten; no content navigation or mastery choice')
    sequence.add_argument('course_id', type=identifier)
    sequence.add_argument('asset_type', choices=('ModuleItem', 'File', 'Page', 'Discussion', 'Assignment', 'Quiz', 'ExternalTool'))
    sequence.add_argument('asset_id', help='Positive numeric asset ID, or one page URL slug for Page')
    for name in ('module-item', 'module-item-done', 'module-item-not-done', 'module-item-mark-read'):
        item = sub.add_parser(name, help='Inspect one scoped item or preview an explicit own module event, never an assessment attempt')
        item.add_argument('course_id', type=identifier)
        item.add_argument('module_id', type=identifier)
        item.add_argument('item_id', type=identifier)
        if name != 'module-item':
            item.add_argument('--acknowledge-module-progress', action='store_true',
                              help='Acknowledge own planner/module unlocking and configured SIS completion effects')
            if name == 'module-item-mark-read':
                item.add_argument('--acknowledge-content-viewed', action='store_true',
                                  help='Use only after accessing the content separately; the CLI does not open it')
            _confirmation(item)
    for name in ('module-paths', 'module-path-select'):
        paths = sub.add_parser(name, help='Inspect own eligible mastery paths or preview selecting/switching a native choice')
        paths.add_argument('course_id', type=identifier)
        paths.add_argument('module_id', type=identifier)
        paths.add_argument('item_id', type=identifier)
        if name == 'module-path-select':
            paths.add_argument('set_id', type=identifier)
            paths.add_argument('--acknowledge-path-change', action='store_true',
                               help='Acknowledge own assignment overrides, availability/dates and module-progress effects')
            paths.add_argument('--acknowledge-path-switch', action='store_true',
                               help='Required when switching an existing choice; other path assignments can be removed')
            paths.add_argument('--reapply-selected-path', action='store_true',
                               help='Deliberately reapply the already-reported set, including a pending automatic path; never automatic retry')
            _confirmation(paths)
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
    _confirmation(export_create)
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
        _confirmation(event)
    remove_event = sub.add_parser('event-delete', help='Preview removing one personal calendar event occurrence')
    remove_event.add_argument('event', type=identifier)
    remove_event.add_argument('--reason', help='Optional cancellation reason shown in the preview')
    _confirmation(remove_event)
    appointments = sub.add_parser('appointment-groups', help='Paginated own-reservable native Scheduler groups, not external advising')
    appointments.add_argument('--course', type=identifier, action='append', default=[])
    appointments.add_argument('--include-past', action='store_true', help='Include past native appointment groups')
    appointments.add_argument('--include-details', action='store_true', help='Opt in to organizer description text')
    appointments = sub.add_parser('appointment-group', help='Visible current slots and own individual reservation IDs for one Scheduler group')
    appointments.add_argument('appointment_group', type=identifier)
    appointments.add_argument('--include-details', action='store_true', help='Opt in to organizer description text')
    for name in ('appointment-reserve', 'appointment-cancel'):
        appointments = sub.add_parser(name, help='Preview one own individual Scheduler reservation change, never group/admin allocation')
        appointments.add_argument('appointment_group', type=identifier)
        if name == 'appointment-reserve':
            appointments.add_argument('slot', type=identifier, help='Parent slot ID from appointment-group, not a reservation ID')
            appointments.add_argument('--comments-file', type=Path, help='Optional UTF-8 comments shared with the organizer; local size bounds apply')
        else:
            appointments.add_argument('reservation', type=identifier, help='Own reservation ID from reserved_times, never the parent slot')
            appointments.add_argument('--reason', help='Optional reason visible to the organizer')
        _confirmation(appointments)
    for name in ('appointment-team-reservations', 'appointment-team-reserve', 'appointment-team-cancel'):
        appointments = sub.add_parser(name, help='Read or preview reservations for one joined course team, not an individual')
        appointments.add_argument('appointment_group', type=identifier)
        appointments.add_argument('team', type=identifier, help='Explicit Canvas course group ID, not the Scheduler group ID')
        if name == 'appointment-team-reservations':
            continue
        appointments.add_argument('--acknowledge-team-change', action='store_true',
                                  help='Required: this change affects every member, including bookings made by teammates')
        if name == 'appointment-team-reserve':
            appointments.add_argument('slot', type=identifier, help='Parent slot ID from appointment-group')
            appointments.add_argument('--comments-file', type=Path, help='Bounded UTF-8 comments shared with the organizer')
        else:
            appointments.add_argument('reservation', type=identifier, help='Team reservation ID, never its parent slot')
            appointments.add_argument('--reason', help='Optional reason visible to the organizer')
        _confirmation(appointments)
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
    _confirmation(batch)
    personal_upload = sub.add_parser('upload-personal', help='Preview uploading a file to your Canvas Files')
    personal_upload.add_argument('--file', required=True, type=Path)
    personal_upload.add_argument('--folder', type=identifier, help='Existing own folder ID; preview verifies its context')
    personal_upload.add_argument('--max-bytes', type=int, default=25 * 1024 * 1024)
    _confirmation(personal_upload)
    assignment_upload = sub.add_parser('upload-assignment-file', help='Upload a file for an assignment without submitting it')
    assignment_upload.add_argument('course', type=identifier)
    assignment_upload.add_argument('assignment', type=identifier)
    assignment_upload.add_argument('--file', required=True, type=Path)
    assignment_upload.add_argument('--max-bytes', type=int, default=25 * 1024 * 1024)
    _confirmation(assignment_upload)
    context_upload = sub.add_parser('upload-context', help='Preview a shared course/group file upload, not an assignment submission')
    context_upload.add_argument('context_id', type=identifier)
    context_upload.add_argument('--context', required=True, choices=('course', 'group'))
    context_upload.add_argument('--folder', type=identifier, help='Existing folder ID; otherwise the exact context root')
    context_upload.add_argument('--file', required=True, type=Path)
    context_upload.add_argument('--max-bytes', type=int, default=25 * 1024 * 1024)
    _confirmation(context_upload)
    scheduling = sub.add_parser('page-schedule', help='Preview one course RCE page publication date or cancellation; both leave a draft')
    scheduling.add_argument('course_id', type=identifier)
    scheduling.add_argument('page_id', type=identifier, help='Exact numeric page ID, never an ambiguous slug')
    dates = scheduling.add_mutually_exclusive_group(required=True)
    dates.add_argument('--publish-at', help='Future RFC 3339 time with explicit offset, at least 60 seconds ahead')
    dates.add_argument('--cancel', action='store_true', help='Clear a reported date and leave the page unpublished, not publish now')
    scheduling.add_argument('--acknowledge-shared-page', action='store_true', help='Required even for previews; this changes shared publication state')
    _confirmation(scheduling)
    duplication = sub.add_parser('topic-duplicate', help='Preview a native shared prompt copy, not a complete reply/file backup')
    duplication.add_argument('context_id', type=identifier)
    duplication.add_argument('topic_id', type=identifier)
    duplication.add_argument('--context', choices=('course', 'group'), default='course')
    duplication.add_argument('--acknowledge-shared-topic', action='store_true')
    duplication.add_argument('--acknowledge-copy-effects', action='store_true',
                             help='Required even for preview; copy can change audience/publication/order and drops associations')
    _confirmation(duplication)
    page_duplication = sub.add_parser('page-duplicate', help='Preview one native course wiki draft copy, including explicitly acknowledged assignment copies')
    page_duplication.add_argument('course_id', type=identifier)
    page_duplication.add_argument('page_id', type=identifier, help='Exact numeric source page ID, never an ambiguous slug')
    page_duplication.add_argument('--acknowledge-shared-page', action='store_true', help='Required even for previews; creates shared course content, not a private note')
    page_duplication.add_argument('--acknowledge-linked-assignment-copy', action='store_true', help='Required when a reported linked wiki assignment and its native associations will also be copied')
    _confirmation(page_duplication)
    page_deletion = sub.add_parser('page-delete', help='Preview native shared wiki deletion, including explicitly acknowledged assignment cascades')
    page_deletion.add_argument('context_id', type=identifier)
    page_deletion.add_argument('page_id', type=identifier, help='Exact numeric page ID, never an ambiguous slug')
    page_deletion.add_argument('--context', required=True, choices=('course', 'group'))
    page_deletion.add_argument('--acknowledge-page-deletion', action='store_true', help='Required even for previews; deletes shared content and can affect module links')
    page_deletion.add_argument('--acknowledge-linked-assignment-deletion', action='store_true', help='Required when a reported linked wiki assignment will also be deleted')
    _confirmation(page_deletion)
    for name in ('page-revisions', 'page-revision', 'page-restore'):
        history = sub.add_parser(name, help=('Preview restoring one shared RCE page revision with exact-ID verification'
                                             if name == 'page-restore' else 'Inspect native-authorized RCE wiki history; content/editors are opt-in'))
        history.add_argument('context_id', type=identifier)
        history.add_argument('page_id', type=identifier, help='Exact numeric page ID, never an ambiguous slug')
        history.add_argument('--context', required=True, choices=('course', 'group'))
        if name != 'page-revisions':
            history.add_argument('revision_id', type=identifier if name == 'page-restore' else str,
                                 help='Exact numeric revision ID' + (' or latest' if name == 'page-revision' else ''))
        if name == 'page-restore':
            history.add_argument('--acknowledge-shared-page', action='store_true', help='Required even for previews; restores shared title/body/URL')
            history.add_argument('--acknowledge-front-page-change', action='store_true', help='Required if restoration may deselect the current front page')
            _confirmation(history)
        else:
            history.add_argument('--include-editors', action='store_true', help='Include editor IDs/display names, never full native contact records')
            if name == 'page-revision':
                history.add_argument('--include-content', action='store_true', help='Include potentially private historical title/URL/HTML')
    for name in ('page-create', 'page-edit'):
        authoring = sub.add_parser(name, help='Preview shared RCE page authoring with native authorization and exact-ID readback')
        authoring.add_argument('context_id', type=identifier)
        if name == 'page-edit':
            authoring.add_argument('page_id', type=identifier, help='Exact numeric page ID, never an ambiguous slug')
        authoring.add_argument('--context', required=True, choices=('course', 'group'))
        authoring.add_argument('--title', required=name == 'page-create')
        authoring.add_argument('--body-file', type=Path, help='UTF-8 HTML; empty clears the body, maximum 40000 bytes')
        authoring.add_argument('--editing-roles', help='Comma-separated teachers/students/public for courses, members/public for groups')
        authoring.add_argument('--published', action=argparse.BooleanOptionalAction, default=None)
        authoring.add_argument('--front-page', action=argparse.BooleanOptionalAction, default=None)
        authoring.add_argument('--notify', action='store_true', help='Explicitly request participant notifications; delivery is not verified')
        authoring.add_argument('--acknowledge-shared-page', action='store_true', help='Required even for previews; affects shared wiki content/progress')
        _confirmation(authoring)
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
    _confirmation(feedback)
    for name, file_flag in (('submit-url', '--url-file'), ('submit-text', '--text-file')):
        submit = sub.add_parser(name, help='Preview an assignment submission before explicit confirmation')
        submit.add_argument('course', type=identifier)
        submit.add_argument('assignment', type=identifier)
        submit.add_argument(file_flag, required=True, type=Path)
        _confirmation(submit)
    file_submit = sub.add_parser('submit-file', help='Preview submitting one or more previously uploaded Canvas file IDs')
    file_submit.add_argument('course', type=identifier)
    file_submit.add_argument('assignment', type=identifier)
    file_submit.add_argument('file', type=identifier, nargs='+')
    _confirmation(file_submit)
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
    _confirmation(personal_folder)
    for name in ('my-folder-edit', 'my-folder-delete'):
        s = sub.add_parser(name, help='Preview a personal folder change; deletion requires an empty non-root folder')
        s.add_argument('folder', type=identifier)
        if name == 'my-folder-edit':
            s.add_argument('--name')
            s.add_argument('--parent', type=identifier)
        _confirmation(s)
    for name in ('my-file-edit', 'my-file-copy', 'my-file-delete'):
        s = sub.add_parser(name, help='Preview organizing a personal Canvas file without overwriting or sharing')
        s.add_argument('file', type=identifier)
        if name != 'my-file-delete':
            s.add_argument('--folder', type=identifier, required=name == 'my-file-copy')
        if name == 'my-file-edit':
            s.add_argument('--name')
        if name == 'my-file-delete':
            s.add_argument('--permanent', action='store_true', help='Acknowledge irreversible file destruction')
        _confirmation(s)
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
            _confirmation(s)
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
            _confirmation(s)
    creation = sub.add_parser('topic-create', help='Preview one shared ungraded topic using native creation/draft permissions')
    creation.add_argument('context_id', type=identifier)
    creation.add_argument('--context', choices=('course', 'group'), default='course')
    creation.add_argument('--title', required=True)
    creation.add_argument('--message-file', type=Path, help='Optional UTF-8 plain text escaped to HTML')
    creation.add_argument('--published', action=argparse.BooleanOptionalAction, default=None,
                          help='Omitted uses native default: moderator draft, other creator published')
    creation.add_argument('--acknowledge-shared-topic', action='store_true', help='Required even for a creation preview')
    _confirmation(creation)
    for name in ('topic-view', 'topic-view-set'):
        view = sub.add_parser(name, help='Read own effective discussion view; native queries can initialize your participant record' if name == 'topic-view' else
                              'Preview own discussion display preferences, not shared topic defaults')
        view.add_argument('context_id', type=identifier)
        view.add_argument('topic_id', type=identifier)
        view.add_argument('--context', choices=('course', 'group'), default='course')
        view.add_argument('--acknowledge-participant-initialization', action='store_true',
                          help='Required even for reads/previews; native query can create your own participant/default state')
        if name == 'topic-view-set':
            view.add_argument('--sort-order', choices=('asc', 'desc', 'inherit'), help='Shared locks can mask a saved override')
            expansion = view.add_mutually_exclusive_group()
            expansion.add_argument('--expanded', action=argparse.BooleanOptionalAction, default=None)
            expansion.add_argument('--inherit-expansion', action='store_true', help='Request explicit null, not a copied shared default')
            pinned = view.add_mutually_exclusive_group()
            pinned.add_argument('--show-pinned-entries', action=argparse.BooleanOptionalAction, default=None)
            pinned.add_argument('--clear-pinned-entry-preference', action='store_true')
            _confirmation(view)
    from .topic_options import FIELDS
    configuration = sub.add_parser('topic-configure', help='Preview shared ungraded reply/like/view settings, not personal preferences')
    configuration.add_argument('context_id', type=identifier)
    configuration.add_argument('topic_id', type=identifier)
    configuration.add_argument('--context', choices=('course', 'group'), default='course')
    for key, choices in FIELDS.items():
        if choices is None:
            configuration.add_argument('--' + key.replace('_', '-'), action=argparse.BooleanOptionalAction, default=None)
        else:
            configuration.add_argument('--' + key.replace('_', '-'), choices=choices)
    configuration.add_argument('--acknowledge-shared-topic', action='store_true')
    configuration.add_argument('--acknowledge-reply-visibility-change', action='store_true',
                               help='Required when setting require-initial-post; other participants can gain/lose reply visibility')
    _confirmation(configuration)
    sections = sub.add_parser('topic-sections', help='Preview a course discussion section filter, not participant overrides')
    sections.add_argument('course_id', type=identifier)
    sections.add_argument('topic_id', type=identifier)
    selection = sections.add_mutually_exclusive_group(required=True)
    selection.add_argument('--section-id', action='append', type=identifier, default=[], help='Repeat for each selected course section')
    selection.add_argument('--all-sections', action='store_true', help='Disable this filter; other visibility rules still apply')
    sections.add_argument('--acknowledge-shared-topic', action='store_true')
    sections.add_argument('--acknowledge-audience-change', action='store_true', help='Required even for previews; access to existing replies can change')
    _confirmation(sections)
    todo = sub.add_parser('topic-todo', help='Preview a shared course/group discussion to-do date, not a private reminder')
    todo.add_argument('context_id', type=identifier)
    todo.add_argument('topic_id', type=identifier)
    todo.add_argument('--context', choices=('course', 'group'), default='course')
    selection = todo.add_mutually_exclusive_group(required=True)
    selection.add_argument('--todo-at', metavar='TIMESTAMP', help='RFC 3339 whole-second instant with Z or explicit offset')
    selection.add_argument('--clear-todo', action='store_true')
    todo.add_argument('--acknowledge-shared-topic', action='store_true')
    todo.add_argument('--acknowledge-student-todo-change', action='store_true', help='Required even for previews; affects other participants')
    _confirmation(todo)
    scheduling = sub.add_parser('topic-schedule', help='Preview course discussion dates, acknowledging native publication/reply-state effects')
    scheduling.add_argument('course_id', type=identifier)
    scheduling.add_argument('topic_id', type=identifier)
    for label in ('opening', 'closing'):
        selection = scheduling.add_mutually_exclusive_group()
        selection.add_argument('--' + ('opens-at' if label == 'opening' else 'closes-at'), metavar='TIMESTAMP',
                               help='RFC 3339 whole-second instant with Z or explicit offset')
        selection.add_argument('--clear-' + label, action='store_true')
    scheduling.add_argument('--acknowledge-shared-topic', action='store_true')
    scheduling.add_argument('--acknowledge-availability-change', action='store_true',
                            help='Required even for preview; dates can publish drafts or reopen/close replies')
    _confirmation(scheduling)
    ordering = sub.add_parser('topic-order', help='Preview the complete shared pinned-topic order with native context moderation rights')
    ordering.add_argument('context_id', type=identifier)
    ordering.add_argument('topic_ids', nargs='+', type=identifier, metavar='TOPIC_ID')
    ordering.add_argument('--context', choices=('course', 'group'), default='course')
    ordering.add_argument('--acknowledge-all-pinned-topics', action='store_true')
    _confirmation(ordering)
    for name in ('publish', 'unpublish', 'close', 'open', 'pin', 'unpin'):
        state = sub.add_parser('topic-' + name, help='Preview one native shared discussion state change with independent readback')
        state.set_defaults(topic_action=name)
        state.add_argument('context_id', type=identifier)
        state.add_argument('topic_id', type=identifier)
        state.add_argument('--context', choices=('course', 'group'), default='course')
        state.add_argument('--acknowledge-shared-topic', action='store_true')
        if name in ('pin', 'unpin'):
            state.add_argument('--acknowledge-topic-ordering-change', action='store_true', help='Required because other positions can shift')
        if name == 'open':
            state.add_argument('--acknowledge-closing-schedule-removal', action='store_true', help='Required when reopening clears a closing date')
        _confirmation(state)
    for name in ('topic-edit', 'topic-delete'):
        s = sub.add_parser(name, help='Preview exact ungraded discussion prompt management, not a reply or assignment change')
        s.add_argument('context_id', type=identifier)
        s.add_argument('topic_id', type=identifier)
        s.add_argument('--context', choices=('course', 'group'), default='course')
        s.add_argument('--acknowledge-shared-topic', action='store_true', help='Required for shared course/group discussion changes')
        if name == 'topic-edit':
            s.add_argument('--title', help='Selected title; omitted preserves it')
            s.add_argument('--message-file', type=Path, help='Selected UTF-8 plain text, escaped to HTML; omitted preserves it')
        else:
            s.add_argument('--acknowledge-topic-removal', action='store_true', help='Required for native soft deletion and loss of topic access')
        _confirmation(s)
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
    _confirmation(rate)
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
        _confirmation(s)
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
