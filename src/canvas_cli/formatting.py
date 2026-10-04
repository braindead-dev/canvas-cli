"""Human-readable summaries of already-fetched data; JSON stays complete."""

import json

from .text import terminal_safe


def _diff_lines(diff):
    """A field-name index shared by sync and explicitly selected offline diffs."""
    count = len(diff['course_changed_fields']) + sum(
        len(group[key]) for group in diff['changes'].values()
        for key in ('added', 'removed', 'changed'))
    observed = sum(len(items) for items in diff['observed_changes'].values())
    lines = [f'{count} change(s) in fully covered resources; '
             f'{observed} change(s) observed in partial resources.']
    if diff['course_changed_fields']:
        lines.append('Course fields: ' + ', '.join(diff['course_changed_fields']))
    for kind, group in diff['changes'].items():
        for action in ('added', 'removed', 'changed'):
            for row in group[action]:
                fields = ' [' + ', '.join(row['fields']) + ']' if action == 'changed' else ''
                lines.append(f"{kind} {action}: {row['title']} ({row['id']}){fields}")
    for kind, rows in diff['observed_changes'].items():
        for row in rows:
            lines.append(f"{kind} observed change: {row['title']} ({row['id']}) "
                         '[' + ', '.join(row['fields']) + ']')
    if diff['skipped']:
        lines.append('Skipped full inventory comparisons: ' + ', '.join(sorted(diff['skipped'])) +
                     '. Unseen changes remain unknown.')
    return lines


def brief(data):
    """Small human index. JSON remains the complete representation."""
    return terminal_safe(_brief(data))


def _brief(data):
    if isinstance(data, dict) and 'attention_status' in data and not data.get('dry_run'):
        lines = [f"Own feedback indicators: course {data['course_id']}, assignment {data['assignment_id']}",
                 data['attention_status'], 'Aggregate: ' + str(data['aggregate_read_state'])]
        lines.extend(key + ': ' + ('read' if value else 'unread') for key, value in data['preference_read_markers'].items())
        if data.get('mutation_acknowledged'):
            lines.append(f"Native {data['surface']} request acknowledged; no coursework was completed.")
            if data['aggregate_matches_requested_state'] is False:
                lines.append('The aggregate differs from the requested state; other native unread items can remain.')
            if not data['selected_preference_readback_verified']:
                lines.append('Individual participation-item storage is not independently verified.')
        return '\n'.join([*lines, data['note']])
    if isinstance(data, dict) and 'inventory_status' in data and 'selected_attempts' in data and not data.get('dry_run'):
        lines = [f"Own comments: course {data['course_id']}, assignment {data['assignment_id']}", data['inventory_status']]
        for row in data['comments']:
            lines.append(f"{row['id']} · attempt {row['attempt']} · {'draft' if row['draft'] else 'published'} · "
                         f"{len(row['file_ids'])} reported attachment(s)")
        if data.get('own_draft_absence_verified'):
            lines.append('Own draft absent from the complete selected-attempt inventory; linked group copies are unverified.')
        elif data.get('mutation_acknowledged'):
            lines.append('Own comment state read back; no final submission was requested.')
        if any(data.get(key) is False for key in ('reported_html_matches_request', 'reported_file_ids_match_request',
                                                 'reported_media_id_matches_request')):
            lines.append('Returned content/associations differ from the request; inspect Canvas and JSON. Raw storage is unverified.')
        lines.append('Comment content is private; use JSON to inspect it.')
        return '\n'.join([*lines, data['note']])
    if isinstance(data, dict) and 'submission_draft' in data and not data.get('dry_run'):
        row = data['submission_draft']
        lines = [f"Own draft: course {data['course_id']}, assignment {data['assignment_id']}"]
        if row is None:
            lines.append(data['next_draft_status'])
        else:
            lines.append(f"Draft {row['id']}, attempt {row['attempt']}, type {row['type']}")
            lines.append(f"{len(row['file_ids'])} reported attachment(s); content is private, use JSON to inspect it.")
        if data.get('next_attempt_draft_identity_verified'):
            lines.append('Next-attempt draft identity verified; this did not turn in work.')
            if not all(data['reported_fields_match_request'].values()):
                lines.append('Returned content differs from the request; inspect Canvas and JSON. Raw storage is unverified.')
        if data.get('next_attempt_absence_verified'):
            lines.append('Next-attempt absence verified; historical deletion is server-reported only. Deleted drafts cannot be restored by the CLI.')
        return '\n'.join([*lines, data['note']])
    if isinstance(data, dict) and 'discussion_languages' in data:
        rows = data['discussion_languages']['values']
        return '\n'.join([*(row['enum'] + (' (deprecated)' if row['deprecated'] else '') for row in rows), data['note']])
    if isinstance(data, dict) and 'topic_view' in data:
        row = data['topic_view']
        lines = [f"Own view for {row['context_type']} {row['context_id']} topic {row['topic_id']}",
                 'Reported: ' + ', '.join(key + '=' + (value if key == 'preferred_language' and isinstance(value, str)
                                                       else str(value).lower()) for key, value in row['reported'].items())]
        if data.get('mutation_acknowledged'):
            lines.append('Mutation acknowledged; selected native readback independently verified.')
        if data.get('masked_by_shared_locks'):
            lines.append('Masked by shared locks: ' + ', '.join(data['masked_by_shared_locks']))
        lines.append('Raw saved sort/expansion overrides are not verified.')
        return '\n'.join([*lines, data['note']])
    if isinstance(data, dict) and 'copied_topic' in data:
        row = data['copied_topic']
        lines = [f"{data['context_type'].title()} {data[data['context_type'] + '_id']} topic {data['source_topic_id']} → {row['id']} copied",
                 row['title'], 'Published' if row['published'] else 'Draft', row['html_url']]
        different = [key for key, value in data['stored_fields_match_source'].items() if not value]
        if different:
            lines.append('Copy differs from source: ' + ', '.join(different))
        lines.append(f"Attachment associations: {data['source_attachment_count']} in source, {data['copy_attachment_count']} in copy.")
        if data['pinned_ordering']:
            lines.append('Accessible pinned positions verified; hidden ordering is not verified.')
        return '\n'.join([*lines, data['note']])
    if isinstance(data, dict) and 'pinned_topic_order' in data:
        return (f"{data['context_type'].title()} {data[data['context_type'] + '_id']} pinned order verified\n" +
                ' → '.join(str(identifier) for identifier in data['pinned_topic_order']) +
                '\n' + data['html_url'] + '\n' + data['note'])
    if isinstance(data, dict) and 'created_topic' in data:
        row = data['created_topic']
        lines = [f"{data['context_type'].title()} {data[data['context_type'] + '_id']} topic {row['id']} created",
                 row['title'], 'Published' if row['published'] else 'Draft', row['html_url']]
        if not all(data['stored_fields_match_request'].values()):
            lines.append('Stored fields differ from the request; inspect Canvas and JSON before using the topic.')
        return '\n'.join([*lines, data['note']])
    if isinstance(data, dict) and 'edited_topic' in data:
        row = data['edited_topic']
        verb = 'updated' if any(key in data for key in ('topic_state', 'configured_topic_settings', 'scheduled_topic_dates',
                                                      'student_todo_date', 'topic_section_filter')) else 'edited'
        lines = [f"{data['context_type'].title()} {data[data['context_type'] + '_id']} topic {row['id']} {verb}",
                 row['title'], row['html_url']]
        if 'topic_state' in data:
            state = data['topic_state']
            lines.append(f"Native {state['field']}={str(state['value']).lower()} verified.")
            if state['closing_schedule_cleared']:
                lines.append('Closing schedule cleared.')
        if 'configured_topic_settings' in data:
            values = data['configured_topic_settings']['values']
            lines.append('Native options verified: ' + ', '.join(sorted(values)))
        if 'scheduled_topic_dates' in data:
            dates = data['scheduled_topic_dates']
            lines.extend(key + ': ' + (value or 'cleared') for key, value in dates['stored'].items())
            lines.append('Stored instants verified; future execution and student availability are not verified.')
        if 'student_todo_date' in data:
            lines.append('Shared student to-do date: ' + (data['student_todo_date']['stored'] or 'cleared'))
            lines.append('Stored date verified; planner effects and completion are not verified.')
        if 'topic_section_filter' in data:
            selection = data['topic_section_filter']
            lines.append('Section filter: ' + (', '.join(str(value) for value in selection['section_ids'])
                                              if selection['is_section_specific'] else 'all sections'))
            lines.append('Stored filter verified; effective participant visibility is not verified.')
        if 'observed_inventory_changes' in data:
            inventory = data['observed_inventory_changes']
            lines.append(f"Observed inventory changes: {len(inventory['added_ids'])} added, "
                         f"{len(inventory['removed_ids'])} removed, {len(inventory['changed'])} changed; not causal proof.")
        if not all(data['stored_text_matches_request'].values()):
            lines.append('Stored text differs from the request; inspect Canvas and JSON before using the topic.')
        if data['unrequested_changed_fields']:
            lines.append('Other observed changes: ' + ', '.join(data['unrequested_changed_fields']))
        return '\n'.join([*lines, data['note']])
    if isinstance(data, dict) and 'deleted_topic' in data:
        return (f"{data['context_type'].title()} {data[data['context_type'] + '_id']} topic {data['deleted_topic']['id']} soft-deleted\n"
                f"{data['deleted_topic']['title']}\n{data['note']}")
    if isinstance(data, dict) and 'mastery_paths' in data and not data.get('dry_run'):
        item_id = data.get('item_id') or data['module_item']['id']
        module_id = data.get('module_id') or data['module']['id']
        lines = [f"Course {data['course_id']} module {module_id} item {item_id} | mastery paths"]
        paths = data['mastery_paths']
        if paths is None:
            lines.append('No native mastery-path metadata reported for this item.')
        else:
            lines.append(f"Selected set: {paths.get('selected_set_id') or 'none/unknown'}; "
                         f"locked: {paths.get('locked', 'unknown')}; processing: {paths.get('still_processing', 'unknown')}")
            for row in paths.get('assignment_sets', []):
                identifiers = row['assignment_ids']
                lines.append(f"Set {row['id']} | assignments: " +
                             (', '.join(str(value) for value in identifiers) or 'none' if identifiers is not None else 'unknown'))
        if data.get('request_acknowledged'):
            lines.append('Request acknowledged; ' + ('choice independently verified.' if data['choice_verified'] else
                                                    'choice not yet verified. Check Canvas before repeating.'))
        return '\n'.join([*lines, data['note']])
    if isinstance(data, dict) and 'module_sequence' in data:
        lines = [f"Course {data['course_id']} | {data['asset_type']} {data['asset_id']} | {data['matched_occurrences']} occurrence(s)"]
        for node in data['module_sequence']:
            for key in ('prev', 'current', 'next'):
                item = node[key]
                lines.append(f"{key}: {item['title']} ({item['id']}) | {item['html_url']}" if item else f'{key}: none')
            if node['mastery_path']:
                lines.append('Mastery-path metadata is reported; see JSON. No choice was made.')
        if data['at_native_limit']:
            lines.append('At the native ten-occurrence limit; additional occurrences may exist.')
        return '\n'.join([*lines, data['note']])
    if isinstance(data, dict) and 'module_item' in data and not data.get('dry_run'):
        item = data['module_item']
        lines = [f"Course {data['course_id']} module {data['module']['id']} item {item['id']}",
                 f"{item['title']} | {item['type']} | {item['completion']}", item['html_url']]
        if item['locked_for_user']:
            lines.append('Content is locked for this user; no content was opened.')
        if data.get('event_acknowledged'):
            lines.append('Native event acknowledged; requirement state ' +
                         ('verified.' if data['requirement_status_verified'] is True else 'not verifiable for this read event.'))
        return '\n'.join([*lines, data['note']])
    if isinstance(data, dict) and 'scheduled_page' in data:
        page = data['scheduled_page']
        date = page['publish_at'] or 'cancelled'
        return (f"Course {data['course_id']} page {page['page_id']} | publication date {date} | draft\n"
                f"{page['title']}\n{page['html_url']}\n{data['note']}")
    if isinstance(data, dict) and 'copied_page' in data:
        row = data['copied_page']
        lines = [f"Course {data['course_id']} page {data['source_page_id']} copied to new draft {row['page_id']}",
                 row['title'], row['html_url']]
        if not data['content_matches_source']:
            lines.append('Stored content differs from the source; inspect Canvas and JSON before using the copy.')
        if data['copied_assignment']:
            lines.append(f"Linked assignment copied to {data['copied_assignment']['id']}; exact source lineage verified.")
        if data['assignment_configuration_changed_fields']:
            lines.append('Assignment configuration differs: ' + ', '.join(data['assignment_configuration_changed_fields']))
        if data['assignment_configuration_unknown_fields']:
            lines.append(f"{len(data['assignment_configuration_unknown_fields'])} selected assignment configuration fields were not comparable; see JSON.")
        return '\n'.join([*lines, data['note']])
    if isinstance(data, dict) and 'deleted_page' in data:
        page = data['deleted_page']
        lines = [f"Shared {data['context_type']} page {page['page_id']} deleted | {page['title']}",
                 f"Removed from page inventory; exact-ID read returned {data['exact_id_read_status']}."]
        if data['original_url_resolution']['status'] == 'resolves_to_another_page':
            lines.append(f"The old URL now resolves to page {data['original_url_resolution']['page_id']}; that page was not deleted.")
        if data['linked_assignment_id'] is not None:
            lines.append(f"Linked wiki assignment {data['linked_assignment_id']} independently returned 404.")
        return '\n'.join([*lines, data['note']])
    if isinstance(data, dict) and 'restored_page' in data:
        row = data['restored_page']
        lines = [f"Shared {data['context_type']} page {row['page_id']} restored from revision {data['selected_revision_id']}",
                 f"{row['title']} | current revision {data['current_revision_id']}", row['html_url']]
        if data['html_matches_revision'] is False or data['url_matches_revision'] is False:
            lines.append('Stored HTML/URL differs from the historical revision; inspect Canvas and JSON.')
        if data['front_page_deselected']:
            lines.append('This page is no longer the front page. No automatic repair was requested.')
        return '\n'.join([*lines, data['note']])
    if isinstance(data, dict) and ('page_revisions' in data or 'page_revision' in data):
        lines = [f"{data['context_type'].title()} {data[data['context_type'] + '_id']} page {data['page']['page_id']} revision metadata"]
        for row in data.get('page_revisions', [data.get('page_revision')]):
            lines.append(f"{row['revision_id']} | {row['updated_at']}" + (' | latest' if row['latest'] else ''))
            if row.get('edited_by'):
                actor = row['edited_by']
                lines.append(f"  editor {actor['id']} | {actor.get('display_name') or actor.get('name') or '(name unavailable)'}")
        if data.get('page_revision', {}).get('body') is not None:
            lines.append('Content included in JSON only; inspect it before restoring.')
        return '\n'.join([*lines, data['note']])
    if isinstance(data, dict) and 'shared_page' in data:
        row = data['shared_page']
        status = 'created' if data['created'] else 'edited'
        body = ('\nStored HTML differs from input; inspect JSON and the page in Canvas.'
                if data['html_matches_request'] is False else '')
        return (f"Shared {data['context_type']} {data[data['context_type'] + '_id']} page {row['page_id']} {status}\n"
                f"{row['title']} | {row['url']} | {'published' if row['published'] else 'draft'}\n"
                f"{row['html_url']}\n"
                f"Acknowledgement matches separate readback.{body}\n{data['note']}")
    if isinstance(data, dict) and 'team_reservations' in data and not data.get('dry_run'):
        team, group = data['team'], data['appointment_group']
        lines = [f"Team {team['id']} | {team.get('name') or '(unnamed)'} | Scheduler group {group['id']}"]
        lines.extend(f"  team reservation {row['id']} | slot {row['parent_event_id']} | "
                     f"{row.get('start_at') or 'undated'} to {row.get('end_at') or 'unknown'}"
                     for row in data['team_reservations'])
        if not data['team_reservations']:
            lines.append('No active reservations returned for this team and Scheduler group.')
        lines.append(data['note'])
        return '\n'.join(lines)
    if isinstance(data, dict) and ('appointment_groups' in data or 'appointment_group' in data) and not data.get('dry_run'):
        groups = data.get('appointment_groups', [data.get('appointment_group')])
        lines = ['Native Canvas Scheduler']
        for group in groups:
            lines.append(f"{group['id']} | {group.get('title') or '(untitled)'} | {group['participant_type']} booking")
            for slot in group.get('appointments', []):
                own = 'reserved by you' if slot.get('reserved') is True else 'not reserved by you' if slot.get('reserved') is False else 'own status unknown'
                count = slot.get('available_slots')
                available = f'{count} available' if count is not None else 'capacity count not reported'
                lines.append(f"  slot {slot['id']} | {slot.get('start_at') or 'undated'} to {slot.get('end_at') or 'unknown'} | {own} | {available}")
            for reservation in group.get('reserved_times') or []:
                lines.append(f"  own reservation {reservation['id']} | {reservation.get('start_at') or 'undated'} to {reservation.get('end_at') or 'unknown'}")
        if not groups:
            lines.append('No groups returned within the selected native scope.')
        lines.append(data['note'])
        return '\n'.join(lines)
    if isinstance(data, dict) and 'appointment_reservation' in data:
        row = data['appointment_reservation']
        owner = f"Team {data['team']['id']} Scheduler" if 'team' in data else 'Own Scheduler'
        return (f"{owner} reservation {row['id']} | group {row['appointment_group_id']} | slot {row['parent_event_id']} | "
                f"{'cancelled' if data['cancelled'] else 'reserved'}\n{row.get('start_at') or 'undated'} to {row.get('end_at') or 'unknown'}\n{data['note']}")
    if isinstance(data, dict) and 'help_text' in data:
        return f"{data['safety']}\n\n{data['help_text'].rstrip()}"
    if isinstance(data, dict) and 'schema_version' in data and 'commands' in data:
        lines = [f"Canvas CLI parser schema v{data['schema_version']} (JSON has full argument details)"]
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
    if isinstance(data, dict) and 'permissions' in data and 'context_type' in data and not data.get('dry_run'):
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
    if isinstance(data, dict) and 'channel_change' in data:
        row = data['channel_change']
        return (f"Own channel {row['id']} | {row['type']} | {row['workflow_state']} | "
                f"{'removed' if data['deleted'] else 'added or reactivated'}\n{data['note']}")
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
        lines.append(f"Viewer {data['user_id']}; origin {data['origin']}; course snapshots are account-separated.")
        if data['baseline']:
            lines.append('Baseline created; no earlier snapshot to compare.')
        else:
            lines.extend(_diff_lines(data['diff']))
        return '\n'.join(lines)
    if isinstance(data, dict) and all(key in data for key in
                                       ('course_changed_fields', 'changes', 'observed_changes', 'skipped',
                                        'viewer_identity_verified', 'viewer_note')):
        viewer = str(data['viewer_user_id']) if data['viewer_identity_verified'] else 'unverified'
        lines = [f"Snapshot diff: course {data['course_id']}; viewer {viewer}; origin {data['origin']}",
                 f"{data.get('older_captured_at') or 'unknown date'} → "
                 f"{data.get('newer_captured_at') or 'unknown date'}"]
        lines.extend(_diff_lines(data))
        lines.append(data['viewer_note'])
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
