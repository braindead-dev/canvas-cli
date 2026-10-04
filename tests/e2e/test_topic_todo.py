"""Installed shared discussion to-do changes against independent synthetic HTTPS."""

import copy
import json

from . import topic_management
from .fixture import CanvasFixture


class TopicTodoE2E(CanvasFixture):
    def setUp(self):
        self.reset()

    def reset(self):
        topic_management.initialize(type(self), enabled=True)
        type(self).topic_todo_enabled = True

    def command(self, *extra, group=False, clear=False):
        selected = ('--clear-todo',) if clear else ('--todo-at', '2040-10-02T12:00:00-07:00')
        return ('topic-todo', '119' if group else '111', '901', '--context', 'group' if group else 'course',
                *selected, '--acknowledge-shared-topic', '--acknowledge-student-todo-change', *extra)

    def approved(self, command):
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def writes(self, before):
        return [row for row in self.calls[before:] if row[0] != 'GET']

    def test_preview_reports_shared_student_date_permission_without_prompt_signed_links_or_peer_reads(self):
        before = len(self.calls)
        result = self.invoke(*self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['body'], {'todo_date': '2040-10-02T19:00:00Z'})
        self.assertEqual(data['todo_permissions'], {'manage_course_content_add': True})
        self.assertTrue(data['additional_context_permission_required'])
        self.assertTrue(data['acknowledge_student_todo_change'])
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertEqual(self.writes(before), [])
        self.assertTrue(any('page=2' in route for _, route in self.calls[before:]))
        self.assertFalse(any('/entries' in route or '/view' in route for _, route in self.calls[before:]))

    def test_course_and_group_exact_date_changes_preserve_prompt_states_associations_and_peer_entries(self):
        for group in (False, True):
            self.reset()
            source = copy.deepcopy(self.managed_topics[901])
            sibling = copy.deepcopy(self.managed_topics[902])
            before = len(self.calls)
            result = self.approved(self.command(group=group))
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertTrue(data['student_todo_date']['verified'])
            self.assertFalse(data['student_todo_date']['planner_effects_verified'])
            self.assertEqual(data['student_todo_date']['stored'], '2040-10-02T19:00:00Z')
            self.assertEqual(data['changed_fields'], ['todo_date'])
            self.assertEqual(self.managed_topics[901], source | {'todo_date': '2040-10-02T19:00:00Z'})
            self.assertEqual(self.managed_topics[902], sibling)
            self.assertEqual(self.topic_entries, [{'id': 991, 'message': 'synthetic-private-peer-reply'}])
            self.assertFalse(self.topic_attachment_deleted)
            prefix = 'groups/119' if group else 'courses/111'
            self.assertEqual(self.writes(before), [('PUT', f'/api/v1/{prefix}/discussion_topics/901?no_verifiers=true')])
            self.assertNotIn('synthetic-private', result.stdout)

    def test_native_clearing_needs_topic_update_but_no_add_permission_and_no_permission_lookup(self):
        for group in (False, True):
            self.reset()
            self.managed_topics[901]['todo_date'] = '2040-10-02T19:00:00Z'
            type(self).topic_content_add = False
            before = len(self.calls)
            result = self.approved(self.command(group=group, clear=True))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsNone(json.loads(result.stdout)['student_todo_date']['stored'])
            self.assertEqual(len(self.writes(before)), 1)
            self.assertFalse(any('/permissions' in route for _, route in self.calls[before:]))
        self.reset()
        self.managed_topics[901].update(todo_date='2040-10-02T19:00:00Z', permissions={'update': False, 'delete': True})
        before = len(self.calls)
        result = self.invoke(*self.command(clear=True))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.writes(before), [])

    def test_past_midnight_and_equivalent_offset_storage_do_not_apply_availability_midnight_rules(self):
        self.managed_topics[901].update(published=False, locked=True, delayed_post_at='2045-01-01T00:00:00Z')
        command = ('topic-todo', '111', '901', '--todo-at', '2020-01-01T00:00:00-07:00',
                   '--acknowledge-shared-topic', '--acknowledge-student-todo-change')
        result = self.approved(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['student_todo_date']['stored'], '2020-01-01T07:00:00Z')
        self.assertFalse(self.managed_topics[901]['published'])
        self.assertTrue(self.managed_topics[901]['locked'])
        self.reset()
        type(self).topic_todo_offset_storage = True
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['student_todo_date']['stored'], '2040-10-02T19:00:00+00:00')
        before = len(self.calls)
        result = self.invoke(*self.command())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already matches', result.stderr)
        self.assertEqual(self.writes(before), [])

    def test_missing_denied_or_malformed_add_rights_and_unsupported_topics_never_put(self):
        for value in (False, None, 1, 'true'):
            self.reset()
            type(self).topic_content_add = value
            before = len(self.calls)
            result = self.invoke(*self.command())
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.writes(before), [])
        for report in ({}, [], {'manage_course_content_add': 1}):
            self.reset()
            type(self).topic_content_add_report = report
            before = len(self.calls)
            result = self.invoke(*self.command())
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.writes(before), [])
        for field, value in (('assignment_id', 88), ('root_topic_id', 89), ('group_category_id', 90),
                             ('anonymous_state', 'full_anonymity'), ('is_announcement', True), ('todo_date', 'not-a-date')):
            self.reset()
            self.managed_topics[901][field] = value
            before = len(self.calls)
            result = self.invoke(*self.command())
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.writes(before), [])
        self.reset()
        del self.managed_topics[901]['todo_date']
        before = len(self.calls)
        result = self.invoke(*self.command())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.writes(before), [])

    def test_stale_account_context_prompt_date_audience_inventory_or_permission_never_put(self):
        for mode in ('account', 'context', 'prompt', 'date', 'audience', 'inventory', 'permission'):
            self.reset()
            command = self.command()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'account':
                type(self).topic_viewer = 8
            elif mode == 'context':
                self.topic_context['name'] = 'Changed'
            elif mode == 'prompt':
                self.managed_topics[901]['message'] = 'Changed'
            elif mode == 'date':
                self.managed_topics[901]['todo_date'] = '2040-10-01T19:00:00Z'
            elif mode == 'audience':
                self.managed_topics[901]['ungraded_discussion_overrides'] = []
            elif mode == 'inventory':
                self.managed_topics[902]['title'] = 'Changed'
            else:
                type(self).topic_content_add = False
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, (mode, result.stderr))
            self.assertEqual(self.writes(before), [])

    def test_ignored_shifted_unavailable_wrong_ack_or_changed_account_fail_once_without_cleanup(self):
        for field, value in (('topic_ignore', True), ('topic_todo_shift', True), ('topic_readback_denied', True),
                             ('topic_account_changed', True), ('topic_ack_patch', []),
                             ('topic_ack_patch', {'todo_date': 'synthetic-private-malformed'}),
                             ('topic_readback_patch', {'todo_date': '2040-10-01T19:00:00Z'})):
            self.reset()
            setattr(type(self), field, value)
            before = len(self.calls)
            result = self.approved(self.command())
            self.assertNotEqual(result.returncode, 0, (field, result.stderr))
            self.assertIn('may already have succeeded', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)
            self.assertEqual(result.stdout, '')
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertFalse(self.topic_attachment_deleted)
        self.reset()
        type(self).topic_denied = True
        before = len(self.calls)
        result = self.approved(self.command())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.writes(before)), 1)

    def test_verified_date_can_lose_future_update_and_unavailable_inventory_is_not_success(self):
        type(self).topic_state_lose_edit = True
        result = self.approved(self.command('--format', 'brief'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Shared student to-do date', result.stdout)
        self.assertIn('planner effects and completion are not verified', result.stdout)
        self.assertFalse(self.managed_topics[901]['permissions']['update'])
        for flag in ('topic_state_inventory_denied', 'topic_state_hide_after'):
            self.reset()
            type(self).topic_state_enabled = True
            setattr(type(self), flag, True)
            before = len(self.calls)
            result = self.approved(self.command())
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(self.writes(before)), 1)

    def test_parser_flags_bad_dates_partial_pagination_and_offline_help_never_write(self):
        commands = (('topic-todo', '111', '901'), ('topic-todo', '111', '901', '--clear-todo'),
                    self.command('--max-pages', '1'), self.command('--max-pages', '0'),
                    self.command('--clear-todo'), self.command('--yes'), self.command('--confirm', 'unpaired'))
        for command in commands:
            before = len(self.calls)
            result = self.invoke(*command)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.writes(before), [])
        for value in ('tomorrow', '2040-10-02', '2040-10-02T12:00:00', '2040-10-02T12:00:00.001Z'):
            command = ('topic-todo', '111', '901', '--todo-at', value,
                       '--acknowledge-shared-topic', '--acknowledge-student-todo-change')
            before = len(self.calls)
            result = self.invoke(*command)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.writes(before), [])
        before = len(self.calls)
        result = self.invoke('help', 'topic-todo', '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('usage: canvas topic-todo', result.stdout)
        self.assertEqual(self.calls[before:], [])
