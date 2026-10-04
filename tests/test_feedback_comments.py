"""Published feedback indicators use metadata only and exact own-submission scope."""

import copy
import json
import unittest

from test_submission_comments import CommentClient, record

from canvas_cli.arguments import parser
from canvas_cli.client import CanvasError
from canvas_cli.feedback_comments import _comment, mark_read, read
from canvas_cli.formatting import brief
from canvas_cli.navigation import command_help


class FeedbackClient(CommentClient):
    def __init__(self):
        super().__init__()
        self.rows = [record('91', draft=False), record('92', 0, False), record('93', draft=False), record('94')]
        self.rows[2]['author'] = {'_id': '8'}
        self.viewed = set()
        self.aggregate = 'unread'
        self.other_read_after = False

    def row(self, row):
        metadata = {key: copy.deepcopy(row[key]) for key in (
            '_id', 'submissionId', 'assignment', 'course', 'draft', 'attempt', 'createdAt', 'updatedAt', 'provisional')}
        return {**metadata, 'read': self.aggregate == 'read' or row['_id'] in self.viewed}

    def graphql(self, document, variables, operation):
        self.calls.append((operation, document, copy.deepcopy(variables)))
        if operation == 'CanvasFeedbackComments':
            if self.read_error or self.written and self.payload_patch == 'read_error':
                raise CanvasError('synthetic-private-read-error', status=403)
            assignment, submission = copy.deepcopy(self.assignment), copy.deepcopy(self.submission)
            if self.written and self.policy_after:
                assignment['published'] = False
            if self.context_race and variables['after'] is not None:
                assignment['updatedAt'] = '2026-10-04T01:00:00Z'
            if submission is not None:
                selected = submission['attempt'] if variables['attempt'] is None else variables['attempt']
                rows = [self.row(row) for row in self.rows if not row['draft'] and not row['provisional']
                        and row['attempt'] in ((0, 1) if selected <= 1 else (selected,))]
                if self.written and self.drop_after:
                    rows = [row for row in rows if row['_id'] != '91']
                offset = 0 if variables['after'] is None else int(variables['after'])
                nodes = rows[offset:offset + self.page_size]
                page = {'hasNextPage': offset + len(nodes) < len(rows), 'endCursor': str(offset + len(nodes)) if nodes else None}
                if self.page_patch:
                    page.update(self.page_patch)
                submission.update(readState=self.aggregate, commentsConnection={'nodes': nodes, 'pageInfo': page})
                if self.query_patch:
                    submission.update(copy.deepcopy(self.query_patch))
            return {} if self.payload_patch == 'missing' else {'assignment': assignment, 'submission': submission}
        assert operation == 'CanvasFeedbackCommentRead', operation
        self.mutations.append((operation, document, copy.deepcopy(variables)))
        self.written = True
        if self.write_error:
            raise CanvasError('synthetic-private-write-error', status=self.write_error)
        identifiers = variables['input']['submissionCommentIds']
        if not self.ignore:
            self.viewed.update(identifiers)
        if self.other_read_after:
            self.viewed.add('93')
        ack = {'markSubmissionCommentsRead': {'errors': None, 'submissionComments': [self.row(row) for row in self.rows if row['_id'] in identifiers]}}
        if self.advance:
            self.submission['attempt'] += 1
        return self.ack if self.ack is not None else ack


class FeedbackCommentTests(unittest.TestCase):
    def setUp(self):
        self.client = FeedbackClient()

    def preview(self, identifier='91', **options):
        return mark_read(self.client, '123', '44', identifier, acknowledge=True, **options)

    def execute(self, identifier='91', **options):
        preview = self.preview(identifier, **options)
        return self.preview(identifier, yes=True, confirm=preview['confirm'], **options)

    def test_metadata_includes_visible_authors_but_no_identities_content_or_marker_change(self):
        result = read(self.client, '123', '44')
        self.assertEqual([row['id'] for row in result['comments']], ['91', '93'])
        self.assertEqual(result['inventory_status'], 'complete_reported_visible_published_selected_attempt')
        self.assertFalse(any(row['effective_read'] for row in result['comments']))
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertTrue(all('author' not in row and 'author_id' not in row for row in result['comments']))
        self.assertIn('91: attempt 2, unread', brief(result))
        queries = [row for row in self.client.calls if row[0] == 'CanvasFeedbackComments']
        self.assertEqual([row[2]['after'] for row in queries], [None, '1'])
        for query in queries:
            self.assertIn('peerReview: false', query[1])
            self.assertIn('allComments: false', query[1])
            self.assertIn('includeDraftComments: false', query[1])
            self.assertFalse(any(value in query[1] for value in ('htmlComment', 'author ', 'score', 'annotationContext', 'assignedAssessments')))
        self.assertEqual(self.client.mutations, [])
        self.assertEqual(self.client.viewed, set())

    def test_all_attempts_remain_separately_filtered_and_first_bucket_is_shared(self):
        self.client.rows.append(record('95', 1, False))
        result = read(self.client, '123', '44', all_attempts=True)
        self.assertEqual(result['selected_attempts'], [1, 2])
        self.assertEqual([row['id'] for row in result['comments']], ['91', '92', '93', '95'])
        result = read(self.client, '123', '44', attempt=0)
        self.assertEqual([row['attempt'] for row in result['comments']], [0, 1])

    def test_exact_selected_comment_write_preserves_other_rows_and_aggregate(self):
        result = self.execute()
        self.assertEqual(self.client.viewed, {'91'})
        self.assertEqual(self.client.mutations[0][2], {'input': {'submissionId': '71', 'submissionCommentIds': ['91']}})
        self.assertTrue(result['effective_readback_verified'])
        self.assertFalse(result['viewed_row_storage_verified'])
        self.assertFalse(result['coursework_completion_requested'])
        self.assertEqual(result['aggregate_read_state'], 'unread')
        self.assertEqual(result['other_observed_comment_changes'], [])
        self.assertIn('viewed-row storage unverified', brief(result))
        self.assertEqual(len(self.client.mutations), 1)

    def test_other_authored_comment_and_old_attempt_are_native_targets_on_own_submission(self):
        self.execute('93')
        self.execute('92', attempt=1)
        self.assertEqual(self.client.viewed, {'92', '93'})

    def test_effective_read_can_be_masked_by_aggregate_without_viewed_row_proof(self):
        self.client.aggregate = 'read'
        self.client.ignore = True
        result = self.execute()
        self.assertTrue(result['effective_readback_verified'])
        self.assertFalse(result['viewed_row_storage_verified'])
        self.assertEqual(self.client.viewed, set())

    def test_other_observed_changes_are_labeled_not_attributed_to_selected_write(self):
        self.client.other_read_after = True
        result = self.execute()
        self.assertEqual(result['other_observed_comment_changes'], ['93'])

    def test_unknown_submission_and_missing_target_do_not_initialize_or_mutate(self):
        self.client.submission = None
        result = read(self.client, '123', '44')
        self.assertEqual(result['inventory_status'], 'unknown_no_accessible_submission')
        self.assertIsNone(result['aggregate_read_state'])
        with self.assertRaisesRegex(CanvasError, 'exact visible published'):
            self.preview()
        self.setUp()
        for target in ('94', '999'):
            with self.assertRaises(CanvasError):
                self.preview(target)
        self.assertEqual(self.client.mutations, [])

    def test_acknowledgement_and_valid_ids_flags_are_required_before_queries(self):
        with self.assertRaisesRegex(CanvasError, 'acknowledge-feedback'):
            mark_read(self.client, '123', '44', '91')
        for options in ({'yes': True}, {'confirm': 'wrong'}):
            with self.assertRaises(CanvasError):
                self.preview(**options)
        with self.assertRaises(CanvasError):
            self.preview('../91')
        self.assertEqual(self.client.calls, [])

    def test_foreign_draft_provisional_attempt_dates_and_boolean_metadata_are_refused(self):
        row = self.client.row(self.client.rows[0])
        state = self.preview()
        for patch in ({'_id': None}, {'submissionId': '72'}, {'assignment': None}, {'course': {'_id': '124'}},
                      {'draft': True}, {'provisional': True}, {'read': 1}, {'attempt': True}, {'attempt': -1},
                      {'attempt': 3}, {'createdAt': ''}, {'createdAt': None}, {'updatedAt': {}}, {'read': 'true'}):
            with self.subTest(patch=patch), self.assertRaises(CanvasError):
                _comment({**row, **patch}, state, 2)
        for value in ({}, [], None):
            with self.assertRaises(CanvasError):
                _comment(value, state, 2)

    def test_stale_preview_binds_scope_policy_attempt_inventory_and_effective_markers(self):
        for mode in ('marker', 'aggregate', 'policy', 'attempt', 'inventory', 'account'):
            self.setUp()
            preview = self.preview()
            if mode == 'marker':
                self.client.viewed.add('91')
            elif mode == 'aggregate':
                self.client.aggregate = 'read'
            elif mode == 'policy':
                self.client.assignment['updatedAt'] = '2026-10-05T00:00:00Z'
            elif mode == 'attempt':
                self.client.submission['attempt'] = 3
            elif mode == 'inventory':
                self.client.rows.append(record('95', draft=False))
            else:
                self.client.user_id = 8
                self.client.submission['userId'] = '8'
            with self.assertRaises(CanvasError):
                self.preview(yes=True, confirm=preview['confirm'])
            self.assertEqual(self.client.mutations, [])

    def test_partial_missing_foreign_duplicate_or_wrong_ack_is_uncertain_after_one_write(self):
        row = self.client.row(self.client.rows[0])
        valid = {**row, 'read': True}
        for ack in ({}, {'errors': None}, {'errors': [{'attribute': None}], 'submissionComments': [valid]},
                    {'errors': None, 'submissionComments': None}, {'errors': None, 'submissionComments': []},
                    {'errors': None, 'submissionComments': [valid, valid]},
                    {'errors': None, 'submissionComments': [{**valid, '_id': '93'}]},
                    {'errors': None, 'submissionComments': [{**valid, 'read': False}]},
                    {'errors': None, 'submissionComments': [{**valid, 'submissionId': '72'}]}):
            self.setUp()
            self.client.ack = {'markSubmissionCommentsRead': ack}
            with self.assertRaisesRegex(CanvasError, 'unverified'):
                self.execute()
            self.assertEqual(len(self.client.mutations), 1)
        self.setUp()
        self.client.ack = {'markSubmissionCommentsRead': None}
        with self.assertRaisesRegex(CanvasError, 'unverified'):
            self.execute()

    def test_denial_ignored_marker_missing_target_changed_scope_and_readback_failure_are_uncertain(self):
        for mode in ('denied', 'ignore', 'advance', 'switch', 'policy', 'drop', 'read'):
            self.setUp()
            if mode == 'denied':
                self.client.write_error = 403
            elif mode == 'read':
                self.client.payload_patch = 'read_error'
            else:
                setattr(self.client, {'ignore': 'ignore', 'advance': 'advance', 'switch': 'switch',
                                      'policy': 'policy_after', 'drop': 'drop_after'}[mode], True)
            with self.assertRaisesRegex(CanvasError, 'unverified') as raised:
                self.execute()
            self.assertNotIn('synthetic-private', str(raised.exception))
            self.assertEqual(len(self.client.mutations), 1)

    def test_parser_help_and_metadata_brief_are_offline(self):
        root = parser()
        self.assertEqual(command_help(root, 'feedback-comments')['safety'], 'Read-only')
        self.assertEqual(command_help(root, 'feedback-comment-mark-read')['safety'], 'Canvas writes (preview-first)')
        parsed = root.parse_args(['feedback-comments', '123', '44', '--all-attempts'])
        self.assertTrue(parsed.all_attempts)
        self.assertIsNone(parsed.attempt)
