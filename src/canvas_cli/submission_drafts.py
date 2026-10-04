"""Own native submission drafts, never a final submission or assessment attempt."""

from urllib.parse import urlsplit

from .client import CanvasError
from .group_content import _number
from .own_submission import ASSIGNMENT_FIELDS, SUBMISSION_FIELDS, context
from .snapshot import redact
from .text import html_body
from .writes import account, check_flags, digest, review

TYPES = ('online_text_entry', 'online_url', 'online_upload', 'media_recording', 'basic_lti_launch', 'student_annotation')
text_input = html_body
_CONTENT = ('body', 'url', 'file_ids', 'media_id', 'external_tool_id', 'lti_launch_url', 'resource_link_lookup_uuid')
_DRAFT = ('_id submissionAttempt activeSubmissionType body(rewriteUrls: false) url attachments { _id } '
          'mediaObject { _id } externalTool { _id } ltiLaunchUrl resourceLinkLookupUuid')
_READ = ('query CanvasSubmissionDraft($assignmentId: ID!, $userId: ID!) { '
         'assignment(id: $assignmentId) { ' + ASSIGNMENT_FIELDS + ' } '
         'submission(assignmentId: $assignmentId, userId: $userId) { ' + SUBMISSION_FIELDS + ' submissionDraft { ' + _DRAFT + ' } } }')
_SAVE = ('mutation CanvasSubmissionDraftSave($input: CreateSubmissionDraftInput!) { '
         'createSubmissionDraft(input: $input) { errors { attribute } '
         'submissionDraft { _id submissionAttempt activeSubmissionType } } }')
_DELETE = ('mutation CanvasSubmissionDraftDelete($input: DeleteSubmissionDraftInput!) { '
           'deleteSubmissionDraft(input: $input) { errors { attribute } submissionDraftIds } }')
_NOTE = ('Own next-attempt draft only, not a complete draft inventory. No final submission, quiz attempt, '
         'annotation initialization, file upload, external launch or assessment-criteria query. '
         'Assignment policy uses GraphQL metadata, not the single-assignment REST GET that can record module access. '
         'Canvas enforces native read/submit rights at the endpoint. Draft storage need not satisfy assignment '
         'submission criteria. HTML/URLs may be processed; returned representations are not raw-storage proof. '
         'Other draft-type fields are retained natively. Confirmation is not an atomic lock; concurrent submission '
         'can hide a draft, and native duplicate-record cleanup can occur. No automatic retries or rollback.')
_UNCERTAIN = ('The draft operation outcome is unverified; it may have applied, including creating a partial draft. '
              'No private response was logged. Inspect Canvas before repeating. No automatic retries.')


def _nullable_text(value):
    if value is not None and not isinstance(value, str):
        raise CanvasError('Canvas returned malformed draft text; no private response was logged')
    return value


def _draft(row, attempt, *, content=True):
    if not isinstance(row, dict):
        raise CanvasError('Canvas returned malformed draft metadata')
    identifier = _number(row.get('_id'))
    if type(row.get('submissionAttempt')) is not int or row['submissionAttempt'] != attempt:
        raise CanvasError('Canvas returned a different draft attempt')
    kind = row.get('activeSubmissionType')
    if 'activeSubmissionType' not in row or kind is not None and kind not in TYPES:
        raise CanvasError('Canvas returned unavailable draft-type metadata')
    result = {'id': identifier, 'attempt': attempt, 'type': kind}
    if not content:
        return result
    for key in ('body', 'url', 'ltiLaunchUrl', 'resourceLinkLookupUuid', 'attachments', 'mediaObject', 'externalTool'):
        if key not in row:
            raise CanvasError('Canvas omitted selected draft fields; no private response was logged')
    files = row['attachments']
    if not isinstance(files, list):
        raise CanvasError('Canvas returned unavailable draft attachment metadata')
    ids = [_number(item.get('_id')) if isinstance(item, dict) else _number(None) for item in files]
    if len(set(ids)) != len(ids):
        raise CanvasError('Canvas returned duplicate draft attachment IDs')
    for native, selected in (('mediaObject', 'media_id'), ('externalTool', 'external_tool_id')):
        item = row[native]
        if item is not None and (not isinstance(item, dict) or not isinstance(item.get('_id'), str) or not item['_id']):
            raise CanvasError('Canvas returned malformed draft associations')
        result[selected] = None if item is None else item['_id']
    if result['external_tool_id'] is not None:
        _number(result['external_tool_id'])
    result.update(body=_nullable_text(row['body']), url=_nullable_text(row['url']), file_ids=sorted(ids, key=int),
                  lti_launch_url=_nullable_text(row['ltiLaunchUrl']),
                  resource_link_lookup_uuid=_nullable_text(row['resourceLinkLookupUuid']))
    return result


def _inspect(client, course_id, assignment_id):
    _number(course_id)
    _number(assignment_id)
    identity = account(client)
    data = client.graphql(_READ, {'assignmentId': assignment_id, 'userId': str(identity['user_id'])}, 'CanvasSubmissionDraft')
    state = context(data, identity, course_id, assignment_id)
    row = data['submission']
    draft = None
    if row is not None:
        if 'submissionDraft' not in row:
            raise CanvasError('Canvas returned unavailable own submission metadata')
        if row['submissionDraft'] is not None:
            draft = _draft(row['submissionDraft'], state['submission']['attempt'] + 1)
    if account(client) != identity:
        raise CanvasError('Signed-in account changed during draft inspection; no mutation was sent')
    return {**state, 'draft': draft}


def _projection(state, include_content=False):
    draft = state['draft']
    selected = None
    if draft is not None:
        selected = {key: draft[key] for key in ('id', 'attempt', 'type', 'file_ids', 'media_id', 'external_tool_id')}
        selected['content_fingerprints'] = {key: digest(draft[key]) for key in _CONTENT if key != 'file_ids'}
        if include_content:
            selected['content'] = redact({key: draft[key] for key in _CONTENT})
    return {**{key: value for key, value in state.items() if key != 'draft'}, 'submission_draft': selected,
            'next_draft_status': 'unknown_no_accessible_submission' if state['submission'] is None
            else 'present' if draft is not None else 'absent_for_next_attempt',
            'complete_draft_inventory': False, 'note': _NOTE}


def read(client, course_id, assignment_id, *, include_content=False):
    return _projection(_inspect(client, course_id, assignment_id), include_content)


def _input(kind, values, clear):
    if kind not in TYPES or not isinstance(values, dict):
        raise CanvasError('Choose a supported native draft type')
    expected = {'online_text_entry': {'body'}, 'online_url': {'url'}, 'online_upload': {'fileIds'},
                'media_recording': {'mediaId'}, 'basic_lti_launch': {'externalToolId', 'ltiLaunchUrl'}, 'student_annotation': set()}[kind]
    allowed = expected | ({'resourceLinkLookupUuid'} if kind == 'basic_lti_launch' else set())
    if set(values) - allowed or clear and values or clear and kind in ('basic_lti_launch', 'student_annotation'):
        raise CanvasError('Draft input fields must match the selected type; clearing cannot be combined with content')
    if clear:
        return {key: [] if key == 'fileIds' else None for key in expected}
    if not expected.issubset(values):
        raise CanvasError('Provide explicit content for the selected draft type, or use --clear-content')
    for key, value in values.items():
        if key == 'fileIds':
            if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value) or len(value) != len(set(value)):
                raise CanvasError('Choose distinct positive file IDs, or --clear-content')
            for identifier in value:
                _number(identifier)
        elif key == 'externalToolId':
            _number(value)
        elif not isinstance(value, str) or not value and kind == 'basic_lti_launch':
            raise CanvasError('Draft content must be text; external-tool inputs must be nonempty')
        if key in ('url', 'ltiLaunchUrl'):
            try:
                parsed = urlsplit(value)
                if parsed.username is not None or parsed.password is not None:
                    raise ValueError
            except ValueError:
                raise CanvasError('Draft URL must not contain embedded credentials or malformed authority') from None
    result = values.copy()
    if 'fileIds' in result:
        result['fileIds'] = sorted(result['fileIds'], key=int)
    return result


def _preview(state, document, operation, selected, effect):
    if state['submission'] is None:
        raise CanvasError('No accessible existing own submission record. Draft mutations cannot create one; '
                          'the CLI will not turn in work or start an attempt to manufacture it.')
    return {**_projection(state), 'reported_state_fingerprint': digest(state), 'method': 'POST', 'route': '/api/graphql',
            'body': {'query': document, 'variables': {'input': {'submissionId': state['submission']['id'], **selected}},
                     'operationName': operation}, 'effect': effect}


def _ack(client, preview, field):
    try:
        body = preview['body']
        data = client.graphql(body['query'], body['variables'], body['operationName'])
        ack = data.get(field)
        if not isinstance(ack, dict) or 'errors' not in ack or ack['errors'] not in (None, []):
            raise CanvasError(_UNCERTAIN)
        return ack
    except CanvasError as error:
        raise CanvasError(_UNCERTAIN, status=error.status) from None


def _after(client, before):
    try:
        after = _inspect(client, before['course_id'], before['assignment_id'])
        if {key: value for key, value in before.items() if key != 'draft'} != {key: value for key, value in after.items() if key != 'draft'}:
            raise CanvasError(_UNCERTAIN)
        return after
    except CanvasError:
        raise CanvasError(_UNCERTAIN) from None


def save(client, course_id, assignment_id, kind, values, *, clear=False, yes=False, confirm=None):
    check_flags(yes, confirm)
    selected = _input(kind, values, clear)
    before = _inspect(client, course_id, assignment_id)
    attempt = before['submission']['attempt'] + 1 if before['submission'] is not None else None
    selected = {'activeSubmissionType': kind, 'attempt': attempt, **selected}
    preview = _preview(before, _SAVE, 'CanvasSubmissionDraftSave', selected, _NOTE)
    result = review(preview, yes, confirm)
    if result is not None:
        return result
    ack = _ack(client, preview, 'createSubmissionDraft')
    try:
        returned = _draft(ack.get('submissionDraft'), attempt, content=False)
        after = _after(client, before)
        draft = after['draft']
        if draft is None or any(draft[key] != returned[key] for key in ('id', 'attempt', 'type')) or draft['type'] != kind:
            raise CanvasError(_UNCERTAIN)
    except CanvasError:
        raise CanvasError(_UNCERTAIN) from None
    fields = {'body': 'body', 'url': 'url', 'fileIds': 'file_ids', 'mediaId': 'media_id', 'externalToolId': 'external_tool_id',
              'ltiLaunchUrl': 'lti_launch_url', 'resourceLinkLookupUuid': 'resource_link_lookup_uuid'}
    matches = {fields[key]: draft[fields[key]] == value for key, value in selected.items() if key in fields}
    changed = [key for key in _CONTENT if before['draft'] is not None and before['draft'][key] != draft[key]]
    return {**_projection(after), 'mutation_acknowledged': True, 'next_attempt_draft_identity_verified': True,
            'reported_fields_match_request': matches, 'observed_content_changes': changed,
            'raw_storage_verified': False, 'final_submission_requested': False,
            'note': _NOTE + ' Reported differences can reflect sanitization, URL normalization, replacement attachments, '
                    'hidden/deleted associations or concurrent changes. Acknowledgement alone is not content proof.'}


def delete(client, course_id, assignment_id, *, acknowledge_all=False, yes=False, confirm=None):
    check_flags(yes, confirm)
    if not acknowledge_all:
        raise CanvasError('Use --acknowledge-all-drafts: native deletion removes ALL draft attempts, including hidden history; '
                          'the read query cannot inventory them. This is not just the next draft.')
    before = _inspect(client, course_id, assignment_id)
    effect = 'Native deletion removes ALL submission drafts, including unobservable historical attempts. ' + _NOTE
    preview = _preview(before, _DELETE, 'CanvasSubmissionDraftDelete', {}, effect)
    result = review(preview, yes, confirm)
    if result is not None:
        return result
    ack = _ack(client, preview, 'deleteSubmissionDraft')
    try:
        ids = ack.get('submissionDraftIds')
        if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids):
            raise CanvasError(_UNCERTAIN)
        for identifier in ids:
            _number(identifier)
        if before['draft'] is not None and before['draft']['id'] not in ids:
            raise CanvasError(_UNCERTAIN)
        after = _after(client, before)
        if after['draft'] is not None:
            raise CanvasError(_UNCERTAIN)
    except (CanvasError, TypeError):
        raise CanvasError(_UNCERTAIN) from None
    return {**_projection(after), 'mutation_acknowledged': True, 'server_reported_deleted_draft_ids': ids,
            'next_attempt_absence_verified': True, 'historical_draft_absence_verified': False,
            'final_submission_requested': False, 'note': effect + ' Old-attempt deletion is server-reported only, '
                    'not independently verified. The CLI cannot restore deleted drafts.'}
