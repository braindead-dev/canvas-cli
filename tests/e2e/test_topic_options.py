"""Installed shared configuration against independent native TLS option semantics."""

import json

from . import topic_management
from .fixture import CanvasFixture


class TopicOptionsE2E(CanvasFixture):
    def setUp(self):
        self.reset()

    def reset(self):
        topic_management.initialize(type(self), enabled=True)
        type(self).topic_config_enabled = type(self).topic_state_enabled = True
        self.managed_topics[901].update(discussion_type='threaded', allow_rating=True, only_graders_can_rate=False,
                                        sort_order='asc', sort_order_locked=False, expanded=False, expanded_locked=False)

    def command(self, *options, group=False):
        return ('topic-configure', '119' if group else '111', '901', '--context', 'group' if group else 'course',
                '--acknowledge-shared-topic', *options)

    def approved(self, command):
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def writes(self, before):
        return [row for row in self.calls[before:] if row[0] != 'GET']

    def test_all_options_have_bounded_previews_and_exact_stored_values_in_native_course_or_group_context(self):
        choices = (('discussion_type', 'flat', ('--discussion-type', 'flat')),
                   ('require_initial_post', True, ('--require-initial-post', '--acknowledge-reply-visibility-change')),
                   ('allow_rating', False, ('--no-allow-rating',)), ('only_graders_can_rate', True, ('--only-graders-can-rate',)),
                   ('sort_order', 'desc', ('--sort-order', 'desc')), ('sort_order_locked', True, ('--sort-order-locked',)),
                   ('expanded', True, ('--expanded',)), ('expanded_locked', True, ('--expanded-locked',)))
        for field, value, flags in choices:
            self.reset()
            if field == 'expanded_locked':
                self.managed_topics[901]['expanded'] = True
            group = field in ('expanded', 'sort_order', 'discussion_type')
            command = self.command(*flags, group=group)
            before = len(self.calls)
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, (field, preview.stderr))
            self.assertEqual(json.loads(preview.stdout)['body'], {field: value})
            self.assertEqual(self.writes(before), [])
            self.assertTrue(any('page=2' in route for _, route in self.calls[before:]))
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertEqual(result.returncode, 0, (field, result.stderr))
            data = json.loads(result.stdout)
            self.assertEqual(data['configured_topic_settings']['values'], {field: value})
            self.assertTrue(data['configured_topic_settings']['verified'])
            prefix = 'groups/119' if group else 'courses/111'
            self.assertEqual(self.writes(before), [('PUT', f'/api/v1/{prefix}/discussion_topics/901?no_verifiers=true')])
            self.assertEqual(self.managed_topics[901][field], value)
            self.assertNotIn('synthetic-private', preview.stdout + result.stdout + result.stderr)
            self.assertFalse(any('/entries' in route or '/view' in route or '/permissions' in route
                                 for _, route in self.calls[before:]))

    def test_combined_fields_preserve_prompt_attachment_replies_and_other_topics_without_reading_peer_posts(self):
        before = len(self.calls)
        command = self.command('--discussion-type', 'side_comment', '--require-initial-post',
                               '--acknowledge-reply-visibility-change', '--no-allow-rating', '--only-graders-can-rate',
                               '--sort-order', 'desc', '--sort-order-locked', '--expanded', '--expanded-locked')
        result = self.approved(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)['configured_topic_settings']['values']
        self.assertEqual(len(values), 8)
        self.assertEqual(self.writes(before), [('PUT', '/api/v1/courses/111/discussion_topics/901?no_verifiers=true')])
        self.assertEqual(self.topic_notifications, [901])
        self.assertEqual(self.managed_topics[901]['message'], '<p>synthetic-private-prior-prompt</p>')
        self.assertEqual(self.managed_topics[901]['attachments'][0]['id'], 881)
        self.assertEqual(self.topic_entries, [{'id': 991, 'message': 'synthetic-private-peer-reply'}])
        self.assertFalse(self.topic_attachment_deleted)
        self.assertEqual(self.managed_topics[902]['title'], 'Synthetic other topic')
        self.assertNotIn('synthetic-private', result.stdout)

    def test_reply_visibility_changes_require_separate_acknowledgement_and_native_groups_refuse_post_first_locally(self):
        for value in (True, False):
            self.reset()
            self.managed_topics[901]['require_initial_post'] = not value
            flag = '--require-initial-post' if value else '--no-require-initial-post'
            before = len(self.calls)
            result = self.invoke(*self.command(flag))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('reply-visibility-change', result.stderr)
            self.assertEqual(self.calls[before:], [])
            result = self.approved(self.command(flag, '--acknowledge-reply-visibility-change'))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIs(self.managed_topics[901]['require_initial_post'], value)
        before = len(self.calls)
        result = self.invoke(*self.command('--require-initial-post', '--acknowledge-reply-visibility-change', group=True))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('group topic updates', result.stderr)
        self.assertEqual(self.calls[before:], [])

    def test_native_expansion_constraint_combines_selected_and_current_state_without_assuming_defaults(self):
        before = len(self.calls)
        result = self.invoke(*self.command('--expanded-locked'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('collapsed', result.stderr)
        self.assertEqual(self.writes(before), [])
        result = self.approved(self.command('--expanded', '--expanded-locked'))
        self.assertEqual(result.returncode, 0, result.stderr)
        before = len(self.calls)
        result = self.invoke(*self.command('--no-expanded'))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.writes(before), [])
        result = self.approved(self.command('--no-expanded', '--no-expanded-locked', '--format', 'brief'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Native options verified: expanded, expanded_locked', result.stdout)
        self.assertFalse(self.managed_topics[901]['expanded_locked'])
        self.assertFalse(self.managed_topics[901]['expanded'])

    def test_disabled_native_granular_feature_does_not_make_false_granular_permissions_a_global_denial(self):
        type(self).topic_edit_options = type(self).topic_edit_views = False
        result = self.approved(self.command('--no-allow-rating', '--sort-order', 'desc'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.managed_topics[901]['allow_rating'])
        self.assertEqual(self.managed_topics[901]['sort_order'], 'desc')

    def test_native_granular_permission_stripping_is_not_success_and_partial_writes_never_retry_or_rollback(self):
        for field in ('topic_edit_options', 'topic_edit_views'):
            self.reset()
            type(self).topic_granular_options_enabled = True
            setattr(type(self), field, False)
            before = len(self.calls)
            result = self.approved(self.command('--no-allow-rating', '--sort-order', 'desc'))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('may already have succeeded', result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertEqual(len(self.writes(before)), 1)
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual(self.managed_topics[901]['allow_rating'], field == 'topic_edit_options')
            self.assertEqual(self.managed_topics[901]['sort_order'], 'asc' if field == 'topic_edit_views' else 'desc')

    def test_configuration_can_legitimately_remove_future_edit_permission_without_losing_account_proof(self):
        type(self).topic_state_lose_edit = True
        result = self.approved(self.command('--no-allow-rating'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['edited_topic']['permissions']['update'])

    def test_stale_selected_settings_permissions_context_identity_audience_and_inventory_never_put(self):
        for mode in ('selected', 'dependent', 'permission', 'prompt', 'context', 'account', 'audience', 'inventory'):
            self.reset()
            command = self.command('--sort-order', 'desc')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            row = self.managed_topics[901]
            if mode == 'selected':
                row['sort_order'] = 'desc'
            elif mode == 'dependent':
                row['expanded'] = True
            elif mode == 'permission':
                row['permissions']['update'] = False
            elif mode == 'prompt':
                row['message'] = 'Changed'
            elif mode == 'context':
                self.topic_context['name'] = 'Changed'
            elif mode == 'account':
                type(self).topic_viewer = 8
            elif mode == 'audience':
                row['ungraded_discussion_overrides'] = []
            else:
                self.managed_topics[902]['position'] = 3
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, (mode, result.stderr))
            self.assertEqual(self.writes(before), [])

    def test_ignored_partial_foreign_and_unverified_results_have_one_put_without_secret_response_logging(self):
        for mode in ('ignored', 'partial', 'foreign', 'ack', 'readback', 'account', 'context', 'hidden', 'inventory', 'denial'):
            self.reset()
            if mode == 'ignored':
                type(self).topic_ignore = True
            elif mode == 'partial':
                type(self).topic_ignored_fields = {'sort_order'}
            elif mode == 'foreign':
                type(self).topic_ack_patch = {'id': 902, 'secret': 'synthetic-private-foreign-ack'}
            elif mode == 'ack':
                type(self).topic_ack_patch = {'sort_order': 'asc'}
            elif mode == 'readback':
                type(self).topic_readback_denied = True
            elif mode == 'account':
                type(self).topic_account_changed = True
            elif mode == 'context':
                type(self).topic_context['name'] = 'Changed before preview'
                type(self).topic_readback_patch = {'context_id': 112}
            elif mode == 'hidden':
                type(self).topic_state_hide_after = True
            elif mode == 'inventory':
                type(self).topic_state_inventory_denied = True
            else:
                type(self).topic_denied = True
            before = len(self.calls)
            result = self.approved(self.command('--sort-order', 'desc', '--no-allow-rating'))
            self.assertNotEqual(result.returncode, 0, (mode, result.stderr))
            self.assertEqual(result.stdout, '')
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)

    def test_unknown_missing_noop_or_incomplete_inventory_never_causes_a_write(self):
        before = len(self.calls)
        for flags in ((), ('--sort-order', 'inherit'), ('--discussion-type', 'unknown'), ('--sort-order', 'asc'),
                      ('--no-allow-rating', '--max-pages', '1')):
            result = self.invoke(*self.command(*flags))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.writes(before), [])
        self.managed_topics[901].pop('sort_order')
        result = self.invoke(*self.command('--sort-order', 'desc'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('current value', result.stderr)
        self.assertEqual(self.writes(before), [])
