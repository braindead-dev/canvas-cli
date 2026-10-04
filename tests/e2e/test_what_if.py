"""Installed what-if read, saved points and explicit clearing over synthetic HTTPS."""

import json

from . import what_if
from .fixture import CanvasFixture


class WhatIfE2E(CanvasFixture):
    def setUp(self):
        what_if.initialize(type(self), enabled=True)

    def approved(self, *extra, action='what-if-set'):
        command = (action, '141', '941', '--acknowledge-forecast-change', *extra)
        if action == 'what-if-set':
            command += ('--score', '8.5')
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def test_read_is_own_metadata_without_native_assignment_view_or_assessment(self):
        result = self.invoke('what-if', '141', '941')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['student_entered_score'], 4.0)
        self.assertEqual(self.what_if_mutations, [])
        self.assertTrue(all(query['variables']['userId'] == '7' for query in self.what_if_queries))
        self.assertFalse(any(word in query['query'] for query in self.what_if_queries for word in ('score ', 'grade ', 'commentsConnection', 'annotationContext')))

    def test_set_then_clear_exact_saved_hypothesis_with_independent_readback(self):
        result = self.approved()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['hypothetical_score_readback_verified'])
        result = self.approved(action='what-if-clear')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.what_if_mutations, [{'student_entered_score': 8.5}, {'student_entered_score': None}])
        self.assertIsNone(self.what_if_score)
        self.assertEqual(self.what_if_actual_grade, 20.0)

    def test_opt_in_native_totals_are_projected_without_private_response_fields(self):
        result = self.approved('--include-forecasts')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['native_forecast_totals'], [{'current': {'grade': 85.0, 'total': 8.5, 'possible': 10.0},
                                                         'final': {'grade': None, 'full_weight': 100.0}}])
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)
        self.assertFalse(data['official_grade_change_requested'])

    def test_missing_submission_and_nonfinite_input_do_not_initialize_or_write(self):
        type(self).what_if_submission = None
        result = self.invoke('what-if', '141', '941')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['what_if_status'], 'unknown_no_accessible_submission')
        result = self.invoke('what-if-set', '141', '941', '--score', '8.5', '--acknowledge-forecast-change')
        self.assertEqual(result.returncode, 1)
        self.setUp()
        for score in ('nan', 'inf', '1e309'):
            result = self.invoke('what-if-set', '141', '941', '--score', score, '--acknowledge-forecast-change')
            self.assertEqual(result.returncode, 1)
        self.assertEqual(self.what_if_mutations, [])

    def test_stale_hypothesis_or_new_output_opt_in_refuses_old_digest(self):
        command = ('what-if-set', '141', '941', '--score', '8.5', '--acknowledge-forecast-change')
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        type(self).what_if_score = 3.0
        result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.what_if_mutations, [])

    def test_native_error_can_follow_saved_column_update_without_retry(self):
        type(self).what_if_calculation_error = True
        result = self.approved()
        self.assertEqual(result.returncode, 1)
        self.assertIn('already have changed', result.stderr)
        self.assertEqual(self.what_if_score, 8.5)
        self.assertEqual(len(self.what_if_mutations), 1)
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)

    def test_denial_ignored_storage_bad_ack_and_post_write_races_are_uncertain(self):
        for mode in ('denied', 'ignore', 'ack', 'account', 'attempt', 'policy', 'readback'):
            with self.subTest(mode=mode):
                self.setUp()
                if mode == 'ack':
                    type(self).what_if_ack = {'submission': {'id': 742, 'student_entered_score': 8.5}, 'grades': []}
                else:
                    setattr(type(self), {'denied': 'what_if_denied', 'ignore': 'what_if_ignore', 'account': 'what_if_switch',
                                        'attempt': 'what_if_advance', 'policy': 'what_if_policy_after', 'readback': 'what_if_read_after'}[mode], True)
                result = self.approved()
                self.assertEqual(result.returncode, 1)
                self.assertIn('unverified', result.stderr)
                self.assertEqual(len(self.what_if_mutations), 1)
                self.assertNotIn('synthetic-private', result.stdout + result.stderr)
