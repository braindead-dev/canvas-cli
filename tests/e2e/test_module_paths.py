"""Installed commands, native HTTPS choice effects, pagination and uncertain readback."""

import json

from . import module_items, module_paths
from .fixture import CanvasFixture


class MasteryPathsE2E(CanvasFixture):
    def setUp(self):
        module_items.initialize(type(self), enabled=True)
        module_paths.initialize(type(self), enabled=True)

    def command(self, choice='801', *, switching=False):
        return ('module-path-select', '109', '21', '201', choice, '--acknowledge-path-change',
                *(('--acknowledge-path-switch',) if switching else ()))

    def approve(self, choice='801', *, switching=False):
        args = self.command(choice, switching=switching)
        result = self.invoke(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.invoke(*args, '--yes', '--confirm', json.loads(result.stdout)['confirm'])

    def writes(self, since):
        return [row for row in self.calls[since:] if row[0] != 'GET']

    def test_installed_discovery_and_preview_have_no_choice_write_and_do_not_expose_models_or_answers(self):
        before = len(self.calls)
        result = self.invoke('module-paths', '109', '21', '201', '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Set 801 | assignments: 91, 92', result.stdout)
        self.assertIn('processing: unknown', result.stdout)
        preview = self.invoke(*self.command())
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertEqual(data['body'], {'assignment_set_id': 801, 'student_id': 7})
        self.assertEqual(data['trigger']['submission']['score'], 0)
        self.assertNotIn('synthetic-private', result.stdout + preview.stdout)
        self.assertEqual(self.writes(before), [])
        self.assertEqual(self.module_single_gets, 0)

    def test_native_selection_switch_removes_old_only_preserves_shared_and_reads_own_choice(self):
        before = len(self.calls)
        result = self.approve()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['choice_verified'])
        self.assertEqual(self.path_assigned, {91, 92})
        result = self.invoke(*self.command('802'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('acknowledge-path-switch', result.stderr)
        result = self.approve('802', switching=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['choice_verified'])
        self.assertEqual(data['effects']['potentially_removed_assignment_ids'], [91])
        self.assertEqual(data['effects']['shared_with_other_choices_assignment_ids'], [92])
        self.assertEqual(self.path_assigned, {92, 93})
        self.assertEqual(len(self.writes(before)), 2)
        self.assertFalse(data['due_dates_verified'])
        self.assertNotIn('synthetic-private', result.stdout)

    def test_quiz_discussion_and_page_triggers_use_native_associations_without_quiz_attempt_or_page_view(self):
        for kind in ('Quiz', 'Discussion', 'Page'):
            self.setUp()
            type(self).path_item_type = kind
            self.native_items[0].update(type=kind, content_id=77)
            if kind == 'Page':
                self.native_items[0]['page_url'] = 'welcome'
            before = len(self.calls)
            result = self.approve()
            with self.subTest(kind=kind):
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(json.loads(result.stdout)['choice_verified'])
                self.assertEqual(len(self.writes(before)), 1)
                self.assertEqual(self.module_single_gets, 0)
                self.assertFalse(any('/pages/' in route or '/quizzes/77/submissions' in route for _, route in self.calls[before:]))
                if kind == 'Page':
                    self.assertGreaterEqual(self.path_page_lists, 4)
                    self.assertTrue(any('/pages?' in route and 'page=2' in route for _, route in self.calls[before:]))

    def test_page_and_module_limits_never_turn_partial_inventories_into_a_selection(self):
        before = len(self.calls)
        result = self.invoke(*self.command(), '--max-pages', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Page limit', result.stderr)
        # Keep module inventory on one page to independently hit page-association pagination.
        type(self).path_item_type = 'Page'
        self.native_items[0].update(type='Page', content_id=77, page_url='welcome')
        self.native_items.pop()
        self.native_module['items_count'] = 1
        result = self.invoke(*self.command(), '--max-pages', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Page limit', result.stderr)
        self.assertEqual(self.writes(before), [])

    def test_stale_grade_or_choice_preview_no_post_unposted_trigger_and_reselect_are_refused(self):
        before = len(self.calls)
        preview = self.invoke(*self.command())
        self.path_submission['score'] = 1
        result = self.invoke(*self.command(), '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Preview changed', result.stderr)
        type(self).path_posted = False
        result = self.invoke(*self.command())
        self.assertNotEqual(result.returncode, 0)
        type(self).path_posted = True
        type(self).path_choice = 801
        result = self.invoke(*self.command())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already reports selected', result.stderr)
        self.assertEqual(self.writes(before), [])

    def test_native_ignored_delayed_result_is_acknowledged_not_verified_and_never_retried(self):
        type(self).path_ignored = True
        before = len(self.calls)
        result = self.approve()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['status'], 'accepted_choice_unverified')
        self.assertFalse(data['choice_verified'])
        self.assertEqual(len(self.writes(before)), 1)

    def test_installed_single_automatic_path_reapplication_requires_explicit_flag_and_stays_unverified(self):
        self.path_choices.pop(802)
        type(self).path_choice = 801
        before = len(self.calls)
        result = self.invoke(*self.command())
        self.assertNotEqual(result.returncode, 0)
        args = (*self.command(), '--reapply-selected-path')
        preview = self.invoke(*args)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        result = self.invoke(*args, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['automatic_path_reported'])
        self.assertFalse(data['choice_verified'])
        self.assertEqual(len(self.writes(before)), 1)

    def test_denial_foreign_ack_and_readback_denial_fail_with_one_post_and_no_private_body(self):
        for mode in ('denied', 'foreign_ack', 'readback'):
            self.setUp()
            if mode == 'denied':
                type(self).path_denied = True
            elif mode == 'foreign_ack':
                type(self).path_ack_override = {'meta': {'primaryCollection': 'assignments'}, 'items': [],
                                               'assignments': [{'id': 99, 'description': 'synthetic-private-ack'}]}
            else:
                type(self).path_readback_denied = True
            before = len(self.calls)
            result = self.approve()
            with self.subTest(mode=mode):
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('synthetic-private', result.stdout + result.stderr)
                self.assertEqual(len(self.writes(before)), 1)
                if mode != 'denied':
                    self.assertIn('may have changed', result.stderr)

    def test_offline_help_schema_discovery_and_invalid_flags_need_no_auth(self):
        before = len(self.calls)
        result = self.invoke('help', '--search', 'mastery', '--format', 'brief', token='invalid')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('module-path-select', result.stdout)
        result = self.invoke('schema', 'module-path-select', token='invalid')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['commands'][0]['safety'], 'Canvas writes (preview-first)')
        for extra in ((), ('--yes',), ('--confirm', 'fake')):
            result = self.invoke('module-path-select', '109', '21', '201', '801', *extra)
            self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls[before:], [])
