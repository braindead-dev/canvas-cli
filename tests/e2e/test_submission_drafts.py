"""Installed CLI native draft lifecycle against independent synthetic HTTPS state."""

import copy
import json
from pathlib import Path

from . import submission_drafts
from .fixture import CanvasFixture


class SubmissionDraftE2E(CanvasFixture):
    def setUp(self):
        submission_drafts.initialize(type(self), enabled=True)
        self.text = Path(self.tmp.name) / 'synthetic-draft.txt'
        self.text.write_text('Synthetic <draft>\n& content', encoding='utf-8')
        self.url = Path(self.tmp.name) / 'synthetic-url.txt'
        self.url.write_text('unfinished.example', encoding='utf-8')
        self.tool_url = Path(self.tmp.name) / 'synthetic-tool-url.txt'
        self.tool_url.write_text('https://tool.example.edu/launch', encoding='utf-8')

    def command(self, *extra, action='draft-save'):
        return (action, '141', '941', *extra)

    def approved(self, *extra, action='draft-save'):
        command = self.command(*extra, action=action)
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def test_reads_are_own_next_only_metadata_default_with_private_content_opt_in(self):
        result = self.invoke(*self.command(action='draft'))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['submission_draft']['id'], '951')
        self.assertFalse(data['complete_draft_inventory'])
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)
        self.assertNotIn('synthetic-secret', result.stdout + result.stderr)
        result = self.invoke(*self.command('--include-content', action='draft'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('synthetic-private-draft-body', result.stdout)
        self.assertNotIn('synthetic-secret', result.stdout)
        self.assertEqual(self.draft_mutations, [])
        self.assertEqual(self.draft_view_events, [])
        self.assertTrue(all(row['variables'] == {'assignmentId': '941', 'userId': '7'} for row in self.draft_queries))
        self.assertFalse(any(word in row['query'] for row in self.draft_queries
                             for word in ('meets', 'readStatus', 'readState', 'annotationContext', 'submissionsConnection', 'score')))

    def test_six_types_lifecycle_and_plain_text_escaping_never_call_final_submission_or_external_endpoints(self):
        choices = (('online_text_entry', '--text-file', str(self.text)), ('online_url', '--url-file', str(self.url)),
                   ('online_upload', '--file-id', '892', '--file-id', '891'), ('media_recording', '--media-id', 'synthetic-media'),
                   ('basic_lti_launch', '--external-tool-id', '691', '--lti-url-file', str(self.tool_url),
                    '--resource-link-lookup-uuid', 'synthetic-resource'), ('student_annotation',))
        before_calls = len(self.calls)
        for choice in choices:
            with self.subTest(kind=choice[0]):
                self.setUp()
                original = copy.deepcopy(self.draft_next)
                result = self.approved('--type', *choice)
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)
                self.assertEqual(data['submission_draft']['type'], choice[0])
                self.assertTrue(data['next_attempt_draft_identity_verified'])
                self.assertTrue(all(data['reported_fields_match_request'].values()))
                self.assertFalse(data['final_submission_requested'])
                self.assertFalse(data['raw_storage_verified'])
                self.assertEqual(len(self.draft_mutations), 1)
                selected = self.draft_mutations[0]['variables']['input']
                self.assertEqual(selected['submissionId'], '741')
                self.assertEqual(selected['attempt'], 1)
                if choice[0] == 'online_text_entry':
                    self.assertEqual(self.draft_next['body'], '<p>Synthetic &lt;draft&gt;<br>&amp; content</p>')
                else:
                    self.assertEqual(self.draft_next['body'], original['body'])
                self.assertEqual(self.draft_submission['state'], 'unsubmitted')
                self.assertIsNone(self.draft_submission['submittedAt'])
                self.assertNotIn('synthetic-private', result.stdout + result.stderr)
        self.assertEqual({path for _, path in self.calls[before_calls:]},
                         {'/api/v1/users/self/profile', '/api/graphql'})
        self.assertEqual(self.draft_view_events, [])

    def test_first_draft_and_explicit_clearing_preserve_unselected_dormant_content(self):
        type(self).draft_next = None
        result = self.approved('--type', 'online_text_entry', '--text-file', str(self.text))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['submission_draft']['id'], '952')
        for kind, key, value in (('online_text_entry', 'body', None), ('online_url', 'url', None),
                                 ('online_upload', 'fileIds', []), ('media_recording', 'mediaId', None)):
            result = self.approved('--type', kind, '--clear-content')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.draft_mutations[-1]['variables']['input'][key], value)
        self.assertEqual(self.draft_history, ['950'])

    def test_html_input_is_explicit_and_native_normalization_is_reported_as_representation_difference(self):
        self.text.write_text('<p>HTML draft</p><script>synthetic()</script>', encoding='utf-8')
        type(self).draft_normalize = True
        result = self.approved('--type', 'online_text_entry', '--html-file', str(self.text))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data['reported_fields_match_request']['body'])
        self.assertFalse(data['raw_storage_verified'])
        self.assertEqual(self.draft_mutations[0]['variables']['input']['body'], self.text.read_text())
        result = self.approved('--type', 'online_upload', '--file-id', '891')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['reported_fields_match_request']['file_ids'])

    def test_invalid_type_payload_acknowledgement_flags_or_missing_files_never_mutate(self):
        before = len(self.calls)
        commands = (('--type', 'online_text_entry'), ('--type', 'student_annotation', '--text-file', str(self.text)),
                    ('--type', 'online_upload', '--file-id', '891', '--file-id', '891'),
                    ('--type', 'media_recording', '--clear-content', '--media-id', 'm'),
                    ('--type', 'basic_lti_launch', '--clear-content'),
                    ('--type', 'online_text_entry', '--text-file', str(self.text), '--yes'),
                    ('--type', 'online_text_entry', '--text-file', str(self.text) + '-missing'))
        for command in commands:
            with self.subTest(command=command):
                result = self.invoke(*self.command(*command))
                self.assertEqual(result.returncode, 1)
        result = self.invoke(*self.command(action='draft-delete'))
        self.assertEqual(result.returncode, 1)
        self.assertIn('acknowledge-all-drafts', result.stderr)
        self.assertEqual(self.calls[before:], [])
        self.assertEqual(self.draft_mutations, [])

    def test_null_or_foreign_submission_owner_is_not_no_work_or_permission_to_save(self):
        for mode in ('none', 'foreign', 'anonymous'):
            with self.subTest(mode=mode):
                self.setUp()
                if mode == 'none':
                    type(self).draft_submission = None
                    result = self.invoke(*self.command(action='draft'))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout)['next_draft_status'], 'unknown_no_accessible_submission')
                else:
                    self.draft_submission['userId'] = '8' if mode == 'foreign' else None
                result = self.invoke(*self.command('--type', 'online_text_entry', '--text-file', str(self.text)))
                self.assertEqual(result.returncode, 1)
                self.assertEqual(self.draft_mutations, [])

    def test_stale_rendered_content_file_input_attempt_or_policy_requires_a_new_preview(self):
        for mode in ('content', 'file', 'attempt', 'policy'):
            with self.subTest(mode=mode):
                self.setUp()
                command = self.command('--type', 'online_text_entry', '--text-file', str(self.text))
                preview = self.invoke(*command)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                if mode == 'content':
                    self.draft_next['body'] = '<p>concurrent</p>'
                elif mode == 'file':
                    self.text.write_text('changed local content', encoding='utf-8')
                elif mode == 'attempt':
                    self.draft_submission['attempt'] = 1
                    type(self).draft_next = None
                else:
                    self.draft_assignment['allowed_extensions'] = ['pdf']
                result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
                self.assertEqual(result.returncode, 1)
                self.assertIn('Preview changed', result.stderr)
                self.assertEqual(self.draft_mutations, [])

    def test_native_permission_denial_never_leaks_response_or_retries(self):
        type(self).draft_can_read = False
        result = self.invoke(*self.command(action='draft'))
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)
        self.assertEqual(self.draft_mutations, [])
        self.setUp()
        type(self).draft_can_submit = False
        result = self.approved('--type', 'online_text_entry', '--text-file', str(self.text))
        self.assertEqual(result.returncode, 1)
        self.assertIn('unverified', result.stderr)
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)
        self.assertEqual(len(self.draft_mutations), 1)

    def test_post_mutation_races_partial_ack_and_http_errors_do_not_trigger_retries(self):
        for mode in ('advance', 'account', 'policy', 'read_error', 'partial', 'http_error', 'foreign_draft'):
            with self.subTest(mode=mode):
                self.setUp()
                if mode == 'advance':
                    type(self).draft_advance = True
                elif mode == 'account':
                    type(self).draft_account_after = True
                elif mode == 'policy':
                    type(self).draft_policy_after = True
                elif mode == 'read_error':
                    type(self).draft_error_after = True
                elif mode == 'partial':
                    type(self).draft_ack = {'errors': [{'attribute': 'synthetic-private'}]}
                elif mode == 'http_error':
                    type(self).draft_error_status = 500
                else:
                    type(self).draft_ack = {'errors': [], 'submissionDraft': {'_id': '999', 'submissionAttempt': 1,
                                                                           'activeSubmissionType': 'online_text_entry'}}
                result = self.approved('--type', 'online_text_entry', '--text-file', str(self.text))
                self.assertEqual(result.returncode, 1)
                self.assertIn('unverified', result.stderr)
                self.assertNotIn('synthetic-private', result.stdout + result.stderr)
                self.assertEqual(len(self.draft_mutations), 1)

    def test_delete_removes_all_attempts_but_only_current_absence_is_independently_verified(self):
        original_submission = copy.deepcopy(self.draft_submission)
        result = self.approved('--acknowledge-all-drafts', action='draft-delete')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['server_reported_deleted_draft_ids'], ['950', '951'])
        self.assertTrue(data['next_attempt_absence_verified'])
        self.assertFalse(data['historical_draft_absence_verified'])
        self.assertFalse(data['complete_draft_inventory'])
        self.assertEqual(self.draft_history, [])
        self.assertIsNone(self.draft_next)
        self.assertEqual(self.draft_submission, original_submission)
        self.assertEqual(len(self.draft_mutations), 1)
        self.assertEqual(self.draft_mutations[0]['variables']['input'], {'submissionId': '741'})

    def test_history_only_delete_and_no_drafts_native_error_do_not_fake_complete_inventory(self):
        type(self).draft_next = None
        result = self.approved('--acknowledge-all-drafts', action='draft-delete')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['server_reported_deleted_draft_ids'], ['950'])
        result = self.approved('--acknowledge-all-drafts', action='draft-delete')
        self.assertEqual(result.returncode, 1)
        self.assertIn('unverified', result.stderr)
        self.assertEqual(len(self.draft_mutations), 2)

    def test_ignored_delete_is_not_claimed_as_verified_absence(self):
        type(self).draft_ignore = True
        result = self.approved('--acknowledge-all-drafts', action='draft-delete')
        self.assertEqual(result.returncode, 1)
        self.assertIn('unverified', result.stderr)
        self.assertIsNotNone(self.draft_next)
        self.assertEqual(len(self.draft_mutations), 1)

    def test_offline_help_schema_and_brief_navigate_cleanly_without_private_content(self):
        before = len(self.calls)
        result = self.invoke('help', '--search', 'draft', '--format', 'brief', token='invalid')
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ('draft', 'draft-save', 'draft-delete'):
            self.assertIn(name, result.stdout)
        result = self.invoke('schema', 'draft-save', token='invalid')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['commands'][0]['command'], 'draft-save')
        self.assertEqual(self.calls[before:], [])
        result = self.invoke(*self.command('--format', 'brief', action='draft'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertIn('not a complete draft inventory', result.stdout)
