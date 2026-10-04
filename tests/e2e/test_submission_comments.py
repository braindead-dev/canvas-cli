"""Installed CLI own comment lifecycle against independent synthetic HTTPS state."""

import json
from pathlib import Path

from . import submission_comments
from .fixture import CanvasFixture


class SubmissionCommentE2E(CanvasFixture):
    def setUp(self):
        submission_comments.initialize(type(self), enabled=True)
        self.text = Path(self.tmp.name) / 'synthetic-comment.txt'
        self.text.write_text('Synthetic <comment>\n& context', encoding='utf-8')

    def command(self, action='create', *extra):
        command = ['comment-draft-' + action, '141', '941']
        if action != 'create':
            command.append('961')
        if action in ('create', 'edit'):
            command.extend(('--message-file', str(self.text)))
        return (*command, '--acknowledge-native-effects', *extra)

    def approved(self, action='create', *extra):
        command = self.command(action, *extra)
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def test_paginated_own_comments_all_attempts_never_query_peer_feedback_or_change_read_state(self):
        type(self).comments_page_size = 1
        result = self.invoke('submission-comments', '141', '941', '--all-attempts')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([row['id'] for row in json.loads(result.stdout)['comments']], ['961', '962', '963'])
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)
        self.assertEqual(self.comments_read_events, [])
        self.assertEqual(self.comments_assignment_views, [])
        self.assertEqual(self.comments_mutations, [])
        self.assertEqual(len(self.comments_queries), 3)
        self.assertTrue(all(row['variables']['userId'] == '7' for row in self.comments_queries))
        self.assertTrue(all('allComments: false' in row['query'] and 'peerReview: true' in row['query'] for row in self.comments_queries))
        result = self.invoke('submission-comments', '141', '941', '--include-content')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('synthetic-private-own-comment', result.stdout)

    def test_create_edit_publish_lifecycle_verifies_own_comment_and_never_turns_in_work(self):
        result = self.approved('create', '--file-id', '891', '--media-id', 'existing-media', '--media-type', 'audio')
        self.assertEqual(result.returncode, 0, result.stderr)
        created = json.loads(result.stdout)
        self.assertTrue(created['own_draft_presence_verified'])
        self.assertTrue(created['reported_file_ids_match_request'])
        self.assertTrue(created['reported_media_id_matches_request'])
        self.assertEqual(self.comments_rows[-1]['htmlComment'], '<p>Synthetic &lt;comment&gt;<br>&amp; context</p>')
        self.assertEqual(self.comments_read_events, [created['own_comment_id']])
        result = self.approved('edit')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['own_comment_state_verified'])
        self.assertEqual(self.comments_mutations[-1][2], {'comment': '<p>Synthetic &lt;comment&gt;<br>&amp; context</p>'})
        result = self.approved('publish')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(next(row for row in self.comments_rows if row['_id'] == '961')['draft'])
        self.assertEqual(self.comments_submission['attempt'], 2)
        self.assertEqual(self.comments_assignment_views, [])
        self.assertEqual(len(self.comments_mutations), 3)
        self.assertFalse(any('reviewerSubmissionId' in row['query'] for row in self.comments_queries))

    def test_group_graded_creation_is_forced_native_and_first_ack_can_be_another_group_copy(self):
        self.comments_assignment['groupCategoryId'] = '31'
        type(self).comments_foreign_group_ack = True
        result = self.invoke(*self.command())
        self.assertEqual(result.returncode, 1)
        self.assertIn('acknowledge-group', result.stderr)
        self.assertEqual(self.comments_mutations, [])
        result = self.approved('create', '--acknowledge-group-effects')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data['acknowledged_comment_is_own_copy'])
        self.assertFalse(data['native_collateral_effects_verified'])
        self.assertEqual(self.comments_group_callbacks, ['create-group-copy'])
        self.assertNotIn('981', result.stdout)
        self.assertFalse(self.comments_mutations[0][2]['variables']['input']['groupComment'])

    def test_publish_delete_group_callbacks_are_acknowledged_but_only_own_readback_is_asserted(self):
        for action in ('publish', 'delete'):
            with self.subTest(action=action):
                self.setUp()
                self.comments_rows[0]['_linked'] = 'old-group'
                result = self.approved(action)
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)
                self.assertFalse(data['native_collateral_effects_verified'])
                if action == 'delete':
                    self.assertTrue(data['own_draft_absence_verified'])
                    self.assertFalse(data['linked_group_absence_verified'])
                    self.assertFalse(any(row['_id'] in ('961', '965') for row in self.comments_rows))
                else:
                    self.assertTrue(all(not row['draft'] for row in self.comments_rows if row['_id'] in ('961', '965')))
                self.assertEqual(len(self.comments_mutations), 1)

    def test_stale_message_file_content_inventory_or_attempt_invalidates_approval(self):
        for mode in ('file', 'content', 'inventory', 'attempt'):
            with self.subTest(mode=mode):
                self.setUp()
                command = self.command('edit')
                preview = self.invoke(*command)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                if mode == 'file':
                    self.text.write_text('concurrent input', encoding='utf-8')
                elif mode == 'content':
                    self.comments_rows[0]['htmlComment'] = '<p>concurrent</p>'
                elif mode == 'inventory':
                    self.comments_rows.append(submission_comments.record('999'))
                else:
                    self.comments_submission['attempt'] = 3
                result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
                self.assertEqual(result.returncode, 1)
                self.assertEqual(self.comments_mutations, [])

    def test_sanitized_html_is_reported_as_difference_and_not_raw_storage_proof(self):
        type(self).comments_normalize = True
        result = self.approved()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data['reported_html_matches_request'])
        self.assertFalse(data['raw_storage_verified'])

    def test_denied_http_partial_ack_changed_account_attempt_or_policy_is_uncertain_without_retry(self):
        for mode in ('denied', 'http', 'partial', 'account', 'attempt', 'policy', 'readback'):
            with self.subTest(mode=mode):
                self.setUp()
                if mode == 'denied':
                    type(self).comments_denied = True
                elif mode == 'http':
                    type(self).comments_error_status = 500
                elif mode == 'partial':
                    type(self).comments_ack = {'data': {'createSubmissionComment': {'errors': [{'attribute': 'synthetic-private'}]}}}
                else:
                    setattr(type(self), {'account': 'comments_switch', 'attempt': 'comments_advance',
                                        'policy': 'comments_policy_after', 'readback': 'comments_read_after'}[mode], True)
                result = self.approved()
                self.assertEqual(result.returncode, 1)
                self.assertIn('unverified', result.stderr)
                self.assertNotIn('synthetic-private', result.stdout + result.stderr)
                self.assertEqual(len(self.comments_mutations), 1)

    def test_published_foreign_and_missing_submission_are_never_mutation_authority(self):
        self.comments_rows[0]['draft'] = False
        result = self.invoke(*self.command('edit'))
        self.assertEqual(result.returncode, 1)
        self.setUp()
        self.comments_submission['userId'] = '8'
        result = self.invoke(*self.command())
        self.assertEqual(result.returncode, 1)
        self.setUp()
        type(self).comments_submission = None
        result = self.invoke('submission-comments', '141', '941')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['inventory_status'], 'unknown_no_accessible_submission')
        result = self.invoke(*self.command())
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.comments_mutations, [])

    def test_page_cap_and_invalid_acknowledgements_never_mutate_or_bypass_pagination(self):
        type(self).comments_page_size = 1
        result = self.invoke(*self.command('delete', '--max-pages', '1'))
        self.assertEqual(result.returncode, 1)
        self.assertIn('page cap', result.stderr)
        self.assertEqual(self.comments_mutations, [])
        result = self.invoke('comment-draft-delete', '141', '941', '961')
        self.assertEqual(result.returncode, 1)
        self.assertIn('acknowledge-native', result.stderr)
        self.assertEqual(self.comments_mutations, [])

    def test_offline_navigation_and_brief_are_private_and_use_canvas(self):
        for command in (('help', 'comment-draft-create', '--format', 'brief'), ('schema', 'submission-comments')):
            result = self.invoke(*command)
            self.assertEqual(result.returncode, 0, result.stderr)
        result = self.invoke('submission-comments', '141', '941', '--include-content', '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertEqual(self.comments_mutations, [])
