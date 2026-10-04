"""Installed full pinned ordering against independent native moderation and positions."""

import json

from . import topic_management
from .fixture import CanvasFixture


class TopicOrderingE2E(CanvasFixture):
    def setUp(self):
        self.reset()

    def reset(self):
        topic_management.initialize(type(self), enabled=True)
        type(self).topic_order_enabled = type(self).topic_moderator = True
        self.managed_topics[902].update(pinned=True, assignment_id=88, message=None, author=None)
        self.managed_topics[903] = {'id': 903, 'title': 'Synthetic unpinned topic', 'is_announcement': False,
                                    'published': True, 'locked': False, 'pinned': False, 'position': 1}

    def command(self, *extra, group=False, order=('902', '901')):
        return ('topic-order', '119' if group else '111', *order,
                '--context', 'group' if group else 'course', '--acknowledge-all-pinned-topics', *extra)

    def approved(self, command):
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def writes(self, before):
        return [row for row in self.calls[before:] if row[0] != 'GET']

    def test_preview_full_pagination_native_context_rights_and_exact_order_without_prompt_or_peer_reads(self):
        before = len(self.calls)
        result = self.invoke(*self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['body'], {'order': [902, 901]})
        self.assertEqual(data['previous_order'], [901, 902])
        self.assertEqual(data['permissions'], {'read_forum': True, 'moderate_forum': True})
        self.assertTrue(any('page=3' in route for _, route in self.calls[before:]))
        self.assertEqual(self.writes(before), [])
        self.assertFalse(any('/entries' in route or '/view' in route or '/discussion_topics/901' in route
                             for _, route in self.calls[before:]))
        self.assertNotIn('synthetic-private', result.stdout)

    def test_course_or_group_order_has_one_post_and_independent_complete_position_readback(self):
        for group in (False, True):
            self.reset()
            before = len(self.calls)
            result = self.approved(self.command(group=group))
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertTrue(data['order_verified'])
            self.assertEqual(data['pinned_topic_order'], [902, 901])
            self.assertEqual(data['positions'], [{'id': 902, 'position': 1}, {'id': 901, 'position': 2}])
            prefix = 'groups/119' if group else 'courses/111'
            self.assertEqual(self.writes(before), [('POST', f'/api/v1/{prefix}/discussion_topics/reorder')])
            self.assertEqual(self.managed_topics[903]['position'], 1)
            self.assertEqual(self.managed_topics[902]['assignment_id'], 88)
            self.assertEqual(self.managed_topics[901]['attachments'][0]['id'], 881)
            self.assertEqual(self.topic_entries, [{'id': 991, 'message': 'synthetic-private-peer-reply'}])
            self.assertEqual(self.topic_notifications, [])
            self.assertNotIn('synthetic-private', result.stdout)

    def test_author_permissions_and_creation_rights_do_not_replace_exact_context_moderation(self):
        for field in ('topic_moderator', 'topic_read_forum'):
            self.reset()
            setattr(type(self), field, False)
            before = len(self.calls)
            result = self.invoke(*self.command())
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('context read/moderation', result.stderr)
            self.assertEqual(self.writes(before), [])
        self.reset()
        type(self).topic_create_permission = False
        self.managed_topics[901]['permissions']['update'] = False
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_duplicate_foreign_unpinned_and_noop_orders_are_never_posted(self):
        before = len(self.calls)
        for order in (('901',), ('902', '902'), ('902', '903'), ('902', '901', '903'), ('902', '904'), ('901', '902')):
            result = self.invoke(*self.command(order=order))
            self.assertNotEqual(result.returncode, 0, (order, result.stderr))
            self.assertEqual(self.writes(before), [])
        result = self.invoke('topic-order', '111', '902', '901')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('acknowledge-all-pinned', result.stderr)
        self.assertEqual(self.writes(before), [])

    def test_unknown_pin_flags_and_ambiguous_positions_are_not_guessed(self):
        for field, value in (('pinned', None), ('pinned', 1), ('position', None), ('position', 1), ('position', True), ('position', -1)):
            self.reset()
            self.managed_topics[902][field] = value
            before = len(self.calls)
            result = self.invoke(*self.command())
            self.assertNotEqual(result.returncode, 0, (field, value, result.stderr))
            self.assertEqual(self.writes(before), [])

    def test_stale_positions_pin_flags_titles_context_rights_account_and_requested_order_never_post(self):
        for mode in ('position', 'pin', 'title', 'context', 'rights', 'account', 'selected'):
            self.reset()
            command = self.command()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'position':
                self.managed_topics[902]['position'] = 3
            elif mode == 'pin':
                self.managed_topics[903]['pinned'] = True
                self.managed_topics[903]['position'] = 3
            elif mode == 'title':
                self.managed_topics[903]['title'] = 'Changed'
            elif mode == 'context':
                self.topic_context['name'] = 'Changed'
            elif mode == 'rights':
                type(self).topic_moderator = False
            elif mode == 'account':
                type(self).topic_viewer = 8
            else:
                command = self.command(order=('901', '902'))
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, (mode, result.stderr))
            self.assertEqual(self.writes(before), [])

    def test_ignored_wrong_extra_or_malformed_acknowledgements_and_unavailable_readback_never_retry(self):
        for mode in ('ignored', 'wrong', 'extra', 'malformed', 'false', 'read_denied', 'account', 'denial'):
            self.reset()
            if mode == 'ignored':
                type(self).topic_order_ignore = True
            elif mode == 'wrong':
                type(self).topic_order_ack = {'reorder': True, 'order': ['901', '902'], 'private': 'synthetic-private-wrong-order'}
            elif mode == 'extra':
                type(self).topic_order_ack = {'reorder': True, 'order': ['902', '901', '904']}
            elif mode == 'malformed':
                type(self).topic_order_ack = []
            elif mode == 'false':
                type(self).topic_order_ack = {'reorder': False, 'order': ['902', '901']}
            elif mode == 'read_denied':
                type(self).topic_order_read_denied = True
            elif mode == 'account':
                type(self).topic_account_changed = True
            else:
                type(self).topic_denied = True
            before = len(self.calls)
            result = self.approved(self.command())
            self.assertNotEqual(result.returncode, 0, (mode, result.stderr))
            self.assertEqual(result.stdout, '')
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)

    def test_native_full_order_acknowledgement_does_not_substitute_for_independent_position_readback(self):
        type(self).topic_order_ignore = True
        type(self).topic_order_ack = {'reorder': True, 'order': ['902', '901']}
        before = len(self.calls)
        result = self.approved(self.command())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('may already have succeeded', result.stderr)
        self.assertEqual(len(self.writes(before)), 1)
        self.assertEqual(self.managed_topics[901]['position'], 1)

    def test_partial_inventory_and_invalid_local_order_never_send_a_post(self):
        before = len(self.calls)
        for command in (self.command('--max-pages', '1'), self.command('--max-pages', '0'),
                        self.command(order=()), self.command(order=('0', '901'))):
            result = self.invoke(*command)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.writes(before), [])

    def test_brief_and_offline_help_keep_order_visible_without_native_private_response_fields(self):
        result = self.approved(self.command('--format', 'brief'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('902 → 901', result.stdout)
        self.assertIn('pinned order verified', result.stdout)
        self.assertNotIn('synthetic-private', result.stdout)
        result = self.invoke('help', 'topic-order', '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('usage: canvas topic-order', result.stdout)
