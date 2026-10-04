"""Own native attached entries: rights, confirmation, privacy and partial outcomes."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from canvas_cli.cli import brief, parser
from canvas_cli.client import CanvasError
from canvas_cli.dispatch import execute
from canvas_cli.entry_attachments import post
from canvas_cli.multipart import MAX_BYTES


class EntryClient:
    host = 'https://canvas.example.edu'

    def __init__(self, context='course'):
        self.kind = context
        self.calls, self.transmitted = [], []
        self.identity = 7
        self.context = {'id': 123, 'name': 'Synthetic discussion context', 'workflow_state': 'available'}
        self.topic = {'id': 9, 'context_id': 123, 'context_type': context.title(), 'title': 'Synthetic prompt',
                      'message': '<p>Synthetic prompt body</p>', 'published': True, 'locked': False,
                      'locked_for_user': False, 'require_initial_post': False, 'user_can_see_posts': True,
                      'permissions': {'update': False, 'attach': False, 'reply': True}}
        self.parent = {'id': 301, 'user_id': 8, 'parent_id': None, 'message': '<p>Synthetic parent</p>',
                       'attachment': {'id': 61, 'url': 'https://storage.example/?token=synthetic-private-parent'}}
        self.created = None
        self.mode = None
        self.ack_patch = self.read_patch = self.preflight_mutation = self.after_mutation = None
        self.profile_reads = 0

    @property
    def base(self):
        return f'/api/v1/{self.kind}s/123/discussion_topics/9'

    def request(self, route):
        self.calls.append(('GET', route))
        if route == '/api/v1/users/self/profile':
            self.profile_reads += 1
            if self.profile_reads == 2 and self.preflight_mutation:
                self.preflight_mutation(self)
            return {'id': self.identity}, ''
        if route == f'/api/v1/{self.kind}s/123':
            return copy.deepcopy(self.context), ''
        if route == self.base:
            return copy.deepcopy(self.topic), ''
        raise AssertionError(route)

    def list(self, route, max_pages):
        self.calls.append(('GET', route))
        if max_pages < 2:
            raise CanvasError('Synthetic exact-entry pagination is incomplete')
        self.assert_route(route)
        identifier = int(parse_qs(urlsplit(route).query)['ids[]'][0])
        row = self.parent if identifier == 301 else self.created
        if identifier != 301 and self.mode == 'read-denied':
            raise CanvasError('synthetic-private-read-denial', status=403)
        if identifier != 301 and self.read_patch is not None:
            row = row | self.read_patch if isinstance(self.read_patch, dict) else self.read_patch
        return copy.deepcopy([row]) if row is not None else []

    def assert_route(self, route):
        assert urlsplit(route).path == self.base + '/entry_list'
        assert set(parse_qs(urlsplit(route).query)) == {'ids[]', 'per_page'}

    def multipart(self, route, method, fields, name, mime, content):
        self.calls.append((method, route))
        self.transmitted.append((name, mime, content))
        if self.mode in ('denied', 'quota'):
            raise CanvasError('synthetic-private-post-denial', status=403)
        self.created = {'id': 402, 'user_id': self.identity, 'parent_id': 301 if '/replies' in route else None,
                        'message': '<p>Native normalized text</p>' if self.mode == 'normalized' else fields['message'],
                        'user_name': 'synthetic-private-author', 'user': {'email': 'synthetic-private-profile'}}
        if self.mode == 'error-after-entry':
            raise CanvasError('synthetic-private-error-after-entry', status=500)
        if self.mode != 'ignored':
            self.created['attachment'] = {'id': 73, 'filename': 'renamed-' + name, 'display_name': name,
                                          'size': len(content), 'url': 'https://storage.example/?token=synthetic-private-file'}
        if self.mode == 'error-after-file':
            raise CanvasError('synthetic-private-error-after-file', status=500)
        self.topic['user_can_see_posts'] = True
        self.topic['discussion_subentry_count'] = 10
        self.topic['last_reply_at'] = '2026-10-04T12:00:00Z'
        if self.after_mutation:
            self.after_mutation(self)
        result = copy.deepcopy(self.created)
        if self.ack_patch is not None:
            result = result | self.ack_patch if isinstance(self.ack_patch, dict) else self.ack_patch
        return result, ''


class EntryAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / 'notes \u2603.txt'
        self.file.write_bytes(b'synthetic-private-upload\x00\xff\r\n')
        self.text = 'hello <script> &\nworld'
        self.reset()

    def reset(self, context='course', reply=False):
        self.client = EntryClient(context)
        self.reply = '301' if reply else None

    def preview(self, **options):
        return post(self.client, '123', '9', self.reply, self.text, self.file,
                    **({'acknowledge_upload': True, 'context_type': self.client.kind} | options))

    def approved(self, **options):
        preview = self.preview(**options)
        return self.preview(yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [call for call in self.client.calls if call[0] != 'GET']

    def test_preview_uses_entry_not_shared_prompt_rights_and_never_exposes_private_paths_parent_content_or_links(self):
        self.reset(reply=True)
        data = self.preview()
        self.assertTrue(data['dry_run'])
        self.assertEqual(data['body'], {'message': '<p>hello &lt;script&gt; &amp;<br>world</p>'})
        self.assertEqual(data['reply_parent']['id'], 301)
        self.assertFalse(data['native_entry_attachment_permission_preverified'])
        self.assertNotIn('source', data['file'])
        self.assertNotIn(self.tmp.name, json.dumps(data))
        self.assertNotIn('synthetic-private', json.dumps(data))
        self.assertNotIn('Synthetic parent', json.dumps(data))
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.client.transmitted, [])

    def test_course_and_group_root_and_reply_transmit_once_and_verify_exact_own_entry_and_size_not_bytes_or_credit(self):
        for context in ('course', 'group'):
            for reply in (False, True):
                self.reset(context, reply)
                original = copy.deepcopy(self.client.parent)
                data = self.approved()
                self.assertEqual(self.writes(), [('POST', self.client.base + ('/entries/301/replies' if reply else '/entries'))])
                self.assertEqual(self.client.transmitted, [(self.file.name, 'text/plain', self.file.read_bytes())])
                self.assertEqual(self.client.parent, original)
                self.assertEqual(data['attached_post']['parent_id'], 301 if reply else None)
                self.assertTrue(data['entry_identity_and_parent_verified'])
                self.assertTrue(data['attachment_id_and_size_verified'])
                self.assertTrue(data['reported_html_matches_request'])
                for field in ('stored_bytes_verified', 'grade_credit_verified', 'storage_location_verified',
                              'notification_delivery_verified', 'new_id_historical_uniqueness_verified'):
                    self.assertFalse(data[field])
                self.assertNotIn('synthetic-private', json.dumps(data))
                self.assertIn('stored bytes and grade credit are unverified', brief(data))
                self.assertFalse(any('/view' in route or '/files/' in route or '/storage/' in route for _, route in self.client.calls))
                ids = [parse_qs(urlsplit(route).query)['ids[]'][0] for _, route in self.client.calls if '/entry_list?' in route]
                self.assertEqual(set(ids), {'301', '402'} if reply else {'402'})

    def test_initial_root_can_post_without_reading_peers_but_reply_cannot_bypass_initial_post(self):
        self.client.topic.update(require_initial_post=True, user_can_see_posts=False)
        data = self.approved()
        self.assertTrue(data['entry_identity_and_parent_verified'])
        self.assertEqual([route for _, route in self.client.calls if '/entry_list?' in route],
                         [self.client.base + '/entry_list?ids%5B%5D=402&per_page=100'])
        self.reset(reply=True)
        self.client.topic.update(require_initial_post=True, user_can_see_posts=False)
        with self.assertRaisesRegex(CanvasError, 'initial post'):
            self.preview()
        self.assertEqual(self.writes(), [])
        self.assertFalse(any('/entry_list?' in route for _, route in self.client.calls))

    def test_local_invalid_flags_limits_inputs_and_ids_refuse_before_reads(self):
        for options in ({'acknowledge_upload': False}, {'acknowledge_upload': 1}, {'max_bytes': 0},
                        {'max_bytes': False}, {'max_bytes': MAX_BYTES + 1}, {'max_pages': 0}, {'max_pages': False},
                        {'context_type': 'user'}, {'yes': True}, {'confirm': 'unpaired'}):
            self.reset()
            with self.subTest(options=options), self.assertRaises(CanvasError):
                self.preview(**options)
            self.assertEqual(self.client.calls, [])
        for text in ('', ' ', '\ud800', '\x00', 'x' * 40001):
            self.reset()
            self.text = text
            with self.subTest(text=len(text)), self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.client.calls, [])
        self.text = 'normal'
        for reply in ('0', '../1', '01', True):
            self.reset()
            self.reply = reply
            with self.subTest(reply=reply), self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.client.calls, [])

    def test_invalid_native_rights_topic_context_and_hidden_or_malformed_parent_never_post(self):
        for change in ({'permissions': []}, {'permissions': {'reply': 1}}, {'permissions': {'reply': False}},
                       {'message': {}}, {'published': 1}, {'locked': True}, {'locked_for_user': True},
                       {'published': False}, {'context_id': 456}, {'context_type': 'Group'},
                       {'anonymous_state': 'partial_anonymity'}, {'anonymous_state': 'full_anonymity'}):
            self.reset()
            self.client.topic.update(change)
            with self.subTest(change=change), self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.writes(), [])
        for change in ({'id': 302}, {'user_id': True}, {'deleted': True}, {'hidden_for_user': True},
                       {'locked_for_user': True}, {'message': None}, {'topic_id': True}):
            self.reset(reply=True)
            self.client.parent.update(change)
            with self.subTest(change=change), self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.writes(), [])
        self.reset(reply=True)
        with self.assertRaisesRegex(CanvasError, 'pagination'):
            self.preview(max_pages=1)
        self.assertEqual(self.writes(), [])

    def test_confirmation_binds_file_bytes_path_text_account_context_topic_and_exact_parent(self):
        for mode in ('bytes', 'path', 'text', 'account', 'context', 'topic', 'parent'):
            self.reset(reply=True)
            data = self.preview()
            if mode == 'bytes':
                self.file.write_bytes(self.file.read_bytes() + b'changed')
            elif mode == 'path':
                self.file = Path(self.tmp.name) / 'other.txt'
                self.file.write_bytes(b'synthetic-private-changed-path')
            elif mode == 'text':
                self.text += 'changed'
            elif mode == 'account':
                self.client.identity = 8
            elif mode == 'context':
                self.client.context['name'] += 'changed'
            elif mode == 'topic':
                self.client.topic['message'] += 'changed'
            else:
                self.client.parent['message'] += 'changed'
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'Preview changed'):
                self.preview(yes=True, confirm=data['confirm'])
            self.assertEqual(self.writes(), [])

    def test_change_during_preflight_or_byte_capture_never_posts(self):
        for mutate in (lambda client: setattr(client, 'identity', 8),
                       lambda client: client.context.update(name='Changed'),
                       lambda client: client.topic.update(message='Changed'),
                       lambda client: client.parent.update(message='Changed')):
            self.reset(reply=True)
            self.client.preflight_mutation = mutate
            with self.assertRaisesRegex(CanvasError, 'preflight'):
                self.preview()
            self.assertEqual(self.writes(), [])
        from canvas_cli.upload import file_info
        def change_file(*args):
            result = file_info(*args)
            self.file.write_bytes(b'x' * result['size'])
            return result
        self.reset()
        with patch('canvas_cli.upload.file_info', side_effect=change_file), self.assertRaisesRegex(CanvasError, 'changed'):
            self.preview()
        self.assertEqual(self.client.calls, [])

    def test_post_uses_frozen_bytes_even_if_source_changes_after_capture(self):
        data = self.preview()
        original = self.file.read_bytes()
        self.client.profile_reads = 0
        self.client.preflight_mutation = lambda client: self.file.write_bytes(b'x' * len(original))
        self.preview(yes=True, confirm=data['confirm'])
        self.assertEqual(self.client.transmitted[0][-1], original)

    def test_silent_stripping_denial_and_errors_after_entry_or_file_are_uncertain_once_without_retry(self):
        for mode in ('ignored', 'denied', 'quota', 'error-after-entry', 'error-after-file'):
            self.reset()
            data = self.preview()
            self.client.mode = mode
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'entry may already') as error:
                self.preview(yes=True, confirm=data['confirm'])
            self.assertNotIn('synthetic-private', str(error.exception))
            self.assertEqual(len(self.writes()), 1)
            if mode == 'error-after-entry':
                self.assertIsNotNone(self.client.created)
                self.assertNotIn('attachment', self.client.created)
            elif mode == 'error-after-file':
                self.assertEqual(self.client.created['attachment']['id'], 73)

    def test_bad_ack_or_independent_own_entry_readback_cannot_claim_success(self):
        changes = ([], {'id': True}, {'user_id': 8}, {'parent_id': 301}, {'message': None},
                   {'attachment': None}, {'attachment': {'id': 73, 'size': True, 'filename': 'x', 'display_name': 'x'}},
                   {'attachment': {'id': 73, 'size': 1, 'filename': 'x', 'display_name': 'x'}},
                   {'attachment': {'id': 73, 'size': self.file.stat().st_size, 'filename': '', 'display_name': 'x'}})
        for changed in changes:
            self.reset()
            data = self.preview()
            self.client.ack_patch = changed
            with self.subTest(changed=changed), self.assertRaisesRegex(CanvasError, 'Could not verify'):
                self.preview(yes=True, confirm=data['confirm'])
            self.assertEqual(len(self.writes()), 1)
        for mode in ('read-denied', 'readback', 'account', 'context', 'topic'):
            self.reset()
            data = self.preview()
            if mode == 'readback':
                self.client.read_patch = {'updated_at': 'Changed'}
            elif mode == 'account':
                self.client.after_mutation = lambda client: setattr(client, 'identity', 8)
            elif mode == 'context':
                self.client.after_mutation = lambda client: client.context.update(name='Changed')
            elif mode == 'topic':
                self.client.after_mutation = lambda client: client.topic.update(message='Changed')
            else:
                self.client.mode = mode
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'Could not verify'):
                self.preview(yes=True, confirm=data['confirm'])
            self.assertEqual(len(self.writes()), 1)
        self.reset(reply=True)
        data = self.preview()
        self.client.ack_patch = {'id': 301}
        with self.assertRaisesRegex(CanvasError, 'Could not verify'):
            self.preview(yes=True, confirm=data['confirm'])

    def test_native_html_normalization_is_labeled_not_an_integrity_or_credit_claim(self):
        self.client.mode = 'normalized'
        data = self.approved()
        self.assertFalse(data['reported_html_matches_request'])
        self.assertTrue(data['attachment_id_and_size_verified'])

    def test_parser_dispatch_uses_same_post_command_and_requires_file_for_attachment_options(self):
        message = Path(self.tmp.name) / 'message.txt'
        message.write_text(self.text, encoding='utf-8')
        args = parser().parse_args(['post', '123', '9', '--message-file', str(message), '--attachment', str(self.file),
                                   '--acknowledge-attachment-upload'])
        data = execute(self.client, args)
        self.assertTrue(data['dry_run'])
        self.assertEqual(self.writes(), [])
        for extra in (['--acknowledge-attachment-upload'], ['--max-attachment-bytes', '1']):
            self.reset()
            args = parser().parse_args(['post', '123', '9', '--message-file', str(message), *extra])
            with self.assertRaisesRegex(CanvasError, 'require --attachment'):
                execute(self.client, args)
            self.assertEqual(self.client.calls, [])
        for content in (b'x' * 40001, b'\xff'):
            self.reset()
            message.write_bytes(content)
            args = parser().parse_args(['post', '123', '9', '--message-file', str(message)])
            with self.assertRaises(CanvasError):
                execute(self.client, args)
            self.assertEqual(self.client.calls, [])
