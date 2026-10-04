"""Installed attachment commands against native-style multipart HTTPS routes."""

import copy
import json
from pathlib import Path

from . import announcement_authoring, topic_attachments, topic_management
from .fixture import CanvasFixture


class AttachmentE2E(CanvasFixture):
    def setUp(self):
        self.file = Path(self.tmp.name) / 'notes \u2603.txt'
        self.file.write_bytes(b'synthetic-private-file\x00\xff\r\n' * 100)
        self.reset()

    def reset(self, *, announcement=False, group=False, empty=False):
        announcement_authoring.initialize(type(self), enabled=announcement)
        topic_management.initialize(type(self), enabled=not announcement)
        topic_attachments.initialize(type(self))
        type(self).attachment_enabled = True
        if not announcement:
            type(self).topic_state_enabled = True
        self.kind = 'announcement' if announcement else 'topic'
        self.context_id = '123' if announcement else '119' if group else '111'
        self.identifier = '9' if announcement else '901'
        self.context = 'group' if group else 'course'
        self.row()['permissions']['attach'] = True
        if empty:
            self.row()['attachments'] = None
        self.replacing = not empty

    def row(self):
        return self.rows()[int(self.identifier)]

    def rows(self):
        return self.announcements if self.kind == 'announcement' else self.managed_topics

    def command(self, *extra, consent=True):
        return (self.kind + '-attachment-set', self.context_id, self.identifier, str(self.file), '--context', self.context,
                '--acknowledge-shared-' + self.kind,
                *(('--acknowledge-broadcast',) if self.kind == 'announcement' else ()),
                *(('--acknowledge-attachment-upload',) if consent else ()),
                *(('--acknowledge-attachment-replacement',) if self.replacing else ()), *extra)

    def writes(self, before):
        return [call for call in self.calls[before:] if call[0] != 'GET']

    def configure(self, announcement_key, topic_key, value):
        setattr(type(self), announcement_key if self.kind == 'announcement' else topic_key, value)

    def test_add_and_replace_course_group_discussion_announcement_with_one_native_authenticated_put_exact_bytes_and_no_storage_requests(self):
        for announcement in (False, True):
            for group in (False, True):
                for empty in (False, True):
                    self.reset(announcement=announcement, group=group, empty=empty)
                    old = copy.deepcopy(self.rows())
                    before = len(self.calls)
                    preview = self.invoke(*self.command())
                    self.assertEqual(preview.returncode, 0, preview.stderr)
                    data = json.loads(preview.stdout)
                    self.assertEqual(data['encoding'], 'multipart/form-data')
                    self.assertNotIn(self.tmp.name, preview.stdout)
                    self.assertEqual(self.writes(before), [])
                    result = self.invoke(*self.command('--yes', '--confirm', data['confirm']))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    transfer = json.loads(result.stdout)['attachment_transfer']
                    self.assertEqual(transfer['new_attachment_id'], 1201)
                    self.assertTrue(transfer['new_id_and_size_verified'])
                    self.assertFalse(transfer['stored_bytes_verified'])
                    self.assertFalse(transfer['old_file_deletion_verified'])
                    self.assertEqual(transfer['replaced_attachment_id'], None if empty else 51 if announcement else 881)
                    self.assertEqual(self.attachment_parts, [{'fields': {'is_announcement': 'true', 'lock_comment': 'true'} if announcement else {},
                                     'filename': self.file.name, 'content_type': 'text/plain', 'content': self.file.read_bytes(),
                                     'authorization': 'Bearer synthetic-token'}])
                    self.assertEqual(self.row()['locked'], old[int(self.identifier)]['locked'])
                    for identifier in self.rows():
                        if identifier != int(self.identifier):
                            self.assertEqual(self.rows()[identifier], old[identifier])
                    self.assertEqual(self.writes(before), [('PUT', f'/api/v1/{self.context}s/{self.context_id}/discussion_topics/{self.identifier}?no_verifiers=true')])
                    self.assertTrue(any('page=2' in route for _, route in self.calls[before:]))
                    self.assertFalse(any('/entries' in route or '/view' in route or '/files/' in route or '/storage/' in route for _, route in self.calls[before:]))
                    self.assertNotIn('synthetic-private', preview.stdout + result.stdout + result.stderr)

    def test_missing_consent_permissions_wrong_metadata_empty_replacement_and_page_cap_never_upload(self):
        for mode in ('consent', 'attach', 'update', 'missing', 'boolean', 'multi', 'empty-consent', 'pages', 'size-limit'):
            self.reset(empty=mode == 'empty-consent')
            if mode in ('attach', 'update'):
                self.row()['permissions'][mode] = False
            elif mode == 'missing':
                self.row()['permissions'].pop('attach')
            elif mode == 'boolean':
                self.row()['permissions']['attach'] = 1
            elif mode == 'multi':
                self.row()['attachments'].append({'id': 1202})
            elif mode == 'empty-consent':
                self.replacing = True
            before = len(self.calls)
            result = self.invoke(*self.command(*(('--max-pages', '1') if mode == 'pages' else
                                                  ('--max-bytes', '1') if mode == 'size-limit' else ()), consent=mode != 'consent'))
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertEqual(self.writes(before), [])
            self.assertEqual(self.attachment_parts, [])

    def test_stale_source_content_and_prompt_attachment_inventory_or_account_refuse_before_multipart(self):
        for announcement in (False, True):
            for mode in ('file', 'prompt', 'attachment', 'inventory', 'account', 'right'):
                self.reset(announcement=announcement)
                preview = self.invoke(*self.command())
                self.assertEqual(preview.returncode, 0, preview.stderr)
                before = len(self.calls)
                if mode == 'file':
                    self.file.write_bytes(self.file.read_bytes() + b'changed')
                elif mode == 'prompt':
                    self.row()['message'] = 'Changed'
                elif mode == 'attachment':
                    self.row()['attachments'][0]['size'] += 1
                elif mode == 'inventory':
                    self.rows()[10 if announcement else 902]['title'] = 'Changed'
                elif mode == 'account':
                    self.configure('announcement_viewer', 'topic_viewer', 8)
                else:
                    self.row()['permissions']['attach'] = False
                result = self.invoke(*self.command('--yes', '--confirm', json.loads(preview.stdout)['confirm']))
                self.assertNotEqual(result.returncode, 0, mode)
                self.assertEqual(self.writes(before), [])
                self.assertNotIn('Could not verify', result.stderr)

    def test_native_silent_stripping_quota_and_errors_after_old_removal_or_new_store_are_uncertain_one_attempt(self):
        for announcement in (False, True):
            for mode in ('ignore', 'late_drop_attach', 'quota_denied', 'error_after_removal', 'error_after_store', 'lose_attach'):
                self.reset(announcement=announcement)
                preview = self.invoke(*self.command())
                self.assertEqual(preview.returncode, 0, preview.stderr)
                setattr(type(self), 'attachment_' + mode, True)
                before = len(self.calls)
                result = self.invoke(*self.command('--yes', '--confirm', json.loads(preview.stdout)['confirm']))
                self.assertNotEqual(result.returncode, 0, mode)
                self.assertIn('old attachment may be removed', result.stderr)
                self.assertNotIn('synthetic-private', result.stderr)
                self.assertEqual(len(self.writes(before)), 1)
                if mode == 'error_after_removal':
                    self.assertEqual(self.row()['attachments'], [])
                elif mode == 'error_after_store':
                    self.assertEqual(self.row()['attachments'][0]['id'], 1201)

    def test_bad_ack_denied_readback_foreign_state_or_inventory_does_not_claim_success(self):
        for announcement in (False, True):
            for mode in ('ack', 'id', 'readback', 'read-denied', 'inventory', 'account'):
                self.reset(announcement=announcement)
                preview = self.invoke(*self.command())
                self.assertEqual(preview.returncode, 0, preview.stderr)
                if mode == 'ack':
                    type(self).attachment_ack_patch = {'attachments': [{'id': 1201, 'size': 1}]}
                elif mode == 'id':
                    type(self).attachment_ack_patch = {'id': 999}
                elif mode == 'readback':
                    self.configure('announcement_read_patch', 'topic_readback_patch', {'title': 'Changed independently'})
                elif mode == 'read-denied':
                    self.configure('announcement_read_denied', 'topic_readback_denied', True)
                elif mode == 'inventory':
                    self.configure('announcement_inventory_denied', 'topic_state_inventory_denied', True)
                else:
                    self.configure('announcement_account_changed', 'topic_account_changed', True)
                before = len(self.calls)
                result = self.invoke(*self.command('--yes', '--confirm', json.loads(preview.stdout)['confirm']))
                self.assertNotEqual(result.returncode, 0, mode)
                self.assertIn('Could not verify', result.stderr)
                self.assertEqual(len(self.writes(before)), 1)
                self.assertNotIn('synthetic-private', result.stderr)
