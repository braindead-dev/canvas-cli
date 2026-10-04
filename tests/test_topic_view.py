"""Native effective values are not proof of stored sort/expansion overrides."""

import copy
import json
import unittest
from unittest.mock import patch

from canvas_cli.arguments import parser
from canvas_cli.cli import run
from canvas_cli.client import CanvasError
from canvas_cli.formatting import brief
from canvas_cli.navigation import command_help
from canvas_cli.topic_view import change, read


class ViewClient:
    host = 'https://canvas.example.edu'

    def __init__(self):
        self.calls = []
        self.user_id = 7
        self.row = {'_id': '9', 'contextId': '123', 'contextType': 'Course', 'sortOrder': 'desc',
                    'sortOrderLocked': False, 'expanded': False, 'expandedLocked': False,
                    'permissions': {'read': True, 'update': False}, 'private': 'synthetic-private'}
        self.own = {'sortOrder': 'inherit', 'expanded': None, 'showPinnedEntries': True,
                    'preferredLanguage': None, 'summaryEnabled': False}
        self.language_type = {'name': 'PreferredLanguageType', 'kind': 'ENUM',
                              'enumValues': [{'name': name, 'isDeprecated': False} for name in ('EN', 'FR', 'PT_BR')]}
        self.language_error = False
        self.ignored = set()
        self.written = False
        self.ack = self.after_patch = self.query_patch = None
        self.query_count = self.profile_count = 0
        self.change_on_query = self.change_on_profile = None
        self.error_after_write = self.denied_after = False

    def request(self, route):
        self.calls.append(('GET', route, None))
        self.profile_count += 1
        if self.change_on_profile:
            self.change_on_profile(self)
        return {'id': self.user_id}, ''

    def graphql(self, document, variables, operation_name):
        self.calls.append((operation_name, document, copy.deepcopy(variables)))
        if operation_name == 'CanvasDiscussionLanguages':
            if self.language_error:
                raise CanvasError('Native schema denied', status=403)
            return {'__type': copy.deepcopy(self.language_type)}
        if operation_name == 'CanvasTopicViewSet':
            self.written = True
            for key, value in variables['input'].items():
                if key != 'discussionTopicId' and key not in self.ignored:
                    self.own[key] = value
            if self.error_after_write:
                raise CanvasError('Native mutation failed; check Canvas before repeating')
            ack = {'errors': [], 'discussionTopic': {key: self.row[key] for key in ('_id', 'contextId', 'contextType')}}
            return {'updateDiscussionTopicParticipant': ack if self.ack is None else copy.deepcopy(self.ack)}
        self.query_count += 1
        if self.change_on_query:
            self.change_on_query(self)
        if self.written and self.denied_after:
            raise CanvasError('synthetic-private')
        row = copy.deepcopy(self.row)
        if 'participant {' in document:
            row['participant'] = {key: row[key] if row[key + 'Locked'] or self.own[key] in (None, 'inherit') else self.own[key]
                                  for key in ('sortOrder', 'expanded')}
            row['participant']['showPinnedEntries'] = self.own['showPinnedEntries']
            for key in ('preferredLanguage', 'summaryEnabled'):
                if key in document:
                    value = self.own[key]
                    if key == 'preferredLanguage' and value not in {item['name'] for item in self.language_type['enumValues']}:
                        value = None
                    row['participant'][key] = value
        if self.query_patch:
            row.update(copy.deepcopy(self.query_patch))
        if self.written and self.after_patch:
            row.update(copy.deepcopy(self.after_patch))
        return {'legacyNode': row}


class TopicViewTests(unittest.TestCase):
    def setUp(self):
        self.client = ViewClient()

    def preview(self, values=None, **kwargs):
        return change(self.client, '123', '9', {'sort_order': 'asc', 'expanded': True} if values is None else values,
                      **({'acknowledge': True} | kwargs))

    def execute(self, values=None, **kwargs):
        preview = self.preview(values, **kwargs)
        return self.preview(values, yes=True, confirm=preview['confirm'], **kwargs)

    def mutations(self):
        return [row for row in self.client.calls if row[0] == 'CanvasTopicViewSet']

    def test_read_requires_acknowledgement_before_all_requests_and_is_classified_as_side_effecting(self):
        with self.assertRaisesRegex(CanvasError, 'participant-initialization'):
            read(self.client, '123', '9')
        self.assertEqual(self.client.calls, [])
        result = read(self.client, '123', '9', acknowledge=True)
        self.assertEqual(result['topic_view']['reported'], {'sort_order': 'desc', 'expanded': False, 'show_pinned_entries': True})
        self.assertTrue(result['native_query_may_initialize_participant'])
        self.assertEqual(command_help(parser(), 'topic-view')['safety'], 'Canvas queries (server-side effects possible)')
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertEqual(self.mutations(), [])

    def test_preview_queries_exact_scope_before_participant_and_never_fetches_posts_names_or_grades(self):
        result = self.preview()
        queries = [row[1] for row in self.client.calls if row[0] == 'CanvasTopicView']
        self.assertNotIn('participant {', queries[0])
        self.assertIn('participant {', queries[1])
        self.assertEqual(result['body']['variables']['input'], {'discussionTopicId': '9', 'sortOrder': 'asc', 'expanded': True})
        self.assertTrue(result['dry_run'])
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertEqual(self.mutations(), [])
        self.assertFalse(any(term in document for document in queries for term in ('discussionEntries', 'author', 'message', 'grade', 'posted', 'readStatus')))

    def test_change_sends_selected_own_values_once_and_independently_verifies_effective_values(self):
        source = copy.deepcopy(self.client.row)
        result = self.execute({'sort_order': 'asc', 'expanded': True, 'show_pinned_entries': False})
        self.assertTrue(result['mutation_acknowledged'])
        self.assertEqual(result['verification']['sort_order'], {'effective_value_verified': True, 'stored_override_verified': False})
        self.assertTrue(result['verification']['show_pinned_entries']['stored_override_verified'])
        self.assertFalse(result['verification']['show_pinned_entries']['effective_value_verified'])
        self.assertEqual(result['observed_changed_fields'], ['expanded', 'show_pinned_entries', 'sort_order'])
        self.assertEqual(len(self.mutations()), 1)
        self.assertEqual(self.client.row, source)
        self.assertIn('Raw saved sort/expansion overrides are not verified', brief(result))

    def test_explicit_expansion_inheritance_sends_null_not_default_and_does_not_claim_raw_override_verification(self):
        self.client.own.update(sortOrder='asc', expanded=True, showPinnedEntries=True)
        result = self.execute({'expanded': None})
        self.assertEqual(self.mutations()[0][2]['input'], {'discussionTopicId': '9', 'expanded': None})
        self.assertEqual(result['topic_view']['reported']['sort_order'], 'asc')
        self.assertIsNone(self.client.own['expanded'])
        self.assertFalse(result['verification']['expanded']['stored_override_verified'])

    def test_locks_mask_valid_native_overrides_but_are_never_claimed_saved_or_visible(self):
        self.client.row.update(sortOrderLocked=True, expandedLocked=True, expanded=True)
        result = self.execute({'sort_order': 'asc', 'expanded': False})
        self.assertEqual(result['masked_by_shared_locks'], ['sort_order', 'expanded'])
        self.assertEqual(result['topic_view']['reported']['sort_order'], 'desc')
        self.assertEqual(self.client.own['sortOrder'], 'asc')
        self.assertFalse(result['verification']['sort_order']['stored_override_verified'])
        self.assertIn('Masked by shared locks', brief(result))
        # An ignored write is indistinguishable under a shared lock; it still stays unverified.
        self.client.ignored = {'sortOrder'}
        self.client.own['sortOrder'] = 'desc'
        result = self.execute({'sort_order': 'asc'})
        self.assertFalse(result['verification']['sort_order']['stored_override_verified'])

    def test_group_and_readable_announcement_graded_anonymous_child_topics_do_not_need_update_authority(self):
        self.client.row.update(contextType='Group', isAnnouncement=True, anonymousState='full_anonymity', assignmentId='44', rootTopicId='5')
        result = self.execute({'expanded': True}, context_type='group')
        self.assertEqual(result['topic_view']['context_type'], 'group')
        self.assertEqual(len(self.mutations()), 1)

    def test_invalid_options_flags_or_context_fail_before_network(self):
        for values in ({}, [], {'unsupported': True}, {'sort_order': 'inherit'}, {'sort_order': True}, {'sort_order': None},
                       {'expanded': 1}, {'show_pinned_entries': 'false'}, {'show_pinned_entries': None}, {'summary_enabled': None}):
            with self.subTest(values=values), self.assertRaises(CanvasError):
                self.preview(values)
        for kwargs in ({'yes': True}, {'confirm': 'bad'}, {'acknowledge': False}, {'context_type': 'account'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                self.preview(**kwargs)
        self.assertEqual(self.client.calls, [])

    def test_null_locks_and_expansion_are_native_nullable_metadata_not_invented_defaults(self):
        self.client.row.update(sortOrderLocked=None, expanded=None, expandedLocked=None)
        result = read(self.client, '123', '9', acknowledge=True)
        self.assertIsNone(result['topic_view']['reported']['expanded'])
        self.assertIsNone(result['topic_view']['shared']['expanded_locked'])

    def test_missing_foreign_malformed_or_denied_metadata_never_reaches_participant_query(self):
        for patch_row in ({'_id': '10'}, {'contextId': '124'}, {'contextType': 'Group'}, {'sortOrder': None},
                          {'expandedLocked': 1}, {'expanded': 'false'}, {'permissions': None},
                          {'permissions': {'read': False, 'update': True}}):
            self.client = ViewClient()
            self.client.row.update(patch_row)
            with self.subTest(patch=patch_row), self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.mutations(), [])
            self.assertFalse(any('participant {' in row[1] for row in self.client.calls if row[0] == 'CanvasTopicView'))
        self.client = ViewClient()
        del self.client.row['expandedLocked']
        with self.assertRaises(CanvasError):
            self.preview()

    def test_malformed_own_values_and_inconsistent_locked_views_are_refused(self):
        for own in (None, {'sortOrder': 'wrong'}, {'sortOrder': 'asc', 'expanded': 1, 'showPinnedEntries': None},
                    {'sortOrder': 'asc', 'expanded': True}):
            self.client = ViewClient()
            self.client.query_patch = {'participant': own}
            with self.subTest(own=own), self.assertRaises(CanvasError):
                self.preview()
        self.client = ViewClient()
        self.client.row['sortOrderLocked'] = True
        self.client.query_patch = {'participant': {'sortOrder': 'asc', 'expanded': False, 'showPinnedEntries': False}}
        with self.assertRaisesRegex(CanvasError, 'inconsistent locked'):
            self.preview()

    def test_intra_query_account_or_shared_default_changes_prevent_explicit_mutation(self):
        def change_defaults(client):
            if client.query_count == 2:
                client.row['sortOrder'] = 'asc'
        for mode in ('defaults', 'account'):
            self.client = ViewClient()
            if mode == 'defaults':
                self.client.change_on_query = change_defaults
            else:
                self.client.change_on_profile = lambda c: setattr(c, 'user_id', 8 if c.profile_count > 1 else 7)
            with self.assertRaisesRegex(CanvasError, 'no preference mutation'):
                self.preview()
            self.assertEqual(self.mutations(), [])

    def test_stale_account_scope_shared_or_own_view_confirmation_prevents_mutation(self):
        for mode in ('account', 'scope', 'shared', 'own'):
            self.client = ViewClient()
            preview = self.preview()
            if mode == 'account':
                self.client.user_id = 8
            elif mode == 'scope':
                self.client.row['contextId'] = '124'
            elif mode == 'shared':
                self.client.row['expandedLocked'] = True
            else:
                self.client.own['sortOrder'] = 'asc'
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(yes=True, confirm=preview['confirm'])
            self.assertEqual(self.mutations(), [])

    def test_native_errors_malformed_ack_foreign_ack_denied_readback_never_retry_or_leak(self):
        for ack in ([], {'errors': [{'attribute': 'synthetic-private'}]}, {'discussionTopic': {}},
                    {'errors': [], 'discussionTopic': {'_id': '10', 'contextId': '123', 'contextType': 'Course'}}):
            self.client = ViewClient()
            self.client.ack = ack
            with self.subTest(ack=ack), self.assertRaises(CanvasError) as caught:
                self.execute()
            self.assertNotIn('synthetic-private', str(caught.exception))
            self.assertIn('repeating', str(caught.exception))
            self.assertEqual(len(self.mutations()), 1)
        for mode in ('error_after_write', 'denied_after'):
            self.client = ViewClient()
            setattr(self.client, mode, True)
            with self.assertRaises(CanvasError) as caught:
                self.execute()
            self.assertNotIn('synthetic-private', str(caught.exception))
            self.assertEqual(len(self.mutations()), 1)

    def test_ignored_partial_or_unrequested_collateral_changes_are_honestly_verified_or_labeled(self):
        for key in ('sortOrder', 'expanded', 'showPinnedEntries'):
            self.client = ViewClient()
            self.client.ignored = {key}
            with self.subTest(key=key), self.assertRaisesRegex(CanvasError, 'Some changes may have applied'):
                self.execute({'sort_order': 'asc', 'expanded': True, 'show_pinned_entries': False})
            self.assertEqual(len(self.mutations()), 1)
        self.client = ViewClient()
        self.client.after_patch = {'participant': {'sortOrder': 'asc', 'expanded': True, 'showPinnedEntries': False}}
        result = self.execute({'sort_order': 'asc'})
        self.assertEqual(result['observed_changed_fields'], ['expanded', 'show_pinned_entries', 'sort_order'])

    def test_post_mutation_account_or_shared_changes_are_unverified_not_automatically_repaired(self):
        for mode in ('account', 'shared'):
            self.client = ViewClient()
            if mode == 'account':
                self.client.change_on_profile = lambda c: setattr(c, 'user_id', 8 if c.written else 7)
            else:
                self.client.after_patch = {'sortOrder': 'asc'}
            with self.assertRaisesRegex(CanvasError, 'outcome is unverified'):
                self.execute()
            self.assertEqual(len(self.mutations()), 1)

    @patch('canvas_cli.auth.connect')
    def test_parser_dispatch_negative_options_explicit_nulls_and_group_context(self, connect):
        connect.return_value = self.client
        args = parser().parse_args(['topic-view-set', '123', '9', '--inherit-expansion',
                                   '--acknowledge-participant-initialization'])
        result = run(args)
        self.assertEqual(result['body']['variables']['input'], {'discussionTopicId': '9', 'expanded': None})
        args = parser().parse_args(['topic-view-set', '123', '9', '--no-expanded', '--no-show-pinned-entries',
                                   '--acknowledge-participant-initialization'])
        self.assertEqual(run(args)['requested'], {'expanded': False, 'show_pinned_entries': False})
        self.assertTrue(run(parser().parse_args(['topic-view', '123', '9', '--acknowledge-participant-initialization']))['native_query_may_initialize_participant'])
