"""Installed destructive attachment removal against independent synthetic HTTPS."""

import copy
import json

from . import announcement_authoring
from .fixture import CanvasFixture


class AnnouncementAttachmentE2E(CanvasFixture):
    def setUp(self):
        self.reset()

    def reset(self):
        announcement_authoring.initialize(type(self), enabled=True)
        self.announcements[9]['permissions']['attach'] = True

    def command(self, *extra, consent=True):
        return ('announcement-attachment-remove', '123', '9', '--acknowledge-shared-announcement',
                '--acknowledge-broadcast', *(('--acknowledge-attachment-removal',) if consent else ()), *extra)

    def approved(self, command):
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def writes(self, before):
        return [call for call in self.calls[before:] if call[0] != 'GET']

    def test_one_put_exact_attachment_clearing_and_preserved_lock_without_download_peer_or_rollback_requests(self):
        before = len(self.calls)
        original = copy.deepcopy(self.announcements)
        command = self.command()
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertEqual(data['body'], {'remove_attachment': True, 'is_announcement': True, 'lock_comment': True})
        self.assertEqual(data['removed_attachment_id'], 51)
        self.assertIn('soft-delete its file record', data['warning'])
        self.assertNotIn('synthetic-private', preview.stdout)
        self.assertEqual(self.writes(before), [])
        result = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        removal = data['announcement_attachment_removal']
        self.assertTrue(removal['attachment_list_cleared'])
        self.assertTrue(removal['verified'])
        self.assertFalse(removal['file_record_deletion_verified'])
        self.assertFalse(removal['related_record_effects_verified'])
        self.assertFalse(removal['storage_erasure_verified'])
        self.assertFalse(removal['other_references_verified'])
        self.assertTrue(data['comment_lock_preserved'])
        self.assertFalse(data['notification_delivery_verified'])
        self.assertEqual(data['changed_fields'], ['attachments'])
        self.assertEqual(data['unrequested_changed_fields'], [])
        self.assertEqual(self.announcement_destroyed_attachments, [51])
        self.assertEqual(self.announcements[10], original[10])
        self.assertEqual({k: v for k, v in self.announcements[9].items() if k != 'attachments'},
                         {k: v for k, v in original[9].items() if k != 'attachments'})
        self.assertEqual(self.writes(before), [('PUT', '/api/v1/courses/123/discussion_topics/9?no_verifiers=true')])
        self.assertEqual(self.announcement_mutations[0][2], {'remove_attachment': True, 'is_announcement': True, 'lock_comment': True})
        self.assertEqual(self.announcement_preference_writes, 0)
        self.assertFalse(any('/files/' in route or '/entries' in route or '/view' in route for _, route in self.calls[before:]))
        self.assertTrue(any('page=2' in route for _, route in self.calls[before:]))
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)
        repeated = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertNotEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(len(self.writes(before)), 1)

    def test_group_other_author_and_open_comments_work_without_create_delete_or_guessing_roles(self):
        type(self).announcement_creation = False
        self.announcements[9]['permissions']['delete'] = False
        self.announcements[9]['author']['id'] = 8
        self.announcements[9]['locked'] = False
        before = len(self.calls)
        result = self.approved(self.command('--context', 'group', '--format', 'brief'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Group 123 announcement 9', result.stdout)
        self.assertIn('Attachment 51', result.stdout)
        self.assertIn('storage erasure', result.stdout)
        self.assertFalse(self.announcements[9]['locked'])
        self.assertEqual(self.writes(before), [('PUT', '/api/v1/groups/123/discussion_topics/9?no_verifiers=true')])
        self.assertNotIn('locked', self.announcement_mutations[0][2])

    def test_missing_consent_unexpected_text_flags_absent_attachment_rights_or_page_cap_never_write(self):
        for mode in ('consent', 'title', 'attachment', 'multiple', 'missing', 'denied', 'nonboolean', 'update', 'pages'):
            self.reset()
            command = self.command(consent=mode != 'consent')
            if mode == 'title':
                command += ('--title', 'Unsupported combined edit')
            elif mode == 'attachment':
                self.announcements[9]['attachments'] = []
            elif mode == 'multiple':
                self.announcements[9]['attachments'].append(self.announcements[9]['attachments'][0] | {'id': 52})
            elif mode == 'missing':
                self.announcements[9]['permissions'].pop('attach')
            elif mode == 'denied':
                self.announcements[9]['permissions']['attach'] = False
            elif mode == 'nonboolean':
                self.announcements[9]['permissions']['attach'] = 1
            elif mode == 'update':
                self.announcements[9]['permissions']['update'] = False
            elif mode == 'pages':
                command += ('--max-pages', '1')
            before = len(self.calls)
            result = self.invoke(*command)
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertEqual(self.writes(before), [])
            self.assertEqual(result.stdout, '')
            self.assertNotIn('synthetic-private', result.stderr)

    def test_stale_attachment_content_context_inventory_identity_and_rights_invalidate_before_put(self):
        for mode in ('attachment', 'size', 'message', 'context', 'inventory', 'identity', 'attach'):
            self.reset()
            command = self.command()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'attachment':
                self.announcements[9]['attachments'][0]['id'] = 52
            elif mode == 'size':
                self.announcements[9]['attachments'][0]['size'] = 21
            elif mode == 'message':
                self.announcements[9]['message'] = 'Changed'
            elif mode == 'context':
                self.announcement_context['name'] = 'Changed'
            elif mode == 'inventory':
                self.announcements[10]['title'] = 'Changed'
            elif mode == 'identity':
                type(self).announcement_viewer = 8
            else:
                self.announcements[9]['permissions']['attach'] = False
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertEqual(self.writes(before), [])
            self.assertNotIn('may already have succeeded', result.stderr)

    def test_ignored_parameter_or_late_attach_permission_loss_is_uncertain_without_repair(self):
        for mode in ('ignored', 'permission'):
            self.reset()
            command = self.command()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'ignored':
                type(self).announcement_ignore_attachment_removal = True
            else:
                type(self).announcement_drop_attach_on_write = True
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertIn('may already have succeeded', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)
            self.assertEqual(self.announcement_destroyed_attachments, [])
            self.assertEqual(len(self.announcements[9]['attachments']), 1)

    def test_native_error_after_file_destruction_is_uncertain_with_no_retry_delete_or_restoration(self):
        type(self).announcement_attachment_removal_error = True
        before = len(self.calls)
        result = self.approved(self.command())
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn('may already have succeeded', result.stderr)
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)
        self.assertEqual(self.announcement_destroyed_attachments, [51])
        self.assertEqual(self.announcements[9]['attachments'], [])
        self.assertEqual(len(self.writes(before)), 1)

    def test_bad_ack_readback_inventory_context_account_or_comment_lock_fail_uncertain_after_one_attempt(self):
        for mode in ('ack', 'readback', 'inventory', 'context', 'account', 'comments', 'permissions', 'denied'):
            self.reset()
            if mode == 'ack':
                type(self).announcement_ack_patch = {'attachments': self.announcements[9]['attachments']}
            elif mode == 'readback':
                type(self).announcement_read_denied = True
            elif mode == 'inventory':
                type(self).announcement_inventory_denied = True
            elif mode == 'context':
                type(self).announcement_context_changed = True
            elif mode == 'account':
                type(self).announcement_account_changed = True
            elif mode == 'comments':
                self.announcements[9]['locked'] = False
                type(self).announcement_force_lock = True
            elif mode == 'permissions':
                type(self).announcement_ack_patch = {'permissions': {'update': True, 'delete': True}}
            else:
                type(self).announcement_denied = True
            before = len(self.calls)
            result = self.approved(self.command())
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertEqual(result.stdout, '')
            self.assertIn('may already have succeeded', result.stderr)
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)
