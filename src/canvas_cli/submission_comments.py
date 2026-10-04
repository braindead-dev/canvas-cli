"""Native own comment drafts, with own-author pagination and independent readback."""

from .client import CanvasError
from .group_content import _number
from .own_submission import ASSIGNMENT_FIELDS, SUBMISSION_FIELDS, context
from .snapshot import redact
from .writes import account, check_flags, digest, review

_COMMENT = ('_id submissionId author { _id } assignment { _id courseId } course { _id } '
            'draft attempt createdAt updatedAt publishable provisional comment htmlComment mediaCommentId attachments { _id }')
_ACK = '_id submissionId author { _id } draft attempt'
_READ = ('query CanvasOwnSubmissionComments($assignmentId: ID!, $userId: ID!, $attempt: Int, $after: String) { '
         'assignment(id: $assignmentId) { ' + ASSIGNMENT_FIELDS + ' } '
         'submission(assignmentId: $assignmentId, userId: $userId) { ' + SUBMISSION_FIELDS + ' '
         'commentsConnection(first: 50, after: $after, filter: {allComments: false, forAttempt: $attempt, peerReview: true}, '
         'includeDraftComments: true, includeDraftsFromOthers: false, includeProvisionalComments: false) { '
         'nodes { ' + _COMMENT + ' } pageInfo { hasNextPage endCursor } } } }')
_CREATE = ('mutation CanvasCommentDraftCreate($input: CreateSubmissionCommentInput!) { '
           'createSubmissionComment(input: $input) { errors { attribute } submissionComment { ' + _ACK + ' } } }')
_PUBLISH = ('mutation CanvasCommentDraftPublish($input: PostDraftSubmissionCommentInput!) { '
            'postDraftSubmissionComment(input: $input) { submissionComment { ' + _ACK + ' } } }')
_DELETE = ('mutation CanvasCommentDraftDelete($input: DeleteSubmissionCommentInput!) { '
           'deleteSubmissionComment(input: $input) { submissionComment { ' + _ACK + ' } } }')
_NOTE = ('Own-author comments only, not grader/peer feedback. Native first-attempt filtering combines attempts nil/0/1. '
         'No peer-review allocation, read-marker query, final submission, quiz attempt or annotation initialization. '
         'GraphQL metadata avoids the assignment REST access event. Rendered HTML/text and attachment associations '
         'are not raw storage proof. Confirmation is not an atomic lock. No automatic retries or rollback.')
_EFFECT = ('Native comment callbacks remain active: creation marks the returned new comment read and group creation '
           'can create linked comments/submission records for group members. Publishing can notify viewers and publish '
           'linked group drafts; instructor/admin authors may also trigger grade posting. Deleting can remove linked '
           'group copies and refresh submission comment read state. Saving media can request captions. Hidden group '
           'copies, notifications, read state, captions, moderated grader-slot allocation and grade-posting effects '
           'are not independently verified.')
_UNCERTAIN = ('The comment operation outcome is unverified; it may have applied, including partial group effects. '
              'No private response was logged. Inspect Canvas before repeating. No automatic retries.')


def _attempt(value, current):
    selected = current if value is None else value
    if type(selected) is not int or selected < 0 or selected > max(current, 1):
        raise CanvasError('Choose an existing nonnegative comment attempt; native attempts 0 and 1 share a bucket')
    return selected


def _comment(row, state, attempt):
    if not isinstance(row, dict) or any(key not in row for key in (
            '_id', 'submissionId', 'author', 'assignment', 'course', 'draft', 'attempt', 'createdAt', 'updatedAt',
            'publishable', 'provisional', 'comment', 'htmlComment', 'mediaCommentId', 'attachments')):
        raise CanvasError('Canvas omitted selected own comment metadata')
    if (row['author'] != {'_id': str(state['user_id'])} or row['submissionId'] != state['submission']['id']
            or row['assignment'] != {'_id': state['assignment_id'], 'courseId': state['course_id']}
            or row['course'] != {'_id': state['course_id']}):
        raise CanvasError('Canvas returned a foreign or anonymously hidden comment owner/submission/assignment/course')
    if (type(row['attempt']) is not int or row['attempt'] < 0
            or row['attempt'] not in ((0, 1) if attempt <= 1 else (attempt,))):
        raise CanvasError('Canvas returned a different comment attempt')
    if any(type(row[key]) is not bool for key in ('draft', 'publishable', 'provisional')) or row['provisional']:
        raise CanvasError('Canvas returned unavailable or provisional comment metadata')
    for key in ('createdAt', 'updatedAt', 'comment', 'htmlComment', 'mediaCommentId'):
        if row[key] is not None and not isinstance(row[key], str) or key == 'createdAt' and not row[key]:
            raise CanvasError('Canvas returned malformed comment metadata; no private response was logged')
    if not isinstance(row['attachments'], list):
        raise CanvasError('Canvas returned unavailable comment attachments')
    files = [_number(item.get('_id')) if isinstance(item, dict) else _number(None) for item in row['attachments']]
    if len(set(files)) != len(files):
        raise CanvasError('Canvas returned duplicate comment attachment IDs')
    return {'id': _number(row['_id']), 'attempt': row['attempt'], 'draft': row['draft'], 'publishable': row['publishable'],
            'created_at': row['createdAt'], 'updated_at': row['updatedAt'], 'file_ids': sorted(files, key=int),
            'media_id': row['mediaCommentId'], 'text': row['comment'], 'html': row['htmlComment']}


def _inspect(client, course_id, assignment_id, *, attempt=None, all_attempts=False, max_pages=100):
    _number(course_id)
    _number(assignment_id)
    if (type(max_pages) is not int or max_pages < 1 or all_attempts and attempt is not None
            or attempt is not None and (type(attempt) is not int or attempt < 0)):
        raise CanvasError('Use a positive page cap and either --attempt or --all-attempts, not both')
    identity, baseline, comments = account(client), None, {}
    pending, selected_attempts, pages, cursor, cursors = [attempt], [], 0, None, set()
    while pending:
        if pages >= max_pages:
            raise CanvasError('Own comment inventory exceeded the page cap; completeness is unknown, no mutation sent')
        selected = pending[0]
        data = client.graphql(_READ, {'assignmentId': assignment_id, 'userId': str(identity['user_id']),
                                     'attempt': selected, 'after': cursor}, 'CanvasOwnSubmissionComments')
        pages += 1
        state = context(data, identity, course_id, assignment_id)
        if baseline is None:
            baseline = state
            if state['submission'] is not None:
                selected = _attempt(selected, state['submission']['attempt'])
                pending[0] = selected
                if all_attempts:
                    if max(state['submission']['attempt'], 1) > max_pages:
                        raise CanvasError('Own comment attempt inventory exceeds the page cap; no mutation sent')
                    pending += [value for value in range(1, max(state['submission']['attempt'], 1) + 1)
                                if value != max(selected, 1)]
        elif state != baseline:
            raise CanvasError('Own comment account/assignment/submission changed during pagination; no mutation sent')
        if state['submission'] is None:
            break
        connection = data['submission'].get('commentsConnection')
        if (not isinstance(connection, dict) or not isinstance(connection.get('nodes'), list)
                or not isinstance(connection.get('pageInfo'), dict)):
            raise CanvasError('Canvas returned unavailable own comment inventory')
        for row in connection['nodes']:
            item = _comment(row, state, selected)
            if item['id'] in comments:
                raise CanvasError('Canvas returned duplicate own comment IDs; inventory is not complete')
            comments[item['id']] = item
        page = connection['pageInfo']
        if (type(page.get('hasNextPage')) is not bool or 'endCursor' not in page
                or page['endCursor'] is not None and not isinstance(page['endCursor'], str)):
            raise CanvasError('Canvas returned malformed comment pagination')
        if page['hasNextPage']:
            if not page['endCursor'] or page['endCursor'] in cursors or not connection['nodes']:
                raise CanvasError('Canvas returned looping or empty comment pagination')
            cursor = page['endCursor']
            cursors.add(cursor)
        else:
            selected_attempts.append(pending.pop(0))
            cursor, cursors = None, set()
    if account(client) != identity:
        raise CanvasError('Signed-in account changed during comment inspection; no mutation was sent')
    return {**baseline, 'selected_attempts': sorted(selected_attempts), 'comments': comments,
            'inventory_status': 'unknown_no_accessible_submission' if baseline['submission'] is None
            else 'complete_reported_own_all_attempts' if all_attempts else 'complete_reported_own_selected_attempt'}


def _projection(state, include_content=False):
    items = []
    for identifier in sorted(state['comments'], key=int):
        item = state['comments'][identifier]
        selected = {key: value for key, value in item.items() if key not in ('text', 'html')}
        selected['content_fingerprints'] = {key: digest(item[key]) for key in ('text', 'html')}
        if include_content:
            selected['content'] = redact({key: item[key] for key in ('text', 'html')})
        items.append(selected)
    return {**{key: value for key, value in state.items() if key != 'comments'}, 'comments': items, 'note': _NOTE}


def read(client, course_id, assignment_id, *, attempt=None, all_attempts=False, include_content=False, max_pages=100):
    return _projection(_inspect(client, course_id, assignment_id, attempt=attempt, all_attempts=all_attempts, max_pages=max_pages),
                       include_content)


def _preflight(client, course_id, assignment_id, attempt, max_pages, acknowledge):
    if not acknowledge:
        raise CanvasError('Use --acknowledge-native-effects even for preview: ' + _EFFECT)
    state = _inspect(client, course_id, assignment_id, attempt=attempt, max_pages=max_pages)
    if state['submission'] is None:
        raise CanvasError('No accessible existing own submission; the CLI will not submit work or start an attempt to create one')
    if state['assignment_policy']['published'] is not True:
        raise CanvasError('Assignment publication is unavailable or unpublished; refusing comment mutation')
    return state


def _preview(state, method, route, body, effect):
    return {**_projection(state), 'reported_state_fingerprint': digest(state), 'method': method, 'route': route,
            'body': body, 'effect': effect + ' ' + _EFFECT}


def _execute(client, preview, field=None):
    try:
        if field is None:
            result, _ = client.request(preview['route'], preview['method'], preview['body'])
            if not isinstance(result, dict) or type(result.get('id')) is not int or result['id'] < 1:
                raise CanvasError(_UNCERTAIN)
            return str(result['id'])
        body = preview['body']
        data = client.graphql(body['query'], body['variables'], body['operationName'])
        ack = data.get(field)
        if (not isinstance(ack, dict) or ack.get('errors') not in (None, [])
                or field == 'createSubmissionComment' and 'errors' not in ack):
            raise CanvasError(_UNCERTAIN)
        row = ack.get('submissionComment')
        if not isinstance(row, dict):
            raise CanvasError(_UNCERTAIN)
        _number(row.get('_id'))
        _number(row.get('submissionId'))
        if (row.get('author') != {'_id': str(preview['user_id'])} or type(row.get('draft')) is not bool
                or type(row.get('attempt')) is not int or row['attempt'] < 0):
            raise CanvasError(_UNCERTAIN)
        return row
    except CanvasError as error:
        raise CanvasError(_UNCERTAIN, status=error.status) from None


def _after(client, before, max_pages):
    try:
        after = _inspect(client, before['course_id'], before['assignment_id'], attempt=before['selected_attempts'][0], max_pages=max_pages)
        if {key: value for key, value in after.items() if key != 'comments'} != {key: value for key, value in before.items() if key != 'comments'}:
            raise CanvasError(_UNCERTAIN)
        return after
    except CanvasError:
        raise CanvasError(_UNCERTAIN) from None


def _result(before, after, identifier, *, matches=None):
    old, new = before['comments'], after['comments']
    return {**_projection(after), 'mutation_acknowledged': True, 'own_comment_id': identifier,
            'reported_html_matches_request': matches, 'raw_storage_verified': False, 'final_submission_requested': False,
            'other_observed_comment_changes': sorted((set(old) ^ set(new)) - {identifier}, key=int)
            + sorted((key for key in set(old) & set(new) if key != identifier and old[key] != new[key]), key=int),
            'native_collateral_effects_verified': False, 'note': _NOTE + ' ' + _EFFECT
            + ' Content differences can reflect sanitization, ignored fields, hidden attachments or concurrent changes.'}


def create(client, course_id, assignment_id, message, *, attempt=None, file_ids=None, media_id=None, media_type=None,
           group_comment=False, acknowledge=False, acknowledge_group=False, max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    files = [] if file_ids is None else file_ids
    if (not isinstance(message, str) or not isinstance(files, list) or any(not isinstance(value, str) for value in files)
            or len(files) != len(set(files))
            or media_id is not None and (not isinstance(media_id, str) or not media_id)
            or media_type not in (None, 'audio', 'video') or media_type is not None and media_id is None
            or not message.strip() and not files and media_id is None):
        raise CanvasError('Provide comment text or distinct existing file/media IDs; media type needs a media ID')
    for identifier in files:
        _number(identifier)
    before = _preflight(client, course_id, assignment_id, attempt, max_pages, acknowledge)
    policy = before['assignment_policy']
    group = policy['group_category_id']
    if group is not None:
        _number(group)
        if type(policy['grade_group_students_individually']) is not bool:
            raise CanvasError('Group grading policy is unknown; refusing group comment creation')
    if group_comment and group is None or group is not None and not acknowledge_group:
        raise CanvasError('Group assignments require --acknowledge-group-effects; --group-comment also requires a group assignment')
    grouped = group is not None and (group_comment or not policy['grade_group_students_individually'])
    selected = {'submissionId': before['submission']['id'], 'comment': message, 'attempt': before['selected_attempts'][0],
                'draftComment': True, 'groupComment': group_comment, 'fileIds': sorted(files, key=int)}
    if media_id is not None:
        selected['mediaObjectId'] = media_id
    if media_type is not None:
        selected['mediaObjectType'] = media_type
    body = {'query': _CREATE, 'variables': {'input': selected}, 'operationName': 'CanvasCommentDraftCreate'}
    preview = {**_preview(before, 'POST', '/api/graphql', body, 'Creates a draft comment, not a published message.'),
               'native_group_creation': grouped}
    result = review(preview, yes, confirm)
    if result is not None:
        return result
    ack = _execute(client, preview, 'createSubmissionComment')
    after = _after(client, before, max_pages)
    added = set(after['comments']) - set(before['comments'])
    if len(added) != 1:
        raise CanvasError(_UNCERTAIN)
    identifier = added.pop()
    item = after['comments'][identifier]
    own_ack = ack['_id'] == identifier and ack['submissionId'] == before['submission']['id']
    if (not item['draft'] or not ack['draft'] or ack['attempt'] != item['attempt'] or not own_ack and not grouped
            or ack['_id'] in before['comments']):
        raise CanvasError(_UNCERTAIN)
    return {**_result(before, after, identifier, matches=item['html'] == message),
            'own_draft_presence_verified': True, 'acknowledged_comment_is_own_copy': own_ack,
            'acknowledged_own_copy_lineage_verified': own_ack,
            'reported_file_ids_match_request': item['file_ids'] == selected['fileIds'],
            'reported_media_id_matches_request': item['media_id'] == media_id}


def change(client, course_id, assignment_id, comment_id, action, *, message=None, attempt=None, acknowledge=False,
           max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    _number(comment_id)
    if action not in ('edit', 'publish', 'delete') or action == 'edit' and not isinstance(message, str) or action != 'edit' and message is not None:
        raise CanvasError('Choose edit with explicit text, or publish/delete without replacement text')
    before = _preflight(client, course_id, assignment_id, attempt, max_pages, acknowledge)
    item = before['comments'].get(comment_id)
    if item is None or not item['draft']:
        raise CanvasError('Choose an exact own draft in the selected attempt; published student comments cannot be edited/deleted')
    if action == 'publish' and not item['publishable']:
        raise CanvasError('Canvas did not report this own draft as publishable')
    if action == 'edit':
        route = (f'/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/'
                 f"{before['user_id']}/comments/{comment_id}")
        preview = _preview(before, 'PUT', route, {'comment': message}, 'Edits draft text only; attachment/media associations are retained.')
        field = None
    else:
        document, operation, field = (_PUBLISH, 'CanvasCommentDraftPublish', 'postDraftSubmissionComment') if action == 'publish' else (
            _DELETE, 'CanvasCommentDraftDelete', 'deleteSubmissionComment')
        body = {'query': document, 'variables': {'input': {'submissionCommentId': comment_id}}, 'operationName': operation}
        preview = _preview(before, 'POST', '/api/graphql', body, 'Publishes this draft to native viewers.' if action == 'publish' else
                           'Deletes this draft and potentially linked group copies; no CLI restore.')
    result = review(preview, yes, confirm)
    if result is not None:
        return result
    ack = _execute(client, preview, field)
    if (field is None and ack != comment_id or field is not None and
            (ack['_id'] != comment_id or ack['submissionId'] != before['submission']['id'] or ack['attempt'] != item['attempt']
             or ack['draft'] != (action != 'publish'))):
        raise CanvasError(_UNCERTAIN)
    after = _after(client, before, max_pages)
    observed = after['comments'].get(comment_id)
    if action == 'delete':
        if observed is not None:
            raise CanvasError(_UNCERTAIN)
        return {**_result(before, after, comment_id), 'own_draft_absence_verified': True, 'linked_group_absence_verified': False}
    if observed is None or observed['draft'] != (action == 'edit') or observed['attempt'] != item['attempt']:
        raise CanvasError(_UNCERTAIN)
    return {**_result(before, after, comment_id, matches=observed['html'] == message if action == 'edit' else None),
            'own_comment_state_verified': True,
            'observed_target_changes': [key for key in item if item[key] != observed[key]]}
