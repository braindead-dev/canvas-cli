"""Independent native comment filtering, callbacks and mutation state for synthetic HTTPS."""

import copy

from .appointments import _send

READ = ('query CanvasOwnSubmissionComments($assignmentId: ID!, $userId: ID!, $attempt: Int, $after: String) { '
        'assignment(id: $assignmentId) { _id courseId submissionTypes allowedExtensions published dueAt unlockAt lockAt '
        'updatedAt groupCategoryId gradeGroupStudentsIndividually allowedAttempts state } '
        'submission(assignmentId: $assignmentId, userId: $userId) { _id userId assignmentId '
        'assignment { _id courseId } attempt state submittedAt '
        'commentsConnection(first: 50, after: $after, filter: {allComments: false, forAttempt: $attempt, peerReview: true}, '
        'includeDraftComments: true, includeDraftsFromOthers: false, includeProvisionalComments: false) { '
        'nodes { _id submissionId author { _id } assignment { _id courseId } course { _id } '
        'draft attempt createdAt updatedAt publishable provisional comment htmlComment mediaCommentId attachments { _id } } '
        'pageInfo { hasNextPage endCursor } } } }')
ACK = '_id submissionId author { _id } draft attempt'
CREATE = ('mutation CanvasCommentDraftCreate($input: CreateSubmissionCommentInput!) { '
          'createSubmissionComment(input: $input) { errors { attribute } submissionComment { ' + ACK + ' } } }')
PUBLISH = ('mutation CanvasCommentDraftPublish($input: PostDraftSubmissionCommentInput!) { '
           'postDraftSubmissionComment(input: $input) { submissionComment { ' + ACK + ' } } }')
DELETE = ('mutation CanvasCommentDraftDelete($input: DeleteSubmissionCommentInput!) { '
          'deleteSubmissionComment(input: $input) { submissionComment { ' + ACK + ' } } }')


def record(identifier='961', *, attempt=2, draft=True, author='7', submission='741', linked=None):
    return {'_id': identifier, 'submissionId': submission, 'author': {'_id': author},
            'assignment': {'_id': '941', 'courseId': '141'}, 'course': {'_id': '141'},
            'draft': draft, 'attempt': attempt, 'createdAt': '2026-10-04T00:00:00Z', 'updatedAt': '2026-10-04T00:00:00Z',
            'publishable': draft and author == '7', 'provisional': False,
            'comment': 'synthetic-private-own-comment', 'htmlComment': '<p>synthetic-private-own-comment</p>',
            'mediaCommentId': None, 'attachments': [], '_linked': linked}


def initialize(state, *, enabled=False):
    state.comments_enabled = enabled
    state.comments_assignment = {'_id': '941', 'courseId': '141', 'submissionTypes': ['online_upload'],
                                 'allowedExtensions': None, 'published': True, 'dueAt': None, 'unlockAt': None, 'lockAt': None,
                                 'updatedAt': None, 'groupCategoryId': None, 'gradeGroupStudentsIndividually': False,
                                 'allowedAttempts': None, 'state': 'published'}
    state.comments_submission = {'_id': '741', 'userId': '7', 'assignmentId': '941', 'assignment': {'_id': '941', 'courseId': '141'},
                                 'attempt': 2, 'state': 'submitted', 'submittedAt': '2026-10-03T00:00:00Z'}
    state.comments_rows = [record(), record('962', attempt=0), record('963', draft=False),
                           record('964', author='8'), record('965', submission='742', linked='old-group')]
    state.comments_queries = []
    state.comments_mutations = []
    state.comments_read_events = []
    state.comments_group_callbacks = []
    state.comments_assignment_views = []
    state.comments_viewer = 7
    state.comments_page_size = 50
    state.comments_written = False
    state.comments_denied = False
    state.comments_read_denied = False
    state.comments_ignore = False
    state.comments_ack = None
    state.comments_normalize = False
    state.comments_foreign_group_ack = False
    state.comments_advance = state.comments_switch = state.comments_policy_after = state.comments_read_after = False
    state.comments_query_patch = None
    state.comments_page_patch = None
    state.comments_error_status = None


def read(state, handler):
    if not state.comments_enabled:
        return False
    if handler.path == '/api/v1/users/self/profile':
        _send(handler, {'id': 8 if state.comments_written and state.comments_switch else state.comments_viewer,
                        'email': 'synthetic-private@example.edu'})
        return True
    if handler.path == '/api/v1/courses/141/assignments/941':
        state.comments_assignment_views.append('module-access')
        _send(handler, {'id': 941, 'course_id': 141})
        return True
    return False


def _row(row):
    return {key: value for key, value in copy.deepcopy(row).items() if not key.startswith('_linked')}


def _ack(row):
    return {key: copy.deepcopy(row[key]) for key in ('_id', 'submissionId', 'author', 'draft', 'attempt')}


def execute(state, handler, body):
    if not state.comments_enabled:
        return False
    operation = body.get('operationName')
    if handler.path == '/api/graphql' and operation == 'CanvasOwnSubmissionComments':
        state.comments_queries.append(copy.deepcopy(body))
        variables = body.get('variables', {})
        if body.get('query') != READ or variables.get('assignmentId') != '941' or variables.get('userId') != str(state.comments_viewer):
            _send(handler, {'errors': [{'message': 'synthetic-private-unsafe-query'}]})
            return True
        if state.comments_read_denied or state.comments_written and state.comments_read_after:
            _send(handler, {'errors': [{'message': 'synthetic-private-read-denied'}]})
            return True
        submission = copy.deepcopy(state.comments_submission)
        assignment = copy.deepcopy(state.comments_assignment)
        if state.comments_written and state.comments_policy_after:
            assignment['published'] = False
        if submission is not None:
            selected = variables['attempt'] if variables['attempt'] is not None else submission['attempt']
            attempts = (0, 1) if selected <= 1 else (selected,)
            # Native peerReview author filtering only works when allComments is false.
            rows = [_row(row) for row in state.comments_rows if row['submissionId'] == submission['_id']
                    and row['author'] == {'_id': str(state.comments_viewer)} and row['attempt'] in attempts and not row['provisional']]
            offset = 0 if variables['after'] is None else int(variables['after'].removeprefix('c:'))
            batch = rows[offset:offset + state.comments_page_size]
            has_next = offset + len(batch) < len(rows)
            page = {'hasNextPage': has_next, 'endCursor': f'c:{offset + len(batch)}' if batch else None}
            if state.comments_page_patch:
                page.update(state.comments_page_patch)
            submission['commentsConnection'] = {'nodes': batch, 'pageInfo': page}
            if state.comments_query_patch:
                submission.update(copy.deepcopy(state.comments_query_patch))
        _send(handler, {'data': {'assignment': assignment, 'submission': submission}})
        return True
    edit_path = '/api/v1/courses/141/assignments/941/submissions/7/comments/'
    editing = handler.command == 'PUT' and handler.path.startswith(edit_path)
    if not editing and (handler.path != '/api/graphql' or operation not in (
            'CanvasCommentDraftCreate', 'CanvasCommentDraftPublish', 'CanvasCommentDraftDelete')):
        return False
    state.comments_mutations.append((handler.command, handler.path, copy.deepcopy(body)))
    state.comments_written = True
    if state.comments_denied or state.comments_error_status:
        _send(handler, {'errors': [{'message': 'synthetic-private-mutation-denied'}]}, state.comments_error_status or 403)
        return True
    if editing:
        identifier = handler.path.removeprefix(edit_path)
        selected = {'submissionCommentId': identifier}
    else:
        document = {'CanvasCommentDraftCreate': CREATE, 'CanvasCommentDraftPublish': PUBLISH, 'CanvasCommentDraftDelete': DELETE}[operation]
        if body.get('query') != document or set(body.get('variables', {})) != {'input'}:
            _send(handler, {'errors': [{'message': 'synthetic-private-unsafe-mutation'}]})
            return True
        selected = body['variables']['input']
        identifier = selected.get('submissionCommentId')
    if operation == 'CanvasCommentDraftCreate':
        if (selected.get('submissionId') != '741' or selected.get('draftComment') is not True
                or set(selected) - {'submissionId', 'comment', 'attempt', 'draftComment', 'groupComment', 'fileIds', 'mediaObjectId', 'mediaObjectType'}):
            _send(handler, {'errors': [{'message': 'synthetic-private-unsafe-create'}]})
            return True
        row = record(str(970 + len(state.comments_mutations)), attempt=selected['attempt'])
        row.update(comment=selected['comment'], htmlComment=selected['comment'], mediaCommentId=selected.get('mediaObjectId'),
                   attachments=[{'_id': value} for value in selected['fileIds']])
        grouped = state.comments_assignment['groupCategoryId'] is not None and (
            selected['groupComment'] or not state.comments_assignment['gradeGroupStudentsIndividually'])
        if grouped:
            row['_linked'] = 'new-group'
        if not state.comments_ignore:
            state.comments_rows.append(row)
            if grouped:
                peer = {**copy.deepcopy(row), '_id': '981', 'submissionId': '742'}
                state.comments_rows.append(peer)
                state.comments_group_callbacks.append('create-group-copy')
        state.comments_read_events.append('981' if grouped and state.comments_foreign_group_ack else row['_id'])
        ack_row = {**row, '_id': '981', 'submissionId': '742'} if grouped and state.comments_foreign_group_ack else row
        if state.comments_normalize:
            row.update(htmlComment='<p>normalized synthetic comment</p>', attachments=[], mediaCommentId=None)
        response = {'data': {'createSubmissionComment': {'errors': [], 'submissionComment': _ack(ack_row)}}}
    else:
        row = next((row for row in state.comments_rows if row['_id'] == identifier), None)
        if row is None or not row['draft'] or row['author'] != {'_id': '7'}:
            _send(handler, {'errors': [{'message': 'synthetic-private-no-native-draft-permission'}]}, 403)
            return True
        if editing:
            if set(body) != {'comment'}:
                _send(handler, {'errors': [{'message': 'synthetic-private-unsafe-edit'}]})
                return True
            if not state.comments_ignore:
                row.update(comment=body['comment'], htmlComment=body['comment'], updatedAt='2026-10-04T01:00:00Z')
                if state.comments_normalize:
                    row['htmlComment'] = '<p>normalized synthetic comment</p>'
            response = {'id': int(identifier), 'comment': 'synthetic-private-rest-ack'}
        else:
            deleting = operation == 'CanvasCommentDraftDelete'
            if not state.comments_ignore:
                if row['_linked'] is not None:
                    linked = [copy for copy in state.comments_rows if copy['_linked'] == row['_linked']]
                    state.comments_group_callbacks.append('delete-group-copies' if deleting else 'publish-group-copies')
                else:
                    linked = [row]
                if deleting:
                    state.comments_rows = [copy for copy in state.comments_rows if copy not in linked]
                else:
                    for copy_row in linked:
                        copy_row.update(draft=False, publishable=False)
            response = {'data': {('deleteSubmissionComment' if deleting else 'postDraftSubmissionComment'): {'submissionComment': _ack(row)}}}
    if state.comments_advance:
        state.comments_submission['attempt'] += 1
    if state.comments_ack is not None:
        response = state.comments_ack
    _send(handler, response, state.comments_error_status or 200)
    return True
