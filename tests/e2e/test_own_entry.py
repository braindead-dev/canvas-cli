"""Installed modern own-entry reader and preserving editor over native-style TLS."""

import copy
import json
from pathlib import Path

from . import own_entry
from .fixture import CanvasFixture


class OwnEntryE2E(CanvasFixture):
    def setUp(self):
        self.message = Path(self.tmp.name) / 'edit.txt'
        self.message.write_text('New <script> &\ntext', encoding='utf-8')
        self.reset()

    def reset(self, *, group=False, root=False, anonymous=False):
        own_entry.initialize(type(self))
        type(self).own_entry_enabled = True
        self.kind = 'group' if group else 'course'
        self.own_entry_row['discussionTopic']['contextType'] = self.kind.title()
        if root:
            self.own_entry_row['parentId'] = None
        if anonymous:
            self.own_entry_row.update(author=None, anonymousAuthor={'id': 'abc', 'shortName': 'current_user'})
            self.own_entry_row['discussionTopic']['anonymousState'] = 'full_anonymity'

    def command(self, *extra):
        return ('entry-edit', '123', '9', '301', '--context', self.kind, '--message-file', str(self.message),
                '--preserve-attachment', *extra)

    def preview(self):
        result = self.invoke(*self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_owner_first_read_defaults_to_fingerprint_content_opt_in_is_explicit_and_no_mutation_or_file_url_fetch(self):
        result = self.invoke('own-entry', '123', '9', '301')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['own_entry']['attachment']['size_bytes'], 4)
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)
        self.assertEqual(self.own_entry_queries, ['CanvasOwnEntryOwner', 'CanvasOwnEntryDetails'])
        self.assertEqual(self.own_entry_mutations, [])
        result = self.invoke('own-entry', '123', '9', '301', '--include-content', '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('synthetic-private-old-body', result.stdout)

    def test_native_one_edit_preserves_file_visible_quote_and_own_anonymous_marker_in_course_group_root_reply_cases(self):
        for group in (False, True):
            for root in (False, True):
                for anonymous in (False, True):
                    self.reset(group=group, root=root, anonymous=anonymous)
                    original = copy.deepcopy(self.own_entry_row['attachment'])
                    preview = self.preview()
                    self.assertNotIn('synthetic-private', json.dumps(preview))
                    self.assertEqual(self.own_entry_mutations, [])
                    result = self.invoke(*self.command('--yes', '--confirm', preview['confirm']))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    data = json.loads(result.stdout)
                    self.assertTrue(data['attachment_association_verified'])
                    self.assertTrue(data['visible_quote_association_verified'])
                    self.assertFalse(data['stored_file_bytes_verified'])
                    self.assertEqual(self.own_entry_row['attachment'], original)
                    self.assertEqual(len(self.own_entry_mutations), 1)
                    expected = {'discussionEntryId': '301', 'message': '<p>New &lt;script&gt; &amp;<br>text</p>'}
                    if not root:
                        expected['quotedEntryId'] = '302'
                    self.assertEqual(self.own_entry_mutations[0], expected)
                    self.assertNotIn('synthetic-private', result.stdout + result.stderr)

    def test_foreign_owner_missing_rights_and_changed_quote_file_context_or_body_refuse_before_mutation(self):
        for mode in ('owner', 'rights', 'quote', 'file', 'context', 'body'):
            self.reset()
            preview = self.preview()
            if mode == 'owner':
                self.own_entry_row['author']['_id'] = '8'
            elif mode == 'rights':
                self.own_entry_row['permissions']['update'] = False
            elif mode == 'quote':
                self.own_entry_row['quotedEntry'] = None
            elif mode == 'file':
                self.own_entry_row['attachment']['sizeBytes'] = 9
            elif mode == 'context':
                self.own_entry_context['name'] = 'Changed'
            else:
                self.own_entry_row['message'] = '<p>Changed</p>'
            result = self.invoke(*self.command('--yes', '--confirm', preview['confirm']))
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertEqual(self.own_entry_mutations, [])
        self.reset()
        self.own_entry_row['author']['_id'] = '8'
        result = self.invoke('own-entry', '123', '9', '301')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.own_entry_queries, ['CanvasOwnEntryOwner'])

    def test_file_quote_loss_ignored_save_denied_or_diverged_readback_and_error_after_save_are_uncertain_no_retry(self):
        for mode in ('clear-file', 'clear-quote', 'ignored', 'denied-readback', 'error-after-save', 'ack', 'readback'):
            self.reset()
            preview = self.preview()
            if mode == 'ack':
                type(self).own_entry_ack_patch = {'_id': '999'}
            elif mode == 'readback':
                type(self).own_entry_read_patch = {'message': '<p>Different readback</p>'}
            else:
                type(self).own_entry_mode = mode
            result = self.invoke(*self.command('--yes', '--confirm', preview['confirm']))
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertIn('may have applied', result.stderr)
            self.assertNotIn('synthetic-private', result.stdout + result.stderr)
            self.assertEqual(len(self.own_entry_mutations), 1)

    def test_attachment_modes_are_mutually_exclusive_without_network(self):
        start = len(self.calls)
        result = self.invoke(*self.command('--remove-attachment'))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls[start:], [])

    def test_invalid_or_oversized_local_text_is_rejected_before_canvas_requests(self):
        for mode in ('--preserve-attachment', '--remove-attachment'):
            for content in (b'x' * 40001, b'\xff'):
                self.message.write_bytes(content)
                start = len(self.calls)
                result = self.invoke('entry-edit', '123', '9', '301', '--message-file', str(self.message), mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.calls[start:], [])
        for content in ('&' * 8000, '\x00'):
            self.message.write_text(content, encoding='utf-8')
            start = len(self.calls)
            result = self.invoke(*self.command())
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.calls[start:], [])
