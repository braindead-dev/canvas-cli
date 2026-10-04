"""Native own draft semantics with synthetic accounts and no real coursework writes."""

import copy
import json
import unittest

from canvas_cli.arguments import parser
from canvas_cli.client import CanvasError
from canvas_cli.formatting import brief
from canvas_cli.navigation import command_help
from canvas_cli.submission_drafts import _draft, _input, delete, read, save, text_input


def draft_record():
    return {'_id': '91', 'submissionAttempt': 1, 'activeSubmissionType': 'online_text_entry',
            'body': '<p>synthetic-private-draft</p>', 'url': 'https://example.edu/project?access_token=synthetic-secret',
            'attachments': [{'_id': '81'}], 'mediaObject': {'_id': 'synthetic-media'}, 'externalTool': {'_id': '61'},
            'ltiLaunchUrl': 'https://example.edu/tool', 'resourceLinkLookupUuid': 'synthetic-private-resource'}


class DraftClient:
    host = 'https://canvas.example.edu'

    def __init__(self):
        self.calls = []
        self.user_id = 7
        self.assignment = {'id': 44, 'course_id': 123, 'submission_types': ['online_text_entry'],
                           'allowed_extensions': ['txt'], 'published': True, 'locked_for_user': False}
        self.row = {'_id': '71', 'userId': '7', 'assignmentId': '44', 'assignment': {'_id': '44', 'courseId': '123'},
                    'attempt': 0, 'state': 'unsubmitted', 'submittedAt': None, 'submissionDraft': draft_record()}
        self.history = ['90']
        self.written = False
        self.ack = self.readback_patch = self.write_error = self.query_error = None
        self.ignore = self.switch_account = self.advance_attempt = self.policy_after = False
        self.normalize = False
        self.query_missing = False
        self.policy_missing = False

    def request(self, path, method='GET', body=None):
        self.calls.append((method, path, body))
        if path == '/api/v1/users/self/profile':
            return {'id': 8 if self.written and self.switch_account else self.user_id, 'email': 'synthetic-private@example.edu'}, ''
        raise AssertionError(path)

    def graphql(self, document, variables, operation):
        self.calls.append((operation, document, copy.deepcopy(variables)))
        if operation == 'CanvasSubmissionDraft':
            if self.query_error:
                raise CanvasError('synthetic-private-query-error', status=403)
            if self.query_missing:
                return {}
            assignment = {'_id': str(self.assignment['id']), 'courseId': str(self.assignment['course_id']),
                          'submissionTypes': self.assignment.get('submission_types'), 'allowedExtensions': self.assignment.get('allowed_extensions'),
                          'published': self.assignment.get('published'), 'dueAt': self.assignment.get('due_at'),
                          'unlockAt': self.assignment.get('unlock_at'), 'lockAt': self.assignment.get('lock_at'),
                          'updatedAt': self.assignment.get('updated_at'), 'groupCategoryId': self.assignment.get('group_category_id'),
                          'gradeGroupStudentsIndividually': self.assignment.get('grade_group_students_individually'),
                          'allowedAttempts': self.assignment.get('allowed_attempts'), 'state': 'published'}
            if self.written and self.policy_after:
                assignment['published'] = False
            if self.policy_missing:
                del assignment['published']
            row = copy.deepcopy(self.row)
            if row is not None and self.written and self.readback_patch:
                row.update(self.readback_patch)
            return {'assignment': assignment, 'submission': row}
        self.written = True
        if self.write_error:
            raise CanvasError('synthetic-private-write-error', status=self.write_error)
        selected = variables['input']
        if operation == 'CanvasSubmissionDraftSave':
            if self.row['submissionDraft'] is None:
                self.row['submissionDraft'] = {**draft_record(), '_id': '92', 'body': None, 'url': None,
                                              'attachments': [], 'mediaObject': None, 'externalTool': None,
                                              'ltiLaunchUrl': None, 'resourceLinkLookupUuid': None}
            draft = self.row['submissionDraft']
            if not self.ignore:
                draft['activeSubmissionType'] = selected['activeSubmissionType']
                draft['submissionAttempt'] = selected['attempt']
                for key in ('body', 'url', 'ltiLaunchUrl', 'resourceLinkLookupUuid'):
                    if key in selected:
                        draft[key] = selected[key]
                if 'fileIds' in selected:
                    draft['attachments'] = [{'_id': item} for item in selected['fileIds']]
                if 'mediaId' in selected:
                    draft['mediaObject'] = None if not selected['mediaId'] else {'_id': selected['mediaId']}
                if 'externalToolId' in selected:
                    draft['externalTool'] = {'_id': selected['externalToolId']}
            ack = {'errors': [], 'submissionDraft': {key: draft[key] for key in ('_id', 'submissionAttempt', 'activeSubmissionType')}}
            if self.normalize:
                draft['body'] = '<p>normalized</p>'
                draft['url'] = 'https://normalized.example.edu/'
                draft['attachments'] = [{'_id': '82'}]
            if self.advance_attempt:
                self.history.append(draft['_id'])
                self.row.update(attempt=1, state='submitted', submittedAt='2026-10-04T00:00:00Z', submissionDraft=None)
            if self.ack is not None:
                ack = self.ack
            return {'createSubmissionDraft': ack}
        if operation == 'CanvasSubmissionDraftDelete':
            ids = self.history + ([self.row['submissionDraft']['_id']] if self.row['submissionDraft'] is not None else [])
            if not self.ignore:
                self.history = []
                self.row['submissionDraft'] = None
            return {'deleteSubmissionDraft': self.ack if self.ack is not None else {'errors': [], 'submissionDraftIds': ids}}
        raise AssertionError(operation)


class SubmissionDraftTests(unittest.TestCase):
    def setUp(self):
        self.client = DraftClient()

    def preview(self, kind='online_text_entry', values=None, **kwargs):
        return save(self.client, '123', '44', kind, {'body': '<p>new</p>'} if values is None else values, **kwargs)

    def execute(self, kind='online_text_entry', values=None, **kwargs):
        preview = self.preview(kind, values, **kwargs)
        return save(self.client, '123', '44', kind, {'body': '<p>new</p>'} if values is None else values,
                    yes=True, confirm=preview['confirm'], **kwargs)

    def mutations(self):
        return [call for call in self.client.calls if call[0] in ('CanvasSubmissionDraftSave', 'CanvasSubmissionDraftDelete')]

    def test_default_is_private_metadata_own_only_and_not_historical_inventory(self):
        result = read(self.client, '123', '44')
        self.assertEqual(result['submission_draft']['id'], '91')
        self.assertEqual(result['submission_draft']['file_ids'], ['81'])
        self.assertEqual(result['next_draft_status'], 'present')
        self.assertFalse(result['complete_draft_inventory'])
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertEqual(self.mutations(), [])
        query = next(call for call in self.client.calls if call[0] == 'CanvasSubmissionDraft')
        self.assertEqual(query[2], {'assignmentId': '44', 'userId': '7'})
        self.assertFalse(any(key in query[1] for key in ('meets', 'readState', 'readStatus', 'annotationContext', 'submissionsConnection', 'score')))

    def test_content_opt_in_redacts_secrets_but_is_rendered_not_raw_storage(self):
        result = read(self.client, '123', '44', include_content=True)
        self.assertIn('synthetic-private-draft', result['submission_draft']['content']['body'])
        self.assertNotIn('synthetic-secret', json.dumps(result))
        self.assertIn('not raw-storage proof', result['note'])
        self.assertNotIn('synthetic-private', brief(result))

    def test_null_submission_is_unknown_and_cannot_manufacture_submission_for_draft_save(self):
        self.client.row = None
        result = read(self.client, '123', '44')
        self.assertEqual(result['next_draft_status'], 'unknown_no_accessible_submission')
        self.assertIsNone(result['submission'])
        with self.assertRaisesRegex(CanvasError, 'cannot create'):
            self.preview()
        with self.assertRaises(CanvasError):
            delete(self.client, '123', '44', acknowledge_all=True)
        self.assertEqual(self.mutations(), [])

    def test_no_next_draft_does_not_mean_no_historical_drafts_and_can_create_next(self):
        self.client.row['submissionDraft'] = None
        self.assertEqual(read(self.client, '123', '44')['next_draft_status'], 'absent_for_next_attempt')
        result = self.execute()
        self.assertEqual(result['submission_draft']['id'], '92')
        self.assertTrue(result['next_attempt_draft_identity_verified'])
        self.assertFalse(result['raw_storage_verified'])

    def test_preview_binds_current_rendered_content_and_explicit_next_attempt_without_exposing_old_body(self):
        preview = self.preview()
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['body']['variables']['input'], {'submissionId': '71', 'activeSubmissionType': 'online_text_entry',
                                                               'attempt': 1, 'body': '<p>new</p>'})
        self.assertNotIn('synthetic-private', json.dumps(preview))
        self.assertEqual(self.mutations(), [])

    def test_six_types_save_selected_fields_and_keep_other_type_content(self):
        selections = {'online_text_entry': {'body': 'text'}, 'online_url': {'url': 'unfinished.example'},
                      'online_upload': {'fileIds': ['82', '83']}, 'media_recording': {'mediaId': 'new-media'},
                      'basic_lti_launch': {'externalToolId': '62', 'ltiLaunchUrl': 'https://example.edu/new-tool',
                                           'resourceLinkLookupUuid': 'new-resource'}, 'student_annotation': {}}
        for kind, values in selections.items():
            with self.subTest(kind=kind):
                self.setUp()
                original = copy.deepcopy(self.client.row['submissionDraft'])
                result = self.execute(kind, values)
                self.assertEqual(result['submission_draft']['type'], kind)
                self.assertTrue(all(result['reported_fields_match_request'].values()))
                self.assertFalse(result['final_submission_requested'])
                self.assertEqual(len(self.mutations()), 1)
                self.assertEqual(self.mutations()[0][2]['input'], {'submissionId': '71', 'attempt': 1,
                                                                 'activeSubmissionType': kind, **values})
                if kind != 'online_text_entry':
                    self.assertEqual(self.client.row['submissionDraft']['body'], original['body'])
                if kind != 'online_upload':
                    self.assertEqual(self.client.row['submissionDraft']['attachments'], original['attachments'])

    def test_explicit_clearing_only_selected_content_sends_null_or_empty_list(self):
        for kind, key, expected in (('online_text_entry', 'body', None), ('online_url', 'url', None),
                                    ('online_upload', 'fileIds', []), ('media_recording', 'mediaId', None)):
            with self.subTest(kind=kind):
                self.setUp()
                result = self.execute(kind, {}, clear=True)
                self.assertEqual(self.mutations()[0][2]['input'][key], expected)
                self.assertTrue(all(result['reported_fields_match_request'].values()))

    def test_plain_text_is_escaped_but_empty_is_a_valid_draft(self):
        self.assertEqual(text_input('<x>\n&'), '<p>&lt;x&gt;<br>&amp;</p>')
        self.assertEqual(text_input(''), '')
        self.assertTrue(self.execute(values={'body': ''})['reported_fields_match_request']['body'])

    def test_native_drafts_are_not_refused_just_because_final_type_or_availability_differs(self):
        self.client.assignment.update(submission_types=['online_upload'], locked_for_user=True, published=False)
        result = self.execute()
        self.assertTrue(result['next_attempt_draft_identity_verified'])
        self.assertFalse(result['assignment_policy']['published'])
        self.assertFalse(any(path.startswith('/api/v1/courses/') for method, path, _ in self.client.calls if method == 'GET'))

    def test_assignment_owner_course_or_missing_metadata_fails_without_mutation(self):
        patches = ({'userId': '8'}, {'userId': None}, {'assignmentId': '45'}, {'assignment': {'_id': '44', 'courseId': '124'}},
                   {'_id': '0'}, {'attempt': True}, {'attempt': -1}, {'state': ''}, {'submittedAt': {}}, {'submissionDraft': []})
        for patch in patches:
            with self.subTest(patch=patch):
                self.setUp()
                self.client.row.update(patch)
                with self.assertRaises(CanvasError):
                    self.preview()
                self.assertEqual(self.mutations(), [])
        self.setUp()
        self.client.query_missing = True
        with self.assertRaisesRegex(CanvasError, 'omitted'):
            read(self.client, '123', '44')
        self.setUp()
        self.client.policy_missing = True
        with self.assertRaisesRegex(CanvasError, 'omitted'):
            read(self.client, '123', '44')
        for patch in ({'id': 45}, {'course_id': 124}, {'published': 1}, {'grade_group_students_individually': 'false'},
                      {'submission_types': {}}, {'allowed_extensions': [1]}):
            self.setUp()
            self.client.assignment.update(patch)
            with self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.mutations(), [])

    def test_malformed_draft_metadata_is_not_empty_or_success(self):
        patches = ({'_id': '0'}, {'submissionAttempt': 2}, {'submissionAttempt': True}, {'activeSubmissionType': 'unknown'},
                   {'body': []}, {'url': {}}, {'attachments': None}, {'attachments': [None]},
                   {'attachments': [{'_id': '81'}, {'_id': '81'}]}, {'mediaObject': {'_id': 2}}, {'externalTool': {'_id': 'opaque'}})
        for patch in patches:
            with self.subTest(patch=patch):
                row = draft_record()
                row.update(patch)
                with self.assertRaises(CanvasError):
                    _draft(row, 1)
        for missing in ('activeSubmissionType', 'body', 'externalTool'):
            row = draft_record()
            del row[missing]
            with self.assertRaises(CanvasError):
                _draft(row, 1)

    def test_invalid_flags_type_input_or_scope_fail_before_network(self):
        invalid = [('unsupported', {}, False), ('online_text_entry', {}, False), ('student_annotation', {'body': 'x'}, False),
                   ('online_url', {'url': 'https://user:password@example.edu/'}, False),
                   ('online_url', {'url': 'https://['}, False), ('online_text_entry', {'body': 1}, False),
                   ('basic_lti_launch', {'externalToolId': '61', 'ltiLaunchUrl': ''}, False),
                   ('online_upload', {'fileIds': []}, False), ('online_upload', {'fileIds': ['81', '81']}, False),
                   ('online_upload', {'fileIds': [{}]}, False), ('online_upload', {'fileIds': ['0']}, False),
                   ('media_recording', {'mediaId': 'm'}, True), ('student_annotation', {}, True)]
        for kind, values, clear in invalid:
            with self.subTest(kind=kind, values=values), self.assertRaises(CanvasError):
                self.preview(kind, values, clear=clear)
        for kwargs in ({'yes': True}, {'confirm': 'bad'}):
            with self.assertRaises(CanvasError):
                self.preview(**kwargs)
        with self.assertRaises(CanvasError):
            delete(self.client, '123', '44')
        with self.assertRaises(CanvasError):
            read(self.client, '../123', '44')
        self.assertEqual(self.client.calls, [])

    def test_every_observable_preflight_change_requires_new_confirmation(self):
        for target in ('account', 'draft', 'attempt', 'policy', 'submission'):
            with self.subTest(target=target):
                self.setUp()
                preview = self.preview()
                if target == 'account':
                    self.client.user_id = 8
                    self.client.row['userId'] = '8'
                elif target == 'draft':
                    self.client.row['submissionDraft']['body'] = 'changed'
                elif target == 'attempt':
                    self.client.row.update(attempt=1, submissionDraft=None)
                elif target == 'policy':
                    self.client.assignment['allowed_extensions'] = ['pdf']
                else:
                    self.client.row['state'] = 'submitted'
                with self.assertRaisesRegex(CanvasError, 'Preview changed'):
                    save(self.client, '123', '44', 'online_text_entry', {'body': '<p>new</p>'}, yes=True, confirm=preview['confirm'])
                self.assertEqual(self.mutations(), [])

    def test_account_switch_during_initial_inspection_fails_before_mutation(self):
        original = self.client.request
        reads = 0

        def switched(path, method='GET', body=None):
            nonlocal reads
            result = original(path, method, body)
            if path == '/api/v1/users/self/profile':
                reads += 1
                if reads == 2:
                    return {'id': 8}, ''
            return result

        self.client.request = switched
        with self.assertRaisesRegex(CanvasError, 'account changed'):
            self.preview()
        self.assertEqual(self.mutations(), [])

    def test_normalized_content_replacement_attachments_report_differences_not_raw_storage_success(self):
        self.client.normalize = True
        result = self.execute()
        self.assertFalse(result['reported_fields_match_request']['body'])
        self.assertFalse(result['raw_storage_verified'])
        self.assertIn('differs', brief(result))
        self.assertIn('file_ids', result['observed_content_changes'])
        self.setUp()
        self.client.normalize = True
        result = self.execute('online_upload', {'fileIds': ['81']})
        self.assertFalse(result['reported_fields_match_request']['file_ids'])

    def test_permission_error_partial_ack_or_changed_readback_is_uncertain_never_retried(self):
        modes = ('denied', 'errors', 'missing', 'foreign_id', 'different_type', 'advance', 'account', 'policy', 'missing_after')
        for mode in modes:
            with self.subTest(mode=mode):
                self.setUp()
                if mode == 'denied':
                    self.client.write_error = 403
                elif mode == 'errors':
                    self.client.ack = {'errors': [{'attribute': 'synthetic-private'}]}
                elif mode == 'missing':
                    self.client.ack = {}
                elif mode == 'foreign_id':
                    self.client.ack = {'errors': [], 'submissionDraft': {**draft_record(), '_id': '99'}}
                elif mode == 'different_type':
                    self.client.ignore = True
                    self.client.row['submissionDraft']['activeSubmissionType'] = 'online_url'
                elif mode == 'advance':
                    self.client.advance_attempt = True
                elif mode == 'account':
                    self.client.switch_account = True
                elif mode == 'policy':
                    self.client.policy_after = True
                else:
                    self.client.readback_patch = {'submissionDraft': None}
                with self.assertRaisesRegex(CanvasError, 'unverified') as raised:
                    self.execute()
                self.assertNotIn('synthetic-private', str(raised.exception))
                self.assertEqual(len(self.mutations()), 1)

    def test_delete_is_all_attempts_one_mutation_with_only_next_absence_independently_verified(self):
        preview = delete(self.client, '123', '44', acknowledge_all=True)
        self.assertIn('ALL submission drafts', preview['effect'])
        self.assertNotIn('"90"', json.dumps(preview))
        self.assertEqual(self.mutations(), [])
        result = delete(self.client, '123', '44', acknowledge_all=True, yes=True, confirm=preview['confirm'])
        self.assertEqual(result['server_reported_deleted_draft_ids'], ['90', '91'])
        self.assertTrue(result['next_attempt_absence_verified'])
        self.assertFalse(result['historical_draft_absence_verified'])
        self.assertFalse(result['final_submission_requested'])
        self.assertEqual(self.client.history, [])
        self.assertIsNone(self.client.row['submissionDraft'])
        self.assertEqual(len(self.mutations()), 1)
        self.assertIn('cannot be restored', brief(result))

    def test_delete_can_explicitly_remove_history_when_next_draft_absent(self):
        self.client.row['submissionDraft'] = None
        preview = delete(self.client, '123', '44', acknowledge_all=True)
        result = delete(self.client, '123', '44', acknowledge_all=True, yes=True, confirm=preview['confirm'])
        self.assertEqual(result['server_reported_deleted_draft_ids'], ['90'])
        self.assertFalse(result['historical_draft_absence_verified'])

    def test_bad_deletion_ids_or_ignored_deletion_is_uncertain_without_retry(self):
        for ids in ([], ['91', '91'], ['0'], [{}], None, ['90']):
            with self.subTest(ids=ids):
                self.setUp()
                self.client.ack = {'errors': [], 'submissionDraftIds': ids}
                preview = delete(self.client, '123', '44', acknowledge_all=True)
                with self.assertRaisesRegex(CanvasError, 'unverified'):
                    delete(self.client, '123', '44', acknowledge_all=True, yes=True, confirm=preview['confirm'])
                self.assertEqual(len(self.mutations()), 1)
        self.setUp()
        self.client.ignore = True
        preview = delete(self.client, '123', '44', acknowledge_all=True)
        with self.assertRaises(CanvasError):
            delete(self.client, '123', '44', acknowledge_all=True, yes=True, confirm=preview['confirm'])

    def test_parser_navigation_and_safety_use_single_actual_command_surface(self):
        root = parser()
        for name, safety in (('draft', 'Read-only'), ('draft-save', 'Canvas writes (preview-first)'),
                             ('draft-delete', 'Canvas writes (preview-first)')):
            self.assertEqual(command_help(root, name)['safety'], safety)
        args = root.parse_args(['draft-save', '123', '44', '--type', 'student_annotation'])
        self.assertEqual(args.draft_type, 'student_annotation')
        self.assertFalse(args.yes)
        self.assertEqual(_input('online_url', {'url': 'unfinished draft URL'}, False), {'url': 'unfinished draft URL'})
