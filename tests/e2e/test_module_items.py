"""Real installed command/HTTPS transport with independent own native progress."""

import copy
import json

from . import module_items
from .fixture import CanvasFixture


class ModuleItemsE2E(CanvasFixture):
    def setUp(self):
        module_items.initialize(type(self), enabled=True)

    def command(self, operation='done'):
        name = {'done': 'module-item-done', 'not-done': 'module-item-not-done', 'read': 'module-item-mark-read'}[operation]
        return (name, '109', '21', '201', '--acknowledge-module-progress',
                *(('--acknowledge-content-viewed',) if operation == 'read' else ()))

    def approve(self, operation='done'):
        arguments = self.command(operation)
        preview = self.invoke(*arguments)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*arguments, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def writes(self, since):
        return [row for row in self.calls[since:] if row[0] != 'GET']

    def test_inspection_paginates_and_never_invokes_horizon_implicit_read(self):
        self.native_items[0]['completion_requirement'] = {'type': 'must_view', 'completed': False}
        before = len(self.calls)
        result = self.invoke('module-item', '109', '21', '201')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['module_item']['completion'], 'incomplete')
        self.assertTrue(data['complete_item_inventory'])
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertEqual(self.module_single_gets, 0)
        self.assertTrue(any('page=2' in route for _, route in self.calls[before:]))
        self.assertEqual(self.writes(before), [])

    def test_sequence_installed_navigation_private_mastery_projection_without_content_follow(self):
        before = len(self.calls)
        result = self.invoke('module-sequence', '109', 'ModuleItem', '201')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertIsNone(data['module_sequence'][0]['current']['locked_for_user'])
        self.assertEqual(data['module_sequence'][0]['current']['completion'], 'unknown')
        self.assertEqual(data['module_sequence'][0]['mastery_path']['assignment_set_ids'], [801])
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertEqual(self.calls[before:], [('GET', '/api/v1/courses/109'),
                                              ('GET', '/api/v1/courses/109/module_item_sequence?asset_type=ModuleItem&asset_id=201')])
        self.assertEqual(self.module_single_gets, 0)

    def test_sequence_quiz_and_discussion_associated_assignment_is_checked_without_attempts(self):
        for kind, resource in (('Quiz', 'quizzes'), ('Discussion', 'discussion_topics')):
            self.setUp()
            before = len(self.calls)
            result = self.invoke('module-sequence', '109', kind, '77')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.calls[before:][-1], ('GET', f'/api/v1/courses/109/{resource}/77'))
            self.assertEqual(self.writes(before), [])
            self.assertNotIn('synthetic-private', result.stdout)
        self.module_source['assignment_id'] = 89
        result = self.invoke('module-sequence', '109', 'Quiz', '77')
        self.assertNotEqual(result.returncode, 0)

    def test_sequence_ten_native_occurrences_are_labeled_potentially_incomplete(self):
        template = self.module_sequence['items'][0]
        self.module_sequence['items'] = [dict(copy.deepcopy(template), current={**copy.deepcopy(template['current']), 'id': 201 + index})
                                         for index in range(10)]
        self.module_sequence['modules'][0]['items_count'] = 12
        result = self.invoke('module-sequence', '109', 'Assignment', '88', '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('additional occurrences may exist', result.stdout)
        self.assertNotIn('synthetic-private', result.stdout)

    def test_sequence_invalid_asset_input_no_requests_and_foreign_neighbors_fail_closed(self):
        for kind, item in (('File', '../3'), ('Page', 'https://foreign.example'), ('Page', 'private?token=x')):
            before = len(self.calls)
            result = self.invoke('module-sequence', '109', kind, item)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.calls[before:], [])
        self.module_sequence['items'][0]['next']['module_id'] = 99
        result = self.invoke('module-sequence', '109', 'ModuleItem', '201')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('referenced module', result.stderr)

    def test_preview_no_event_account_bound_safe_projection_and_page_limit_not_partial_success(self):
        before = len(self.calls)
        result = self.invoke(*self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['user_id'], 7)
        self.assertEqual(data['method'], 'PUT')
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertTrue(any('student_id=7' in route for _, route in self.calls[before:]))
        result = self.invoke(*self.command(), '--max-pages', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Page limit', result.stderr)
        self.assertEqual(self.writes(before), [])

    def test_done_then_not_done_one_event_each_with_independent_stored_state(self):
        before = len(self.calls)
        done = self.approve()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(json.loads(done.stdout)['requirement_status_verified'])
        self.assertTrue(self.module_planner_complete)
        undone = self.approve('not-done')
        self.assertEqual(undone.returncode, 0, undone.stderr)
        data = json.loads(undone.stdout)
        self.assertFalse(data['module_item']['requirement']['completed'])
        self.assertFalse(data['planner_synchronization_verified'])
        self.assertFalse(self.module_planner_complete)
        self.assertEqual(self.writes(before), [
            ('PUT', '/api/v1/courses/109/modules/21/items/201/done'),
            ('DELETE', '/api/v1/courses/109/modules/21/items/201/done')])
        self.assertEqual(self.module_single_gets, 0)

    def test_read_is_distinct_never_starts_quiz_and_labels_unverifiable_criteria(self):
        for criterion, expected in (({'type': 'must_view', 'completed': False}, True),
                                    ({'type': 'must_submit', 'completed': False}, None), (None, None)):
            self.setUp()
            self.native_items[0].update(type='Quiz', completion_requirement=criterion)
            before = len(self.calls)
            result = self.approve('read')
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertIs(data['requirement_status_verified'], expected)
            self.assertEqual(self.writes(before), [('POST', '/api/v1/courses/109/modules/21/items/201/mark_read')])
            self.assertFalse(any('/quizzes/' in route for _, route in self.calls[before:]))
            self.assertEqual(self.module_single_gets, 0)

    def test_invalid_arguments_and_missing_acknowledgement_make_no_canvas_calls(self):
        for arguments in (('module-item-done', '109', '21', '201'),
                          ('module-item-mark-read', '109', '21', '201', '--acknowledge-module-progress'),
                          ('module-item', '109', '21', '0'),
                          (*self.command(), '--yes'), (*self.command(), '--confirm', 'digest'),
                          (*self.command(), '--max-pages', '0')):
            before = len(self.calls)
            result = self.invoke(*arguments)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.calls[before:], [])

    def test_native_role_module_lock_and_assessment_requirement_fail_before_events(self):
        for mode in ('role', 'locked_module', 'locked_item', 'unpublished', 'requirement', 'already', 'wrong_parent'):
            self.setUp()
            if mode == 'role':
                self.module_rights['participate_as_student'] = False
            elif mode == 'locked_module':
                self.native_module['state'] = 'locked'
            elif mode == 'locked_item':
                self.native_items[0]['content_details']['locked_for_user'] = True
            elif mode == 'unpublished':
                self.native_items[0]['published'] = False
            elif mode == 'requirement':
                self.native_items[0]['completion_requirement']['type'] = 'min_score'
            elif mode == 'already':
                self.native_items[0]['completion_requirement']['completed'] = True
            else:
                self.native_items[0]['module_id'] = 99
            before = len(self.calls)
            result = self.invoke(*self.command())
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.writes(before), [])
            self.assertNotIn('synthetic-private', result.stderr)

    def test_stale_preview_other_item_and_own_identity_changes_send_no_event(self):
        for mode in ('inventory', 'policy', 'viewer'):
            self.setUp()
            preview = self.invoke(*self.command())
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'inventory':
                self.native_items[1]['title'] = 'Changed'
            elif mode == 'policy':
                self.native_module['publish_final_grade'] = True
            else:
                type(self).module_viewer = 8
            before = len(self.calls)
            result = self.invoke(*self.command(), '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Preview changed', result.stderr)
            self.assertEqual(self.writes(before), [])

    def test_ignored_denied_or_unverifiable_event_never_retries_or_logs_response_bodies(self):
        for mode in ('ignored', 'denied', 'readback', 'ack', 'metadata'):
            self.setUp()
            if mode == 'ignored':
                type(self).module_ignore_event = True
            elif mode == 'denied':
                type(self).module_events_denied = True
            elif mode == 'readback':
                type(self).module_readback_denied = True
            elif mode == 'ack':
                type(self).module_acknowledgement = {'private': 'synthetic-private-malformed-ack'}
            else:
                type(self).module_post_patch = {'title': 'Changed'}
            before = len(self.calls)
            result = self.approve()
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(self.writes(before)), 1)
            self.assertNotIn('synthetic-private', result.stderr)
            if mode != 'denied':
                self.assertIn('may have changed', result.stderr)
