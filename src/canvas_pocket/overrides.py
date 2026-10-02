"""Account-bound planner checkbox/visibility controls, never assessment attempts."""

from .client import CanvasError
from .planner import items
from .writes import account, check_flags, confirmed, digest

TYPE_NAMES = {'announcement': 'Announcement', 'assignment': 'Assignment',
              'discussion_topic': 'DiscussionTopic', 'quiz': 'Quizzes::Quiz',
              'wiki_page': 'WikiPage', 'planner_note': 'PlannerNote',
              'calendar_event': 'CalendarEvent', 'assessment_request': 'AssessmentRequest',
              'sub_assignment': 'SubAssignment', 'peer_review_sub_assignment': 'PeerReviewSubAssignment'}
FIELDS = ('id', 'user_id', 'plannable_type', 'plannable_id', 'assignment_id',
          'marked_complete', 'dismissed', 'workflow_state', 'updated_at', 'deleted_at')
EFFECT = ('Changes personal planner completion/visibility, not an assignment submission or grade. '
          'For course content, Canvas may also sync a module mark-done requirement. '
          'This does not prove assessed work is complete.')


def kind(value):
    if not isinstance(value, str):
        return None
    if value in TYPE_NAMES:
        return value
    return next((key for key, name in TYPE_NAMES.items() if value == name), None)


def validate(record, identity, expected_id=None):
    if (not isinstance(record, dict) or type(record.get('id')) is not int or record['id'] < 1 or
            (expected_id is not None and str(record['id']) != expected_id) or
            type(record.get('user_id')) is not int or record['user_id'] != identity['user_id'] or
            type(record.get('plannable_id')) is not int or record['plannable_id'] < 1 or
            not isinstance(record.get('plannable_type'), str) or not kind(record['plannable_type']) or
            any(type(record.get(flag)) is not bool for flag in ('marked_complete', 'dismissed'))):
        raise CanvasError('Canvas did not identify a valid planner override owned by this user')
    return record


def flags(marked_complete, dismissed):
    changes = {}
    for key, value in (('marked_complete', marked_complete), ('dismissed', dismissed)):
        if value is not None:
            if type(value) is not bool:
                raise CanvasError('Planner completion/dismissal values must be true or false')
            changes[key] = value
    if not changes:
        raise CanvasError('Choose --complete/--no-complete or --dismiss/--no-dismiss')
    return changes


def acknowledge(item_type, allow_module_progress):
    if item_type not in ('planner_note', 'calendar_event') and not allow_module_progress:
        raise CanvasError('Course-content planner writes may change module mark-done status. '
                          'Review this effect and add --allow-module-progress to the preview command.')


def read(client, override_id):
    identity = account(client)
    record, _ = client.request(f'/api/v1/planner/overrides/{override_id}')
    validate(record, identity, override_id)
    return {key: record.get(key) for key in FIELDS}


def result(record, identity, target_type, target_id, changes=None, override_id=None, delete=False):
    try:
        validate(record, identity, override_id)
        same_target = kind(record['plannable_type']) == target_type and record['plannable_id'] == int(target_id)
        # Canvas normalizes quiz/discussion/page assignments to their linked planner object.
        normalized_assignment = (override_id is None and target_type == 'assignment' and
                                 kind(record['plannable_type']) in ('quiz', 'discussion_topic', 'wiki_page') and
                                 type(record.get('assignment_id')) is int and record['assignment_id'] == int(target_id))
        if not same_target and not normalized_assignment:
            raise CanvasError('Different planner target')
        if delete:
            if record.get('workflow_state') != 'deleted' and not record.get('deleted_at'):
                raise CanvasError('Deletion not confirmed')
        elif (record.get('workflow_state') not in ('active', 'published') or
              any(record.get(flag) is not value for flag, value in changes.items())):
            raise CanvasError('Planner changes not confirmed')
    except CanvasError:
        raise CanvasError('Planner write outcome uncertain; inspect planner-overrides before repeating it') from None
    return {'planner_override': {key: record.get(key) for key in FIELDS},
            'note': ('Removed only the override, not its assignment/task. This does not undo prior module progress.'
                     if delete else EFFECT)}


def create(client, item_type, item_id, max_pages, marked_complete=None, dismissed=None,
           start=None, end=None, allow_module_progress=False, yes=False, confirm=None):
    check_flags(yes, confirm)
    if not isinstance(item_type, str) or item_type not in TYPE_NAMES:
        raise CanvasError('Unsupported planner item type')
    if not isinstance(item_id, str) or not item_id.isdecimal() or int(item_id) < 1:
        raise CanvasError('Expected a positive planner item ID')
    changes = flags(marked_complete, dismissed)
    acknowledge(item_type, allow_module_progress)
    identity = account(client)
    existing = client.list('/api/v1/planner/overrides?per_page=100', max_pages)
    for row in existing:
        validate(row, identity)
        if (kind(row['plannable_type']) == item_type and str(row['plannable_id']) == item_id or
                item_type == 'assignment' and type(row.get('assignment_id')) is int and
                row['assignment_id'] == int(item_id)):
            raise CanvasError(f"A planner override already exists; use planner-override-edit {row['id']} instead")
    feed = items(client, max_pages, start, end)
    matches = [row for row in feed['items'] if row.get('plannable_type') == item_type and
               type(row.get('plannable_id')) is int and str(row['plannable_id']) == item_id]
    if len(matches) != 1:
        raise CanvasError('Item was not uniquely identified in your planner window. Check planner and --start/--end; no write made.')
    target = matches[0]
    content = target.get('plannable') or {}
    if (target.get('planner_override') or any(row.get('published') is False or
            row.get('hidden_for_user') or row.get('locked_for_user') or
            row.get('workflow_state') in ('unpublished', 'deleted') for row in (target, content))):
        raise CanvasError('Item already has an override or is unpublished, hidden, locked or deleted')
    body = {'plannable_type': item_type, 'plannable_id': int(item_id),
            'marked_complete': changes.get('marked_complete', False), 'dismissed': changes.get('dismissed', False)}
    preview = {**identity, 'method': 'POST', 'route': '/api/v1/planner/overrides', 'body': body,
               'planner_window': feed['planner_window'], 'source_digest': digest(target),
               'target': {'type': item_type, 'id': int(item_id), 'course_id': target.get('course_id'),
                          'title': content.get('title') or content.get('name'),
                          'date': target.get('plannable_date')},
               'module_progress_acknowledged': bool(allow_module_progress), 'effect': EFFECT}
    written = confirmed(client, preview, yes, confirm)
    return result(written, identity, item_type, item_id,
                  {key: body[key] for key in ('marked_complete', 'dismissed')}) if yes else written


def change(client, override_id, marked_complete=None, dismissed=None, delete=False,
           allow_module_progress=False, yes=False, confirm=None):
    check_flags(yes, confirm)
    if delete:
        if marked_complete is not None or dismissed is not None:
            raise CanvasError('Override removal cannot also edit checkboxes')
        changes = {}
    else:
        changes = flags(marked_complete, dismissed)
    identity = account(client)
    route = f'/api/v1/planner/overrides/{override_id}'
    current, _ = client.request(route)
    validate(current, identity, override_id)
    if current.get('deleted_at') or current.get('workflow_state') not in ('active', 'published'):
        raise CanvasError('This override is deleted or unpublished; refusing another mutation')
    item_type = kind(current['plannable_type'])
    if not delete:
        acknowledge(item_type, allow_module_progress)
        # Canvas resets omitted fields to false rather than treating them as unchanged.
        changes = {**{key: current[key] for key in ('marked_complete', 'dismissed')}, **changes}
    preview = {**identity, 'method': 'DELETE' if delete else 'PUT', 'route': route,
               'before': {key: current.get(key) for key in FIELDS},
               'body': None if delete else changes,
               'module_progress_acknowledged': bool(allow_module_progress),
               'effect': 'Removes only the personal override, not its assignment/task or prior module progress.' if delete else EFFECT}
    written = confirmed(client, preview, yes, confirm)
    return result(written, identity, item_type, str(current['plannable_id']), changes,
                  override_id, delete) if yes else written
