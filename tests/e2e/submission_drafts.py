"""Independent native own draft storage, separate from final submission endpoints."""

import copy

from .appointments import _send

READ = ('query CanvasSubmissionDraft($assignmentId: ID!, $userId: ID!) { '
        'assignment(id: $assignmentId) { _id courseId submissionTypes allowedExtensions published dueAt unlockAt lockAt '
        'updatedAt groupCategoryId gradeGroupStudentsIndividually allowedAttempts state } '
        'submission(assignmentId: $assignmentId, userId: $userId) { _id userId assignmentId '
        'assignment { _id courseId } attempt state submittedAt submissionDraft { '
        '_id submissionAttempt activeSubmissionType body(rewriteUrls: false) url attachments { _id } '
        'mediaObject { _id } externalTool { _id } ltiLaunchUrl resourceLinkLookupUuid } } }')
SAVE = ('mutation CanvasSubmissionDraftSave($input: CreateSubmissionDraftInput!) { '
        'createSubmissionDraft(input: $input) { errors { attribute } '
        'submissionDraft { _id submissionAttempt activeSubmissionType } } }')
DELETE = ('mutation CanvasSubmissionDraftDelete($input: DeleteSubmissionDraftInput!) { '
          'deleteSubmissionDraft(input: $input) { errors { attribute } submissionDraftIds } }')


def initialize(state, *, enabled=False):
    state.drafts_enabled = enabled
    state.draft_assignment = {'id': 941, 'course_id': 141, 'published': True, 'locked_for_user': False,
                              'submission_types': ['online_text_entry', 'online_url', 'online_upload', 'media_recording',
                                                   'basic_lti_launch', 'student_annotation'], 'allowed_extensions': ['txt']}
    state.draft_submission = {'_id': '741', 'userId': '7', 'assignmentId': '941', 'assignment': {'_id': '941', 'courseId': '141'},
                              'attempt': 0, 'state': 'unsubmitted', 'submittedAt': None}
    state.draft_next = {'_id': '951', 'submissionAttempt': 1, 'activeSubmissionType': 'online_text_entry',
                        'body': '<p>synthetic-private-draft-body</p>', 'url': 'https://example.edu/private?access_token=synthetic-secret',
                        'attachments': [{'_id': '891'}], 'mediaObject': None, 'externalTool': None,
                        'ltiLaunchUrl': None, 'resourceLinkLookupUuid': None}
    state.draft_history = ['950']
    state.draft_viewer = 7
    state.draft_written = False
    state.draft_mutations = []
    state.draft_can_read = state.draft_can_submit = True
    state.draft_ack = state.draft_readback_patch = None
    state.draft_normalize = state.draft_advance = state.draft_ignore = False
    state.draft_account_after = state.draft_policy_after = state.draft_error_after = False
    state.draft_queries = []
    state.draft_view_events = []
    state.draft_error_status = None


def read(state, handler):
    if not state.drafts_enabled:
        return False
    if handler.path == '/api/v1/users/self/profile':
        _send(handler, {'id': 8 if state.draft_written and state.draft_account_after else state.draft_viewer,
                        'email': 'synthetic-private-student@example.edu'})
        return True
    if handler.path == '/api/v1/courses/141/assignments/941':
        state.draft_view_events.append('assignment-module-read')
        row = copy.deepcopy(state.draft_assignment)
        if state.draft_written and state.draft_policy_after:
            row['locked_for_user'] = True
        _send(handler, row)
        return True
    return False


def execute(state, handler, body):
    if not state.drafts_enabled or handler.path != '/api/graphql':
        return False
    operation, document, variables = body.get('operationName'), body.get('query'), body.get('variables')
    if operation == 'CanvasSubmissionDraft':
        state.draft_queries.append(copy.deepcopy(body))
        if document != READ or variables != {'assignmentId': '941', 'userId': str(state.draft_viewer)}:
            _send(handler, {'errors': [{'message': 'synthetic-private-unexpected-query'}]})
            return True
        if not state.draft_can_read or state.draft_written and state.draft_error_after:
            _send(handler, {'errors': [{'message': 'synthetic-private-read-denied'}]})
            return True
        assignment = {'_id': str(state.draft_assignment['id']), 'courseId': str(state.draft_assignment['course_id']),
                      'submissionTypes': state.draft_assignment['submission_types'], 'allowedExtensions': state.draft_assignment['allowed_extensions'],
                      'published': state.draft_assignment['published'], 'dueAt': None, 'unlockAt': None, 'lockAt': None,
                      'updatedAt': None, 'groupCategoryId': None, 'gradeGroupStudentsIndividually': None, 'allowedAttempts': None,
                      'state': 'published'}
        if state.draft_written and state.draft_policy_after:
            assignment['published'] = False
        row = None
        if state.draft_submission is not None:
            row = {**copy.deepcopy(state.draft_submission), 'submissionDraft': copy.deepcopy(state.draft_next)}
            if state.draft_written and state.draft_readback_patch is not None:
                row.update(state.draft_readback_patch)
        _send(handler, {'data': {'assignment': assignment, 'submission': row}})
        return True
    if (operation not in ('CanvasSubmissionDraftSave', 'CanvasSubmissionDraftDelete') or
            document != (SAVE if operation == 'CanvasSubmissionDraftSave' else DELETE) or not isinstance(variables, dict)
            or set(variables) != {'input'} or not isinstance(variables['input'], dict)):
        _send(handler, {'errors': [{'message': 'synthetic-private-unexpected-operation'}]})
        return True
    selected = variables['input']
    state.draft_mutations.append(copy.deepcopy(body))
    state.draft_written = True
    if not state.draft_can_submit or state.draft_error_status:
        _send(handler, {'errors': [{'message': 'synthetic-private-submit-denied'}]}, state.draft_error_status or 403)
        return True
    if state.draft_submission is None or selected.get('submissionId') != state.draft_submission['_id']:
        _send(handler, {'errors': [{'message': 'synthetic-private-submission-missing'}]})
        return True
    if operation == 'CanvasSubmissionDraftSave':
        kind = selected.get('activeSubmissionType')
        fields = {'online_text_entry': {'body'}, 'online_url': {'url'}, 'online_upload': {'fileIds'},
                  'media_recording': {'mediaId'}, 'basic_lti_launch': {'externalToolId', 'ltiLaunchUrl', 'resourceLinkLookupUuid'},
                  'student_annotation': set()}
        if kind not in fields or set(selected) - fields[kind] - {'submissionId', 'attempt', 'activeSubmissionType'}:
            _send(handler, {'errors': [{'message': 'synthetic-private-invalid-draft-fields'}]})
            return True
        if selected.get('attempt') != state.draft_submission['attempt'] + 1:
            _send(handler, {'errors': [{'message': 'synthetic-private-invalid-attempt'}]})
            return True
        if state.draft_next is None:
            state.draft_next = {'_id': '952', 'submissionAttempt': selected['attempt'], 'activeSubmissionType': None,
                                'body': None, 'url': None, 'attachments': [], 'mediaObject': None, 'externalTool': None,
                                'ltiLaunchUrl': None, 'resourceLinkLookupUuid': None}
        draft = state.draft_next
        if not state.draft_ignore:
            draft['activeSubmissionType'] = kind
            for key in fields[kind] & selected.keys():
                if key == 'fileIds':
                    draft['attachments'] = [{'_id': item} for item in reversed(selected[key])]
                elif key in ('mediaId', 'externalToolId'):
                    draft['mediaObject' if key == 'mediaId' else 'externalTool'] = {'_id': selected[key]} if selected[key] else None
                else:
                    draft[key] = selected[key]
        ack = {'errors': [], 'submissionDraft': {key: draft[key] for key in ('_id', 'submissionAttempt', 'activeSubmissionType')}}
        if state.draft_normalize:
            if 'body' in selected:
                draft['body'] = '<p>normalized draft</p>'
            if 'fileIds' in selected:
                draft['attachments'] = [{'_id': '893'}]
        if state.draft_advance:
            state.draft_history.append(draft['_id'])
            state.draft_next = None
            state.draft_submission.update(attempt=1, state='submitted', submittedAt='2026-10-04T00:00:00Z')
        _send(handler, {'data': {'createSubmissionDraft': state.draft_ack if state.draft_ack is not None else ack}})
    else:
        if set(selected) != {'submissionId'}:
            _send(handler, {'errors': [{'message': 'synthetic-private-unexpected-delete-fields'}]})
            return True
        ids = state.draft_history + ([state.draft_next['_id']] if state.draft_next is not None else [])
        if not ids:
            _send(handler, {'errors': [{'message': 'synthetic-private-no-drafts'}]})
            return True
        if not state.draft_ignore:
            state.draft_history = []
            state.draft_next = None
        ack = state.draft_ack if state.draft_ack is not None else {'errors': [], 'submissionDraftIds': ids}
        _send(handler, {'data': {'deleteSubmissionDraft': ack}})
    return True
