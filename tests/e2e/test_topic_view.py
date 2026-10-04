"""Installed native own-view workflows; all records and mutations are synthetic."""

import copy
import json

from . import topic_view
from .fixture import CanvasFixture


class TopicViewE2E(CanvasFixture):
    def setUp(self):
        topic_view.initialize(type(self), enabled=True)

    def command(self, *extra, read=False):
        return ('topic-view' if read else 'topic-view-set', '131', '931',
                '--acknowledge-participant-initialization', *(() if read else ('--sort-order', 'asc')), *extra)

    def approved(self, *extra):
        preview = self.invoke(*self.command(*extra), '--format', 'json')
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*self.command(*extra), '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def test_native_read_requires_ack_before_requests_and_metadata_read_precedes_participant_initialization(self):
        before = len(self.calls)
        denied = self.invoke('topic-view', '131', '931')
        self.assertEqual(denied.returncode, 1)
        self.assertEqual(self.calls[before:], [])
        result = self.invoke(*self.command(read=True))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['native_query_may_initialize_participant'])
        self.assertEqual(data['topic_view']['reported']['sort_order'], 'desc')
        self.assertTrue(self.view_initialized)
        self.assertFalse(self.view_own['read'])
        self.assertFalse(self.view_own['subscribed'])
        self.assertEqual(self.view_mutations, [])
        self.assertEqual(self.calls[before:], [('GET', '/api/v1/users/self/profile'),
                                              ('POST', '/api/graphql'), ('POST', '/api/graphql'),
                                              ('GET', '/api/v1/users/self/profile')])
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)

    def test_preview_can_materialize_native_own_author_defaults_but_is_not_a_selected_preference_mutation(self):
        type(self).view_author = 7
        result = self.invoke(*self.command('--expanded'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.view_own['subscribed'])
        self.assertFalse(self.view_own['read'])
        self.assertTrue(self.view_own['plannerCacheCleared'])
        self.assertEqual(self.view_mutations, [])
        data = json.loads(result.stdout)
        self.assertTrue(data['dry_run'])
        self.assertTrue(data['native_query_may_initialize_participant'])
        self.assertEqual(data['body']['variables']['input'], {'discussionTopicId': '931', 'sortOrder': 'asc', 'expanded': True})
        self.assertNotIn('synthetic-private', result.stdout)

    def test_selected_values_mutate_once_with_independent_readback_and_no_shared_or_marker_change(self):
        self.invoke(*self.command(read=True))
        topic = copy.deepcopy(self.view_topic)
        state = {key: value for key, value in self.view_own.items() if key not in ('sortOrder', 'expanded', 'showPinnedEntries')}
        result = self.approved('--expanded', '--no-show-pinned-entries')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['mutation_acknowledged'])
        self.assertEqual(len(self.view_mutations), 1)
        self.assertEqual(self.view_mutations[0], {'discussionTopicId': '931', 'sortOrder': 'asc',
                                                'expanded': True, 'showPinnedEntries': False})
        self.assertEqual(self.view_topic, topic)
        self.assertEqual({key: value for key, value in self.view_own.items() if key in state}, state)
        self.assertFalse(data['verification']['sort_order']['stored_override_verified'])
        self.assertTrue(data['verification']['show_pinned_entries']['stored_override_verified'])
        self.assertEqual(self.view_query_count, 7)
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)

    def test_omission_preserves_and_explicit_null_reset_inherits_but_does_not_prove_raw_storage(self):
        self.invoke(*self.command(read=True))
        self.view_own.update(sortOrder='asc', expanded=True, showPinnedEntries=True)
        result = self.approved()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.view_own['expanded'])
        self.assertTrue(self.view_own['showPinnedEntries'])
        reset = ('topic-view-set', '131', '931', '--sort-order', 'inherit', '--inherit-expansion',
                 '--clear-pinned-entry-preference', '--acknowledge-participant-initialization')
        preview = self.invoke(*reset)
        result = self.invoke(*reset, '--yes', '--confirm', json.loads(preview.stdout)['confirm'], '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.view_mutations[-1], {'discussionTopicId': '931', 'sortOrder': None, 'expanded': None, 'showPinnedEntries': None})
        self.assertIn('sort_order=desc', result.stdout)
        self.assertIn('Raw saved sort/expansion overrides are not verified', result.stdout)

    def test_locked_preferences_remain_masked_and_storage_unverified_even_when_native_save_is_ignored(self):
        self.view_topic.update(sortOrderLocked=True, expandedLocked=True, expanded=True)
        type(self).view_ignored = {'sortOrder', 'expanded'}
        result = self.approved('--no-expanded')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['masked_by_shared_locks'], ['sort_order', 'expanded'])
        self.assertIsNone(self.view_own['sortOrder'])
        self.assertEqual(data['topic_view']['reported']['sort_order'], 'desc')
        self.assertFalse(data['verification']['sort_order']['stored_override_verified'])
        self.assertEqual(len(self.view_mutations), 1)

    def test_native_group_context_uses_read_permission_without_manager_or_reply_authority(self):
        self.view_topic.update(contextType='Group')
        self.view_topic['permissions'].update(update=False, reply=False)
        result = self.approved('--context', 'group')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['topic_view']['context_type'], 'group')
        self.assertEqual(len(self.view_mutations), 1)

    def test_foreign_or_denied_metadata_never_initializes_participant_or_mutates(self):
        for patch in ({'_id': '932'}, {'contextId': '132'}, {'contextType': 'Group'},
                      {'permissions': {'read': False, 'update': True}}, {'sortOrderLocked': 'false'}):
            self.setUp()
            self.view_topic.update(patch)
            result = self.invoke(*self.command())
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertFalse(self.view_initialized)
            self.assertEqual(self.view_mutations, [])
            self.assertNotIn('synthetic-private', result.stdout + result.stderr)

    def test_stale_account_own_or_shared_confirmation_prevents_mutation(self):
        for mode in ('account', 'own', 'shared'):
            self.setUp()
            preview = self.invoke(*self.command())
            if mode == 'account':
                type(self).view_viewer = 8
            elif mode == 'own':
                self.view_own['sortOrder'] = 'asc'
            else:
                self.view_topic['expandedLocked'] = True
            result = self.invoke(*self.command(), '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertEqual(result.returncode, 1)
            self.assertEqual(self.view_mutations, [])

    def test_auth_http_and_graphql_partial_errors_fail_without_retry_or_private_response(self):
        for mode in (401, 403, 429, 302, 500, 'partial'):
            self.setUp()
            type(self).view_query_error = mode
            before = len(self.calls)
            result = self.invoke(*self.command())
            self.assertEqual(result.returncode, 1)
            self.assertEqual(self.calls[before:].count(('POST', '/api/graphql')), 1)
            self.assertEqual(self.view_mutations, [])
            self.assertNotIn('synthetic-private', result.stdout + result.stderr)

    def test_partial_ignored_and_failed_after_apply_mutations_never_report_success_or_repeat(self):
        for mode in ('ignored', 'partial', 'error_after_apply', 'denied', 'account', 'shared'):
            self.setUp()
            if mode == 'ignored':
                type(self).view_ignored = {'sortOrder'}
            elif mode == 'partial':
                type(self).view_ack = {'errors': [{'attribute': 'synthetic-private'}]}
            elif mode == 'error_after_apply':
                type(self).view_ack = mode
            elif mode == 'denied':
                type(self).view_post_error = 403
            elif mode == 'account':
                type(self).view_account_after = True
            else:
                type(self).view_shared_after = True
            result = self.approved()
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertEqual(len(self.view_mutations), 1)
            self.assertIn('repeating', result.stderr)
            self.assertNotIn('synthetic-private', result.stdout + result.stderr)

    def test_read_and_write_navigation_and_brief_labels_are_accurate(self):
        read = self.invoke('help', 'topic-view')
        write = self.invoke('help', 'topic-view-set')
        self.assertEqual(json.loads(read.stdout)['safety'], 'Canvas queries (server-side effects possible)')
        self.assertEqual(json.loads(write.stdout)['safety'], 'Canvas writes (preview-first)')
        result = self.invoke(*self.command(read=True), '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Own view for course 131 topic 931', result.stdout)
        self.assertIn('queries can initialize', result.stdout)
