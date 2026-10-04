"""Own hypothetical score storage and native forecast privacy, using synthetic data."""

import copy
import json
import unittest

from test_submission_attention import AttentionClient

from canvas_cli.arguments import parser
from canvas_cli.client import CanvasError
from canvas_cli.formatting import brief
from canvas_cli.navigation import command_help
from canvas_cli.what_if import _forecasts, change, read


class WhatIfClient(AttentionClient):
    def __init__(self):
        super().__init__()
        self.score = 4.0
        self.actual_grade = 20.0
        self.omit_score = False
        self.score_override = None
        self.ack = None
        self.forecasts = [{'current': {'grade': 80.0, 'total': 8.0, 'possible': 10.0, 'private': 'synthetic-private'},
                          'final': {'grade': None, 'full_weight': 100.0}, 'current_groups': {'private': 'synthetic-private'}}]
        self.calculation_error = False

    def graphql(self, document, variables, operation):
        result = super().graphql(document, variables, operation)
        if result['submission'] is not None and not self.omit_score:
            result['submission']['studentEnteredScore'] = self.score if self.score_override is None else self.score_override
        return result

    def request(self, path, method='GET', body=None, **options):
        if method == 'GET':
            return super().request(path, method, body, **options)
        self.calls.append((method, path, copy.deepcopy(body)))
        self.mutations.append((method, path, copy.deepcopy(body)))
        self.written = True
        if self.write_error:
            raise CanvasError('synthetic-private-write-error', status=self.write_error)
        if not self.ignore:
            self.score = body['student_entered_score']
        if self.calculation_error:
            raise CanvasError('synthetic-private-calculation-error', status=500)
        if self.advance:
            self.submission['attempt'] += 1
        result = {'submission': {'id': 71, 'student_entered_score': self.score, 'private': 'synthetic-private'},
                  'grades': self.forecasts, 'private': 'synthetic-private'}
        return self.ack if self.ack is not None else result, ''


class WhatIfTests(unittest.TestCase):
    def setUp(self):
        self.client = WhatIfClient()

    def preview(self, score=8.5, **options):
        return change(self.client, '123', '44', score, acknowledge=True, **options)

    def execute(self, score=8.5, **options):
        preview = self.preview(score, **options)
        return self.preview(score, yes=True, confirm=preview['confirm'], **options)

    def test_read_selects_own_hypothesis_not_actual_grade_or_assessment(self):
        result = read(self.client, '123', '44')
        self.assertEqual(result['student_entered_score'], 4.0)
        query = next(row for row in self.client.calls if row[0] == 'CanvasWhatIfScore')
        self.assertEqual(query[2], {'assignmentId': '44', 'userId': '7'})
        self.assertIn(' studentEnteredScore ', query[1])
        self.assertFalse(any(value in query[1] for value in ('score ', 'grade ', 'commentsConnection', 'meets', 'annotationContext')))
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertIn('Saved hypothetical points: 4.0', brief(result))
        self.assertEqual(self.client.mutations, [])

    def test_fractional_negative_and_extra_credit_scores_use_one_native_own_write(self):
        for score in (8.5, -10.0, 200.0, 0.0):
            self.setUp()
            result = self.execute(score)
            self.assertEqual(self.client.mutations, [('PUT', '/api/v1/submissions/71/what_if_grades', {'student_entered_score': score})])
            self.assertTrue(result['hypothetical_score_readback_verified'])
            self.assertFalse(result['official_grade_change_requested'])
            self.assertFalse(result['coursework_completion_requested'])
            self.assertEqual(self.client.actual_grade, 20.0)

    def test_single_clear_is_explicit_null_not_zero_or_course_wide_reset(self):
        result = self.execute(None)
        self.assertIsNone(result['student_entered_score'])
        self.assertEqual(self.client.mutations[0][2], {'student_entered_score': None})
        self.assertIn('no official grade change', brief(result))

    def test_native_forecasts_are_private_opt_in_whitelisted_totals_not_raw_dump(self):
        result = self.execute()
        self.assertFalse(result['forecasts_included'])
        self.assertNotIn('native_forecast_totals', result)
        self.setUp()
        result = self.execute(include_forecasts=True)
        self.assertEqual(result['native_forecast_totals'], [{'current': {'grade': 80.0, 'total': 8.0, 'possible': 10.0},
                                                            'final': {'grade': None, 'full_weight': 100.0}}])
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertNotIn('synthetic-private', brief(result))
        self.assertIn('current:', brief(result))
        self.setUp()
        self.client.forecasts = []
        self.assertEqual(self.execute(include_forecasts=True)['native_forecast_totals'], [])

    def test_nonfinite_boolean_text_or_huge_inputs_and_missing_flags_never_query(self):
        for score in (True, '8.0', [], float('nan'), float('inf'), float('-inf'), 10 ** 10000):
            with self.assertRaises(CanvasError):
                self.preview(score)
        with self.assertRaisesRegex(CanvasError, 'acknowledge-forecast'):
            change(self.client, '123', '44', 8.0)
        with self.assertRaises(CanvasError):
            self.preview(yes=True)
        self.assertEqual(self.client.calls, [])

    def test_missing_or_malformed_selected_score_is_not_cleared_or_write_authority(self):
        self.client.omit_score = True
        with self.assertRaisesRegex(CanvasError, 'omitted'):
            self.preview()
        for value in (False, '8.0', [], float('inf')):
            self.setUp()
            self.client.score_override = value
            with self.assertRaises(CanvasError):
                self.preview()
        self.assertEqual(self.client.mutations, [])

    def test_missing_submission_is_unknown_and_never_initialized(self):
        self.client.submission = None
        result = read(self.client, '123', '44')
        self.assertEqual(result['what_if_status'], 'unknown_no_accessible_submission')
        with self.assertRaisesRegex(CanvasError, 'existing own submission'):
            self.preview()
        self.assertEqual(self.client.mutations, [])

    def test_stale_score_policy_attempt_account_and_forecast_output_opt_in_require_new_preview(self):
        for mode in ('score', 'policy', 'attempt', 'account', 'output'):
            self.setUp()
            preview = self.preview()
            if mode == 'score':
                self.client.score = 2.0
            elif mode == 'policy':
                self.client.assignment['updatedAt'] = '2026-10-05T00:00:00Z'
            elif mode == 'attempt':
                self.client.submission['attempt'] += 1
            elif mode == 'account':
                self.client.user_id = 8
                self.client.submission['userId'] = '8'
            with self.assertRaisesRegex(CanvasError, 'Preview changed'):
                self.preview(yes=True, confirm=preview['confirm'], include_forecasts=mode == 'output')
            self.assertEqual(self.client.mutations, [])

    def test_documented_decimal_string_ack_is_accepted_but_malformed_or_foreign_ack_is_uncertain(self):
        self.client.ack = {'submission': {'id': 71, 'student_entered_score': '8.5'}, 'grades': self.client.forecasts}
        self.assertTrue(self.execute()['hypothetical_score_readback_verified'])
        for selected in (None, {}, {'id': True, 'student_entered_score': 8.5}, {'id': 72, 'student_entered_score': 8.5},
                         {'id': 71}, {'id': 71, 'student_entered_score': 8.0}, {'id': 71, 'student_entered_score': 'bad'},
                         {'id': 71, 'student_entered_score': 'nan'}, {'id': 71, 'student_entered_score': False}):
            self.setUp()
            self.client.ack = {'submission': selected, 'grades': self.client.forecasts}
            with self.assertRaisesRegex(CanvasError, 'unverified'):
                self.execute()
            self.assertEqual(len(self.client.mutations), 1)
        self.setUp()
        self.client.ack = []
        with self.assertRaisesRegex(CanvasError, 'unverified'):
            self.execute()

    def test_forecast_shapes_and_values_do_not_expose_private_errors_or_other_users(self):
        for rows in (None, {}, [{}, {}], [None], [{}], [{'current': None, 'final': {}}],
                     [{'current': {'grade': True}, 'final': {}}]):
            with self.assertRaises(CanvasError):
                _forecasts(rows)
        self.client.forecasts = None
        with self.assertRaisesRegex(CanvasError, 'unverified'):
            self.execute()
        self.assertEqual(len(self.client.mutations), 1)

    def test_native_calculation_failure_can_happen_after_saved_hypothesis_changed(self):
        self.client.calculation_error = True
        with self.assertRaisesRegex(CanvasError, 'already have changed') as raised:
            self.execute()
        self.assertEqual(self.client.score, 8.5)
        self.assertEqual(raised.exception.status, 500)
        self.assertEqual(len(self.client.mutations), 1)

    def test_denial_ignored_score_context_race_and_failed_readback_are_uncertain_without_retry(self):
        for mode in ('denied', 'ignore', 'switch', 'advance', 'policy', 'read'):
            self.setUp()
            if mode == 'denied':
                self.client.write_error = 403
            else:
                setattr(self.client, {'ignore': 'ignore', 'switch': 'switch_after', 'advance': 'advance',
                                      'policy': 'policy_after', 'read': 'read_after'}[mode], True)
            with self.assertRaisesRegex(CanvasError, 'unverified') as raised:
                self.execute()
            self.assertNotIn('synthetic-private', str(raised.exception))
            self.assertEqual(len(self.client.mutations), 1)

    def test_initial_account_switch_is_refused_before_mutation(self):
        self.client.switch_initial = True
        with self.assertRaisesRegex(CanvasError, 'account changed'):
            self.preview()
        self.assertEqual(self.client.mutations, [])

    def test_parser_and_help_distinguish_read_and_hypothesis_writes_offline(self):
        root = parser()
        self.assertEqual(command_help(root, 'what-if')['safety'], 'Read-only')
        for name in ('what-if-set', 'what-if-clear'):
            self.assertEqual(command_help(root, name)['safety'], 'Canvas writes (preview-first)')
        self.assertEqual(root.parse_args(['what-if-set', '123', '44', '--score', '-1']).score, -1.0)
