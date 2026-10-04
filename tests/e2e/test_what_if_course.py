"""Actual CLI subprocesses against synthetic TLS, never a real course reset."""

import json

from . import what_if_course
from .fixture import CanvasFixture


class CourseWhatIfE2E(CanvasFixture):
    def setUp(self):
        what_if_course.initialize(type(self), enabled=True)

    def approved(self, *extra):
        command = ('what-if-reset', '141', '--acknowledge-all-what-if', *extra)
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def test_reported_inventory_paginated_own_only_with_unsubmitted_rows_not_hidden_scores(self):
        type(self).course_hypothesis_paginate = True
        result = self.invoke('what-if-course', '141', '--max-pages', '2')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(set(data['submissions']), {'741', '742'})
        self.assertEqual(data['submissions']['741']['state'], 'unsubmitted')
        self.assertFalse(data['hidden_rows_verified'])
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)
        self.assertTrue(all(query['variables']['userId'] == '7' for query in self.course_hypothesis_queries))
        self.assertEqual(self.course_hypothesis_mutations, [])

    def test_bulk_reset_not_per_item_fallback_and_hidden_clear_storage_is_not_claimed_verified(self):
        result = self.approved()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['reported_hypotheses_clear_verified'])
        self.assertFalse(data['hidden_rows_verified'])
        self.assertFalse(data['official_grade_change_requested'])
        self.assertEqual(self.course_hypothesis_mutations, [{}])
        self.assertEqual(self.course_hidden_hypotheses, [None, None])
        self.assertEqual(self.course_hypothesis_timestamps, 4)
        self.assertEqual(self.course_hypothesis_actual_grade, 90.0)
        self.assertNotIn('native_recalculated_totals', data)

    def test_opt_in_totals_are_native_projection_not_private_raw_grade_records(self):
        result = self.approved('--include-totals', '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('current:', result.stdout)
        self.assertIn('hidden-row clearing remains unverified', result.stdout)
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)

    def test_explicit_all_ack_permission_or_incomplete_pagination_prevent_reset(self):
        result = self.invoke('what-if-reset', '141')
        self.assertEqual(result.returncode, 1)
        self.assertIn('acknowledge-all', result.stderr)
        type(self).course_reset_permission = False
        result = self.invoke('what-if-reset', '141', '--acknowledge-all-what-if')
        self.assertEqual(result.returncode, 1)
        self.setUp()
        type(self).course_hypothesis_paginate = True
        result = self.invoke('what-if-reset', '141', '--acknowledge-all-what-if', '--max-pages', '1')
        self.assertEqual(result.returncode, 1)
        self.assertIn('page cap', result.stderr)
        self.assertEqual(self.course_hypothesis_mutations, [])

    def test_stale_score_output_opt_in_and_inventory_changes_refuse_old_preview(self):
        command = ('what-if-reset', '141', '--acknowledge-all-what-if')
        for mode in ('score', 'output', 'row'):
            with self.subTest(mode=mode):
                self.setUp()
                preview = self.invoke(*command)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                if mode == 'score':
                    self.course_hypotheses[0]['studentEnteredScore'] = 7.0
                elif mode == 'row':
                    self.course_hypotheses[0]['attempt'] += 1
                extra = ('--include-totals',) if mode == 'output' else ()
                result = self.invoke(*command, *extra, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
                self.assertEqual(result.returncode, 1)
                self.assertEqual(self.course_hypothesis_mutations, [])

    def test_calculation_can_fail_after_all_hidden_and_reported_hypotheses_clear(self):
        type(self).course_reset_calculation_error = True
        result = self.approved()
        self.assertEqual(result.returncode, 1)
        self.assertIn('already have been cleared', result.stderr)
        self.assertEqual(self.course_hidden_hypotheses, [None, None])
        self.assertTrue(all(row['studentEnteredScore'] is None for row in self.course_hypotheses))
        self.assertEqual(len(self.course_hypothesis_mutations), 1)
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)

    def test_empty_published_inventory_still_has_explicit_hidden_scope(self):
        type(self).course_hypotheses = []
        result = self.approved()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['submissions'], {})
        self.assertFalse(json.loads(result.stdout)['hidden_rows_verified'])
        self.assertEqual(self.course_hidden_hypotheses, [None, None])

    def test_denial_bad_ack_ignored_storage_and_post_write_races_are_uncertain(self):
        for mode in ('denial', 'ack', 'ignore', 'account', 'permission', 'row', 'read'):
            with self.subTest(mode=mode):
                self.setUp()
                if mode == 'ack':
                    type(self).course_reset_ack = {'grades': [{}, {}], 'private': 'synthetic-private'}
                else:
                    setattr(type(self), {'denial': 'course_reset_denied', 'ignore': 'course_reset_ignore',
                                        'account': 'course_reset_switch', 'permission': 'course_reset_permission_after',
                                        'row': 'course_reset_row_after', 'read': 'course_reset_read_after'}[mode], True)
                result = self.approved()
                self.assertEqual(result.returncode, 1)
                self.assertIn('unverified', result.stderr)
                self.assertEqual(len(self.course_hypothesis_mutations), 1)
                self.assertNotIn('synthetic-private', result.stdout + result.stderr)
