"""Own comment lifecycle and privacy invariants using synthetic records only."""

import copy
import json
import unittest

from canvas_cli.arguments import parser
from canvas_cli.client import CanvasError
from canvas_cli.formatting import brief
from canvas_cli.navigation import command_help
from canvas_cli.own_submission import context
from canvas_cli.submission_comments import _comment, change, create, read


def record(identifier='91', attempt=2, draft=True):
    return {'_id': identifier, 'submissionId': '71', 'author': {'_id': '7'},
            'assignment': {'_id': '44', 'courseId': '123'}, 'course': {'_id': '123'}, 'attempt': attempt,
            'draft': draft, 'publishable': draft, 'provisional': False, 'createdAt': '2026-10-04T00:00:00Z', 'updatedAt': None,
            'comment': 'synthetic-private-text', 'htmlComment': '<p>synthetic-private-text</p>',
            'mediaCommentId': None, 'attachments': []}


class CommentClient:
    host = 'https://canvas.example.edu'

    def __init__(self):
        self.assignment = {'_id': '44', 'courseId': '123', 'submissionTypes': ['online_upload'], 'allowedExtensions': None,
                           'published': True, 'dueAt': None, 'unlockAt': None, 'lockAt': None, 'updatedAt': None,
                           'groupCategoryId': None, 'gradeGroupStudentsIndividually': False, 'allowedAttempts': None, 'state': 'published'}
        self.submission = {'_id': '71', 'userId': '7', 'assignmentId': '44', 'assignment': {'_id': '44', 'courseId': '123'},
                           'attempt': 2, 'state': 'submitted', 'submittedAt': '2026-10-03T00:00:00Z'}
        self.rows = [record(), record('92', 0), record('93', draft=False)]
        self.calls, self.mutations = [], []
        self.page_size = 1
        self.user_id = 7
        self.written = False
        self.switch = self.advance = self.policy_after = self.ignore = self.normalize = False
        self.read_error = self.write_error = self.ack = self.query_patch = self.page_patch = None
        self.foreign_group_ack = False
        self.account_count = 0
        self.switch_initial = False
        self.context_race = False
        self.payload_patch = None
        self.drop_after = self.extra_after = False

    def request(self, path, method='GET', body=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        if method == 'GET':
            self.account_count += 1
            return {'id': 8 if self.written and self.switch or self.switch_initial and self.account_count > 1 else self.user_id}, ''
        self.mutations.append((method, path, copy.deepcopy(body)))
        self.written = True
        if self.write_error:
            raise CanvasError('synthetic-private-write-error', status=self.write_error)
        row = next(row for row in self.rows if row['_id'] == path.rsplit('/', 1)[-1])
        if not self.ignore:
            row.update(comment=body['comment'], htmlComment='<p>normalized</p>' if self.normalize else body['comment'])
        return self.ack if self.ack is not None else {'id': int(row['_id']), 'comment': 'synthetic-private-ack'}, ''

    def graphql(self, document, variables, operation):
        self.calls.append((operation, document, copy.deepcopy(variables)))
        if operation == 'CanvasOwnSubmissionComments':
            if self.read_error or self.written and self.payload_patch == 'read_error':
                raise CanvasError('synthetic-private-read-error', status=403)
            assignment = copy.deepcopy(self.assignment)
            if self.written and self.policy_after:
                assignment['published'] = False
            if self.context_race and variables['after'] is not None:
                assignment['updatedAt'] = '2026-10-04T01:00:00Z'
            submission = copy.deepcopy(self.submission)
            if submission is not None:
                attempt = variables['attempt'] if variables['attempt'] is not None else submission['attempt']
                rows = [copy.deepcopy(row) for row in self.rows if row['attempt'] in ((0, 1) if attempt <= 1 else (attempt,))]
                if self.written and self.drop_after:
                    rows = [row for row in rows if row['_id'] != '91']
                if self.written and self.extra_after:
                    for row in rows:
                        if row['_id'] == '93':
                            row['htmlComment'] = '<p>concurrent other comment</p>'
                offset = 0 if variables['after'] is None else int(variables['after'])
                nodes = rows[offset:offset + self.page_size]
                page = {'hasNextPage': offset + len(nodes) < len(rows), 'endCursor': str(offset + len(nodes)) if nodes else None}
                if self.page_patch:
                    page.update(self.page_patch)
                submission['commentsConnection'] = {'nodes': nodes, 'pageInfo': page}
                if self.query_patch:
                    submission.update(copy.deepcopy(self.query_patch))
            result = {'assignment': assignment, 'submission': submission}
            return {} if self.payload_patch == 'missing' else result
        self.mutations.append((operation, document, copy.deepcopy(variables)))
        self.written = True
        if self.write_error:
            raise CanvasError('synthetic-private-write-error', status=self.write_error)
        selected = variables['input']
        if operation == 'CanvasCommentDraftCreate':
            row = record('94', selected['attempt'])
            row.update(comment=selected['comment'], htmlComment='<p>normalized</p>' if self.normalize else selected['comment'],
                       attachments=[{'_id': value} for value in selected['fileIds']], mediaCommentId=selected.get('mediaObjectId'))
            if not self.ignore:
                self.rows.append(row)
            field = 'createSubmissionComment'
        else:
            row = next(row for row in self.rows if row['_id'] == selected['submissionCommentId'])
            if operation == 'CanvasCommentDraftPublish':
                if not self.ignore:
                    row.update(draft=False, publishable=False)
                field = 'postDraftSubmissionComment'
            elif operation == 'CanvasCommentDraftDelete':
                if not self.ignore:
                    self.rows.remove(row)
                field = 'deleteSubmissionComment'
            else:
                raise AssertionError(operation)
        ack = {key: copy.deepcopy(row[key]) for key in ('_id', 'submissionId', 'author', 'draft', 'attempt')}
        if self.foreign_group_ack:
            ack.update(_id='95', submissionId='72')
        if self.advance:
            self.submission['attempt'] += 1
        return self.ack if self.ack is not None else {field: {'errors': [], 'submissionComment': ack}}


class SubmissionCommentTests(unittest.TestCase):
    def setUp(self):
        self.client = CommentClient()

    def create(self, **kwargs):
        return create(self.client, '123', '44', '<p>new</p>', acknowledge=True, **kwargs)

    def change(self, action='edit', identifier='91', **kwargs):
        if action == 'edit':
            kwargs.setdefault('message', '<p>replacement</p>')
        return change(self.client, '123', '44', identifier, action, acknowledge=True, **kwargs)

    def execute(self, action='create', **kwargs):
        method = self.create if action == 'create' else lambda **options: self.change(action, **options)
        preview = method(**kwargs)
        return method(yes=True, confirm=preview['confirm'], **kwargs)

    def test_metadata_default_is_own_author_and_each_page_keeps_native_safe_filter(self):
        result = read(self.client, '123', '44')
        self.assertEqual([item['id'] for item in result['comments']], ['91', '93'])
        self.assertEqual(result['selected_attempts'], [2])
        self.assertNotIn('synthetic-private', json.dumps(result))
        queries = [call for call in self.client.calls if call[0] == 'CanvasOwnSubmissionComments']
        self.assertEqual([row[2]['after'] for row in queries], [None, '1'])
        self.assertTrue(all(row[2]['userId'] == '7' for row in queries))
        self.assertTrue(all('allComments: false' in row[1] and 'peerReview: true' in row[1] for row in queries))
        self.assertFalse(any(word in row[1] for row in queries for word in (
            'includeDraftsFromOthers: true', 'readState', 'readStatus', 'read ', 'score', 'meets', 'reviewerSubmissionId')))
        self.assertEqual(self.client.mutations, [])

    def test_all_attempts_queries_separate_buckets_and_zero_one_comments_are_shared(self):
        self.client.rows.append(record('95', 1))
        result = read(self.client, '123', '44', all_attempts=True)
        self.assertEqual(result['selected_attempts'], [1, 2])
        self.assertEqual([item['id'] for item in result['comments']], ['91', '92', '93', '95'])
        self.client.submission['attempt'] = 0
        result = read(self.client, '123', '44', all_attempts=True)
        self.assertEqual(result['selected_attempts'], [0])
        self.assertEqual([item['attempt'] for item in result['comments']], [0, 1])
        self.assertEqual(read(self.client, '123', '44', attempt=1)['selected_attempts'], [1])

    def test_opt_in_content_is_private_and_credentials_are_redacted(self):
        self.client.rows[0]['htmlComment'] = '<a href="https://example.edu/?access_token=synthetic-secret">own</a>'
        result = read(self.client, '123', '44', include_content=True)
        self.assertIn('synthetic-private-text', json.dumps(result))
        self.assertNotIn('synthetic-secret', json.dumps(result))
        self.assertNotIn('synthetic-private', brief(result))

    def test_null_submission_is_unknown_and_cannot_manufacture_a_record(self):
        self.client.submission = None
        result = read(self.client, '123', '44', all_attempts=True)
        self.assertEqual(result['inventory_status'], 'unknown_no_accessible_submission')
        self.assertEqual(result['comments'], [])
        with self.assertRaisesRegex(CanvasError, 'existing own submission'):
            self.create()
        self.assertEqual(self.client.mutations, [])

    def test_creation_with_existing_attachments_media_and_one_graphql_write(self):
        result = self.execute(file_ids=['82', '81'], media_id='existing-media', media_type='video')
        self.assertTrue(result['own_draft_presence_verified'])
        self.assertTrue(result['acknowledged_comment_is_own_copy'])
        self.assertTrue(result['reported_file_ids_match_request'])
        self.assertTrue(result['reported_media_id_matches_request'])
        self.assertEqual(len(self.client.mutations), 1)
        selected = self.client.mutations[0][2]['input']
        self.assertEqual(selected['draftComment'], True)
        self.assertEqual(selected['attempt'], 2)
        self.assertEqual(selected['fileIds'], ['81', '82'])
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertEqual(self.client.submission['attempt'], 2)

    def test_group_policy_controls_native_copying_not_false_group_flag(self):
        self.client.assignment['groupCategoryId'] = '31'
        with self.assertRaisesRegex(CanvasError, 'acknowledge-group'):
            self.create()
        self.client.foreign_group_ack = True
        result = self.execute(acknowledge_group=True)
        self.assertFalse(result['acknowledged_comment_is_own_copy'])
        self.assertEqual(result['own_comment_id'], '94')
        self.assertFalse(result['native_collateral_effects_verified'])
        self.setUp()
        self.client.assignment.update(groupCategoryId='31', gradeGroupStudentsIndividually=True)
        self.assertFalse(self.create(acknowledge_group=True)['native_group_creation'])
        self.assertTrue(self.create(group_comment=True, acknowledge_group=True)['native_group_creation'])
        self.client.assignment['gradeGroupStudentsIndividually'] = None
        with self.assertRaisesRegex(CanvasError, 'policy is unknown'):
            self.create(acknowledge_group=True)

    def test_edit_is_text_only_and_keeps_existing_attachments_and_media(self):
        self.client.rows[0].update(attachments=[{'_id': '81'}], mediaCommentId='media')
        result = self.execute('edit')
        self.assertTrue(result['own_comment_state_verified'])
        self.assertTrue(result['reported_html_matches_request'])
        self.assertEqual(self.client.mutations[0], ('PUT', '/api/v1/courses/123/assignments/44/submissions/7/comments/91',
                                                    {'comment': '<p>replacement</p>'}))
        self.assertEqual(self.client.rows[0]['attachments'], [{'_id': '81'}])
        preview = self.change(message='')
        result = self.change(message='', yes=True, confirm=preview['confirm'])
        self.assertTrue(result['reported_html_matches_request'])

    def test_publish_and_delete_verify_own_state_or_complete_scoped_absence(self):
        result = self.execute('publish')
        self.assertTrue(result['own_comment_state_verified'])
        self.assertFalse(self.client.rows[0]['draft'])
        with self.assertRaisesRegex(CanvasError, 'published student'):
            self.change('delete')
        self.setUp()
        result = self.execute('delete')
        self.assertTrue(result['own_draft_absence_verified'])
        self.assertFalse(result['linked_group_absence_verified'])
        self.assertEqual(len(self.client.mutations), 1)

    def test_published_unknown_foreign_and_unpublishable_comments_never_mutate(self):
        for action, identifier in (('edit', '93'), ('delete', '93'), ('publish', '900')):
            with self.assertRaises(CanvasError):
                self.change(action, identifier)
        self.client.rows[0]['publishable'] = False
        with self.assertRaisesRegex(CanvasError, 'publishable'):
            self.change('publish')
        self.assertEqual(self.client.mutations, [])

    def test_stale_content_inventory_policy_attempt_or_account_requires_fresh_preview(self):
        for mode in ('text', 'attachment', 'new', 'policy', 'attempt', 'account'):
            with self.subTest(mode=mode):
                self.setUp()
                preview = self.change()
                if mode == 'text':
                    self.client.rows[0]['htmlComment'] = '<p>concurrent</p>'
                elif mode == 'attachment':
                    self.client.rows[0]['attachments'] = [{'_id': '82'}]
                elif mode == 'new':
                    self.client.rows.append(record('95'))
                elif mode == 'policy':
                    self.client.assignment['dueAt'] = '2026-10-10T00:00:00Z'
                elif mode == 'attempt':
                    self.client.submission['attempt'] = 3
                else:
                    self.client.user_id = 8
                    self.client.submission['userId'] = '8'
                    for row in self.client.rows:
                        row['author'] = {'_id': '8'}
                with self.assertRaises(CanvasError):
                    self.change(yes=True, confirm=preview['confirm'])
                self.assertEqual(self.client.mutations, [])

    def test_ignored_or_normalized_text_is_labeled_not_raw_storage_proof(self):
        for mode in ('normalize', 'ignore'):
            with self.subTest(mode=mode):
                self.setUp()
                setattr(self.client, mode, True)
                result = self.execute('edit')
                self.assertFalse(result['reported_html_matches_request'])
                self.assertFalse(result['raw_storage_verified'])
        self.setUp()
        self.client.normalize = True
        self.assertFalse(self.execute()['reported_html_matches_request'])

    def test_ignored_create_delete_or_publish_is_uncertain_without_retry(self):
        for action in ('create', 'publish', 'delete'):
            with self.subTest(action=action):
                self.setUp()
                self.client.ignore = True
                with self.assertRaisesRegex(CanvasError, 'unverified'):
                    self.execute(action)
                self.assertEqual(len(self.client.mutations), 1)

    def test_write_denial_partial_or_wrong_ack_does_not_retry_or_leak(self):
        for action in ('create', 'edit', 'publish', 'delete'):
            for mode in ('denied', 'partial', 'id', 'parent', 'author', 'attempt', 'draft'):
                with self.subTest(action=action, mode=mode):
                    self.setUp()
                    if mode == 'denied':
                        self.client.write_error = 403
                    elif action == 'edit':
                        self.client.ack = None if mode == 'denied' else {'id': 999} if mode == 'id' else {'comment': 'synthetic-private-ack'}
                    else:
                        row = record('94' if action == 'create' else '91')
                        row['draft'] = action != 'publish'
                        if mode == 'id':
                            row['_id'] = '99'
                        elif mode == 'parent':
                            row['submissionId'] = '72'
                        elif mode == 'author':
                            row['author'] = {'_id': '8'}
                        elif mode == 'attempt':
                            row['attempt'] = 0
                        elif mode == 'draft':
                            row['draft'] = not row['draft']
                        field = {'create': 'createSubmissionComment', 'publish': 'postDraftSubmissionComment', 'delete': 'deleteSubmissionComment'}[action]
                        self.client.ack = {field: {'errors': [{'attribute': 'synthetic-private-error'}] if mode == 'partial' else [], 'submissionComment': row}}
                    with self.assertRaisesRegex(CanvasError, 'unverified') as raised:
                        self.execute(action)
                    self.assertNotIn('synthetic-private', str(raised.exception))
                    self.assertEqual(len(self.client.mutations), 1)

    def test_account_attempt_policy_or_unavailable_readback_after_write_is_uncertain(self):
        for mode in ('switch', 'advance', 'policy_after', 'read_error'):
            with self.subTest(mode=mode):
                self.setUp()
                if mode == 'read_error':
                    self.client.payload_patch = mode
                else:
                    setattr(self.client, mode, True)
                with self.assertRaisesRegex(CanvasError, 'unverified'):
                    self.execute()
                self.assertEqual(len(self.client.mutations), 1)

    def test_pagination_caps_loops_duplicates_and_context_races_fail_before_write(self):
        for mode in ('cap', 'empty', 'missing_cursor', 'loop', 'duplicate', 'race', 'attempt_cap'):
            with self.subTest(mode=mode):
                self.setUp()
                options = {}
                if mode == 'cap':
                    options['max_pages'] = 1
                elif mode == 'empty':
                    self.client.rows = []
                    self.client.page_patch = {'hasNextPage': True, 'endCursor': '1'}
                elif mode == 'missing_cursor':
                    self.client.page_patch = {'hasNextPage': True, 'endCursor': None}
                elif mode == 'loop':
                    self.client.rows.append(record('94'))
                    self.client.page_patch = {'hasNextPage': True, 'endCursor': '1'}
                elif mode == 'duplicate':
                    self.client.rows.append(record())
                elif mode == 'race':
                    self.client.context_race = True
                else:
                    self.client.submission['attempt'] = 1000000000
                    options = {'all_attempts': True}
                with self.assertRaises(CanvasError):
                    read(self.client, '123', '44', **options)
                self.assertEqual(self.client.mutations, [])

    def test_missing_hidden_foreign_malformed_comment_fields_do_not_become_empty(self):
        state = context({'assignment': self.client.assignment, 'submission': self.client.submission},
                        {'origin': self.client.host, 'user_id': 7}, '123', '44')
        patches = ({'author': None}, {'author': {'_id': '8'}}, {'submissionId': '72'}, {'assignment': None}, {'course': {'_id': '124'}},
                   {'attempt': 3}, {'attempt': True}, {'draft': None}, {'provisional': True}, {'createdAt': ''},
                   {'updatedAt': {}}, {'comment': {}}, {'mediaCommentId': []}, {'attachments': None},
                   {'attachments': [None]}, {'attachments': [{'_id': '81'}, {'_id': '81'}]}, {'_id': '0'})
        for patch in patches:
            with self.subTest(patch=patch), self.assertRaises(CanvasError):
                _comment({**record(), **patch}, state, 2)
        for key in record():
            row = record()
            del row[key]
            with self.subTest(missing=key), self.assertRaises(CanvasError):
                _comment(row, state, 2)

    def test_scope_flags_inputs_and_required_acknowledgements_are_validated(self):
        for options in ({'attempt': -1}, {'attempt': True}, {'attempt': 99}, {'attempt': 1, 'all_attempts': True}, {'max_pages': 0}):
            with self.assertRaises(CanvasError):
                read(self.client, '123', '44', **options)
        for options in ({'file_ids': ['81', '81']}, {'file_ids': [[]]}, {'media_type': 'audio'}, {'media_id': ''}, {'media_type': 'pdf'},
                        {'file_ids': ['0']}, {'group_comment': True}, {'yes': True}):
            with self.assertRaises(CanvasError):
                self.create(**options)
        for args in ('unknown', 'edit', 'publish'):
            with self.assertRaises(CanvasError):
                change(self.client, '123', '44', '91', args, message=None if args != 'publish' else 'text', acknowledge=True)
        with self.assertRaisesRegex(CanvasError, 'acknowledge-native'):
            create(self.client, '123', '44', 'text')
        self.client.assignment['published'] = None
        with self.assertRaisesRegex(CanvasError, 'publication'):
            self.create()
        self.assertEqual(self.client.mutations, [])

    def test_initial_account_change_missing_inventory_and_denial_are_private(self):
        self.client.switch_initial = True
        with self.assertRaisesRegex(CanvasError, 'account changed'):
            read(self.client, '123', '44')
        for patch in ({'commentsConnection': None}, {'commentsConnection': {'nodes': None, 'pageInfo': {}}},
                      {'commentsConnection': {'nodes': [], 'pageInfo': {'hasNextPage': None, 'endCursor': None}}},
                      {'commentsConnection': {'nodes': [], 'pageInfo': {'hasNextPage': False, 'endCursor': 1}}}):
            self.setUp()
            self.client.query_patch = patch
            with self.assertRaises(CanvasError):
                self.create()
        self.setUp()
        self.client.payload_patch = 'missing'
        with self.assertRaisesRegex(CanvasError, 'omitted'):
            self.create()
        self.assertEqual(self.client.mutations, [])

    def test_offline_help_schema_classification_and_parser_contract(self):
        root = parser()
        names = ('submission-comments', 'comment-draft-create', 'comment-draft-edit', 'comment-draft-publish', 'comment-draft-delete')
        for name in names:
            selected = command_help(root, name)
            self.assertIn(name, selected['help_text'])
            self.assertEqual(selected['safety'], 'Read-only' if name == 'submission-comments' else 'Canvas writes (preview-first)')
        parsed = root.parse_args(['comment-draft-create', '123', '44', '--message-file', 'synthetic.txt', '--file-id', '81'])
        self.assertEqual(parsed.file_id, ['81'])

    def test_missing_mutation_record_or_target_readback_is_not_acknowledged_success(self):
        for action in ('create', 'publish', 'delete'):
            self.setUp()
            field = {'create': 'createSubmissionComment', 'publish': 'postDraftSubmissionComment', 'delete': 'deleteSubmissionComment'}[action]
            self.client.ack = {field: {'errors': [], 'submissionComment': None}}
            with self.assertRaisesRegex(CanvasError, 'unverified'):
                self.execute(action)
            self.assertEqual(len(self.client.mutations), 1)
        self.setUp()
        self.client.drop_after = True
        with self.assertRaisesRegex(CanvasError, 'unverified'):
            self.execute('publish')
        self.assertEqual(len(self.client.mutations), 1)

    def test_other_observed_changes_are_labeled_not_attributed_to_the_mutation(self):
        self.client.extra_after = True
        result = self.execute('edit')
        self.assertEqual(result['other_observed_comment_changes'], ['93'])
        self.assertIn('concurrent changes', result['note'])

    def test_shared_own_context_rejects_foreign_missing_or_malformed_policy_and_submission_metadata(self):
        identity = {'origin': self.client.host, 'user_id': 7}
        for patch in ({'_id': '45'}, {'courseId': '124'}, {'submissionTypes': {}}, {'allowedExtensions': [1]},
                      {'published': 'true'}, {'gradeGroupStudentsIndividually': 1}):
            with self.subTest(assignment=patch), self.assertRaises(CanvasError):
                context({'assignment': {**self.client.assignment, **patch}, 'submission': self.client.submission}, identity, '123', '44')
        assignment = self.client.assignment.copy()
        del assignment['published']
        with self.assertRaisesRegex(CanvasError, 'omitted'):
            context({'assignment': assignment, 'submission': self.client.submission}, identity, '123', '44')
        for patch in ({'attempt': True}, {'attempt': -1}, {'state': ''}, {'state': None}, {'submittedAt': {}},
                      {'userId': None}, {'assignmentId': '45'}, {'assignment': None}, {'_id': '0'}):
            with self.subTest(submission=patch), self.assertRaises(CanvasError):
                context({'assignment': self.client.assignment, 'submission': {**self.client.submission, **patch}}, identity, '123', '44')
        for missing in ('attempt', 'state', 'submittedAt'):
            row = self.client.submission.copy()
            del row[missing]
            with self.subTest(missing=missing), self.assertRaises(CanvasError):
                context({'assignment': self.client.assignment, 'submission': row}, identity, '123', '44')
