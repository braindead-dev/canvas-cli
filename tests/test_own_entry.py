"""Native ownership before details; no anonymous ID guessing or foreign bodies."""

import copy
import json
import unittest

from canvas_cli.client import CanvasError
from canvas_cli.own_entry import edit, history, read


class OwnEntryClient:
    host = 'https://canvas.example.edu'

    def __init__(self):
        self.calls = []
        self.identity = 7
        self.context = {'id': 123, 'name': 'Synthetic context'}
        self.row = {'_id': '301', 'discussionTopicId': '9', 'parentId': None, 'deleted': False,
                    'createdAt': None, 'updatedAt': '2026-10-04T12:00:00Z', 'author': {'_id': '7'},
                    'anonymousAuthor': None, 'permissions': {'read': True, 'update': True, 'attach': False},
                    'discussionTopic': {'_id': '9', 'contextId': '123', 'contextType': 'Course',
                                        'anonymousState': None, 'permissions': {'read': True}},
                    'message': '<p>synthetic-private-body</p>', 'quotedEntry': {'_id': '302'},
                    'attachment': {'_id': '61', 'displayName': 'Synthetic file', 'sizeBytes': 0, 'updatedAt': None,
                                   'url': 'https://storage.example/?token=synthetic-private-file'}}
        self.detail_change = self.after_identity = self.after_context = None

    def request(self, route):
        self.calls.append(('GET', route))
        if route == '/api/v1/users/self/profile':
            return {'id': self.identity}, ''
        if route == '/api/v1/courses/123' or route == '/api/v1/groups/123':
            return copy.deepcopy(self.context), ''
        raise AssertionError(route)

    def graphql(self, document, variables, operation):
        self.calls.append((operation, document, variables))
        row = copy.deepcopy(self.row)
        if operation == 'CanvasOwnEntryDetails':
            if self.detail_change is not None:
                row = row | self.detail_change
            if self.after_identity is not None:
                self.identity = self.after_identity
            if self.after_context is not None:
                self.context['name'] = self.after_context
        else:
            assert ' message ' not in document and 'attachment' not in document and 'quotedEntry' not in document
        return {'legacyNode': row}


class OwnEntryTests(unittest.TestCase):
    def setUp(self):
        self.client = OwnEntryClient()

    def read(self, **options):
        return read(self.client, '123', '9', '301', **options)

    def test_own_metadata_first_then_body_file_bytes_and_quote_id_without_private_content_or_file_url_output(self):
        result = self.read()
        self.assertEqual(result['own_entry']['ownership_proof'], 'native_author_id')
        self.assertEqual(result['own_entry']['attachment']['size_bytes'], 0)
        self.assertEqual(result['own_entry']['quoted_entry_id'], 302)
        self.assertFalse(result['raw_storage_verified'])
        self.assertFalse(result['grade_credit_verified'])
        self.assertNotIn('synthetic-private', json.dumps(result))
        operations = [call for call in self.client.calls if call[0] != 'GET']
        self.assertEqual([call[0] for call in operations], ['CanvasOwnEntryOwner', 'CanvasOwnEntryDetails'])
        self.assertEqual(operations[0][2], {'entryId': '301'})
        for _, document, _ in operations:
            self.assertNotIn('entryParticipant', document)
            self.assertNotIn('submission', document.lower())
            self.assertNotIn(' url ', document)
            self.assertNotIn('mutation', document)

    def test_explicit_content_opt_in_and_group_context_are_separate_from_raw_storage_proof(self):
        self.client.row['discussionTopic']['contextType'] = 'Group'
        self.client.row['attachment'] = self.client.row['quotedEntry'] = None
        result = self.read(context_type='group', include_content=True)
        self.assertEqual(result['own_entry']['rendered_message'], '<p>synthetic-private-body</p>')
        self.assertIsNone(result['own_entry']['attachment'])
        self.assertFalse(result['raw_storage_verified'])

    def test_foreign_author_hidden_or_unavailable_context_denied_rights_and_malformed_owner_never_request_body(self):
        for change in ({'_id': '302'}, {'discussionTopicId': '10'}, {'author': {'_id': '8'}},
                       {'author': None}, {'deleted': True}, {'parentId': 1}, {'updatedAt': []},
                       {'permissions': {'read': False, 'update': True, 'attach': True}},
                       {'permissions': {'read': True, 'update': 1, 'attach': True}},
                       {'discussionTopic': {'_id': '9', 'contextId': '456', 'contextType': 'Course'}}):
            self.client = OwnEntryClient()
            self.client.row.update(change)
            with self.subTest(change=change), self.assertRaises(CanvasError):
                self.read()
            self.assertFalse(any(call[0] == 'CanvasOwnEntryDetails' for call in self.client.calls))

    def test_anonymous_ownership_uses_only_native_current_user_marker_and_not_participant_or_user_id_guess(self):
        for state in ('partial_anonymity', 'full_anonymity'):
            self.client = OwnEntryClient()
            self.client.row['author'] = None
            self.client.row['anonymousAuthor'] = {'id': 'abc', 'shortName': 'current_user'}
            self.client.row['discussionTopic']['anonymousState'] = state
            result = self.read()
            self.assertEqual(result['own_entry']['user_id'], 7)
            self.assertEqual(result['own_entry']['ownership_proof'], 'native_current_user_anonymous_marker')
            self.assertNotIn('"abc"', json.dumps(result))
            self.assertNotIn('anonymousAuthor', result['own_entry'])
        for marker in (None, {'id': '7', 'shortName': '7'}, {'id': 'abc', 'shortName': 'another'},
                       {'id': '../7', 'shortName': 'current_user'}):
            self.client = OwnEntryClient()
            self.client.row['author'] = None
            self.client.row['anonymousAuthor'] = marker
            self.client.row['discussionTopic']['anonymousState'] = 'full_anonymity'
            with self.subTest(marker=marker), self.assertRaises(CanvasError):
                self.read()
            self.assertFalse(any(call[0] == 'CanvasOwnEntryDetails' for call in self.client.calls))

    def test_detail_owner_account_or_context_race_and_bad_file_quote_content_metadata_refuse_without_mutation(self):
        for change in ({'author': {'_id': '8'}}, {'updatedAt': 'Changed'}, {'message': None},
                       {'attachment': []}, {'attachment': {'_id': '61', 'displayName': 'x', 'sizeBytes': True, 'updatedAt': None}},
                       {'quotedEntry': []}, {'quotedEntry': {'_id': '0'}}):
            self.client = OwnEntryClient()
            self.client.detail_change = change
            with self.subTest(change=change), self.assertRaises(CanvasError):
                self.read()
        for field, value in (('after_identity', 8), ('after_context', 'Changed')):
            self.client = OwnEntryClient()
            setattr(self.client, field, value)
            with self.subTest(field=field), self.assertRaises(CanvasError):
                self.read()

    def test_invalid_context_identifier_or_content_flag_refuses_before_network(self):
        for options in ({'context_type': 'user'}, {'include_content': 1}):
            with self.subTest(options=options), self.assertRaises(CanvasError):
                self.read(**options)
            self.assertEqual(self.client.calls, [])
        with self.assertRaises(CanvasError):
            read(self.client, '123', '9', '../301')
        self.assertEqual(self.client.calls, [])


class OwnEntryHistoryClient(OwnEntryClient):
    def __init__(self):
        super().__init__()
        self.versions = [{'_id': '501', 'version': 1, 'createdAt': None, 'updatedAt': None,
                          'message': '<p>synthetic-private-old-version</p>'},
                         {'_id': '502', 'version': 3, 'createdAt': '2026-10-04T12:00:00Z',
                          'updatedAt': '2026-10-04T12:00:00Z', 'message': '<p>synthetic-private-new-version</p>'}]
        self.history_change = self.after_history = None

    def graphql(self, document, variables, operation):
        if operation != 'CanvasOwnEntryHistory':
            return super().graphql(document, variables, operation)
        self.calls.append((operation, document, variables))
        row = copy.deepcopy(self.row)
        row['discussionEntryVersions'] = copy.deepcopy(self.versions)
        if isinstance(row['discussionEntryVersions'], list) and not variables['includeContent']:
            for version in row['discussionEntryVersions']:
                if isinstance(version, dict):
                    version.pop('message', None)
        if self.history_change:
            row.update(self.history_change)
        if self.after_history == 'body':
            self.row['message'] += 'Changed'
        elif self.after_history == 'identity':
            self.identity = 8
        elif self.after_history == 'context':
            self.context['name'] = 'Changed'
        return {'legacyNode': row}


class OwnEntryHistoryTests(unittest.TestCase):
    def setUp(self):
        self.client = OwnEntryHistoryClient()

    def history(self, **options):
        return history(self.client, '123', '9', '301', **options)

    def test_default_history_is_metadata_only_owner_first_ordered_and_not_a_complete_archive_claim(self):
        result = self.history()
        versions = result['own_entry_history']['versions']
        self.assertEqual([row['version'] for row in versions], [3, 1])
        self.assertTrue(result['native_unpaginated'])
        self.assertFalse(result['complete_history_verified'])
        self.assertFalse(result['raw_storage_verified'])
        self.assertNotIn('synthetic-private', json.dumps(result))
        calls = [call for call in self.client.calls if call[0] != 'GET']
        self.assertEqual([call[0] for call in calls], ['CanvasOwnEntryOwner', 'CanvasOwnEntryDetails',
                                                     'CanvasOwnEntryHistory', 'CanvasOwnEntryOwner', 'CanvasOwnEntryDetails'])
        self.assertEqual(calls[2][2], {'entryId': '301', 'includeContent': False})
        self.assertIn('message @include(if: $includeContent)', calls[2][1])
        self.assertNotIn('messageIntro', calls[2][1])
        self.assertNotIn('participant', calls[2][1].lower())
        self.assertNotIn('mutation', calls[2][1])

    def test_historical_content_is_explicit_for_group_and_native_anonymous_ownership_and_empty_lists_stay_unknown(self):
        self.client.row['discussionTopic'].update(contextType='Group', anonymousState='full_anonymity')
        self.client.row.update(author=None, anonymousAuthor={'id': 'abc', 'shortName': 'current_user'})
        result = self.history(context_type='group', include_content=True)
        self.assertIn('synthetic-private-new-version', result['own_entry_history']['versions'][0]['message'])
        self.assertEqual(result['own_entry_history']['ownership_proof'], 'native_current_user_anonymous_marker')
        self.assertNotIn('"abc"', json.dumps(result))
        self.client.versions = []
        result = self.history(context_type='group')
        self.assertEqual(result['own_entry_history']['versions'], [])
        self.assertFalse(result['complete_history_verified'])

    def test_invalid_local_options_or_foreign_owner_stop_before_history_content_query(self):
        for options in ({'include_content': 1}, {'max_versions': True}, {'max_versions': 0},
                        {'max_versions': 1001}, {'context_type': 'user'}):
            with self.subTest(options=options), self.assertRaises(CanvasError):
                self.history(**options)
            self.assertEqual(self.client.calls, [])
        self.client.row['author']['_id'] = '8'
        with self.assertRaises(CanvasError):
            self.history(include_content=True)
        self.assertFalse(any(call[0] == 'CanvasOwnEntryHistory' for call in self.client.calls))

    def test_missing_oversized_duplicate_or_malformed_native_versions_do_not_become_empty_or_complete_history(self):
        version = copy.deepcopy(self.client.versions[0])
        cases = [None, {}, [None], [version, version],
                 [version | {'_id': '0'}], [version | {'version': True}], [version | {'version': 0}],
                 [version | {'createdAt': []}], [{key: value for key, value in version.items() if key != 'updatedAt'}],
                 [version | {'message': None}]]
        for versions in cases:
            self.client = OwnEntryHistoryClient()
            self.client.versions = versions
            with self.subTest(versions=versions), self.assertRaises(CanvasError):
                self.history(include_content=True)
        self.client = OwnEntryHistoryClient()
        with self.assertRaisesRegex(CanvasError, 'cap'):
            self.history(max_versions=1)

    def test_changed_scope_revision_account_or_context_is_refused_without_mutation(self):
        for change in ({'_id': '302'}, {'updatedAt': 'Changed'}, {'author': {'_id': '8'}}):
            self.client = OwnEntryHistoryClient()
            self.client.history_change = change
            with self.subTest(change=change), self.assertRaises(CanvasError):
                self.history()
        for mode in ('body', 'identity', 'context'):
            self.client = OwnEntryHistoryClient()
            self.client.after_history = mode
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.history()


class OwnEntryEditClient(OwnEntryClient):
    def __init__(self):
        super().__init__()
        self.mode = None
        self.row['parentId'] = '300'

    def graphql(self, document, variables, operation):
        if operation != 'CanvasOwnEntryEdit':
            return super().graphql(document, variables, operation)
        self.calls.append((operation, document, copy.deepcopy(variables)))
        body = variables['input']
        if self.mode == 'denied':
            return {'updateDiscussionEntry': {'errors': [{'attribute': 'synthetic-private-denial'}], 'discussionEntry': None}}
        # Native update preserves files when omitted, but clears quotes for
        # replies if quotedEntryId is absent. The test models that independently.
        self.row['message'] = body['message']
        self.row['updatedAt'] = '2026-10-04T13:00:00Z'
        if self.row['parentId'] is not None:
            selected = body.get('quotedEntryId')
            self.row['quotedEntry'] = {'_id': selected} if selected is not None else None
        if self.mode == 'clear-file':
            self.row['attachment'] = None
        elif self.mode == 'clear-quote':
            self.row['quotedEntry'] = None
        elif self.mode == 'normalized':
            self.row['message'] = '<p>Different native text</p>'
        elif self.mode == 'error-after-save':
            raise CanvasError('synthetic-private-save-failure')
        return {'updateDiscussionEntry': {'errors': [], 'discussionEntry': copy.deepcopy(self.row)}}


class OwnEntryEditTests(unittest.TestCase):
    def setUp(self):
        self.client = OwnEntryEditClient()

    def preview(self, **options):
        return edit(self.client, '123', '9', '301', 'New <script> &\ntext', **options)

    def writes(self):
        return [call for call in self.client.calls if call[0] == 'CanvasOwnEntryEdit']

    def approved(self, **options):
        preview = self.preview(**options)
        return self.preview(yes=True, confirm=preview['confirm'], **options)

    def test_preview_binds_context_revision_quote_and_file_without_raw_previous_body_urls_or_mutation(self):
        preview = self.preview()
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['input'], {'discussionEntryId': '301', 'message': '<p>New &lt;script&gt; &amp;<br>text</p>',
                                            'quotedEntryId': '302'})
        self.assertEqual(preview['context']['id'], 123)
        self.assertNotIn('synthetic-private', json.dumps(preview))
        self.assertEqual(self.writes(), [])

    def test_one_mutation_preserves_own_course_group_root_reply_file_and_visible_quote_without_attach_rights(self):
        for group in (False, True):
            for root in (False, True):
                self.client = OwnEntryEditClient()
                if group:
                    self.client.row['discussionTopic']['contextType'] = 'Group'
                if root:
                    self.client.row['parentId'] = None
                before_file = copy.deepcopy(self.client.row['attachment'])
                result = self.approved(context_type='group' if group else 'course')
                self.assertEqual(len(self.writes()), 1)
                supplied = self.writes()[0][2]['input']
                for field in ('fileId', 'removeAttachment', 'pinType'):
                    self.assertNotIn(field, supplied)
                self.assertEqual('quotedEntryId' in supplied, not root)
                self.assertEqual(self.client.row['attachment'], before_file)
                self.assertTrue(result['rendered_text_verified'])
                self.assertTrue(result['attachment_association_verified'])
                self.assertFalse(result['grade_credit_verified'])
                self.assertFalse(result['stored_file_bytes_verified'])

    def test_anonymous_own_marker_and_absent_file_or_quote_remain_distinct_native_cases(self):
        self.client.row['author'] = None
        self.client.row['anonymousAuthor'] = {'id': 'abc', 'shortName': 'current_user'}
        self.client.row['discussionTopic']['anonymousState'] = 'full_anonymity'
        self.client.row['attachment'] = self.client.row['quotedEntry'] = None
        result = self.approved()
        self.assertEqual(result['own_entry']['ownership_proof'], 'native_current_user_anonymous_marker')
        self.assertIsNone(self.writes()[0][2]['input']['quotedEntryId'])
        self.assertTrue(result['visible_quote_association_verified'])
        self.assertFalse(result['hidden_quote_storage_verified'])

    def test_stale_revision_file_quote_parent_identity_and_context_never_mutate(self):
        for mode in ('text', 'file', 'quote', 'parent', 'identity', 'context'):
            self.client = OwnEntryEditClient()
            preview = self.preview()
            if mode == 'text':
                self.client.row['message'] += 'Changed'
            elif mode == 'file':
                self.client.row['attachment']['sizeBytes'] = 1
            elif mode == 'quote':
                self.client.row['quotedEntry'] = None
            elif mode == 'parent':
                self.client.row['parentId'] = '333'
            elif mode == 'identity':
                self.client.identity = 8
            else:
                self.client.context['name'] = 'Changed'
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(yes=True, confirm=preview['confirm'])
            self.assertEqual(self.writes(), [])

    def test_unpaired_flags_invalid_text_and_missing_native_update_refuse_before_mutation(self):
        for options in ({'yes': True}, {'confirm': 'unpaired'}):
            with self.assertRaises(CanvasError):
                self.preview(**options)
            self.assertEqual(self.client.calls, [])
        for text in ('', '\x00', '\ud800', 'x' * 40001):
            with self.assertRaises(CanvasError):
                edit(self.client, '123', '9', '301', text)
            self.assertEqual(self.client.calls, [])
        self.client.row['permissions']['update'] = False
        with self.assertRaisesRegex(CanvasError, 'update rights'):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_partial_file_or_quote_loss_denial_normalization_and_error_after_save_are_uncertain_once(self):
        for mode in ('clear-file', 'clear-quote', 'denied', 'normalized', 'error-after-save'):
            self.client = OwnEntryEditClient()
            preview = self.preview()
            self.client.mode = mode
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'may have applied') as error:
                self.preview(yes=True, confirm=preview['confirm'])
            self.assertNotIn('synthetic-private', str(error.exception))
            self.assertEqual(len(self.writes()), 1)
