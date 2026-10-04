"""Own course hypotheses, bounded visibility and genuinely bulk reset semantics."""

import copy
import json
import unittest

from canvas_cli.arguments import parser
from canvas_cli.client import CanvasError
from canvas_cli.formatting import brief
from canvas_cli.navigation import command_help
from canvas_cli.what_if_course import read, reset


class CourseHypothesisClient:
    host = 'https://canvas.example.edu'

    def __init__(self):
        self.course = {'_id': '123', 'state': 'available'}
        self.rows = [{'_id': '71', 'userId': '7', 'assignmentId': '44', 'assignment': {'_id': '44', 'courseId': '123', 'published': True},
                      'attempt': 0, 'state': 'unsubmitted', 'submittedAt': None, 'studentEnteredScore': 8.0},
                     {'_id': '72', 'userId': '7', 'assignmentId': '45', 'assignment': {'_id': '45', 'courseId': '123', 'published': True},
                      'attempt': 2, 'state': 'graded', 'submittedAt': '2026-10-03T00:00:00Z', 'studentEnteredScore': None}]
        self.hidden = [9.0, None]
        self.timestamp_writes = 0
        self.official_grade = 90.0
        self.user_id = 7
        self.permission = True
        self.written = self.ignore = self.calculation_error = False
        self.switch_initial = self.switch_after = self.permission_after = self.course_after = self.row_after = self.read_after = False
        self.course_between_pages = self.permission_during = False
        self.account_calls = self.graphql_calls = 0
        self.permission_calls = 0
        self.pages = self.ack = self.permission_override = None
        self.write_error = None
        self.forecasts = [{'current': {'grade': 90.0, 'private': 'synthetic-private'}, 'final': {'grade': None}}]
        self.calls, self.mutations = [], []

    def request(self, route, method='GET', body=None):
        self.calls.append((method, route, copy.deepcopy(body)))
        if route == '/api/v1/users/self/profile':
            self.account_calls += 1
            return {'id': 8 if self.written and self.switch_after or self.switch_initial and self.account_calls > 1 else self.user_id}, ''
        if method == 'GET':
            self.permission_calls += 1
            if self.permission_override is not None:
                return self.permission_override, ''
            return {'reset_what_if_grades': False if self.written and self.permission_after or self.permission_during and self.permission_calls > 1
                    else self.permission}, ''
        self.written = True
        self.mutations.append((method, route, body))
        if self.write_error:
            raise CanvasError('synthetic-private-denial', status=self.write_error)
        if not self.ignore:
            for row in self.rows:
                row['studentEnteredScore'] = None
            self.hidden = [None] * len(self.hidden)
            self.timestamp_writes += len(self.rows) + len(self.hidden)
        if self.calculation_error:
            raise CanvasError('synthetic-private-calculation-failure', status=500)
        if self.row_after:
            self.rows[0]['attempt'] += 1
        return self.ack if self.ack is not None else {'grades': self.forecasts, 'private': 'synthetic-private'}, ''

    def graphql(self, document, variables, operation):
        self.calls.append((operation, document, copy.deepcopy(variables)))
        self.graphql_calls += 1
        if self.written and self.read_after:
            raise CanvasError('synthetic-private-readback-failure', status=403)
        course = copy.deepcopy(self.course)
        if self.written and self.course_after or self.course_between_pages and self.graphql_calls > 1:
            course['state'] = 'completed'
        connection = (copy.deepcopy(self.pages[self.graphql_calls - 1]) if self.pages is not None else
                      {'nodes': copy.deepcopy(self.rows), 'pageInfo': {'hasNextPage': False, 'endCursor': None}})
        return {'course': None if course is None else {**course, 'submissionsConnection': connection}}


class CourseWhatIfTests(unittest.TestCase):
    def setUp(self):
        self.client = CourseHypothesisClient()

    def preview(self, **options):
        return reset(self.client, '123', acknowledge_all=True, **options)

    def execute(self, **options):
        preview = self.preview(**options)
        return self.preview(yes=True, confirm=preview['confirm'], **options)

    def test_course_read_selects_only_own_published_active_hypotheses_including_unsubmitted(self):
        result = read(self.client, '123')
        self.assertEqual(result['submissions']['71']['student_entered_score'], 8.0)
        self.assertFalse(result['hidden_rows_verified'])
        query = next(row for row in self.client.calls if row[0] == 'CanvasCourseWhatIf')
        self.assertEqual(query[2], {'courseId': '123', 'userId': '7', 'after': None})
        self.assertIn('studentIds: [$userId]', query[1])
        self.assertIn('unsubmitted', query[1])
        self.assertFalse(any(word in query[1] for word in ('score ', 'commentsConnection', 'meets', 'annotationContext')))
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertIn('Assignment 44: 8.0', brief(result))
        self.assertEqual(self.client.mutations, [])

    def test_one_native_bulk_reset_clears_hidden_rows_and_touches_already_clear_timestamps(self):
        preview = self.preview()
        self.assertEqual(json.loads(brief(preview)), preview)
        result = self.execute()
        self.assertEqual(self.client.mutations, [('PUT', '/api/v1/courses/123/what_if_grades/reset', None)])
        self.assertEqual(self.client.hidden, [None, None])
        self.assertEqual(self.client.timestamp_writes, 4)
        self.assertEqual(self.client.official_grade, 90.0)
        self.assertTrue(result['reported_hypotheses_clear_verified'])
        self.assertFalse(result['hidden_rows_verified'])
        self.assertFalse(result['official_grade_change_requested'])
        self.assertFalse(result['coursework_completion_requested'])
        self.assertIn('hidden-row clearing remains unverified', brief(result))

    def test_empty_reported_inventory_is_not_empty_stored_course_or_hidden_verification(self):
        self.client.rows = []
        result = self.execute()
        self.assertEqual(result['submissions'], {})
        self.assertFalse(result['hidden_rows_verified'])
        self.assertEqual(self.client.hidden, [None, None])
        self.assertEqual(self.client.timestamp_writes, 2)

    def test_permission_completed_course_missing_ack_and_bad_flags_never_reset_or_fallback(self):
        with self.assertRaisesRegex(CanvasError, 'acknowledge-all'):
            reset(self.client, '123')
        with self.assertRaises(CanvasError):
            self.preview(yes=True)
        self.assertEqual(self.client.calls, [])
        for mode in ('permission', 'completed'):
            self.setUp()
            if mode == 'permission':
                self.client.permission = False
            else:
                self.client.course['state'] = 'completed'
            result = read(self.client, '123')
            self.assertFalse(result['hidden_rows_verified'])
            with self.assertRaisesRegex(CanvasError, 'permission is unavailable'):
                self.preview()
            self.assertEqual(self.client.mutations, [])

    def test_foreign_course_rows_owners_unpublished_deleted_and_bad_scores_fail_closed(self):
        for field, value in (('userId', '8'), ('_id', '0'), ('assignmentId', '../44'), ('attempt', True), ('attempt', -1),
                             ('state', 'deleted'), ('submittedAt', False), ('studentEnteredScore', '8.0'),
                             ('studentEnteredScore', float('inf')), ('assignment', None),
                             ('assignment', {'_id': '44', 'courseId': '124', 'published': True}),
                             ('assignment', {'_id': '44', 'courseId': '123', 'published': 1})):
            self.setUp()
            self.client.rows[0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.client.mutations, [])
        for field in ('submittedAt', 'studentEnteredScore'):
            self.setUp()
            del self.client.rows[0][field]
            with self.assertRaises(CanvasError):
                self.preview()
        for course in (None, {}, {'_id': '124', 'state': 'available'}, {'_id': '123', 'state': None}):
            self.setUp()
            self.client.course = course
            with self.assertRaises(CanvasError):
                self.preview()

    def test_missing_nonboolean_rights_or_initial_account_switch_do_not_query_or_write(self):
        for value in ({}, [], {'reset_what_if_grades': 1}):
            self.setUp()
            self.client.permission_override = value
            with self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.client.graphql_calls, 0)
        self.setUp()
        self.client.switch_initial = True
        with self.assertRaisesRegex(CanvasError, 'account or reset permission changed'):
            self.preview()
        self.assertEqual(self.client.mutations, [])

    def test_page_caps_invalid_ids_and_duplicate_or_looping_inventory_do_not_mutate(self):
        for cap in (0, True, '2'):
            with self.assertRaises(CanvasError):
                read(self.client, '123', max_pages=cap)
        with self.assertRaises(CanvasError):
            read(self.client, '../123')
        self.assertEqual(self.client.calls, [])
        connection = {'nodes': copy.deepcopy(self.client.rows), 'pageInfo': {'hasNextPage': True, 'endCursor': 'next'}}
        self.client.pages = [connection]
        with self.assertRaisesRegex(CanvasError, 'page cap'):
            self.preview(max_pages=1)
        for connection in (None, {}, {'nodes': None, 'pageInfo': {}},
                           {'nodes': self.client.rows, 'pageInfo': {}},
                           {'nodes': self.client.rows, 'pageInfo': {'hasNextPage': False}},
                           {'nodes': self.client.rows, 'pageInfo': {'hasNextPage': False, 'endCursor': 1}},
                           {'nodes': [], 'pageInfo': {'hasNextPage': True, 'endCursor': 'next'}},
                           {'nodes': self.client.rows, 'pageInfo': {'hasNextPage': True, 'endCursor': ''}},
                           {'nodes': self.client.rows * 2, 'pageInfo': {'hasNextPage': False, 'endCursor': None}}):
            self.setUp()
            self.client.pages = [connection]
            with self.subTest(connection=connection), self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.client.mutations, [])

    def test_two_pages_bind_exact_own_rows_and_opaque_cursor_not_raw_responses(self):
        rows = copy.deepcopy(self.client.rows)
        self.client.pages = [{'nodes': rows[:1], 'pageInfo': {'hasNextPage': True, 'endCursor': 'opaque'}},
                             {'nodes': rows[1:], 'pageInfo': {'hasNextPage': False, 'endCursor': None}}]
        result = read(self.client, '123', max_pages=2)
        self.assertEqual(set(result['submissions']), {'71', '72'})
        queries = [row for row in self.client.calls if row[0] == 'CanvasCourseWhatIf']
        self.assertEqual(queries[1][2]['after'], 'opaque')

    def test_stale_score_row_course_permission_identity_or_output_requires_fresh_preview(self):
        for mode in ('score', 'row', 'course', 'permission', 'identity', 'output'):
            self.setUp()
            preview = self.preview()
            if mode == 'score':
                self.client.rows[0]['studentEnteredScore'] = 7.0
            elif mode == 'row':
                self.client.rows[0]['attempt'] += 1
            elif mode == 'course':
                self.client.course['state'] = 'completed'
            elif mode == 'permission':
                self.client.permission = False
            elif mode == 'identity':
                self.client.user_id = 8
                for row in self.client.rows:
                    row['userId'] = '8'
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(yes=True, confirm=preview['confirm'], include_totals=mode == 'output')
            self.assertEqual(self.client.mutations, [])

    def test_course_permission_changes_and_repeated_opaque_cursors_during_pagination_fail(self):
        rows = copy.deepcopy(self.client.rows)
        for mode in ('course', 'cursor', 'permission'):
            self.setUp()
            self.client.pages = [{'nodes': rows[:1], 'pageInfo': {'hasNextPage': True, 'endCursor': 'opaque'}},
                                 {'nodes': rows[1:], 'pageInfo': {'hasNextPage': mode == 'cursor', 'endCursor': 'opaque'}}]
            self.client.course_between_pages = mode == 'course'
            self.client.permission_during = mode == 'permission'
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(max_pages=2)
            self.assertEqual(self.client.mutations, [])

    def test_opt_in_totals_are_whitelisted_not_official_storage_proof_or_raw_dump(self):
        result = self.execute()
        self.assertNotIn('native_recalculated_totals', result)
        self.setUp()
        result = self.execute(include_totals=True)
        self.assertEqual(result['native_recalculated_totals'], [{'current': {'grade': 90.0}, 'final': {'grade': None}}])
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertIn('current:', brief(result))
        self.setUp()
        self.client.forecasts = []
        self.assertEqual(self.execute(include_totals=True)['native_recalculated_totals'], [])

    def test_failed_calculation_after_bulk_clear_is_uncertain_not_retry_or_rollback(self):
        self.client.calculation_error = True
        with self.assertRaisesRegex(CanvasError, 'already have been cleared') as error:
            self.execute()
        self.assertEqual(error.exception.status, 500)
        self.assertEqual(self.client.hidden, [None, None])
        self.assertEqual(len(self.client.mutations), 1)

    def test_bad_ack_denial_ignored_storage_and_post_write_races_are_uncertain(self):
        for mode in ('ack', 'denial', 'ignore', 'account', 'permission', 'course', 'row', 'read'):
            self.setUp()
            if mode == 'ack':
                self.client.ack = []
            elif mode == 'denial':
                self.client.write_error = 403
            else:
                setattr(self.client, {'ignore': 'ignore', 'account': 'switch_after', 'permission': 'permission_after',
                                      'course': 'course_after', 'row': 'row_after', 'read': 'read_after'}[mode], True)
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'unverified') as error:
                self.execute()
            self.assertNotIn('synthetic-private', str(error.exception))
            self.assertEqual(len(self.client.mutations), 1)

    def test_help_and_parser_keep_whole_course_ack_distinct_from_one_score(self):
        root = parser()
        self.assertEqual(command_help(root, 'what-if-course')['safety'], 'Read-only')
        self.assertEqual(command_help(root, 'what-if-reset')['safety'], 'Canvas writes (preview-first)')
        result = root.parse_args(['what-if-reset', '123', '--acknowledge-all-what-if', '--include-totals'])
        self.assertTrue(result.acknowledge_all_what_if)
        self.assertTrue(result.include_totals)
