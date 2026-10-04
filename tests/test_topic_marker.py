"""The own pinned-unread indicator is distinct from viewing or reading replies."""

import copy
import json
import unittest
from unittest.mock import patch

from test_topic_view import ViewClient

from canvas_cli.arguments import parser
from canvas_cli.cli import run
from canvas_cli.client import CanvasError
from canvas_cli.topic_view import change, read


class TopicMarkerTests(unittest.TestCase):
    def setUp(self):
        self.client = ViewClient()

    def preview(self, values=None, **kwargs):
        return change(self.client, '123', '9', {'has_unread_pinned_entry': True} if values is None else values,
                      **({'acknowledge': True, 'acknowledge_marker': True} | kwargs))

    def execute(self, values=None):
        preview = self.preview(values)
        return self.preview(values, yes=True, confirm=preview['confirm'])

    def mutations(self):
        return [row for row in self.client.calls if row[0] == 'CanvasTopicViewSet']

    def test_missing_marker_acknowledgement_is_rejected_before_identity_metadata_or_initialization(self):
        with self.assertRaisesRegex(CanvasError, 'acknowledge-pinned-marker-change'):
            self.preview(acknowledge_marker=False)
        self.assertEqual(self.client.calls, [])

    def test_marker_read_is_opt_in_and_composes_with_assist_without_content_or_service_queries(self):
        basic = read(self.client, '123', '9', acknowledge=True)
        self.assertNotIn('has_unread_pinned_entry', basic['topic_view']['reported'])
        self.client.calls.clear()
        marker = read(self.client, '123', '9', acknowledge=True, include_marker=True)
        self.assertFalse(marker['topic_view']['reported']['has_unread_pinned_entry'])
        self.assertNotIn('preferred_language', marker['topic_view']['reported'])
        document = next(row[1] for row in self.client.calls if row[0] == 'CanvasTopicView' and 'participant {' in row[1])
        self.assertIn('hasUnreadPinnedEntry', document)
        participant = document.split('participant {', 1)[1].split('}', 1)[0]
        self.assertFalse(any(key in participant for key in ('readStatus', 'unreadCount', 'read ', 'message', 'posted', 'summaryEnabled')))
        all_preferences = read(self.client, '123', '9', acknowledge=True, include_assist=True, include_marker=True)
        self.assertEqual(len(all_preferences['topic_view']['reported']), 6)
        self.assertEqual(self.mutations(), [])

    def test_selected_marker_true_and_false_are_stored_once_without_changing_other_fields(self):
        for value in (True, False):
            self.client = ViewClient()
            self.client.own['hasUnreadPinnedEntry'] = not value
            before = copy.deepcopy(self.client.own)
            shared = copy.deepcopy(self.client.row)
            result = self.execute({'has_unread_pinned_entry': value})
            self.assertEqual(len(self.mutations()), 1)
            self.assertEqual(self.mutations()[0][2]['input'], {'discussionTopicId': '9', 'hasUnreadPinnedEntry': value})
            self.assertEqual(self.client.row, shared)
            self.assertEqual({key: item for key, item in self.client.own.items() if key != 'hasUnreadPinnedEntry'},
                             {key: item for key, item in before.items() if key != 'hasUnreadPinnedEntry'})
            self.assertEqual(result['verification']['has_unread_pinned_entry'],
                             {'effective_value_verified': False, 'stored_override_verified': True})
            self.assertEqual(result['observed_changed_fields'], ['has_unread_pinned_entry'])
            self.assertIn('not proof any reply was read or seen', result['note'])

    def test_omission_does_not_query_or_send_marker_and_retains_own_marker(self):
        self.client.own['hasUnreadPinnedEntry'] = True
        self.execute({'expanded': True})
        self.assertTrue(self.client.own['hasUnreadPinnedEntry'])
        self.assertNotIn('hasUnreadPinnedEntry', self.mutations()[0][2]['input'])
        self.assertFalse(any('hasUnreadPinnedEntry' in row[1] for row in self.client.calls if row[0] == 'CanvasTopicView'))

    def test_null_strings_integers_and_foreign_user_selection_are_invalid_before_all_requests(self):
        for values in ({'has_unread_pinned_entry': None}, {'has_unread_pinned_entry': 0},
                       {'has_unread_pinned_entry': 'false'}, {'has_unread_pinned_entry': True, 'user_id': 8}):
            with self.subTest(values=values), self.assertRaises(CanvasError):
                self.preview(values)
        self.assertEqual(self.client.calls, [])

    def test_changed_marker_prevents_mutation_and_ignored_marker_write_is_unverified_without_retry(self):
        preview = self.preview()
        self.client.own['hasUnreadPinnedEntry'] = True
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            self.preview(yes=True, confirm=preview['confirm'])
        self.assertEqual(self.mutations(), [])
        self.client = ViewClient()
        self.client.ignored = {'hasUnreadPinnedEntry'}
        with self.assertRaisesRegex(CanvasError, 'Some changes may have applied'):
            self.execute()
        self.assertEqual(len(self.mutations()), 1)

    def test_nullable_marker_read_is_not_false_and_malformed_readback_does_not_leak(self):
        self.client.own['hasUnreadPinnedEntry'] = None
        result = read(self.client, '123', '9', acknowledge=True, include_marker=True)
        self.assertIsNone(result['topic_view']['reported']['has_unread_pinned_entry'])
        self.client.own['hasUnreadPinnedEntry'] = 'synthetic-private'
        with self.assertRaises(CanvasError) as caught:
            read(self.client, '123', '9', acknowledge=True, include_marker=True)
        self.assertNotIn('synthetic-private', str(caught.exception))

    def test_readable_group_and_combined_changes_need_no_invented_moderation_authority(self):
        self.client.row['contextType'] = 'Group'
        preview = self.preview({'has_unread_pinned_entry': True, 'summary_enabled': True}, context_type='group')
        result = self.preview({'has_unread_pinned_entry': True, 'summary_enabled': True}, context_type='group',
                              yes=True, confirm=preview['confirm'])
        self.assertTrue(result['verification']['has_unread_pinned_entry']['stored_override_verified'])
        self.assertTrue(result['verification']['summary_enabled']['stored_override_verified'])
        self.assertEqual(len(self.mutations()), 1)
        self.assertFalse(any(row[0] == 'CanvasDiscussionLanguages' for row in self.client.calls))

    @patch('canvas_cli.auth.connect')
    def test_parser_dispatch_marker_read_negative_flag_acknowledgement_and_exact_native_payload(self, connect):
        connect.return_value = self.client
        root = parser()
        result = run(root.parse_args(['topic-view', '123', '9', '--include-pinned-marker',
                                     '--acknowledge-participant-initialization']))
        self.assertFalse(result['topic_view']['reported']['has_unread_pinned_entry'])
        for flag, value in (('--pinned-unread', True), ('--no-pinned-unread', False)):
            result = run(root.parse_args(['topic-view-set', '123', '9', flag,
                                         '--acknowledge-pinned-marker-change', '--acknowledge-participant-initialization']))
            self.assertEqual(result['body']['variables']['input'], {'discussionTopicId': '9', 'hasUnreadPinnedEntry': value})
            self.assertTrue(result['pinned_marker_change_acknowledged'])
            self.assertNotIn('synthetic-private', json.dumps(result))
