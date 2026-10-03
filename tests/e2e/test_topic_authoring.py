"""Installed CLI creates only synthetic native course/group topics over HTTPS."""

import json
from pathlib import Path

from . import topic_management
from .fixture import CanvasFixture


class TopicAuthoringE2E(CanvasFixture):
    def setUp(self):
        topic_management.initialize(type(self), enabled=True)
        self.message = Path(self.tmp.name) / 'synthetic-new-topic.txt'
        self.message.write_text('Hello <world>\n🌿', encoding='utf-8')

    def command(self, *, group=False):
        return ('topic-create', '119' if group else '111', '--context', 'group' if group else 'course',
                '--title', 'New 🌿', '--acknowledge-shared-topic')

    def approved(self, command):
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def writes(self, before):
        return [row for row in self.calls[before:] if row[0] != 'GET']

    def test_preview_paginates_dynamic_permissions_and_student_publication_without_private_bodies(self):
        before = len(self.calls)
        result = self.invoke(*self.command(), '--message-file', str(self.message))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['body'], {'title': 'New 🌿', 'message': '<p>Hello &lt;world&gt;<br>🌿</p>', 'published': True})
        self.assertTrue(any('include%5B%5D=permissions' in route for _, route in self.calls[before:]))
        self.assertTrue(any('page=2' in route for _, route in self.calls[before:]))
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertEqual(self.writes(before), [])

    def test_one_native_post_with_new_id_independent_readback_and_no_required_own_edit_right(self):
        before = len(self.calls)
        result = self.approved((*self.command(), '--message-file', str(self.message)))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['created_topic']['id'], 903)
        self.assertEqual(data['created_topic']['author_id'], 7)
        self.assertEqual(data['created_topic']['permissions'], {'update': False, 'delete': False})
        self.assertEqual(data['stored_fields_match_request'], {'title': True, 'message': True, 'published': True})
        self.assertTrue(data['new_id_verified'])
        self.assertEqual(self.writes(before), [('POST', '/api/v1/courses/111/discussion_topics?no_verifiers=true')])
        self.assertEqual(self.topic_notifications, [903])
        self.assertEqual(self.topic_entries, [{'id': 991, 'message': 'synthetic-private-peer-reply'}])
        self.assertEqual(self.managed_topics[901]['message'], '<p>synthetic-private-prior-prompt</p>')
        self.assertFalse(any('/entries' in route or '/view' in route for _, route in self.calls[before:]))
        self.assertNotIn('synthetic-private', result.stdout)

    def test_group_moderator_draft_and_explicit_publication_work_without_role_inference(self):
        type(self).topic_moderator = True
        result = self.approved((*self.command(group=True), '--format', 'brief'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Group 119 topic 903 created', result.stdout)
        self.assertIn('Draft', result.stdout)
        self.assertIn('/groups/119/discussion_topics/903', result.stdout)
        self.assertIsNone(self.managed_topics[903]['message'])
        result = self.approved((*self.command(), '--published'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['created_topic']['published'])

    def test_native_normalization_and_ignored_publication_are_explicit_in_brief(self):
        type(self).topic_moderator = type(self).topic_sanitize = True
        type(self).topic_publication_override = True
        result = self.approved((*self.command(), '--message-file', str(self.message), '--format', 'brief'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Stored fields differ', result.stdout)
        self.assertIn('Published', result.stdout)
        self.assertNotIn('synthetic-private', result.stdout)

    def test_stale_permissions_context_account_inventory_and_publication_consent_never_post(self):
        for mode in ('moderation', 'creation', 'context', 'account', 'inventory', 'publication'):
            topic_management.initialize(type(self), enabled=True)
            command = self.command()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'moderation':
                type(self).topic_moderator = True
            elif mode == 'creation':
                type(self).topic_create_permission = False
            elif mode == 'context':
                self.topic_context['name'] = 'Changed'
            elif mode == 'account':
                type(self).topic_viewer = 8
            elif mode == 'inventory':
                self.managed_topics[902]['title'] = 'Changed'
            else:
                command = (*command, '--published')
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, (mode, result.stderr))
            self.assertEqual(result.stdout, '')
            self.assertEqual(self.writes(before), [])

    def test_local_acknowledgement_draft_file_and_pagination_failures_never_post(self):
        before = len(self.calls)
        for command in (('topic-create', '111', '--title', 'New'), (*self.command(), '--no-published'),
                        (*self.command(), '--max-pages', '1'),
                        (*self.command(), '--message-file', str(Path(self.tmp.name) / 'synthetic-missing.txt'))):
            result = self.invoke(*command)
            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '')
        self.message.write_bytes(b'\xff')
        result = self.invoke(*self.command(), '--message-file', str(self.message))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('UTF-8', result.stderr)
        self.assertEqual(self.writes(before), [])

    def test_native_denial_and_ambiguous_success_never_retry_or_delete_or_leak_responses(self):
        for mode in ('denial', 'old_id', 'foreign_author', 'readback', 'readback_denial', 'account'):
            topic_management.initialize(type(self), enabled=True)
            if mode == 'denial':
                type(self).topic_denied = True
            elif mode == 'old_id':
                type(self).topic_ack_patch = {'id': 902, 'secret': 'synthetic-private-ack'}
            elif mode == 'foreign_author':
                type(self).topic_ack_patch = {'author': {'id': 8}}
            elif mode == 'readback':
                type(self).topic_readback_patch = {'title': 'Changed'}
            elif mode == 'readback_denial':
                type(self).topic_readback_denied = True
            else:
                type(self).topic_account_changed = True
            before = len(self.calls)
            result = self.approved(self.command())
            self.assertNotEqual(result.returncode, 0, (mode, result.stderr))
            self.assertEqual(result.stdout, '')
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)
            self.assertEqual(len(self.topic_notifications), 0 if mode == 'denial' else 1)
