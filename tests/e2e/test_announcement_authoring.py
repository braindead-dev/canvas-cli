"""Subprocess CLI and synthetic TLS announcement lifecycle/uncertainty evidence."""

import json
from pathlib import Path

from . import announcement_authoring
from .fixture import CanvasFixture


class AnnouncementAuthoringE2E(CanvasFixture):
    def setUp(self):
        announcement_authoring.initialize(type(self), enabled=True)
        self.message = Path(self.tmp.name) / 'synthetic-announcement.txt'
        self.message.write_text('Hello <team>\n🌿', encoding='utf-8')

    def command(self, action='create', *, group=False, identifier=9):
        command = (f'announcement-{action}', '123', '--context', 'group' if group else 'course',
                   '--acknowledge-shared-announcement')
        if action != 'create':
            command += (str(identifier),)
        if action == 'delete':
            return (*command, '--acknowledge-announcement-removal')
        command += ('--acknowledge-broadcast', '--title', 'New 🌿')
        return (*command, '--message-file', str(self.message)) if action == 'create' else command

    def approved(self, command):
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def writes(self, before):
        return [call for call in self.calls[before:] if call[0] != 'GET']

    def test_preview_is_paginated_broadcast_bound_and_not_draft_or_creator_preference_write(self):
        before = len(self.calls)
        result = self.invoke(*self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['body'], {'title': 'New 🌿', 'message': '<p>Hello &lt;team&gt;<br>🌿</p>',
                                        'is_announcement': True, 'lock_comment': True})
        self.assertEqual(data['permissions'], {'create_announcement': True})
        self.assertIn('always published', data['warning'])
        self.assertTrue(any('page=2' in route for _, route in self.calls[before:]))
        self.assertTrue(any('include%5B%5D=permissions' in route for _, route in self.calls[before:]))
        self.assertEqual(self.writes(before), [])
        self.assertNotIn('synthetic-private', result.stdout)

    def test_course_and_group_create_edit_delete_lifecycles_use_native_namespace_and_kind(self):
        for group in (False, True):
            announcement_authoring.initialize(type(self), enabled=True)
            before = len(self.calls)
            result = self.approved(self.command(group=group))
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data['created_announcement']['id'], 11)
            self.assertEqual(data['created_announcement']['author_id'], 7)
            self.assertTrue(data['created_announcement']['is_announcement'])
            self.assertTrue(data['created_announcement']['published'])
            self.assertFalse(data['created_announcement']['can_unpublish'])
            self.assertEqual(data['stored_text_matches_request'], {'title': True, 'message': True})
            self.assertFalse(data['notification_delivery_verified'])
            self.assertFalse(data['future_execution_verified'])
            self.assertNotIn('synthetic-private', result.stdout)
            self.assertEqual(len(self.writes(before)), 1)
            self.assertIn('/groups/' if group else '/courses/', self.writes(before)[0][1])
            type(self).announcement_creation = False  # Owning an existing announcement is a different right.
            result = self.invoke(*self.command('edit', group=group, identifier=11),
                                 '--message-file', str(self.message))
            self.assertNotEqual(result.returncode, 0)  # Selected text already matches; no write.
            command = tuple('Changed 🌿' if value == 'New 🌿' else value
                            for value in self.command('edit', group=group, identifier=11))
            result = self.approved(command)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)['comment_lock_preserved'])
            result = self.approved(self.command('delete', group=group, identifier=11))
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertTrue(data['removed_from_active_inventory'])
            self.assertEqual(data['exact_id_read_status'], 404)
            self.assertNotIn(11, self.announcements)
            self.assertEqual([row[0] for row in self.writes(before)], ['POST', 'PUT', 'DELETE'])
            self.assertEqual(self.announcement_notifications, [11, 11])
            self.assertEqual(self.announcement_preference_writes, 0)
            self.assertEqual(self.announcement_entries, [{'id': 301, 'message': 'synthetic-private-peer-comment'}])
            self.assertFalse(any('/entries' in route or '/view' in route for _, route in self.calls[before:]))

    def test_edit_preserves_closed_and_open_comment_state_without_locked_preference_parameter(self):
        for locked in (False, True):
            announcement_authoring.initialize(type(self), enabled=True)
            self.announcements[9]['locked'] = locked
            before = len(self.calls)
            result = self.approved(self.command('edit'))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIs(self.announcements[9]['locked'], locked)
            self.assertEqual(self.announcement_mutations[0][2],
                             {'title': 'New 🌿', 'is_announcement': True, 'lock_comment': locked})
            self.assertEqual(len(self.writes(before)), 1)

    def test_future_course_posting_is_stored_utc_not_draft_or_future_delivery_proof(self):
        result = self.approved((*self.command(), '--post-at', '2099-10-01T09:00:00-07:00', '--comments'))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['stored_posting_at'], '2099-10-01T16:00:00Z')
        self.assertFalse(data['comments_locked'])
        self.assertTrue(data['created_announcement']['published'])
        self.assertFalse(data['future_execution_verified'])

    def test_local_consent_date_files_and_pagination_failures_do_not_mutate(self):
        before = len(self.calls)
        command = self.command()
        for invalid in (tuple(value for value in command if value != '--acknowledge-broadcast'),
                        tuple(value for value in command if value != '--acknowledge-shared-announcement'),
                        (*command, '--post-at', '2020-10-01T16:00:00Z'),
                        (*command, '--post-at', '2099-10-01T16:00:00'),
                        (*self.command(group=True), '--post-at', '2099-10-01T16:00:00Z'),
                        (*command, '--max-pages', '1'),
                        (*command, '--message-file', str(Path(self.tmp.name) / 'missing.txt'))):
            result = self.invoke(*invalid)
            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '')
        self.message.write_bytes(b'\xff')
        result = self.invoke(*command)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('UTF-8', result.stderr)
        self.assertEqual(self.writes(before), [])

    def test_dynamic_creation_denial_does_not_fall_back_to_discussion_or_guess_role(self):
        type(self).announcement_creation = False
        before = len(self.calls)
        result = self.invoke(*self.command())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('creation', result.stderr)
        self.assertEqual(self.writes(before), [])

    def test_stale_preview_binds_account_context_native_rights_inventory_and_comment_choice(self):
        for mode in ('account', 'context', 'permission', 'inventory', 'comments', 'schedule', 'message'):
            announcement_authoring.initialize(type(self), enabled=True)
            command = self.command()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'account':
                type(self).announcement_viewer = 8
            elif mode == 'context':
                self.announcement_context['name'] = 'Changed'
            elif mode == 'permission':
                type(self).announcement_creation = False
            elif mode == 'inventory':
                self.announcements[10]['title'] = 'Changed'
            elif mode == 'comments':
                command += ('--comments',)
            elif mode == 'schedule':
                command += ('--post-at', '2099-10-01T16:00:00Z')
            else:
                self.message.write_text('Changed body', encoding='utf-8')
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, (mode, result.stderr))
            self.assertEqual(self.writes(before), [])
            self.message.write_text('Hello <team>\n🌿', encoding='utf-8')

    def test_native_denial_or_ambiguous_success_is_not_retried_or_cleaned_up(self):
        for mode in ('denial', 'wrong_kind', 'existing_id', 'foreign_author', 'readback', 'inventory',
                     'missing_inventory', 'account', 'context', 'comments', 'schedule'):
            announcement_authoring.initialize(type(self), enabled=True)
            command = self.command()
            if mode == 'denial':
                type(self).announcement_denied = True
            elif mode == 'wrong_kind':
                type(self).announcement_ack_patch = {'is_announcement': False}
            elif mode == 'existing_id':
                type(self).announcement_ack_patch = {'id': 9}
            elif mode == 'foreign_author':
                type(self).announcement_ack_patch = {'author': {'id': 8}}
            elif mode == 'readback':
                type(self).announcement_read_denied = True
            elif mode == 'inventory':
                type(self).announcement_inventory_denied = True
            elif mode == 'missing_inventory':
                type(self).announcement_hide_after = True
            elif mode == 'account':
                type(self).announcement_account_changed = True
            elif mode == 'context':
                type(self).announcement_context_changed = True
            elif mode == 'comments':
                type(self).announcement_force_lock = True
                command += ('--comments',)
            else:
                type(self).announcement_ignore_date = True
                command += ('--post-at', '2099-10-01T16:00:00Z')
            before = len(self.calls)
            result = self.approved(command)
            self.assertNotEqual(result.returncode, 0, (mode, result.stderr))
            self.assertEqual(result.stdout, '')
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)
            self.assertEqual(len(self.announcement_mutations), 0 if mode == 'denial' else 1)
            if mode != 'denial':
                self.assertIn('may already have succeeded', result.stderr)
                self.assertIn(11, self.announcements)

    def test_native_html_normalization_is_labeled_not_hidden_or_retried(self):
        type(self).announcement_sanitize = True
        result = self.approved((*self.command(), '--format', 'brief'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Stored text differs', result.stdout)
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertEqual(len(self.announcement_mutations), 1)

    def test_wrong_type_delete_or_forbidden_readback_does_not_claim_absence_or_recall(self):
        for mode in ('wrong_type', 'ignored_delete', 'forbidden_missing', 'gone'):
            announcement_authoring.initialize(type(self), enabled=True)
            if mode == 'wrong_type':
                type(self).announcement_ack_patch = {'type': 'DiscussionTopic'}
            elif mode == 'ignored_delete':
                type(self).announcement_ignore_delete = True
            else:
                type(self).announcement_missing_status = 410 if mode == 'gone' else 403
            before = len(self.calls)
            result = self.approved(self.command('delete'))
            self.assertEqual(result.returncode, 0 if mode == 'gone' else 1, (mode, result.stderr))
            self.assertEqual(len(self.writes(before)), 1)
            self.assertNotIn('synthetic-private', result.stdout + result.stderr)
            if mode == 'gone':
                self.assertEqual(json.loads(result.stdout)['exact_id_read_status'], 410)
            else:
                self.assertIn('may already have succeeded', result.stderr)
