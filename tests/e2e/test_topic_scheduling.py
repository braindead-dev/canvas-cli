"""Installed date controls against independent synthetic native publication callbacks."""

import json

from . import topic_management
from .fixture import CanvasFixture


class TopicSchedulingE2E(CanvasFixture):
    def setUp(self):
        self.reset()

    def reset(self):
        topic_management.initialize(type(self), enabled=True)
        type(self).topic_schedule_enabled = True
        self.topic_context['time_zone'] = 'America/Los_Angeles'

    def command(self, *extra, dates=('--closes-at', '2040-10-02T12:00:00-07:00')):
        return ('topic-schedule', '111', '901', *dates, '--acknowledge-shared-topic', '--acknowledge-availability-change', *extra)

    def approved(self, command):
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def writes(self, before):
        return [row for row in self.calls[before:] if row[0] != 'GET']

    def test_preview_has_selected_dates_course_zone_and_side_effect_ack_but_no_private_prompt_or_peer_reads(self):
        before = len(self.calls)
        result = self.invoke(*self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        preview = json.loads(result.stdout)
        self.assertEqual(preview['body'], {'lock_at': '2040-10-02T19:00:00Z'})
        self.assertEqual(preview['context']['time_zone'], 'America/Los_Angeles')
        self.assertIn('publish a draft', preview['warning'])
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertEqual(self.writes(before), [])
        self.assertTrue(any('page=2' in route for _, route in self.calls[before:]))
        self.assertFalse(any('/entries' in route or '/view' in route for _, route in self.calls[before:]))

    def test_one_native_put_exact_readback_preserves_prompt_attachments_pin_reply_and_other_topic(self):
        before = len(self.calls)
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['scheduled_topic_dates']['verified'])
        self.assertFalse(data['scheduled_topic_dates']['future_execution_verified'])
        self.assertEqual(data['scheduled_topic_dates']['stored'], {'lock_at': '2040-10-02T19:00:00Z'})
        self.assertEqual(self.writes(before), [('PUT', '/api/v1/courses/111/discussion_topics/901?no_verifiers=true')])
        self.assertEqual(self.managed_topics[901]['message'], '<p>synthetic-private-prior-prompt</p>')
        self.assertEqual(self.managed_topics[901]['attachments'][0]['id'], 881)
        self.assertTrue(self.managed_topics[901]['pinned'])
        self.assertEqual(self.managed_topics[901]['position'], 1)
        self.assertEqual(self.managed_topics[902]['title'], 'Synthetic other topic')
        self.assertEqual(self.topic_entries, [{'id': 991, 'message': 'synthetic-private-peer-reply'}])
        self.assertFalse(self.topic_attachment_deleted)
        self.assertNotIn('synthetic-private', result.stdout)

    def test_native_dates_publish_drafts_reopen_replies_and_can_lose_future_update_permission(self):
        self.managed_topics[901].update(published=False, locked=True)
        type(self).topic_state_lose_edit = True
        result = self.approved(self.command(dates=('--opens-at', '2040-10-01T19:00:00Z')))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['scheduled_topic_dates']['observed_states'],
                         {'published': {'before': False, 'after': True}, 'locked': {'before': True, 'after': False}})
        self.assertFalse(data['edited_topic']['permissions']['update'])
        self.assertIn('published', data['unrequested_changed_fields'])

    def test_explicit_clearing_past_closing_and_preserved_opening_do_not_require_future_only_dates(self):
        result = self.approved(self.command(dates=('--closes-at', '2020-10-02T19:00:00Z')))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['edited_topic']['locked'])
        self.reset()
        self.managed_topics[901].update(delayed_post_at='2040-10-01T19:00:00Z', lock_at='2040-10-02T19:00:00Z', locked=True)
        result = self.approved(self.command(dates=('--clear-opening', '--clear-closing')))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['scheduled_topic_dates']['stored'], {'delayed_post_at': None, 'lock_at': None})
        self.assertFalse(self.managed_topics[901]['locked'])
        self.reset()
        self.managed_topics[901]['delayed_post_at'] = '2040-10-01T19:00:00Z'
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.managed_topics[901]['delayed_post_at'], '2040-10-01T19:00:00Z')

    def test_noop_dates_do_not_reopen_or_publish_and_invalid_selected_preserved_ranges_never_put(self):
        self.managed_topics[901].update(lock_at='2040-10-02T19:00:00+00:00', locked=True, published=False)
        before = len(self.calls)
        result = self.invoke(*self.command())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already match', result.stderr)
        self.assertEqual(self.writes(before), [])
        self.assertFalse(self.managed_topics[901]['published'])
        for opening in ('2040-10-02T19:00:00Z', '2040-10-03T19:00:00Z'):
            self.reset()
            self.managed_topics[901]['delayed_post_at'] = opening
            before = len(self.calls)
            result = self.invoke(*self.command())
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('later than opening', result.stderr)
            self.assertEqual(self.writes(before), [])

    def test_midnight_and_unknown_zone_guard_precedes_native_end_of_day_rewrite(self):
        type(self).topic_schedule_midnight_rewrite = True
        for value in ('2040-10-02T00:00:00-07:00', '2040-10-02T07:00:00Z'):
            before = len(self.calls)
            result = self.invoke(*self.command(dates=('--closes-at', value)))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('course-midnight', result.stderr)
            self.assertEqual(self.writes(before), [])
        for zone in (None, 'not-a-zone'):
            self.reset()
            self.topic_context['time_zone'] = zone
            before = len(self.calls)
            result = self.invoke(*self.command())
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.writes(before), [])

    def test_missing_date_metadata_native_update_denial_and_graded_topics_do_not_write(self):
        for mode in ('missing_opening', 'missing_closing', 'permission', 'graded'):
            self.reset()
            if mode == 'permission':
                self.managed_topics[901]['permissions']['update'] = False
            elif mode == 'graded':
                self.managed_topics[901]['assignment_id'] = 81
            else:
                self.managed_topics[901].pop('delayed_post_at' if mode == 'missing_opening' else 'lock_at')
            before = len(self.calls)
            result = self.invoke(*self.command())
            self.assertNotEqual(result.returncode, 0, (mode, result.stderr))
            self.assertEqual(self.writes(before), [])

    def test_stale_account_zone_dates_state_prompt_audience_and_inventory_never_put(self):
        for mode in ('account', 'zone', 'date', 'state', 'prompt', 'audience', 'inventory'):
            self.reset()
            command = self.command()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'account':
                type(self).topic_viewer = 8
            elif mode == 'zone':
                self.topic_context['time_zone'] = 'UTC'
            elif mode == 'date':
                self.managed_topics[901]['delayed_post_at'] = '2040-10-01T19:00:00Z'
            elif mode == 'state':
                self.managed_topics[901]['locked'] = True
            elif mode == 'prompt':
                self.managed_topics[901]['message'] = 'Changed'
            elif mode == 'audience':
                self.managed_topics[901]['ungraded_discussion_overrides'] = []
            else:
                self.managed_topics[902]['title'] = 'Changed'
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, (mode, result.stderr))
            self.assertEqual(self.writes(before), [])

    def test_ignored_partial_shifted_unreadable_ack_and_zone_changes_after_write_fail_without_retry(self):
        for mode in ('ignored', 'partial', 'shifted', 'unreadable', 'malformed', 'account', 'zone', 'denied'):
            self.reset()
            if mode == 'ignored':
                type(self).topic_ignore = True
            elif mode == 'partial':
                type(self).topic_ignored_fields = {'lock_at'}
            elif mode == 'shifted':
                type(self).topic_ack_patch = type(self).topic_readback_patch = {'lock_at': '2040-10-02T22:00:00Z'}
            elif mode == 'unreadable':
                type(self).topic_readback_denied = True
            elif mode == 'malformed':
                type(self).topic_ack_patch = []
            elif mode == 'account':
                type(self).topic_account_changed = True
            elif mode == 'zone':
                type(self).topic_schedule_time_zone_after = 'UTC'
            else:
                type(self).topic_denied = True
            before = len(self.calls)
            result = self.approved(self.command(dates=('--opens-at', '2040-10-01T19:00:00Z', '--closes-at', '2040-10-02T19:00:00Z')))
            self.assertNotEqual(result.returncode, 0, (mode, result.stderr))
            self.assertEqual(result.stdout, '')
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)

    def test_local_flag_validation_partial_pagination_and_offline_help_never_mutate(self):
        before = len(self.calls)
        for command in (self.command(dates=()), self.command(dates=('--closes-at', '2040-10-02')),
                        self.command(dates=('--closes-at', '2040-10-02T12:00:00.1Z')),
                        self.command(dates=('--closes-at', '2040-10-02T12:00:00-00:00')),
                        self.command(dates=('--closes-at', '2040-10-02T12:00:00Z', '--clear-closing')),
                        self.command('--context', 'group'), self.command('--max-pages', '1'),
                        ('topic-schedule', '111', '901', '--clear-closing', '--acknowledge-shared-topic')):
            result = self.invoke(*command)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.writes(before), [])
        result = self.invoke('help', 'topic-schedule', '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('usage: canvas topic-schedule', result.stdout)

    def test_brief_output_labels_stored_dates_and_unverified_future_jobs(self):
        result = self.approved(self.command('--format', 'brief'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('lock_at: 2040-10-02T19:00:00Z', result.stdout)
        self.assertIn('future execution and student availability are not verified', result.stdout)
        self.assertNotIn('synthetic-private', result.stdout)
