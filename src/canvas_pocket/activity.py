"""Own activity notifications: paginated reads and deliberate hiding, never grading."""

from urllib.parse import urlencode

from .client import CanvasError
from .contexts import read_topic
from .snapshot import redact
from .writes import account, check_flags, confirmed, digest


def _number(value):
    if (not isinstance(value, str) or not value.isascii() or not value.isdecimal() or
            int(value) < 1 or str(int(value)) != value):
        raise CanvasError('Expected a positive numeric activity or course ID')
    return value


def _route(course_id=None, active=False, summary=False):
    if course_id is not None:
        _number(course_id)
        if active:
            raise CanvasError('--active applies only to the global activity feed, not a selected course')
        route = f'/api/v1/courses/{course_id}/activity_stream'
    else:
        route = '/api/v1/users/self/activity_stream'
    if summary:
        route += '/summary'
    query = {} if summary else {'per_page': 100}
    if active:
        query['only_active_courses'] = 'true'
    return route + ('?' + urlencode(query) if query else '')


def _records(client, max_pages, course_id=None, active=False):
    rows = client.list(_route(course_id, active), max_pages)
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] < 1 or
                not isinstance(row.get('type'), str) or not row['type'] or
                (row.get('read_state') is not None and type(row['read_state']) is not bool)):
            raise CanvasError('Canvas returned an invalid activity record')
        if row['id'] in seen:
            raise CanvasError('Canvas returned duplicate activity IDs')
        seen.add(row['id'])
        if course_id and row.get('course_id') is not None and str(row['course_id']) != course_id:
            raise CanvasError('Canvas returned activity from another course')
    return rows


def _item(row, include_content=False, topic=None):
    keys = ('id', 'type', 'title', 'created_at', 'updated_at', 'read_state', 'context_type',
            'course_id', 'group_id', 'html_url', 'discussion_topic_id', 'announcement_id',
            'conversation_id', 'message_id', 'submission_id', 'assignment_id',
            'assessment_request_id', 'notification_category', 'web_conference_id', 'collaboration_id',
            'private', 'participant_count', 'require_initial_post', 'user_has_posted')
    result = {key: row[key] for key in keys if key in row}
    if include_content:
        # Some stream records carry cached discussion replies; do not turn this feed
        # into an initial-post bypass. Standalone entry notices lack a topic access check.
        discussion = row['type'] in ('DiscussionTopic', 'Announcement')
        verified = topic is not None
        can_see_entries = verified and topic.get('user_can_see_posts') is not False and (
            topic.get('require_initial_post') is False or topic.get('user_can_see_posts') is True or
            topic.get('user_has_posted') is True)
        if row['type'] == 'DiscussionEntry':
            result['content_withheld'] = 'Open the authorized discussion thread to verify entry access.'
        elif discussion:
            if verified:
                result['message'] = topic.get('message')
                result['prompt_source'] = 'current_topic'
            else:
                result['content_withheld'] = 'Current discussion access could not be verified.'
        elif 'message' in row:
            result['message'] = row['message']
        if discussion:
            if not can_see_entries:
                result['entries_withheld'] = 'Current entry access unconfirmed or initial-post restricted; no cached peer entries exposed.'
            elif 'root_discussion_entries' in row:
                result['root_discussion_entries'] = row['root_discussion_entries']
        elif row['type'] == 'Conversation' and 'latest_messages' in row:
            result['latest_messages'] = row['latest_messages']
        elif row['type'] == 'Submission':
            for key in ('assignment', 'course', 'submission_comments', 'grade', 'score', 'workflow_state'):
                if key in row:
                    result[key] = row[key]
    return redact(result)


def feed(client, max_pages=100, *, course_id=None, active=False, type_filter=None, include_content=False):
    if type(active) is not bool or type(include_content) is not bool:
        raise CanvasError('Activity content and active-course flags must be explicit booleans')
    if type_filter is not None and (not isinstance(type_filter, str) or not type_filter.strip()):
        raise CanvasError('Activity type filter must be a nonempty exact native type')
    rows = _records(client, max_pages, course_id, active)
    selected = [row for row in rows if type_filter is None or row['type'] == type_filter]
    output = []
    for row in selected:
        topic = None
        if include_content and row['type'] in ('DiscussionTopic', 'Announcement'):
            context = row.get('context_type')
            context_id = row.get(f'{context}_id') if context in ('course', 'group') else None
            topic_id = row.get('discussion_topic_id') or row.get('announcement_id')
            if type(context_id) is int and context_id > 0 and type(topic_id) is int and topic_id > 0:
                try:
                    topic = read_topic(client, str(context_id), str(topic_id), context)
                except CanvasError as error:
                    if error.status not in (403, 404):
                        raise
        output.append(_item(row, include_content, topic))
    return {'activity': output,
            'scope': f'course_{course_id}' if course_id else 'own_global', 'only_active_courses': bool(active),
            'endpoint_record_count': len(rows), 'excluded_by_type': len(rows) - len(selected),
            'complete_for_endpoint': True, 'complete_coursework_inventory': False,
            'note': 'GET only; no read markers changed. Activity is a notification feed, not a complete assignment '
                    'or owed-peer-review inventory. Cached bodies and replies may be truncated or outdated.'}


def summary(client, *, course_id=None, active=False):
    if type(active) is not bool:
        raise CanvasError('Active-course flag must be an explicit boolean')
    rows, _ = client.request(_route(course_id, active, True))
    if not isinstance(rows, list):
        raise CanvasError('Canvas returned an invalid activity summary')
    output = []
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get('type'), str) or not row['type'] or
                type(row.get('count')) is not int or row['count'] < 0 or
                type(row.get('unread_count')) is not int or not 0 <= row['unread_count'] <= row['count'] or
                (row.get('notification_category') is not None and not isinstance(row['notification_category'], str))):
            raise CanvasError('Canvas returned invalid activity counts')
        key = (row['type'], row.get('notification_category'))
        if key in seen:
            raise CanvasError('Canvas returned duplicate activity-summary categories')
        seen.add(key)
        output.append({key: row[key] for key in ('type', 'notification_category', 'count', 'unread_count') if key in row})
    return {'activity_summary': output, 'scope': f'course_{course_id}' if course_id else 'own_global',
            'note': 'Native visible-notification counts, not assignments due or proof of coursework completion.'}


def dismiss(client, item_id=None, *, all_items=False, max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    if type(all_items) is not bool:
        raise CanvasError('Hide-all scope must be an explicit boolean')
    if all_items:
        if item_id is not None:
            raise CanvasError('Hide-all cannot combine with one activity ID')
    else:
        _number(item_id)
    identity = account(client)
    rows = _records(client, max_pages)
    selected = rows if all_items else [row for row in rows if str(row['id']) == item_id]
    if not all_items and not selected:
        raise CanvasError('Activity ID is not in your current visible feed; it may already be hidden or expired')
    route = '/api/v1/users/self/activity_stream' + ('' if all_items else f'/{item_id}')
    preview = {**identity, 'method': 'DELETE', 'route': route, 'body': None,
               'visible_items': [_item(row) for row in selected],
               'feed_revision': digest(sorted(selected, key=lambda row: row['id'])),
               'all_items': bool(all_items),
               'effect': ('Hide ALL your stream items, including any outside the current visible feed.' if all_items else
                          'Hide only this notification from your own activity stream.'),
               'warning': 'Underlying discussions, messages, grades and assignments are not deleted or completed. '
                          'Pocket has no restore command. Hidden notifications are not a task-completion mechanism.'}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    if not isinstance(response, dict) or response.get('hidden') is not True:
        raise CanvasError('Activity hiding was not acknowledged; verify Canvas before repeating')
    return {'activity_hidden': {'item_id': int(item_id) if item_id else None, 'all_items': bool(all_items)},
            'acknowledged': True,
            'note': 'Canvas acknowledged the hide request; underlying content and read markers were not changed by Pocket.'}
