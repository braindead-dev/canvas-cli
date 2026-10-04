"""Installed metadata inspection and one-comment acknowledgement over synthetic HTTPS."""

import json

from . import feedback_comments
from .fixture import CanvasFixture


class FeedbackCommentsE2E(CanvasFixture):
    def setUp(self):
        feedback_comments.initialize(type(self), enabled=True)

    def approved(self, identifier='961', *extra):
        command = ('feedback-comment-mark-read', '141', '941', identifier, '--acknowledge-feedback-indicators', *extra)
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def test_native_filters_and_pagination_expose_only_visible_published_metadata(self):
        result = self.invoke('feedback-comments', '141', '941', '--all-attempts')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual([row['id'] for row in data['comments']], ['961', '962', '963'])
        self.assertEqual(data['selected_attempts'], [1, 2])
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)
        self.assertEqual(self.feedback_mutations, [])
        self.assertEqual(self.feedback_viewed, set())
        self.assertTrue(all(query['variables']['userId'] == '7' for query in self.feedback_queries))
        self.assertTrue(all('peerReview: false' in query['query'] and 'allComments: false' in query['query'] for query in self.feedback_queries))
        self.assertFalse(any(value in query['query'] for query in self.feedback_queries for value in ('htmlComment', 'author ', 'score', 'annotationContext')))

    def test_one_exact_comment_write_has_separate_readback_and_no_global_marking(self):
        result = self.approved('963')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['effective_readback_verified'])
        self.assertFalse(data['viewed_row_storage_verified'])
        self.assertFalse(data['coursework_completion_requested'])
        self.assertEqual(self.feedback_viewed, {'963'})
        self.assertEqual(self.feedback_aggregate, 'unread')
        self.assertEqual(len(self.feedback_mutations), 1)
        self.assertEqual(self.feedback_mutations[0]['variables'], {'input': {'submissionId': '741', 'submissionCommentIds': ['963']}})
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)

    def test_old_attempt_and_zero_one_bucket_are_explicit_targets(self):
        result = self.approved('962', '--attempt', '0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.feedback_viewed, {'962'})

    def test_masked_effective_read_does_not_become_claim_of_viewed_row_storage(self):
        type(self).feedback_aggregate = 'read'
        type(self).feedback_ignore = True
        result = self.approved()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['viewed_row_storage_verified'])
        self.assertEqual(self.feedback_viewed, set())

    def test_draft_foreign_missing_or_null_submission_is_not_marking_authority(self):
        for target in ('964', '965', '999'):
            result = self.invoke('feedback-comment-mark-read', '141', '941', target, '--acknowledge-feedback-indicators')
            self.assertEqual(result.returncode, 1)
        type(self).feedback_submission = None
        result = self.invoke('feedback-comments', '141', '941')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['inventory_status'], 'unknown_no_accessible_submission')
        self.assertEqual(self.feedback_mutations, [])

    def test_truncated_and_malformed_connections_are_errors_not_empty_feedback(self):
        result = self.invoke('feedback-comments', '141', '941', '--max-pages', '1')
        self.assertEqual(result.returncode, 1)
        type(self).feedback_page_patch = {'hasNextPage': 'true'}
        result = self.invoke('feedback-comments', '141', '941')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.feedback_mutations, [])

    def test_uncertain_acknowledgement_denial_or_post_write_race_never_retries(self):
        for mode in ('denied', 'ignored', 'ack', 'account', 'attempt', 'policy', 'readback'):
            with self.subTest(mode=mode):
                self.setUp()
                if mode == 'ack':
                    type(self).feedback_ack = {'data': {'markSubmissionCommentsRead': {'errors': None, 'submissionComments': []}}}
                else:
                    setattr(type(self), {'denied': 'feedback_denied', 'ignored': 'feedback_ignore', 'account': 'feedback_switch',
                                        'attempt': 'feedback_advance', 'policy': 'feedback_policy_after', 'readback': 'feedback_read_after'}[mode], True)
                result = self.approved()
                self.assertEqual(result.returncode, 1)
                self.assertIn('unverified', result.stderr)
                self.assertNotIn('synthetic-private', result.stdout + result.stderr)
                self.assertEqual(len(self.feedback_mutations), 1)

    def test_stale_marker_requires_fresh_preview_without_mutation(self):
        command = ('feedback-comment-mark-read', '141', '941', '961', '--acknowledge-feedback-indicators')
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.feedback_viewed.add('961')
        result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.feedback_mutations, [])
