"""CLI/HTTPS prompt edits and soft deletion, never a real course discussion."""

import json
from pathlib import Path

from . import topic_management
from .fixture import CanvasFixture


class TopicManagementE2E(CanvasFixture):
    def setUp(self):
        topic_management.initialize(type(self), enabled=True)
        self.message = Path(self.tmp.name) / 'synthetic-topic-message.txt'
        self.message.write_text('Hello <world>\n🌿', encoding='utf-8')

    def command(self, *, deleting=False, group=False):
        return ('topic-delete' if deleting else 'topic-edit', '119' if group else '111', '901',
                '--context', 'group' if group else 'course', '--acknowledge-shared-topic',
                *(('--acknowledge-topic-removal',) if deleting else ('--title', 'Renamed 🌿')))

    def approved(self, command):
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def writes(self, before):
        return [row for row in self.calls[before:] if row[0] != 'GET']

    def test_installed_preview_paginates_and_contains_only_requested_text_not_live_content(self):
        before = len(self.calls)
        result = self.invoke(*self.command(), '--message-file', str(self.message))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['body'], {'title': 'Renamed 🌿', 'message': '<p>Hello &lt;world&gt;<br>🌿</p>'})
        self.assertEqual(data['topic']['attachments'][0]['id'], 881)
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertTrue(any('page=2' in route for _, route in self.calls[before:]))
        self.assertFalse(any('/entries' in route or '/view' in route for _, route in self.calls[before:]))
        self.assertEqual(self.writes(before), [])

    def test_installed_one_native_put_title_only_does_not_post_reply_publish_or_remove_attachment(self):
        self.managed_topics[901].update(published=False, author={'id': 8}, locked=True)
        before = len(self.calls)
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data['edited_topic']['published'])
        self.assertEqual(data['edited_topic']['author_id'], 8)
        self.assertEqual(data['changed_fields'], ['title'])
        self.assertTrue(data['acknowledgement_matches_readback'])
        self.assertEqual(self.managed_topics[901]['message'], '<p>synthetic-private-prior-prompt</p>')
        self.assertEqual(self.managed_topics[902]['title'], 'Synthetic other topic')
        self.assertEqual(self.topic_entries, [{'id': 991, 'message': 'synthetic-private-peer-reply'}])
        self.assertFalse(self.topic_attachment_deleted)
        self.assertEqual(self.topic_notifications, [901])
        self.assertEqual(self.writes(before), [('PUT', '/api/v1/courses/111/discussion_topics/901?no_verifiers=true')])
        self.assertNotIn('synthetic-private', result.stdout)

    def test_installed_group_message_edit_and_brief_html_normalization_are_explicit(self):
        type(self).topic_sanitize = True
        command = (*self.command(group=True), '--message-file', str(self.message), '--format', 'brief')
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        result = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Group 119 topic 901 edited', result.stdout)
        self.assertIn('differs from the request', result.stdout)
        self.assertIn('/groups/119/discussion_topics/901', result.stdout)
        self.assertNotIn('synthetic-private', result.stdout)

    def test_installed_one_soft_delete_and_paged_inventory_do_not_delete_peer_posts_or_attachment_explicitly(self):
        self.managed_topics[901]['permissions']['update'] = False
        self.managed_topics[901]['discussion_subentry_count'] = 1
        before = len(self.calls)
        result = self.approved(self.command(deleting=True, group=True))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['exact_id_read_status'], 404)
        self.assertTrue(data['removed_from_active_inventory'])
        self.assertEqual(data['group_id'], 119)
        self.assertEqual(set(self.managed_topics), {902})
        self.assertEqual(self.topic_deleted, {901})
        self.assertEqual(len(self.topic_entries), 1)
        self.assertFalse(self.topic_attachment_deleted)
        self.assertEqual(self.writes(before), [('DELETE', '/api/v1/groups/119/discussion_topics/901?no_verifiers=true')])
        self.assertNotIn('synthetic-private', result.stdout)

    def test_installed_stale_prompt_scope_author_audience_permissions_count_and_viewer_never_write(self):
        for mode in ('message', 'author', 'audience', 'permission', 'count', 'viewer', 'context', 'inventory'):
            topic_management.initialize(type(self), enabled=True)
            command = self.command()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            row = self.managed_topics[901]
            if mode == 'message':
                row['message'] = 'Changed'
            elif mode == 'author':
                row['author']['id'] = 8
            elif mode == 'audience':
                row['ungraded_discussion_overrides'] = []
            elif mode == 'permission':
                row['permissions']['delete'] = False
            elif mode == 'count':
                row['discussion_subentry_count'] = 1
            elif mode == 'viewer':
                type(self).topic_viewer = 8
            elif mode == 'context':
                self.topic_context['name'] = 'Changed'
            else:
                self.managed_topics[902]['title'] = 'Changed'
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, (mode, result.stderr))
            self.assertIn('Preview changed', result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertEqual(self.writes(before), [])

    def test_installed_linked_anonymous_initial_post_and_role_restrictions_do_not_use_hidden_routes(self):
        for patch in ({'assignment_id': 88}, {'root_topic_id': 88}, {'group_category_id': 3},
                      {'group_topic_children': [{'id': 88, 'group_id': 119}]}, {'is_announcement': True},
                      {'anonymous_state': 'partial_anonymity'}, {'lock_info': {'can_view': False}},
                      {'permissions': {'update': False, 'delete': False}}):
            topic_management.initialize(type(self), enabled=True)
            self.managed_topics[901].update(patch)
            before = len(self.calls)
            result = self.invoke(*self.command())
            self.assertNotEqual(result.returncode, 0, (patch, result.stderr))
            self.assertEqual(self.writes(before), [])
            self.assertFalse(any('/entries' in route or '/view' in route for _, route in self.calls[before:]))
        topic_management.initialize(type(self), enabled=True)
        self.managed_topics[901].update(require_initial_post=True, user_can_see_posts=False)
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)  # Prompt update rights are not permission to inspect peer replies.

    def test_installed_pagination_acknowledgements_and_write_failures_do_not_auto_retry(self):
        before = len(self.calls)
        result = self.invoke(*self.command(), '--max-pages', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Page limit', result.stderr)
        self.assertEqual(self.writes(before), [])
        for mode in ('denial', 'foreign_ack', 'readback', 'readback_denial', 'account', 'ignored_delete', 'missing403'):
            topic_management.initialize(type(self), enabled=True)
            deleting = mode in ('ignored_delete', 'missing403')
            if mode == 'denial':
                type(self).topic_denied = True
            elif mode == 'foreign_ack':
                type(self).topic_ack_patch = {'id': 902, 'secret': 'synthetic-private-ack'}
            elif mode == 'readback':
                type(self).topic_readback_patch = {'title': 'Different after'}
            elif mode == 'readback_denial':
                type(self).topic_readback_denied = True
            elif mode == 'account':
                type(self).topic_account_changed = True
            elif mode == 'ignored_delete':
                type(self).topic_ignore = True
            else:
                type(self).topic_missing_status = 403
            before = len(self.calls)
            result = self.approved(self.command(deleting=deleting))
            self.assertNotEqual(result.returncode, 0, (mode, result.stderr))
            self.assertEqual(result.stdout, '')
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)

    def test_installed_selected_fields_acknowledgements_and_local_files_fail_safely(self):
        before = len(self.calls)
        for command in (('topic-edit', '111', '901', '--title', 'New'),
                        ('topic-delete', '111', '901', '--acknowledge-shared-topic'),
                        ('topic-edit', '111', '901', '--acknowledge-shared-topic'),
                        (*self.command(), '--message-file', str(Path(self.tmp.name) / 'synthetic-missing-message.txt'))):
            result = self.invoke(*command)
            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '')
        self.message.write_bytes(b'\xff')
        result = self.invoke(*self.command(), '--message-file', str(self.message))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('UTF-8', result.stderr)
        self.assertEqual(self.writes(before), [])
