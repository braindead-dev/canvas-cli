"""Route authenticated parsed commands to resource-specific operations."""

from datetime import datetime, timezone
from urllib.parse import quote, urlencode

from .auth import config_path
from .client import CanvasError
from .text import read_utf8


def execute(client, args):
    if args.command in ('what-if-course', 'what-if-reset'):
        from . import what_if_course
        if args.command == 'what-if-course':
            return what_if_course.read(client, args.course_id, max_pages=args.max_pages)
        return what_if_course.reset(client, args.course_id, acknowledge_all=args.acknowledge_all_what_if,
                                    include_totals=args.include_totals, max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command in ('what-if', 'what-if-set', 'what-if-clear'):
        from . import what_if
        if args.command == 'what-if':
            return what_if.read(client, args.course_id, args.assignment_id)
        return what_if.change(client, args.course_id, args.assignment_id, getattr(args, 'score', None),
                              acknowledge=args.acknowledge_forecast_change, include_forecasts=args.include_forecasts,
                              yes=args.yes, confirm=args.confirm)
    if args.command in ('feedback-comments', 'feedback-comment-mark-read'):
        from . import feedback_comments
        if args.command == 'feedback-comments':
            return feedback_comments.read(client, args.course_id, args.assignment_id, attempt=args.attempt,
                                          all_attempts=args.all_attempts, max_pages=args.max_pages)
        return feedback_comments.mark_read(client, args.course_id, args.assignment_id, args.comment_id,
                                           attempt=args.attempt, max_pages=args.max_pages,
                                           acknowledge=args.acknowledge_feedback_indicators, yes=args.yes, confirm=args.confirm)
    if args.command in ('submission-attention', 'submission-mark-read', 'submission-mark-unread'):
        from . import submission_attention
        if args.command == 'submission-attention':
            return submission_attention.read(client, args.course_id, args.assignment_id, include_preferences=args.include_feedback_markers)
        return submission_attention.change(client, args.course_id, args.assignment_id,
                                           'unread' if args.command == 'submission-mark-unread' else 'read',
                                           surface=getattr(args, 'surface', 'overall'), acknowledge=args.acknowledge_feedback_indicators,
                                           yes=args.yes, confirm=args.confirm)
    if args.command in ('submission-comments', 'comment-draft-create', 'comment-draft-edit', 'comment-draft-publish', 'comment-draft-delete'):
        from . import submission_comments
        if args.command == 'submission-comments':
            return submission_comments.read(client, args.course_id, args.assignment_id, attempt=args.attempt,
                                            all_attempts=args.all_attempts, include_content=args.include_content, max_pages=args.max_pages)
        options = {'attempt': args.attempt, 'acknowledge': args.acknowledge_native_effects,
                   'max_pages': args.max_pages, 'yes': args.yes, 'confirm': args.confirm}
        if args.command in ('comment-draft-create', 'comment-draft-edit'):
            from .text import html_body
            content = read_utf8(args.message_file if args.message_file is not None else args.html_file, label='Comment body')
            options['message'] = html_body(content) if args.message_file is not None else content
        if args.command == 'comment-draft-create':
            return submission_comments.create(client, args.course_id, args.assignment_id, **options,
                                              file_ids=args.file_id, media_id=args.media_id, media_type=args.media_type,
                                              group_comment=args.group_comment, acknowledge_group=args.acknowledge_group_effects)
        return submission_comments.change(client, args.course_id, args.assignment_id, args.comment_id,
                                          args.command.removeprefix('comment-draft-'), **options)
    if args.command in ('draft', 'draft-save', 'draft-delete'):
        from . import submission_drafts
        if args.command == 'draft':
            return submission_drafts.read(client, args.course_id, args.assignment_id, include_content=args.include_content)
        if args.command == 'draft-delete':
            return submission_drafts.delete(client, args.course_id, args.assignment_id,
                                            acknowledge_all=args.acknowledge_all_drafts, yes=args.yes, confirm=args.confirm)
        values = {}
        if args.text_file is not None or args.html_file is not None:
            text = read_utf8(args.text_file if args.text_file is not None else args.html_file, label='Draft body')
            values['body'] = submission_drafts.text_input(text) if args.text_file is not None else text
        for option, key in (('url_file', 'url'), ('lti_url_file', 'ltiLaunchUrl')):
            source = getattr(args, option)
            if source is not None:
                values[key] = read_utf8(source, label='Draft URL').strip()
        for option, key in (('file_id', 'fileIds'), ('media_id', 'mediaId'), ('external_tool_id', 'externalToolId'),
                            ('resource_link_lookup_uuid', 'resourceLinkLookupUuid')):
            if getattr(args, option) is not None:
                values[key] = getattr(args, option)
        return submission_drafts.save(client, args.course_id, args.assignment_id, args.draft_type, values,
                                      clear=args.clear_content, yes=args.yes, confirm=args.confirm)
    if args.command == 'topic-languages':
        from .topic_view import languages
        return languages(client)
    if args.command in ('topic-view', 'topic-view-set'):
        from . import topic_view
        if args.command == 'topic-view':
            return topic_view.read(client, args.context_id, args.topic_id, context_type=args.context,
                                   acknowledge=args.acknowledge_participant_initialization, include_assist=args.include_assist_preferences,
                                   include_marker=args.include_pinned_marker)
        values = {}
        if args.sort_order is not None:
            values['sort_order'] = args.sort_order
        if args.expanded is not None or args.inherit_expansion:
            values['expanded'] = None if args.inherit_expansion else args.expanded
        if args.show_pinned_entries is not None:
            values['show_pinned_entries'] = args.show_pinned_entries
        if args.preferred_language is not None or args.clear_preferred_language:
            values['preferred_language'] = None if args.clear_preferred_language else args.preferred_language
        if args.summary_enabled is not None:
            values['summary_enabled'] = args.summary_enabled
        if args.pinned_unread is not None:
            values['has_unread_pinned_entry'] = args.pinned_unread
        return topic_view.change(client, args.context_id, args.topic_id, values, context_type=args.context,
                                 acknowledge=args.acknowledge_participant_initialization,
                                 acknowledge_marker=args.acknowledge_pinned_marker_change,
                                 yes=args.yes, confirm=args.confirm)
    if args.command == 'topic-sections':
        from .topic_management import change
        return change(client, args.course_id, args.topic_id,
                      sections={'specific_sections': 'all' if args.all_sections else [int(value) for value in args.section_id]},
                      acknowledge_shared=args.acknowledge_shared_topic, acknowledge_audience=args.acknowledge_audience_change,
                      max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command == 'topic-todo':
        from .topic_management import change
        return change(client, args.context_id, args.topic_id, context_type=args.context,
                      todo={'todo_date': None if args.clear_todo else args.todo_at},
                      acknowledge_shared=args.acknowledge_shared_topic, acknowledge_todo=args.acknowledge_student_todo_change,
                      max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command == 'topic-duplicate':
        from .topic_duplication import duplicate
        return duplicate(client, args.context_id, args.topic_id, context_type=args.context,
                         acknowledge_shared=args.acknowledge_shared_topic, acknowledge_copy=args.acknowledge_copy_effects,
                         max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command == 'topic-schedule':
        from .topic_management import change
        selected = {}
        for key, value, clear in (('delayed_post_at', args.opens_at, args.clear_opening),
                                  ('lock_at', args.closes_at, args.clear_closing)):
            if value is not None or clear:
                selected[key] = None if clear else value
        return change(client, args.course_id, args.topic_id, schedule=selected,
                      acknowledge_shared=args.acknowledge_shared_topic,
                      acknowledge_availability=args.acknowledge_availability_change,
                      max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command == 'topic-order':
        from .topic_ordering import reorder
        return reorder(client, args.context_id, args.topic_ids, context_type=args.context,
                       acknowledge=args.acknowledge_all_pinned_topics,
                       max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command == 'topic-configure':
        from .topic_management import change
        from .topic_options import FIELDS
        return change(client, args.context_id, args.topic_id, context_type=args.context,
                      options={key: getattr(args, key) for key in FIELDS if getattr(args, key) is not None},
                      acknowledge_shared=args.acknowledge_shared_topic,
                      acknowledge_reply_visibility=args.acknowledge_reply_visibility_change,
                      max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if getattr(args, 'topic_action', None) is not None:
        from .topic_management import change
        return change(client, args.context_id, args.topic_id, context_type=args.context, action=args.topic_action,
                      acknowledge_shared=args.acknowledge_shared_topic,
                      acknowledge_ordering=getattr(args, 'acknowledge_topic_ordering_change', False),
                      acknowledge_schedule_removal=getattr(args, 'acknowledge_closing_schedule_removal', False),
                      max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command == 'topic-create':
        from .topic_authoring import create
        return create(client, args.context_id, context_type=args.context, title=args.title,
                      message=read_utf8(args.message_file, label='Topic message') if args.message_file else None,
                      published=args.published, acknowledge_shared=args.acknowledge_shared_topic,
                      max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command in ('topic-edit', 'topic-delete'):
        from .topic_management import change
        source = getattr(args, 'message_file', None)
        return change(client, args.context_id, args.topic_id, context_type=args.context,
                      title=getattr(args, 'title', None), message=read_utf8(source, label='Topic message') if source else None,
                      delete=args.command == 'topic-delete', acknowledge_shared=args.acknowledge_shared_topic,
                      acknowledge_removal=getattr(args, 'acknowledge_topic_removal', False),
                      max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command == 'page-schedule':
        from .page_scheduling import schedule
        return schedule(client, args.course_id, args.page_id, publish_at=args.publish_at, cancel=args.cancel,
                        acknowledge_shared=args.acknowledge_shared_page,
                        max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command == 'page-duplicate':
        from .page_duplication import duplicate
        return duplicate(client, args.course_id, args.page_id, acknowledge_shared=args.acknowledge_shared_page,
                         acknowledge_assignment=args.acknowledge_linked_assignment_copy,
                         max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command == 'page-delete':
        from .page_deletion import delete
        return delete(client, args.context_id, args.page_id, context_type=args.context,
                      acknowledge=args.acknowledge_page_deletion,
                      acknowledge_assignment=args.acknowledge_linked_assignment_deletion,
                      max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command in ('page-revisions', 'page-revision', 'page-restore'):
        from . import page_history
        if args.command == 'page-restore':
            return page_history.restore(client, args.context_id, args.page_id, args.revision_id,
                                        context_type=args.context, acknowledge_shared=args.acknowledge_shared_page,
                                        acknowledge_front=args.acknowledge_front_page_change,
                                        max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
        return page_history.read(client, args.context_id, args.page_id, getattr(args, 'revision_id', None),
                                 context_type=args.context, content=getattr(args, 'include_content', False),
                                 editors=args.include_editors, max_pages=args.max_pages)
    if args.command in ('page-create', 'page-edit'):
        from .page_authoring import change
        content = read_utf8(args.body_file, label='Page body') if args.body_file is not None else None
        return change(client, args.context_id, getattr(args, 'page_id', None), context_type=args.context,
                      title=args.title, body=content, roles=args.editing_roles, published=args.published,
                      front_page=args.front_page, notify=args.notify, acknowledge_shared=args.acknowledge_shared_page,
                      max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command in ('appointment-team-reservations', 'appointment-team-reserve', 'appointment-team-cancel'):
        from . import team_appointments
        if args.command == 'appointment-team-reservations':
            return team_appointments.read(client, args.appointment_group, args.team, max_pages=args.max_pages)
        options = dict(acknowledge_team_change=args.acknowledge_team_change, max_pages=args.max_pages,
                       yes=args.yes, confirm=args.confirm)
        if args.command == 'appointment-team-cancel':
            return team_appointments.cancel(client, args.appointment_group, args.team, args.reservation,
                                            reason=args.reason, **options)
        comments = read_utf8(args.comments_file, label='Reservation comments') if args.comments_file is not None else None
        return team_appointments.reserve(client, args.appointment_group, args.team, args.slot, comments=comments, **options)
    if args.command in ('appointment-groups', 'appointment-group', 'appointment-reserve', 'appointment-cancel'):
        from . import appointments
        if args.command == 'appointment-groups':
            return appointments.listing(client, args.max_pages, courses=args.course,
                                        include_past=args.include_past, include_details=args.include_details)
        if args.command == 'appointment-group':
            return appointments.read(client, args.appointment_group, include_details=args.include_details)
        if args.command == 'appointment-cancel':
            return appointments.cancel(client, args.appointment_group, args.reservation,
                                       reason=args.reason, yes=args.yes, confirm=args.confirm)
        comments = None
        if args.comments_file is not None:
            comments = read_utf8(args.comments_file, label='Reservation comments')
        return appointments.reserve(client, args.appointment_group, args.slot, comments=comments,
                                    max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command in ('profile', 'profile-set'):
        from . import profile
        if args.command == 'profile':
            return profile.read(client, include_bio=args.include_bio, include_email=args.include_email)
        changes = {key: getattr(args, key) for key in ('name', 'short_name', 'sortable_name', 'title',
                                                      'pronunciation', 'pronouns') if getattr(args, key) is not None}
        if args.bio_file is not None:
            # Bound memory before parsing; re-read for every preview/confirmation invocation.
            changes['bio'] = read_utf8(args.bio_file, label='Biography')
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
    if args.command == 'module-sequence':
        from .module_navigation import sequence
        return sequence(client, args.course_id, args.asset_type, args.asset_id)
    if args.command in ('module-paths', 'module-path-select'):
        from . import module_paths
        if args.command == 'module-paths':
            return module_paths.read(client, args.course_id, args.module_id, args.item_id, max_pages=args.max_pages)
        return module_paths.select(client, args.course_id, args.module_id, args.item_id, args.set_id,
                                   acknowledge_change=args.acknowledge_path_change,
                                   acknowledge_switch=args.acknowledge_path_switch,
                                   reapply_selected=args.reapply_selected_path,
                                   max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command in ('module-item', 'module-item-done', 'module-item-not-done', 'module-item-mark-read'):
        from . import module_items
        if args.command == 'module-item':
            return module_items.read(client, args.course_id, args.module_id, args.item_id, max_pages=args.max_pages)
        return module_items.change(client, args.course_id, args.module_id, args.item_id,
                                   {'module-item-done': 'done', 'module-item-not-done': 'not-done',
                                    'module-item-mark-read': 'read'}[args.command],
                                   acknowledge_progress=args.acknowledge_module_progress,
                                   acknowledge_viewed=getattr(args, 'acknowledge_content_viewed', False),
                                   max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
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
                           include_linked_files=args.include_linked_files, incremental=args.incremental)
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
    if args.command in ('channels', 'channel-create', 'channel-delete'):
        from . import channels
        if args.command == 'channels':
            return channels.listing(client, args.max_pages, include_addresses=args.include_addresses)
        if args.command == 'channel-delete':
            return channels.delete(client, args.channel, acknowledge_removal=args.acknowledge_contact_removal,
                                   max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
        address = read_utf8(args.address_file, label='Contact address', max_bytes=4096)
        address = address[:-2] if address.endswith('\r\n') else address.removesuffix('\n')
        return channels.create(client, args.channel_type, address, acknowledge_message=args.acknowledge_contact_message,
                               max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
    if args.command in ('notification-preferences', 'notification-preferences-set', 'notification-category-set'):
        from . import notifications
        if args.command == 'notification-preferences':
            return notifications.preferences(client, args.channel, args.max_pages, category=args.category)
        if args.command == 'notification-category-set':
            return notifications.change(client, args.channel, category=args.category, frequency=args.frequency,
                                        max_pages=args.max_pages, yes=args.yes, confirm=args.confirm)
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
    if args.command == 'auth':
        from .writes import account
        account(client)
        return {'authenticated': True}
    if args.command == 'me':
        return client.request('/api/v1/users/self/profile')[0]
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
        from .writes import account
        user_id = account(client)['user_id']
        enrollments = client.list(base + f'/enrollments?user_id={user_id}&per_page=100', args.max_pages)
        if any(not isinstance(enrollment, dict) or type(enrollment.get('user_id')) is not int
               or enrollment['user_id'] != user_id or type(enrollment.get('course_id')) is not int
               or str(enrollment['course_id']) != args.course
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
