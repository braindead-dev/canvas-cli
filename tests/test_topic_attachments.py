"""Exact native attachment writes, destructive partial outcomes and private inputs."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_announcement_authoring import announcement
from test_topic_management import TopicClient

from canvas_cli.cli import brief, parser
from canvas_cli.client import CanvasError
from canvas_cli.dispatch import execute
from canvas_cli.multipart import MAX_BYTES
from canvas_cli.navigation import command_help
from canvas_cli.topic_attachments import set_attachment


class AttachmentClient(TopicClient):
    def __init__(self, kind='topic'):
        super().__init__()
        self.kind = kind
        if kind == 'announcement':
            self.topics = {identifier: announcement(identifier) for identifier in (9, 10)}
        for row in self.topics.values():
            row['permissions']['attach'] = True
        self.removed = []
        self.transmitted = []
        self.error_after_removal = self.error_after_store = self.drop_attach = False
        self.quota_denied = self.lose_attach = False
        self.hide_after = False

    def list(self, route, max_pages):
        rows = super().list(route, max_pages)
        return [row for row in rows if row['id'] != 9] if self.written and self.hide_after else rows

    def multipart(self, route, method, fields, name, content_type, content):
        self.calls.append((method, route, copy.deepcopy(fields)))
        self.transmitted.append((name, content_type, content))
        row = self.topics[9]
        if self.denied or self.quota_denied:
            raise CanvasError('synthetic-private-native-denial', status=403)
        self.written = True
        if not self.ignore and not self.drop_attach:
            self.removed.extend(attached['id'] for attached in row['attachments'] or [])
            row['attachments'] = []
            if self.error_after_removal:
                raise CanvasError('synthetic-private-error-after-removal', status=500)
            row['attachments'] = [{'id': 73, 'filename': name, 'display_name': name, 'size': len(content),
                                   'url': 'https://storage.example/?token=synthetic-private-signed-file'}]
            if self.lose_attach:
                row['permissions']['attach'] = False
            if self.kind == 'announcement':
                row['locked'] = fields.get('lock_comment', False)
            if self.error_after_store:
                raise CanvasError('synthetic-private-error-after-store', status=500)
        response = copy.deepcopy(row)
        if self.ack_patch is not None:
            response = response | self.ack_patch if isinstance(self.ack_patch, dict) else self.ack_patch
        return response, ''


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / 'notes \u2603.txt'
        self.file.write_bytes(b'synthetic-private-input\x00\xff\r\n')
        self.reset()

    def reset(self, kind='topic', *, empty=False, context='course'):
        self.client = AttachmentClient(kind)
        for row in self.client.topics.values():
            row.update(context_type=context.title(), context_id=123)
        if empty:
            self.client.topics[9]['attachments'] = None

    def preview(self, **options):
        defaults = {'kind': self.client.kind, 'acknowledge_shared': True, 'acknowledge_upload': True,
                    'acknowledge_replacement': bool(self.client.topics[9]['attachments']),
                    'acknowledge_broadcast': self.client.kind == 'announcement'}
        return set_attachment(self.client, '123', '9', self.file, **(defaults | options))

    def approved(self, **options):
        preview = self.preview(**options)
        return self.preview(yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [call for call in self.client.calls if call[0] != 'GET']

    def test_preview_checks_native_rights_and_complete_inventory_without_upload_or_private_path_body_links(self):
        for kind in ('topic', 'announcement'):
            self.reset(kind)
            result = self.preview()
            self.assertEqual(result['encoding'], 'multipart/form-data')
            self.assertEqual(result['body'], {'is_announcement': True, 'lock_comment': True} if kind == 'announcement' else {})
            self.assertEqual(result['file']['name'], self.file.name)
            self.assertEqual(result['file']['size'], self.file.stat().st_size)
            self.assertNotIn('source', result['file'])
            self.assertNotIn(self.tmp.name, json.dumps(result))
            self.assertNotIn('synthetic-private', json.dumps(result))
            self.assertEqual(self.writes(), [])
            self.assertEqual(self.client.transmitted, [])
            self.assertFalse(any('/files/' in route or '/entries' in route or '/view' in route for _, route, _ in self.client.calls))

    def test_one_native_put_adds_or_replaces_with_exact_bytes_and_preserves_lock_and_siblings_in_course_and_group(self):
        for kind in ('topic', 'announcement'):
            for context in ('course', 'group'):
                for empty in (False, True):
                    self.reset(kind, empty=empty, context=context)
                    old = copy.deepcopy(self.client.topics)
                    result = self.approved(context_type=context)
                    self.assertTrue(result['attachment_transfer']['new_id_and_size_verified'])
                    self.assertFalse(result['attachment_transfer']['stored_bytes_verified'])
                    self.assertFalse(result['attachment_transfer']['old_file_deletion_verified'])
                    self.assertEqual(result['attachment_transfer']['replaced_attachment_id'], None if empty else 51)
                    self.assertEqual(result['attachment_transfer']['bytes'], self.file.stat().st_size)
                    self.assertEqual(self.client.transmitted, [(self.file.name, 'text/plain', self.file.read_bytes())])
                    self.assertEqual(self.client.removed, [] if empty else [51])
                    self.assertEqual(self.client.topics[9]['locked'], old[9]['locked'])
                    self.assertEqual(self.client.topics[10], old[10])
                    self.assertEqual(len(self.writes()), 1)
                    self.assertEqual(self.writes()[0][:2], ('PUT', f'/api/v1/{context}s/123/discussion_topics/9?no_verifiers=true'))
                    self.assertNotIn('synthetic-private', json.dumps(result))
                    self.assertIn('stored bytes and old-file deletion are unverified', brief(result))

    def test_missing_consents_invalid_context_limits_and_file_inputs_fail_before_canvas_reads(self):
        for options in ({'acknowledge_shared': False}, {'acknowledge_upload': False}, {'acknowledge_upload': 1},
                        {'acknowledge_replacement': 1}, {'acknowledge_broadcast': True}, {'kind': 'entry'},
                        {'context_type': 'user'}, {'max_bytes': False}, {'max_bytes': 0}, {'max_bytes': MAX_BYTES + 1},
                        {'max_pages': False}, {'max_pages': 0}, {'yes': True}, {'confirm': 'unpaired'}):
            self.reset()
            with self.subTest(options=options), self.assertRaises(CanvasError):
                self.preview(**options)
            self.assertEqual(self.client.calls, [])
        self.reset('announcement')
        with self.assertRaises(CanvasError):
            self.preview(acknowledge_broadcast=False)
        self.assertEqual(self.client.calls, [])
        for content in (b'', b'x' * 101):
            self.file.write_bytes(content)
            self.reset()
            with self.assertRaises(CanvasError):
                self.preview(max_bytes=100)
            self.assertEqual(self.client.calls, [])

    def test_symlink_directory_missing_or_header_injecting_file_is_refused_before_network(self):
        link = Path(self.tmp.name) / 'link.txt'
        link.symlink_to(self.file)
        bad_name = Path(self.tmp.name) / 'bad\r\nprivate.txt'
        bad_name.write_bytes(b'x')
        for path in (link, Path(self.tmp.name), Path(self.tmp.name) / 'missing.txt', bad_name):
            self.file = path
            self.reset()
            with self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.client.calls, [])

    def test_replacement_consent_is_paired_to_reported_inventory_and_exact_attach_rights(self):
        for mode in ('missing', 'denied', 'boolean', 'multi', 'replacement', 'empty-consent', 'pages'):
            self.reset(empty=mode == 'empty-consent')
            if mode == 'missing':
                self.client.topics[9]['permissions'].pop('attach')
            elif mode == 'denied':
                self.client.topics[9]['permissions']['attach'] = False
            elif mode == 'boolean':
                self.client.topics[9]['permissions']['attach'] = 1
            elif mode == 'multi':
                self.client.topics[9]['attachments'].append({'id': 52})
            options = {'acknowledge_replacement': mode == 'empty-consent'} if mode in ('replacement', 'empty-consent') else {}
            if mode == 'pages':
                options['max_pages'] = 1
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(**options)
            self.assertEqual(self.writes(), [])

    def test_stale_file_bytes_path_context_metadata_account_or_permissions_never_upload(self):
        for mode in ('bytes', 'path', 'attachment', 'prompt', 'author', 'context', 'inventory', 'account', 'permission'):
            self.reset()
            preview = self.preview()
            if mode == 'bytes':
                self.file.write_bytes(b'synthetic-changed-file')
            elif mode == 'path':
                other = Path(self.tmp.name) / 'other' / self.file.name
                other.parent.mkdir(exist_ok=True)
                other.write_bytes(self.file.read_bytes())
                self.file = other
            elif mode == 'attachment':
                self.client.topics[9]['attachments'][0]['size'] += 1
            elif mode == 'prompt':
                self.client.topics[9]['message'] = 'Changed'
            elif mode == 'author':
                self.client.topics[9]['author']['id'] = 8
            elif mode == 'context':
                self.client.context['name'] = 'Changed'
            elif mode == 'inventory':
                self.client.topics[10]['title'] = 'Changed'
            elif mode == 'account':
                self.client.identity = 8
            else:
                self.client.topics[9]['permissions']['attach'] = False
            with self.subTest(mode=mode), self.assertRaises(CanvasError) as result:
                self.preview(yes=True, confirm=preview['confirm'])
            self.assertNotIn('may already', str(result.exception))
            self.assertEqual(self.writes(), [])

    def test_change_during_preflight_or_inspection_never_uploads(self):
        self.client.preflight_mutation = lambda client: client.topics[9].update(title='Changed during preflight')
        with self.assertRaisesRegex(CanvasError, 'preflight'):
            self.preview()
        self.assertEqual(self.writes(), [])
        self.reset()
        from canvas_cli.topic_attachments import file_info as inspect
        def mutate(*args):
            result = inspect(*args)
            self.file.write_bytes(b'x' * result['size'])
            return result
        with patch('canvas_cli.topic_attachments.file_info', side_effect=mutate), self.assertRaisesRegex(CanvasError, 'changed'):
            self.preview()
        self.assertEqual(self.client.calls, [])

    def test_native_ignored_attach_or_failures_before_and_after_destruction_are_uncertain_without_retry(self):
        for kind in ('topic', 'announcement'):
            for mode in ('ignore', 'drop_attach', 'error_after_removal', 'error_after_store', 'denied', 'quota_denied', 'lose_attach'):
                self.reset(kind)
                preview = self.preview()
                setattr(self.client, mode, True)
                with self.subTest(kind=kind, mode=mode), self.assertRaisesRegex(CanvasError, 'old attachment may be removed') as result:
                    self.preview(yes=True, confirm=preview['confirm'])
                self.assertNotIn('synthetic-private', str(result.exception))
                self.assertEqual(len(self.writes()), 1)
                if mode == 'error_after_removal':
                    self.assertEqual(self.client.topics[9]['attachments'], [])
                if mode == 'error_after_store':
                    self.assertEqual(self.client.topics[9]['attachments'][0]['id'], 73)

    def test_bad_ack_independent_readback_or_postwrite_scope_inventory_identity_never_claim_success(self):
        for mode in ('ack-shape', 'ack-id', 'old-id', 'size', 'name', 'empty', 'readback', 'read-denied',
                     'context', 'account', 'inventory', 'hidden', 'lock', 'published'):
            self.reset()
            preview = self.preview()
            if mode == 'ack-shape':
                self.client.ack_patch = []
            elif mode == 'ack-id':
                self.client.ack_patch = {'id': 10}
            elif mode in ('old-id', 'size', 'name', 'empty'):
                patch_row = {'id': 51 if mode == 'old-id' else 73, 'size': 1 if mode == 'size' else self.file.stat().st_size,
                             'filename': '' if mode == 'name' else self.file.name, 'display_name': self.file.name}
                self.client.ack_patch = self.client.after_patch = {'attachments': [] if mode == 'empty' else [patch_row]}
            elif mode == 'readback':
                self.client.after_patch = {'title': 'Diverged'}
            elif mode == 'read-denied':
                self.client.after_denied = True
            elif mode == 'context':
                self.client.context_changed = True
            elif mode == 'account':
                self.client.account_changed = True
            elif mode == 'inventory':
                self.client.after_list_fail = True
            elif mode == 'hidden':
                self.client.hide_after = True
            else:
                self.client.ack_patch = self.client.after_patch = {'locked' if mode == 'lock' else mode: mode != 'published'}
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'Could not verify'):
                self.preview(yes=True, confirm=preview['confirm'])
            self.assertEqual(len(self.writes()), 1)

    def test_parser_dispatch_help_and_safety_are_offline_and_use_the_short_command(self):
        for kind in ('topic', 'announcement'):
            self.reset(kind)
            command = [kind + '-attachment-set', '123', '9', str(self.file), '--acknowledge-shared-' + kind,
                       '--acknowledge-attachment-upload', '--acknowledge-attachment-replacement']
            if kind == 'announcement':
                command.append('--acknowledge-broadcast')
            result = execute(self.client, parser().parse_args(command))
            self.assertTrue(result['dry_run'])
            help_result = command_help(parser(), kind + '-attachment-set')
            self.assertIn('usage: canvas ' + kind + '-attachment-set', json.dumps(help_result))
            self.assertIn('Canvas writes (preview-first)', json.dumps(help_result))
