"""Installed marker changes with independent own-state and reply-access boundaries."""

import copy
import json

from . import topic_view
from .fixture import CanvasFixture


class TopicMarkerE2E(CanvasFixture):
    def setUp(self):
        topic_view.initialize(type(self), enabled=True)

    def command(self, *extra, read=False):
        return ('topic-view' if read else 'topic-view-set', '131', '931',
                '--acknowledge-participant-initialization', *extra)

    def approved(self, flag='--pinned-unread', *extra):
        command = self.command(flag, '--acknowledge-pinned-marker-change', *extra)
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def test_marker_ack_is_required_even_for_preview_and_before_all_requests(self):
        before = len(self.calls)
        result = self.invoke(*self.command('--pinned-unread'))
        self.assertEqual(result.returncode, 1)
        self.assertIn('acknowledge-pinned-marker-change', result.stderr)
        self.assertFalse(self.view_initialized)
        self.assertEqual(self.calls[before:], [])

    def test_default_is_not_fetched_and_opt_in_reads_native_false_without_peer_reads(self):
        result = self.invoke(*self.command(read=True))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('has_unread_pinned_entry', json.loads(result.stdout)['topic_view']['reported'])
        result = self.invoke(*self.command('--include-pinned-marker', read=True))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['topic_view']['reported']['has_unread_pinned_entry'])
        self.assertEqual(self.view_generation_requests, [])
        self.assertEqual(self.view_mutations, [])

    def test_true_then_false_marker_stores_exact_boolean_without_read_counts_subscription_or_other_preferences(self):
        self.invoke(*self.command(read=True))
        before = copy.deepcopy(self.view_own)
        topic = copy.deepcopy(self.view_topic)
        for flag, value in (('--pinned-unread', True), ('--no-pinned-unread', False)):
            result = self.approved(flag)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(self.view_mutations[-1], {'discussionTopicId': '931', 'hasUnreadPinnedEntry': value})
            self.assertEqual(self.view_own['hasUnreadPinnedEntry'], value)
            self.assertTrue(data['verification']['has_unread_pinned_entry']['stored_override_verified'])
            self.assertEqual({key: item for key, item in self.view_own.items() if key != 'hasUnreadPinnedEntry'},
                             {key: item for key, item in before.items() if key != 'hasUnreadPinnedEntry'})
            self.assertNotIn('synthetic-private', result.stdout + result.stderr)
        self.assertEqual(len(self.view_mutations), 2)
        self.assertEqual(self.view_topic, topic)
        self.assertEqual(self.view_generation_requests, [])

    def test_stale_marker_blocks_and_ignored_or_partial_mutation_is_never_retried(self):
        command = self.command('--pinned-unread', '--acknowledge-pinned-marker-change')
        preview = self.invoke(*command)
        self.view_own['hasUnreadPinnedEntry'] = True
        result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.view_mutations, [])
        for mode in ('ignored', 'partial', 'error_after_apply', 'denied'):
            self.setUp()
            if mode == 'ignored':
                type(self).view_ignored = {'hasUnreadPinnedEntry'}
            elif mode == 'partial':
                type(self).view_ack = {'errors': [{'attribute': 'synthetic-private'}]}
            elif mode == 'error_after_apply':
                type(self).view_ack = mode
            else:
                type(self).view_post_error = 403
            result = self.approved()
            self.assertEqual(result.returncode, 1)
            self.assertEqual(len(self.view_mutations), 1)
            self.assertNotIn('synthetic-private', result.stdout + result.stderr)

    def test_group_combined_preference_marker_mutation_is_own_only_and_requires_no_manager_rights(self):
        self.view_topic['contextType'] = 'Group'
        self.view_topic['permissions'].update(update=False, reply=False)
        result = self.approved('--pinned-unread', '--context', 'group', '--summary-enabled')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.view_mutations, [{'discussionTopicId': '931', 'summaryEnabled': True, 'hasUnreadPinnedEntry': True}])
        self.assertEqual(self.view_generation_requests, [])

    def test_omission_retains_existing_pinned_marker_and_does_not_include_it_in_preview(self):
        self.invoke(*self.command(read=True))
        self.view_own['hasUnreadPinnedEntry'] = True
        command = self.command('--expanded')
        preview = self.invoke(*command)
        data = json.loads(preview.stdout)
        self.assertNotIn('has_unread_pinned_entry', data['reported'])
        result = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.view_own['hasUnreadPinnedEntry'])
        self.assertNotIn('hasUnreadPinnedEntry', self.view_mutations[-1])
