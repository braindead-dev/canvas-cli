"""Six installed native state controls against synthetic TLS courses and groups."""

import json

from . import topic_management
from .fixture import CanvasFixture

STATES = {'publish': ('published', True), 'unpublish': ('published', False),
          'close': ('locked', True), 'open': ('locked', False), 'pin': ('pinned', True), 'unpin': ('pinned', False)}


class TopicStatesE2E(CanvasFixture):
    def setUp(self):
        self.reset()

    def reset(self):
        topic_management.initialize(type(self), enabled=True)
        type(self).topic_state_enabled = True
        type(self).topic_moderator = True
        self.managed_topics[901].update(can_unpublish=True, can_lock=True, comments_disabled=False, position=2)
        self.managed_topics[902].update(pinned=True, position=3)

    def command(self, action='close', *, group=False):
        return ('topic-' + action, '119' if group else '111', '901', '--context', 'group' if group else 'course',
                '--acknowledge-shared-topic',
                *(('--acknowledge-topic-ordering-change',) if action in ('pin', 'unpin') else ()))

    def prepare(self, action):
        field, value = STATES[action]
        self.managed_topics[901][field] = not value

    def approved(self, command):
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def writes(self, before):
        return [row for row in self.calls[before:] if row[0] != 'GET']

    def test_six_controls_have_one_field_previews_full_pagination_and_no_peer_or_role_reads(self):
        for action, (field, value) in STATES.items():
            self.reset()
            self.prepare(action)
            before = len(self.calls)
            result = self.invoke(*self.command(action), '--format', 'brief')
            self.assertEqual(result.returncode, 0, result.stderr)
            preview = json.loads(result.stdout)
            self.assertEqual(preview['body'], {field: value})
            self.assertEqual(preview['topic_state_action'], action)
            self.assertTrue(any('page=2' in route for _, route in self.calls[before:]))
            self.assertNotIn('synthetic-private', result.stdout)
            self.assertEqual(self.writes(before), [])
            self.assertFalse(any('/entries' in route or '/view' in route or '/permissions' in route
                                 for _, route in self.calls[before:]))

    def test_six_controls_have_one_put_and_independent_state_inventory_proof_without_posting(self):
        for action, (field, value) in STATES.items():
            self.reset()
            self.prepare(action)
            before = len(self.calls)
            result = self.approved(self.command(action, group=action in ('open', 'publish', 'pin')))
            self.assertEqual(result.returncode, 0, (action, result.stderr))
            data = json.loads(result.stdout)
            self.assertTrue(data['topic_state']['verified'])
            self.assertIs(data['edited_topic'][field], value)
            prefix = 'groups/119' if action in ('open', 'publish', 'pin') else 'courses/111'
            self.assertEqual(self.writes(before), [('PUT', f'/api/v1/{prefix}/discussion_topics/901?no_verifiers=true')])
            self.assertIn('/' + prefix + '/', data['edited_topic']['html_url'])
            self.assertEqual(self.topic_notifications, [901])
            self.assertFalse(self.topic_attachment_deleted)
            self.assertEqual(self.topic_entries, [{'id': 991, 'message': 'synthetic-private-peer-reply'}])
            self.assertEqual(self.managed_topics[901]['message'], '<p>synthetic-private-prior-prompt</p>')
            self.assertNotIn('synthetic-private', result.stdout)

    def test_native_draft_eligibility_is_not_a_total_reply_count_or_ownership_heuristic(self):
        self.managed_topics[901].update(discussion_subentry_count=4, author={'id': 8})
        result = self.approved(self.command('unpublish'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['edited_topic']['published'])
        self.reset()
        self.managed_topics[901]['can_unpublish'] = False
        before = len(self.calls)
        result = self.invoke(*self.command('unpublish'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('eligibility', result.stderr)
        self.assertEqual(self.writes(before), [])

    def test_reopening_closing_schedule_requires_acknowledgement_and_kept_schedule_is_uncertain(self):
        self.managed_topics[901].update(locked=True, lock_at='2026-11-01T12:00:00Z')
        before = len(self.calls)
        result = self.invoke(*self.command('open'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('closing-schedule-removal', result.stderr)
        self.assertEqual(self.writes(before), [])
        command = (*self.command('open'), '--acknowledge-closing-schedule-removal', '--format', 'brief')
        result = self.approved(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Native locked=false verified', result.stdout)
        self.assertIn('Closing schedule cleared', result.stdout)
        self.assertIsNone(self.managed_topics[901]['lock_at'])
        self.reset()
        self.managed_topics[901].update(locked=True, lock_at='2026-11-01T12:00:00Z')
        type(self).topic_state_keep_schedule = True
        before = len(self.calls)
        result = self.approved(command)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('may already have succeeded', result.stderr)
        self.assertEqual(len(self.writes(before)), 1)
        self.assertFalse(self.managed_topics[901]['locked'])
        self.assertIsNotNone(self.managed_topics[901]['lock_at'])

    def test_unpin_reports_other_visible_position_changes_without_private_titles_or_causal_claim(self):
        result = self.approved(self.command('unpin'))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['observed_inventory_changes']['changed'],
                         [{'id': 901, 'fields': ['pinned', 'position']}, {'id': 902, 'fields': ['position']}])
        self.assertNotIn('title', str(data['observed_inventory_changes']))
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertIn('not attributed exclusively', data['note'])

    def test_publish_verifies_native_flag_not_immediate_availability_or_future_job_completion(self):
        self.managed_topics[901].update(published=False, delayed_post_at='2026-11-01T12:00:00Z')
        result = self.approved(self.command('publish'))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['edited_topic']['published'])
        self.assertEqual(data['edited_topic']['delayed_post_at'], '2026-11-01T12:00:00Z')
        self.assertIn('availability/future jobs', data['note'])

    def test_state_write_can_legitimately_remove_future_edit_permission_but_not_identity_proof(self):
        type(self).topic_state_lose_edit = True
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['edited_topic']['permissions']['update'])

    def test_stale_states_eligibility_content_inventory_identity_scope_and_audience_never_put(self):
        for mode in ('state', 'eligibility', 'content', 'inventory', 'identity', 'scope', 'audience', 'permission'):
            self.reset()
            command = self.command()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            row = self.managed_topics[901]
            if mode == 'state':
                row['locked'] = True
            elif mode == 'eligibility':
                row['can_lock'] = False
            elif mode == 'content':
                row['message'] = 'Changed'
            elif mode == 'inventory':
                self.managed_topics[902]['position'] += 1
            elif mode == 'identity':
                type(self).topic_viewer = 8
            elif mode == 'scope':
                self.topic_context['name'] = 'Changed'
            elif mode == 'audience':
                row['ungraded_discussion_overrides'] = []
            else:
                row['permissions']['update'] = False
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, (mode, result.stderr))
            self.assertEqual(result.stdout, '')
            self.assertEqual(self.writes(before), [])

    def test_native_denials_ignored_states_and_unverified_outcomes_never_retry_or_cleanup(self):
        for mode in ('denial', 'ignored', 'bad_ack', 'readback', 'readback_denied', 'account', 'hidden', 'inventory_denied'):
            self.reset()
            if mode == 'denial':
                type(self).topic_denied = True
            elif mode == 'ignored':
                type(self).topic_ignore = True
            elif mode == 'bad_ack':
                type(self).topic_ack_patch = {'id': 902, 'secret': 'synthetic-private-ack'}
            elif mode == 'readback':
                type(self).topic_readback_patch = {'locked': False}
            elif mode == 'readback_denied':
                type(self).topic_readback_denied = True
            elif mode == 'account':
                type(self).topic_account_changed = True
            elif mode == 'hidden':
                type(self).topic_state_hide_after = True
            else:
                type(self).topic_state_inventory_denied = True
            before = len(self.calls)
            result = self.approved(self.command())
            self.assertNotEqual(result.returncode, 0, (mode, result.stderr))
            self.assertEqual(result.stdout, '')
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)

    def test_acknowledgements_noops_native_eligibility_and_pagination_never_put(self):
        before = len(self.calls)
        for command in (('topic-close', '111', '901'), ('topic-unpin', '111', '901', '--acknowledge-shared-topic'),
                        (*self.command(), '--max-pages', '1'), self.command('open')):
            result = self.invoke(*command)
            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.writes(before), [])
        self.managed_topics[901]['can_lock'] = False
        result = self.invoke(*self.command())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('eligibility', result.stderr)
        self.assertEqual(self.writes(before), [])
