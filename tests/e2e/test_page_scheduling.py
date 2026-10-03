"""Installed command, native schedule/cancel callbacks and synthetic HTTPS only."""

import json

from . import page_scheduling
from .fixture import CanvasFixture


class PageSchedulingE2E(CanvasFixture):
    def setUp(self):
        page_scheduling.initialize(type(self), enabled=True)

    def command(self, *, cancel=False):
        return ('page-schedule', '107', '1001', '--acknowledge-shared-page',
                *(('--cancel',) if cancel else ('--publish-at', '2030-10-01T10:00:00-07:00')))

    def approve(self, *, cancel=False):
        command = self.command(cancel=cancel)
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def writes(self, since):
        return [row for row in self.calls[since:] if row[0] != 'GET']

    def test_installed_preview_private_projection_exact_id_and_full_pagination(self):
        before = len(self.calls)
        result = self.invoke(*self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['method'], 'PUT')
        self.assertEqual(data['body'], {'wiki_page': {'publish_at': '2030-10-01T17:00:00+00:00', 'notify_of_update': False}})
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertTrue(any('page=2' in route for _, route in self.calls[before:]))
        result = self.invoke(*self.command(), '--max-pages', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Page limit', result.stderr)
        self.assertEqual(self.writes(before), [])

    def test_installed_one_put_normalizes_timestamp_unpublishes_and_preserves_content_and_front(self):
        before = len(self.calls)
        result = self.approve()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['scheduled_page']['publish_at'], '2030-10-01T17:00:00Z')
        self.assertFalse(data['scheduled_page']['published'])
        self.assertTrue(data['content_unchanged'])
        self.assertFalse(data['future_publication_verified'])
        self.assertTrue(self.page_records[1002]['front_page'])
        self.assertEqual(self.page_records[1002]['title'], 'Numeric slug')
        self.assertEqual(self.writes(before), [('PUT', '/api/v1/courses/107/pages/page_id:1001?no_verifiers=true')])
        self.assertNotIn('synthetic-private', result.stdout)

    def test_installed_cancel_draft_can_keep_native_revision_and_does_not_publish_now(self):
        self.page_records[1001].update(published=False, publish_at='2030-10-01T17:00:00Z')
        revision = self.page_revision_id
        result = self.approve(cancel=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertIsNone(data['scheduled_page']['publish_at'])
        self.assertFalse(data['scheduled_page']['published'])
        self.assertEqual(self.page_revision_id, revision)
        self.assertIn('cancel', data['operation'])
        self.assertEqual(self.page_write['wiki_page'], {'publish_at': None, 'notify_of_update': False})

    def test_installed_parser_missing_ack_naive_time_and_unsupported_group_make_no_remote_requests(self):
        for arguments in (('page-schedule', '107', '1001'),
                          ('page-schedule', '107', '1001', '--cancel', '--publish-at', '2030-01-01T12:00:00Z'),
                          (*self.command(), '--context', 'group')):
            before = len(self.calls)
            result = self.invoke(*arguments)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.calls[before:], [])
        for arguments in (('page-schedule', '107', '1001', '--cancel'),
                          ('page-schedule', '107', '1001', '--publish-at', '2030-01-01T12:00:00', '--acknowledge-shared-page')):
            before = len(self.calls)
            result = self.invoke(*arguments)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.calls[before:], [])

    def test_installed_permissions_feature_front_link_and_history_fail_before_put(self):
        for mode in ('manager', 'feature', 'feature_denied', 'front', 'linked', 'history'):
            page_scheduling.initialize(type(self), enabled=True)
            if mode == 'manager':
                self.page_permissions['manage_wiki_update'] = False
            elif mode == 'feature':
                self.schedule_feature['state'] = 'off'
            elif mode == 'feature_denied':
                type(self).schedule_feature_denied = True
            elif mode == 'front':
                self.page_records[1001]['front_page'] = True
            elif mode == 'linked':
                self.page_records[1001]['assignment'] = {'id': 83}
            else:
                type(self).page_history_allowed = False
            before = len(self.calls)
            result = self.invoke(*self.command())
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.writes(before), [])
            self.assertNotIn('synthetic-private', result.stderr)

    def test_installed_stale_source_root_flag_revision_inventory_and_account_never_put(self):
        for mode in ('body', 'flag', 'revision', 'inventory', 'account'):
            page_scheduling.initialize(type(self), enabled=True)
            preview = self.invoke(*self.command())
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'body':
                self.page_records[1001]['body'] = 'Changed'
            elif mode == 'flag':
                self.schedule_feature['locked'] = True
            elif mode == 'revision':
                type(self).page_revision_id = 4
            elif mode == 'inventory':
                self.page_records[1002]['title'] = 'Changed'
            else:
                type(self).page_viewer = 8
            before = len(self.calls)
            result = self.invoke(*self.command(), '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Preview changed', result.stderr)
            self.assertEqual(self.writes(before), [])

    def test_installed_denial_ignored_schedule_or_failed_verification_never_retries_or_repairs(self):
        for mode in ('denial', 'ignored', 'readback', 'foreign', 'published', 'body', 'feature', 'delete_race', 'missing_date'):
            page_scheduling.initialize(type(self), enabled=True)
            preview = self.invoke(*self.command())
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'denial':
                type(self).page_write_denied = True
            elif mode == 'ignored':
                self.page_ignored_fields.add('publish_at')
            elif mode == 'readback':
                type(self).page_readback_denied = True
            elif mode == 'foreign':
                self.page_ack_patch['page_id'] = 9999
            elif mode == 'published':
                self.page_ack_patch['published'] = True
            elif mode == 'body':
                self.page_readback_patch['body'] = 'Changed'
            elif mode == 'feature':
                type(self).schedule_feature_lost = True
            elif mode == 'delete_race':
                type(self).page_delete_race = True
            else:
                type(self).schedule_missing_ack_date = True
            before = len(self.calls)
            result = self.invoke(*self.command(), '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0)
            if mode != 'denial':
                self.assertIn('Could not verify', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)
            self.assertNotIn('synthetic-private', result.stdout + result.stderr)
