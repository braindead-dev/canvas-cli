"""Destructive native attachment removal, not file-link hiding or erasure proof."""

import copy
import json
import unittest
from unittest.mock import patch

from test_announcement_authoring import AnnouncementClient

from canvas_cli.announcement_authoring import change
from canvas_cli.cli import brief, parser, run
from canvas_cli.client import CanvasError
from canvas_cli.dispatch import execute


class AnnouncementAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.client = AnnouncementClient()
        self.client.topics[9]['permissions']['attach'] = True

    def preview(self, **options):
        return change(self.client, '123', '9', **({'remove_attachment': True, 'acknowledge_attachment_removal': True,
                      'acknowledge_shared': True, 'acknowledge_broadcast': True} | options))

    def approved(self, **options):
        preview = self.preview(**options)
        return self.preview(yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [call for call in self.client.calls if call[0] != 'GET']

    def test_preview_names_exact_attachment_and_native_destruction_without_private_signed_urls_or_peer_reads(self):
        result = self.preview()
        self.assertEqual(result['body'], {'remove_attachment': True, 'is_announcement': True, 'lock_comment': True})
        self.assertEqual(result['removed_attachment_id'], 51)
        self.assertTrue(result['acknowledge_attachment_removal'])
        self.assertTrue(result['announcement']['permissions']['attach'])
        self.assertIn('soft-delete its file record', result['warning'])
        self.assertIn('detach media/LTI/draft associations', result['warning'])
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertEqual(self.writes(), [])
        self.assertFalse(any('/files/' in route or '/entries' in route or '/view' in route for _, route, _ in self.client.calls))

    def test_one_exact_put_clears_only_attachment_association_and_verifies_comment_lock_not_erasure(self):
        original = copy.deepcopy(self.client.topics)
        result = self.approved()
        state = result['announcement_attachment_removal']
        self.assertEqual(state['removed_attachment_id'], 51)
        self.assertTrue(state['attachment_list_cleared'])
        self.assertTrue(state['verified'])
        self.assertFalse(state['file_record_deletion_verified'])
        self.assertFalse(state['related_record_effects_verified'])
        self.assertFalse(state['storage_erasure_verified'])
        self.assertFalse(state['other_references_verified'])
        self.assertTrue(result['comment_lock_preserved'])
        self.assertFalse(result['notification_delivery_verified'])
        self.assertEqual(result['changed_fields'], ['attachments'])
        self.assertEqual(result['unrequested_changed_fields'], [])
        self.assertEqual(self.client.destroyed_attachments, [51])
        self.assertEqual(self.client.topics[10], original[10])
        self.assertEqual({k: v for k, v in self.client.topics[9].items() if k != 'attachments'},
                         {k: v for k, v in original[9].items() if k != 'attachments'})
        self.assertEqual(self.writes(), [('PUT', '/api/v1/courses/123/discussion_topics/9?no_verifiers=true',
                                         {'remove_attachment': True, 'is_announcement': True, 'lock_comment': True})])
        self.assertIn('Attachment 51', brief(result))
        self.assertNotIn('synthetic-private', json.dumps(result))

    def test_group_and_other_author_use_exact_update_and_attach_rights_not_creation_or_delete(self):
        for context in ('course', 'group'):
            self.setUp()
            self.client.creation = False
            self.client.topics[9]['permissions']['delete'] = False
            self.client.topics[9]['author']['id'] = 8
            if context == 'group':
                for row in self.client.topics.values():
                    row['context_type'] = 'Group'
            result = self.approved(context_type=context)
            self.assertEqual(result['edited_announcement']['author_id'], 8)
            self.assertEqual(result['context_type'], context)
            self.assertFalse(any('include%5B%5D=permissions' in route for _, route, _ in self.client.calls))
            self.assertEqual(len(self.writes()), 1)

    def test_local_consent_or_combination_errors_refuse_before_network(self):
        for options in ({'remove_attachment': 1}, {'acknowledge_attachment_removal': 1},
                        {'acknowledge_attachment_removal': False}, {'remove_attachment': False},
                        {'title': 'Other edit'}, {'message': 'Other edit'}, {'comments': True, 'acknowledge_comments': True},
                        {'schedule': {'lock_at': None}, 'acknowledge_availability': True},
                        {'sections': {'specific_sections': 'all'}, 'acknowledge_audience': True},
                        {'delete': True, 'acknowledge_removal': True, 'acknowledge_broadcast': False},
                        {'acknowledge_shared': False}, {'acknowledge_broadcast': False}, {'max_pages': 0},
                        {'yes': True}, {'confirm': 'unpaired'}):
            self.setUp()
            with self.subTest(options=options), self.assertRaises(CanvasError):
                self.preview(**options)
            self.assertEqual(self.client.calls, [])

    def test_missing_nonboolean_or_denied_attach_update_rights_refuse_without_put(self):
        for key in ('update', 'attach'):
            for value in (False, None, 1, 'true', 'missing'):
                self.setUp()
                rights = self.client.topics[9]['permissions']
                if value == 'missing':
                    rights.pop(key)
                else:
                    rights[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(CanvasError):
                    self.preview()
                self.assertEqual(self.writes(), [])

    def test_empty_multiple_or_malformed_attachments_refuse_without_put(self):
        original = self.client.topics[9]['attachments'][0]
        for value in (None, [], [original, original | {'id': 52}], [original, original],
                      [original | {'id': True}], [original | {'size': '20'}], [original | {'updated_at': 'bad'}], {}):
            self.setUp()
            self.client.topics[9]['attachments'] = value
            with self.subTest(value=value), self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.writes(), [])

    def test_stale_attachment_metadata_content_author_context_inventory_identity_or_rights_never_put(self):
        for mode in ('id', 'name', 'size', 'date', 'message', 'author', 'context', 'inventory', 'identity', 'attach'):
            self.setUp()
            preview = self.preview()
            if mode in ('id', 'name', 'size', 'date'):
                key, value = {'id': ('id', 52), 'name': ('display_name', 'Changed'), 'size': ('size', 21),
                              'date': ('updated_at', '2026-10-02T12:00:00Z')}[mode]
                self.client.topics[9]['attachments'][0][key] = value
            elif mode == 'message':
                self.client.topics[9]['message'] = 'Changed'
            elif mode == 'author':
                self.client.topics[9]['author']['id'] = 8
            elif mode == 'context':
                self.client.context['name'] = 'Changed'
            elif mode == 'inventory':
                self.client.topics[10]['title'] = 'Changed'
            elif mode == 'identity':
                self.client.identity = 8
            else:
                self.client.topics[9]['permissions']['attach'] = False
            with self.subTest(mode=mode), self.assertRaises(CanvasError) as caught:
                self.preview(yes=True, confirm=preview['confirm'])
            self.assertNotIn('may already have succeeded', str(caught.exception))
            self.assertEqual(self.writes(), [])
        self.setUp()
        self.client.preflight_mutation = lambda c: c.topics[9]['attachments'][0].update(size=21)
        with self.assertRaisesRegex(CanvasError, 'preflight'):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_native_ignored_or_late_attach_right_loss_is_uncertain_and_never_repaired(self):
        for mode in ('ignored', 'permission'):
            self.setUp()
            preview = self.preview()
            if mode == 'ignored':
                self.client.ignore_attachment_removal = True
            else:
                original = self.client.request

                def request(route, method='GET', body=None):
                    if method == 'PUT':
                        self.client.topics[9]['permissions']['attach'] = False
                    return original(route, method, body)

                self.client.request = request
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'may already have succeeded'):
                self.preview(yes=True, confirm=preview['confirm'])
            self.assertEqual(len(self.writes()), 1)
            self.assertEqual(self.client.destroyed_attachments, [])
            self.assertEqual(len(self.client.topics[9]['attachments']), 1)

    def test_failure_after_native_destruction_is_uncertain_with_no_automatic_retry_or_restore(self):
        self.client.attachment_removal_error = True
        with self.assertRaisesRegex(CanvasError, 'may already have succeeded') as caught:
            self.approved()
        self.assertEqual(self.client.topics[9]['attachments'], [])
        self.assertEqual(self.client.destroyed_attachments, [51])
        self.assertEqual(len(self.writes()), 1)
        self.assertNotIn('synthetic-private', str(caught.exception))

    def test_bad_ack_or_unverifiable_read_inventory_context_account_and_comment_state_is_uncertain(self):
        for mode in ('ack', 'readback', 'inventory', 'context', 'account', 'comments', 'permissions', 'denied'):
            self.setUp()
            if mode == 'ack':
                self.client.ack_patch = {'attachments': [self.client.topics[9]['attachments'][0]]}
            elif mode == 'readback':
                self.client.after_denied = True
            elif mode == 'inventory':
                self.client.after_list_fail = True
            elif mode == 'context':
                self.client.context_changed = True
            elif mode == 'account':
                self.client.account_changed = True
            elif mode == 'comments':
                self.client.ignore_comment_lock = True
                self.client.topics[9]['locked'] = False
                self.client.force_comment_lock = True
            elif mode == 'permissions':
                self.client.ack_patch = {'permissions': {'update': True, 'delete': True}}
            else:
                self.client.denied = True
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'may already have succeeded'):
                self.approved()
            self.assertEqual(len(self.writes()), 1)

    def test_unrequested_native_metadata_changes_are_labeled_not_restored(self):
        self.client.ack_patch = self.client.after_patch = {'posted_at': '2026-10-03T12:00:00Z'}
        result = self.approved()
        self.assertEqual(result['unrequested_changed_fields'], ['posted_at'])
        self.assertIn('Other observed changes', brief(result))
        self.assertEqual(len(self.writes()), 1)

    def test_normal_text_edit_preserves_attachment_without_requesting_attach_permission(self):
        self.client.topics[9]['permissions'].pop('attach')
        preview = change(self.client, '123', '9', title='New', acknowledge_shared=True, acknowledge_broadcast=True)
        result = change(self.client, '123', '9', title='New', acknowledge_shared=True, acknowledge_broadcast=True,
                        yes=True, confirm=preview['confirm'])
        self.assertEqual(len(result['edited_announcement']['attachments']), 1)
        self.assertNotIn('remove_attachment', self.writes()[0][2])

    def test_parser_dispatch_offline_help_schema_and_safety_classification(self):
        command = ['announcement-attachment-remove', '123', '9', '--acknowledge-shared-announcement',
                   '--acknowledge-broadcast', '--acknowledge-attachment-removal']
        preview = execute(self.client, parser().parse_args(command))
        self.assertEqual(preview['body']['remove_attachment'], True)
        with patch('canvas_cli.cli.auth.connect', side_effect=AssertionError('Offline discovery must not authenticate')):
            data = run(parser().parse_args(['help', command[0], '--format', 'brief']))
            self.assertEqual(data['safety'], 'Canvas writes (preview-first)')
            self.assertIn('--acknowledge-attachment-removal', brief(data))
            schema = run(parser().parse_args(['schema', command[0]]))
        self.assertEqual(schema['commands'][0]['safety'], 'Canvas writes (preview-first)')
