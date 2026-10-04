"""Installed CLI feedback-indicator workflows with independent native HTTPS state."""

import json

from . import submission_attention
from .fixture import CanvasFixture


class SubmissionAttentionE2E(CanvasFixture):
    def setUp(self):
        submission_attention.initialize(type(self), enabled=True)

    def approved(self, *extra, action='submission-mark-read'):
        command = (action, '141', '941', '--acknowledge-feedback-indicators', *extra)
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def test_metadata_and_preference_reads_never_query_feedback_bodies_or_change_indicators(self):
        result = self.invoke('submission-attention', '141', '941', '--include-feedback-markers')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['preference_read_markers'], {'annotations': False, 'rubric-feedback': False})
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)
        self.assertEqual(self.attention_mutations, [])
        self.assertEqual(self.attention_viewed_comments, [])
        self.assertTrue(all(row['variables']['userId'] == '7' for row in self.attention_queries))
        self.assertFalse(any(word in row['query'] for row in self.attention_queries for word in ('score', 'grade ', 'commentsConnection', 'meets')))

    def test_overall_native_mark_read_can_legitimately_leave_aggregate_unread(self):
        result = self.approved()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data['aggregate_matches_requested_state'])
        self.assertTrue(data['mutation_acknowledged'])
        self.assertFalse(data['participation_item_storage_verified'])
        self.assertEqual(self.attention_items, {'grade': 'read', 'comment': 'unread', 'rubric': 'unread'})
        self.assertEqual(len(self.attention_mutations), 1)
        self.assertEqual(self.attention_submission['attempt'], 2)

    def test_item_surfaces_native_comment_viewed_effects_and_overall_unread_remain_distinct(self):
        for surface in ('grade', 'comment', 'rubric'):
            result = self.approved('--surface', surface)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.attention_items, {'grade': 'read', 'comment': 'read', 'rubric': 'read'})
        self.assertEqual(self.attention_viewed_comments, ['synthetic-visible-own', 'synthetic-visible-grader'])
        self.assertEqual(self.attention_preferences, {'document_annotations': False, 'rubric_assessments': False})
        result = self.approved(action='submission-mark-unread')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['aggregate_matches_requested_state'])
        self.assertEqual(self.attention_items['comment'], 'read')

    def test_preference_markers_are_independently_verified_without_clearing_participation_items(self):
        for surface in ('annotations', 'rubric-feedback'):
            result = self.approved('--surface', surface)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)['selected_preference_readback_verified'])
        self.assertEqual(self.attention_items, {'grade': 'unread', 'comment': 'unread', 'rubric': 'unread'})
        self.assertEqual(self.attention_preferences, {'document_annotations': True, 'rubric_assessments': True})
        self.assertEqual(self.attention_viewed_comments, [])

    def test_wrong_http_ack_denial_and_post_write_races_are_uncertain_without_retry(self):
        for mode in ('body', 'http', 'denied', 'account', 'attempt', 'policy', 'readback'):
            with self.subTest(mode=mode):
                self.setUp()
                if mode in ('body', 'http'):
                    type(self).attention_bad_ack = mode
                else:
                    setattr(type(self), {'denied': 'attention_denied', 'account': 'attention_switch', 'attempt': 'attention_advance',
                                        'policy': 'attention_policy_after', 'readback': 'attention_read_after'}[mode], True)
                result = self.approved()
                self.assertEqual(result.returncode, 1)
                self.assertIn('unverified', result.stderr)
                self.assertNotIn('synthetic-private', result.stdout + result.stderr)
                self.assertEqual(len(self.attention_mutations), 1)

    def test_ignored_or_malformed_preference_ack_never_becomes_verified_readback(self):
        for mode in ('ignore', 'ack'):
            self.setUp()
            if mode == 'ignore':
                type(self).attention_ignore = True
            else:
                type(self).attention_bad_ack = 'malformed'
            result = self.approved('--surface', 'annotations')
            self.assertEqual(result.returncode, 1)
            self.assertEqual(len(self.attention_mutations), 1)

    def test_missing_foreign_or_changed_scope_is_not_write_authority(self):
        type(self).attention_submission = None
        result = self.invoke('submission-attention', '141', '941', '--include-feedback-markers')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['attention_status'], 'unknown_no_accessible_submission')
        result = self.invoke('submission-mark-read', '141', '941', '--acknowledge-feedback-indicators')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.attention_mutations, [])
        self.setUp()
        command = ('submission-mark-read', '141', '941', '--acknowledge-feedback-indicators')
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.attention_items.update(grade='read', comment='read', rubric='read')
        result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertEqual(result.returncode, 1)
        self.assertIn('Preview changed', result.stderr)
        self.assertEqual(self.attention_mutations, [])

    def test_offline_help_and_brief_keep_outputs_metadata_only(self):
        result = self.invoke('help', 'submission-mark-read', '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('usage: canvas ', result.stdout)
        result = self.invoke('submission-attention', '141', '941', '--include-feedback-markers', '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)
