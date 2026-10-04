"""Synthetic own indicator semantics, with no assertion that content was viewed."""

import copy
import json
import unittest

from canvas_cli.arguments import parser
from canvas_cli.client import CanvasError
from canvas_cli.formatting import brief
from canvas_cli.navigation import command_help
from canvas_cli.submission_attention import SURFACES, change, read


class AttentionClient:
    host = 'https://canvas.example.edu'

    def __init__(self):
        self.assignment = {'_id': '44', 'courseId': '123', 'submissionTypes': ['online_upload'], 'allowedExtensions': None,
                           'published': True, 'dueAt': None, 'unlockAt': None, 'lockAt': None, 'updatedAt': None,
                           'groupCategoryId': None, 'gradeGroupStudentsIndividually': False, 'allowedAttempts': None, 'state': 'published'}
        self.submission = {'_id': '71', 'userId': '7', 'assignmentId': '44', 'assignment': {'_id': '44', 'courseId': '123'},
                           'attempt': 2, 'state': 'submitted', 'submittedAt': '2026-10-03T00:00:00Z'}
        self.items = {'grade': 'unread', 'comment': 'unread', 'rubric': 'unread'}
        self.preferences = {'document_annotations': False, 'rubric_assessments': False}
        self.calls, self.mutations = [], []
        self.written = False
        self.user_id = 7
        self.account_calls = 0
        self.switch_initial = self.switch_after = self.advance = self.policy_after = self.read_after = self.ignore = False
        self.state_override = self.marker_override = self.ack_override = self.write_error = None

    def aggregate(self):
        return 'unread' if 'unread' in self.items.values() else 'read'

    def request(self, path, method='GET', body=None, *, expect_no_content=False):
        self.calls.append((method, path, body, expect_no_content))
        if path == '/api/v1/users/self/profile':
            self.account_calls += 1
            return {'id': 8 if self.written and self.switch_after or self.switch_initial and self.account_calls > 1 else self.user_id}, ''
        preference = next((key for key in self.preferences if path.endswith('/' + key + '/read')), None)
        if method == 'GET':
            return self.marker_override if self.marker_override is not None else {'read': self.preferences[preference], 'private': 'synthetic-private'}, ''
        self.mutations.append((method, path, body, expect_no_content))
        self.written = True
        if self.write_error:
            raise CanvasError('synthetic-private-write-error', status=self.write_error)
        if not self.ignore:
            if preference:
                self.preferences[preference] = True
            elif path.endswith('/read'):
                selected = 'unread' if method == 'DELETE' else 'read'
                if selected != self.aggregate():
                    self.items['grade'] = selected
            else:
                self.items[path.rsplit('/', 1)[-1]] = 'read'
        if self.advance:
            self.submission['attempt'] += 1
        if self.ack_override is not None:
            if expect_no_content:
                raise CanvasError('synthetic-private-unexpected-ack')
            return self.ack_override, ''
        return (None if expect_no_content else {'read': True}), ''

    def graphql(self, document, variables, operation):
        self.calls.append((operation, document, copy.deepcopy(variables)))
        if self.written and self.read_after:
            raise CanvasError('synthetic-private-read-error', status=403)
        assignment, submission = copy.deepcopy(self.assignment), copy.deepcopy(self.submission)
        if self.written and self.policy_after:
            assignment['published'] = False
        if submission is not None:
            submission['readState'] = self.aggregate() if self.state_override is None else self.state_override
        return {'assignment': assignment, 'submission': submission}


class SubmissionAttentionTests(unittest.TestCase):
    def setUp(self):
        self.client = AttentionClient()

    def preview(self, state='read', surface='overall', **options):
        return change(self.client, '123', '44', state, surface=surface, acknowledge=True, **options)

    def execute(self, state='read', surface='overall', **options):
        preview = self.preview(state, surface, **options)
        return self.preview(state, surface, yes=True, confirm=preview['confirm'], **options)

    def test_default_query_uses_exact_own_metadata_not_unsafe_read_status_include(self):
        result = read(self.client, '123', '44')
        self.assertEqual(result['aggregate_read_state'], 'unread')
        self.assertEqual(result['preference_read_markers'], {})
        self.assertNotIn('synthetic-private', json.dumps(result))
        query = next(row for row in self.client.calls if row[0] == 'CanvasSubmissionAttention')
        self.assertEqual(query[2], {'assignmentId': '44', 'userId': '7'})
        self.assertIn(' readState ', query[1])
        self.assertFalse(any(word in query[1] for word in ('score', 'grade ', 'commentsConnection', 'meets', 'annotationContext')))
        self.assertEqual({row[1] for row in self.client.calls if row[0] == 'GET'}, {'/api/v1/users/self/profile'})
        self.assertEqual(self.client.mutations, [])

    def test_feedback_preferences_are_distinct_boolean_only_reads(self):
        result = read(self.client, '123', '44', include_preferences=True)
        self.assertEqual(result['preference_read_markers'], {'annotations': False, 'rubric-feedback': False})
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertNotIn('synthetic-private', brief(result))
        self.assertEqual(self.client.mutations, [])

    def test_missing_submission_is_unknown_without_preference_queries_or_initialization(self):
        self.client.submission = None
        result = read(self.client, '123', '44', include_preferences=True)
        self.assertEqual(result['attention_status'], 'unknown_no_accessible_submission')
        self.assertEqual(result['preference_read_markers'], {})
        with self.assertRaisesRegex(CanvasError, 'existing own submission'):
            self.preview()
        self.assertEqual(self.client.mutations, [])
        self.assertFalse(any('/document_annotations/' in row[1] for row in self.client.calls))

    def test_legacy_overall_read_ack_does_not_claim_all_unread_items_were_cleared(self):
        result = self.execute()
        self.assertTrue(result['mutation_acknowledged'])
        self.assertFalse(result['aggregate_matches_requested_state'])
        self.assertEqual(result['aggregate_read_state'], 'unread')
        self.assertEqual(self.client.items, {'grade': 'read', 'comment': 'unread', 'rubric': 'unread'})
        self.assertFalse(result['participation_item_storage_verified'])
        self.assertIn('other native unread items', brief(result))
        self.assertEqual(len(self.client.mutations), 1)

    def test_overall_read_and_unread_match_when_native_aggregate_allows_it(self):
        self.client.items = {'grade': 'unread'}
        result = self.execute()
        self.assertTrue(result['aggregate_matches_requested_state'])
        result = self.execute('unread')
        self.assertTrue(result['aggregate_matches_requested_state'])
        self.assertEqual(self.client.mutations[-1][0], 'DELETE')
        self.assertFalse(result['coursework_completion_requested'])

    def test_each_item_route_is_a_single_empty_204_write_with_effective_readback_only(self):
        for surface in ('grade', 'comment', 'rubric'):
            with self.subTest(surface=surface):
                self.setUp()
                result = self.execute(surface=surface)
                self.assertIsNone(result['aggregate_matches_requested_state'])
                self.assertFalse(result['participation_item_storage_verified'])
                self.assertEqual(self.client.mutations, [('PUT', f'/api/v1/courses/123/assignments/44/submissions/7/read/{surface}', None, True)])
                self.assertFalse(result['selected_preference_readback_verified'])

    def test_preference_markers_get_exact_independent_readback_and_preserve_other_surfaces(self):
        for surface, native in (('annotations', 'document_annotations'), ('rubric-feedback', 'rubric_assessments')):
            with self.subTest(surface=surface):
                self.setUp()
                result = self.execute(surface=surface)
                self.assertTrue(result['selected_preference_readback_verified'])
                self.assertEqual(result['preference_read_markers'], {surface: True})
                self.assertEqual(self.client.mutations, [('PUT', f'/api/v1/courses/123/assignments/44/submissions/7/{native}/read', None, False)])
                self.assertEqual(self.client.items, {'grade': 'unread', 'comment': 'unread', 'rubric': 'unread'})

    def test_required_acknowledgement_invalid_state_or_non_native_unread_never_mutate(self):
        for state, surface in (('done', 'overall'), ('read', 'unknown'), ('unread', 'comment'), ('unread', 'annotations')):
            with self.assertRaises(CanvasError):
                self.preview(state, surface)
        with self.assertRaisesRegex(CanvasError, 'acknowledge-feedback'):
            change(self.client, '123', '44', 'read')
        with self.assertRaises(CanvasError):
            self.preview(yes=True)
        self.assertEqual(self.client.calls, [])

    def test_foreign_hidden_or_unavailable_state_is_not_authority_or_no_work(self):
        for patch in ({'userId': '8'}, {'assignmentId': '45'}, {'assignment': None}, {'attempt': True}):
            self.setUp()
            self.client.submission.update(patch)
            with self.assertRaises(CanvasError):
                self.preview()
        for value in ('unknown', False, {}, ''):
            self.setUp()
            self.client.state_override = value
            with self.assertRaisesRegex(CanvasError, 'aggregate'):
                self.preview()
        self.assertEqual(self.client.mutations, [])

    def test_malformed_preference_boolean_is_not_unread_or_write_authority(self):
        for value in ({}, {'read': None}, {'read': 1}, {'read': 'true'}, []):
            self.setUp()
            self.client.marker_override = value
            with self.assertRaisesRegex(CanvasError, 'unavailable'):
                self.preview(surface='annotations')
            self.assertEqual(self.client.mutations, [])

    def test_stale_indicator_preference_policy_attempt_or_identity_needs_new_preview(self):
        for mode in ('indicator', 'preference', 'policy', 'attempt', 'identity'):
            self.setUp()
            preview = self.preview(surface='annotations')
            if mode == 'indicator':
                self.client.items = {'grade': 'read'}
            elif mode == 'preference':
                self.client.preferences['document_annotations'] = True
            elif mode == 'policy':
                self.client.assignment['updatedAt'] = '2026-10-05T00:00:00Z'
            elif mode == 'attempt':
                self.client.submission['attempt'] += 1
            else:
                self.client.user_id = 8
                self.client.submission['userId'] = '8'
            with self.assertRaisesRegex(CanvasError, 'Preview changed'):
                self.preview(surface='annotations', yes=True, confirm=preview['confirm'])
            self.assertEqual(self.client.mutations, [])

    def test_denied_wrong_ack_ignored_preference_and_changed_readback_are_uncertain_without_retry(self):
        for mode in ('denied', 'ack', 'ignore', 'switch', 'advance', 'policy', 'read'):
            self.setUp()
            if mode == 'denied':
                self.client.write_error = 403
            elif mode == 'ack':
                self.client.ack_override = {'read': False}
            else:
                setattr(self.client, {'ignore': 'ignore', 'switch': 'switch_after', 'advance': 'advance',
                                      'policy': 'policy_after', 'read': 'read_after'}[mode], True)
            with self.assertRaisesRegex(CanvasError, 'unverified') as raised:
                self.execute(surface='annotations')
            self.assertNotIn('synthetic-private', str(raised.exception))
            self.assertEqual(len(self.client.mutations), 1)
        self.setUp()
        self.client.ack_override = {'read': True}
        with self.assertRaisesRegex(CanvasError, 'unverified'):
            self.execute()

    def test_initial_account_switch_is_refused_before_mutation(self):
        self.client.switch_initial = True
        with self.assertRaisesRegex(CanvasError, 'account changed'):
            self.preview()
        self.assertEqual(self.client.mutations, [])

    def test_parser_help_classification_and_surface_choices_are_offline(self):
        root = parser()
        for name in ('submission-attention', 'submission-mark-read', 'submission-mark-unread'):
            help_page = command_help(root, name)
            self.assertEqual(help_page['safety'], 'Read-only' if name == 'submission-attention' else 'Canvas writes (preview-first)')
        for surface in SURFACES:
            self.assertEqual(root.parse_args(['submission-mark-read', '123', '44', '--surface', surface]).surface, surface)
