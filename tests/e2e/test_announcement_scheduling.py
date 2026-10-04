"""Installed course announcement date controls against independent synthetic HTTPS."""

import copy
import json

from . import announcement_authoring
from .fixture import CanvasFixture


class AnnouncementSchedulingE2E(CanvasFixture):
    def setUp(self):
        self.reset()

    def reset(self):
        announcement_authoring.initialize(type(self), enabled=True)
        self.announcement_context['time_zone'] = 'America/Los_Angeles'

    def command(self, *, dates=('--closes-at', '2099-10-02T12:00:00-07:00'), extra=()):
        return ('announcement-schedule', '123', '9', *dates, '--acknowledge-shared-announcement',
                '--acknowledge-broadcast', '--acknowledge-availability-change', *extra)

    def approved(self, command):
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def writes(self, before):
        return [call for call in self.calls[before:] if call[0] != 'GET']

    def test_full_posting_closing_and_clearing_lifecycle_has_one_put_each_and_no_content_or_peer_write(self):
        original = copy.deepcopy(self.announcements)
        before = len(self.calls)
        command = self.command(dates=('--post-at', '2099-10-01T19:00:00Z', '--closes-at', '2099-10-02T19:00:00Z'))
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertEqual(data['body'], {'delayed_post_at': '2099-10-01T19:00:00Z', 'lock_at': '2099-10-02T19:00:00Z',
                                        'is_announcement': True, 'lock_comment': True})
        self.assertIn('override', data['warning'])
        self.assertNotIn('synthetic-private', preview.stdout)
        self.assertEqual(self.writes(before), [])
        result = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(result.returncode, 0, result.stderr)
        dates = json.loads(result.stdout)['scheduled_announcement_dates']
        self.assertTrue(dates['verified'])
        self.assertFalse(dates['future_execution_verified'])
        self.assertFalse(dates['participant_visibility_verified'])
        self.assertFalse(dates['participant_reply_access_verified'])
        self.assertEqual(dates['observed_states']['locked'], {'before': True, 'after': False})
        result = self.approved(self.command(dates=('--clear-posting', '--clear-closing'), extra=('--format', 'brief')))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('lock_at: cleared', result.stdout)
        self.assertIn('Stored instants verified', result.stdout)
        self.assertIsNone(self.announcements[9]['delayed_post_at'])
        self.assertIsNone(self.announcements[9]['lock_at'])
        self.assertTrue(self.announcements[9]['published'])
        self.assertFalse(self.announcements[9]['locked'])
        for field in ('message', 'title', 'attachments', 'pinned', 'position', 'author'):
            self.assertEqual(self.announcements[9][field], original[9][field])
        self.assertEqual(self.announcements[10], original[10])
        self.assertEqual(len(self.writes(before)), 2)
        self.assertEqual(self.announcement_preference_writes, 0)
        self.assertFalse(any('/entries' in route or '/view' in route for _, route in self.calls[before:]))
        self.assertTrue(any('page=2' in route for _, route in self.calls[before:]))

    def test_past_dates_equivalent_offset_storage_global_lock_and_lost_edit_right_are_supported(self):
        result = self.approved(self.command(dates=('--closes-at', '2020-10-02T19:00:00Z')))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['edited_announcement']['locked'])
        self.reset()
        type(self).announcement_store_date_offset = type(self).announcement_force_lock = type(self).announcement_lose_update = True
        self.announcements[9]['comments_disabled'] = True
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['scheduled_announcement_dates']['stored']['lock_at'], '2099-10-02T19:00:00+00:00')
        self.assertTrue(data['edited_announcement']['locked'])
        self.assertFalse(data['edited_announcement']['permissions']['update'])
        self.assertTrue(data['scheduled_announcement_dates']['reported_context_comments_disabled'])

    def test_noop_group_empty_mixed_syntax_missing_consent_or_page_cap_never_mutates(self):
        for mode in ('noop', 'group', 'empty', 'consent', 'broadcast', 'shared', 'mixed', 'pages'):
            self.reset()
            command = self.command()
            if mode == 'noop':
                self.announcements[9]['lock_at'] = '2099-10-02T19:00:00+00:00'
            elif mode == 'group':
                command += ('--context', 'group')
            elif mode == 'empty':
                command = self.command(dates=())
            elif mode in ('consent', 'broadcast', 'shared'):
                flag = {'consent': '--acknowledge-availability-change', 'broadcast': '--acknowledge-broadcast',
                        'shared': '--acknowledge-shared-announcement'}[mode]
                command = tuple(value for value in command if value != flag)
            elif mode == 'mixed':
                command += ('--title', 'Unexpected text')
            else:
                command += ('--max-pages', '1')
            before = len(self.calls)
            result = self.invoke(*command)
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertEqual(result.stdout, '')
            self.assertEqual(self.writes(before), [])

    def test_preserved_date_ranges_midnight_and_missing_course_zone_are_refused(self):
        for mode in ('preserved_close', 'preserved_post', 'midnight', 'zone'):
            self.reset()
            command = self.command()
            if mode == 'preserved_close':
                self.announcements[9]['lock_at'] = '2099-10-02T19:00:00Z'
                command = self.command(dates=('--post-at', '2099-10-03T19:00:00Z'))
            elif mode == 'preserved_post':
                self.announcements[9]['delayed_post_at'] = '2099-10-02T19:00:00Z'
            elif mode == 'midnight':
                command = self.command(dates=('--closes-at', '2099-10-02T07:00:00Z'))
            else:
                self.announcement_context.pop('time_zone')
            before = len(self.calls)
            result = self.invoke(*command)
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertEqual(self.writes(before), [])

    def test_stale_dates_zone_content_eligibility_inventory_or_account_invalidate_digest(self):
        for mode in ('date', 'zone', 'content', 'rights', 'inventory', 'account'):
            self.reset()
            command = self.command()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'date':
                self.announcements[9]['delayed_post_at'] = '2099-10-01T19:00:00Z'
            elif mode == 'zone':
                self.announcement_context['time_zone'] = 'UTC'
            elif mode == 'content':
                self.announcements[9]['message'] = '<p>Changed prior content</p>'
            elif mode == 'rights':
                self.announcements[9]['permissions']['update'] = False
            elif mode == 'inventory':
                self.announcements[10]['title'] = 'Changed other announcement'
            else:
                type(self).announcement_viewer = 8
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertEqual(self.writes(before), [])

    def test_ignored_partial_shifted_dates_wrong_ack_and_inaccessible_readback_are_not_repaired(self):
        for mode in ('ignored', 'partial', 'shift', 'ack', 'read', 'inventory', 'context', 'account'):
            self.reset()
            command = self.command(dates=('--post-at', '2099-10-01T19:00:00Z', '--closes-at', '2099-10-02T19:00:00Z'))
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'ignored':
                type(self).announcement_ignore_date = True
            elif mode == 'partial':
                type(self).announcement_ignored_dates = {'lock_at'}
            elif mode == 'shift':
                type(self).announcement_shift_date = True
            elif mode == 'ack':
                type(self).announcement_ack_patch = {'is_announcement': False}
            elif mode == 'read':
                type(self).announcement_read_denied = True
            elif mode == 'inventory':
                type(self).announcement_inventory_denied = True
            elif mode == 'context':
                type(self).announcement_context_changed = True
            else:
                type(self).announcement_account_changed = True
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertIn('may already have succeeded', result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)

    def test_native_denial_is_a_single_safe_error_not_a_retry_or_raw_response_dump(self):
        command = self.command()
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        type(self).announcement_denied = True
        before = len(self.calls)
        result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('synthetic-private', result.stderr)
        self.assertEqual(len(self.writes(before)), 1)
        self.assertEqual(self.announcement_mutations, [])
