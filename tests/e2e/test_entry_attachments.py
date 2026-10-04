"""Installed post/reply uploads against independent native-style HTTPS behavior."""

import copy
import json
from pathlib import Path

from . import entry_attachments
from .fixture import CanvasFixture


class EntryAttachmentE2E(CanvasFixture):
    def setUp(self):
        self.file = Path(self.tmp.name) / 'notes \u2603.txt'
        self.file.write_bytes(b'synthetic-private-upload\x00\xff\r\n' * 100)
        self.message = Path(self.tmp.name) / 'message.txt'
        self.message.write_text('hello <script> &\nworld', encoding='utf-8')
        self.reset()

    def reset(self, *, group=False, reply=False):
        entry_attachments.initialize(type(self))
        type(self).entry_attachment_enabled = True
        self.context = 'group' if group else 'course'
        type(self).entry_attachment_context = self.context
        self.entry_attachment_topic['context_type'] = self.context.title()
        self.reply = reply

    def command(self, *extra, consent=True):
        return ('post', '123', '9', '--context', self.context, '--message-file', str(self.message),
                '--attachment', str(self.file), *(('--reply-to', '301') if self.reply else ()),
                *(('--acknowledge-attachment-upload',) if consent else ()), *extra)

    def writes(self, start):
        return [call for call in self.calls[start:] if call[0] != 'GET']

    def preview(self):
        result = self.invoke(*self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_root_reply_course_group_graded_or_initial_post_use_one_native_post_exact_bytes_and_own_id_readback_only(self):
        for group in (False, True):
            for reply in (False, True):
                for graded in (False, True):
                    self.reset(group=group, reply=reply)
                    if graded:
                        self.entry_attachment_topic['assignment_id'] = 55
                        type(self).entry_attachment_user_quota_denied = True
                    if not reply:
                        self.entry_attachment_topic.update(require_initial_post=True, user_can_see_posts=False)
                    original = copy.deepcopy(self.entry_attachment_parent)
                    start = len(self.calls)
                    preview = self.preview()
                    self.assertEqual(self.writes(start), [])
                    self.assertNotIn(self.tmp.name, json.dumps(preview))
                    self.assertNotIn('synthetic-private', json.dumps(preview))
                    result = self.invoke(*self.command('--yes', '--confirm', preview['confirm']))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    data = json.loads(result.stdout)
                    self.assertTrue(data['entry_identity_and_parent_verified'])
                    self.assertTrue(data['attachment_id_and_size_verified'])
                    self.assertFalse(data['stored_bytes_verified'])
                    self.assertFalse(data['grade_credit_verified'])
                    self.assertEqual(data['attached_post']['parent_id'], 301 if reply else None)
                    self.assertEqual(self.entry_attachment_parent, original)
                    self.assertEqual(self.entry_attachment_parts, [{'message': '<p>hello &lt;script&gt; &amp;<br>world</p>',
                                     'name': self.file.name, 'content_type': 'text/plain', 'content': self.file.read_bytes(),
                                     'authorization': 'Bearer synthetic-token'}])
                    base = f'/api/v1/{self.context}s/123/discussion_topics/9'
                    self.assertEqual(self.writes(start), [('POST', base + ('/entries/301/replies' if reply else '/entries'))])
                    self.assertTrue(any('page=2' in route for _, route in self.calls[start:]))
                    self.assertFalse(any('/view' in route or '/files/' in route or '/storage/' in route or
                                         route.endswith('/entries') and method == 'GET' for method, route in self.calls[start:]))
                    self.assertNotIn('synthetic-private', result.stdout + result.stderr)

    def test_consent_size_reply_initial_protection_hidden_parent_permission_and_page_cap_never_post(self):
        for mode in ('consent', 'size', 'initial', 'parent', 'reply', 'pages', 'anonymous', 'message'):
            self.reset(reply=True)
            if mode == 'initial':
                self.entry_attachment_topic.update(require_initial_post=True, user_can_see_posts=False)
            elif mode == 'parent':
                self.entry_attachment_parent['hidden_for_user'] = True
            elif mode == 'reply':
                self.entry_attachment_topic['permissions']['reply'] = False
            elif mode == 'message':
                self.message.write_bytes(b'x' * 40001)
            elif mode == 'anonymous':
                self.entry_attachment_topic['anonymous_state'] = 'partial_anonymity'
            start = len(self.calls)
            result = self.invoke(*self.command(*(('--max-pages', '1') if mode == 'pages' else
                                                 ('--max-attachment-bytes', '1') if mode == 'size' else ()),
                                               consent=mode != 'consent'))
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertEqual(self.writes(start), [])
            self.assertEqual(self.entry_attachment_parts, [])

    def test_changed_file_message_destination_parent_or_viewer_refuses_stale_confirmation(self):
        for mode in ('file', 'message', 'context', 'parent', 'viewer'):
            self.reset(reply=True)
            preview = self.preview()
            if mode == 'file':
                self.file.write_bytes(self.file.read_bytes() + b'changed')
            elif mode == 'message':
                self.message.write_text('changed', encoding='utf-8')
            elif mode == 'context':
                self.entry_attachment_context_row['name'] = 'Changed'
            elif mode == 'parent':
                self.entry_attachment_parent['message'] += 'changed'
            else:
                type(self).entry_attachment_viewer = 8
            start = len(self.calls)
            result = self.invoke(*self.command('--yes', '--confirm', preview['confirm']))
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertIn('Preview changed', result.stderr)
            self.assertEqual(self.writes(start), [])

    def test_silent_attachment_omission_own_quota_and_partial_entry_or_orphan_file_failures_are_uncertain_no_retry(self):
        for mode in ('ignored', 'quota', 'after-entry', 'after-store'):
            self.reset()
            preview = self.preview()
            attribute = {'ignored': 'can_attach', 'quota': 'user_quota_denied', 'after-entry': 'error_after_entry',
                         'after-store': 'error_after_store'}[mode]
            setattr(type(self), 'entry_attachment_' + attribute, mode != 'ignored')
            start = len(self.calls)
            result = self.invoke(*self.command('--yes', '--confirm', preview['confirm']))
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertIn('entry may already', result.stderr)
            self.assertNotIn('synthetic-private', result.stdout + result.stderr)
            self.assertEqual(len(self.writes(start)), 1)
            if mode != 'quota':
                self.assertIn(402, self.entry_attachment_posts)
                self.assertNotIn('attachment', self.entry_attachment_posts[402])
            if mode == 'after-store':
                self.assertEqual(self.entry_attachment_files[0]['id'], 73)

    def test_foreign_ack_parent_size_or_denied_duplicate_and_diverged_readback_never_claim_success(self):
        for mode in ('viewer', 'parent', 'size', 'denied', 'duplicate', 'readback', 'account', 'context', 'prompt'):
            self.reset(reply=True)
            preview = self.preview()
            if mode in ('viewer', 'parent', 'size'):
                type(self).entry_attachment_ack_patch = ({'user_id': 8} if mode == 'viewer' else {'parent_id': None}
                                                        if mode == 'parent' else {'attachment': {'id': 73, 'size': 1,
                                                                                                'filename': 'x', 'display_name': 'x'}})
            elif mode == 'denied':
                type(self).entry_attachment_read_denied = True
            elif mode == 'duplicate':
                type(self).entry_attachment_duplicate_read = True
            elif mode == 'readback':
                type(self).entry_attachment_read_patch = {'updated_at': 'Changed independently'}
            else:
                setattr(type(self), 'entry_attachment_after_' + ('viewer' if mode == 'account' else mode), True)
            start = len(self.calls)
            result = self.invoke(*self.command('--yes', '--confirm', preview['confirm']))
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertIn('Could not verify', result.stderr)
            self.assertNotIn('synthetic-private', result.stdout + result.stderr)
            self.assertEqual(len(self.writes(start)), 1)
