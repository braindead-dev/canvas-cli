import unittest
from copy import deepcopy
from unittest.mock import Mock

from canvas_pocket.client import CanvasError
from canvas_pocket.notifications import change, channels, pairs, preferences


class NotificationsTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.channel = {'id': 19, 'user_id': 7, 'type': 'email', 'position': 1,
                        'workflow_state': 'active', 'address': 'synthetic@example.edu',
                        'bounce_count': 0, 'last_bounce_summary': 'private bounce details',
                        'token': 'never output', 'created_at': '2026-10-02T12:00:00Z'}
        self.prefs = {'notification_preferences': [
            {'notification': 'new_announcement', 'frequency': 'daily', 'category': 'announcement',
             'href': 'https://canvas.example.edu/users/7/email/synthetic@example.edu/preferences'},
            {'notification': 'submission_comment', 'frequency': 'never', 'category': 'submission_comment'},
            {'notification': 'special_notice', 'frequency': 'weekly', 'category': None}]}
        self.client.list.return_value = [self.channel]
        self.responses()

    def responses(self, response=None, *, profile=None, links=''):
        self.client.request.side_effect = [(profile or {'id': 7}, ''),
                                           (response if response is not None else self.prefs, links)]

    def test_channel_inventory_is_paginated_own_and_metadata_first(self):
        self.client.request.side_effect = [({'id': 7}, '')]
        result = channels(self.client, 2)
        self.assertEqual(result['communication_channels'][0]['id'], 19)
        self.assertTrue(result['complete_for_endpoint'])
        self.assertFalse(result['addresses_included'])
        for private in ('synthetic@example.edu', 'private bounce details', 'never output'):
            self.assertNotIn(private, str(result))
        self.client.list.assert_called_once_with('/api/v1/users/self/communication_channels?per_page=100', 2)

    def test_address_opt_in_never_exposes_provider_tokens_or_bounce_summaries(self):
        push = {**self.channel, 'id': 20, 'type': 'push', 'address': 'private-provider-token'}
        self.client.list.return_value = [self.channel, push, {**self.channel, 'id': 21, 'type': 'yo'}]
        self.client.request.side_effect = [({'id': 7}, '')]
        result = channels(self.client, include_addresses=True)
        self.assertEqual(result['communication_channels'][0]['address'], 'synthetic@example.edu')
        self.assertNotIn('address', result['communication_channels'][1])
        for private in ('private-provider-token', 'private bounce details', 'never output'):
            self.assertNotIn(private, str(result))
        self.client.list.return_value = [{**self.channel, 'address': ['invalid']}]
        self.client.request.side_effect = [({'id': 7}, '')]
        with self.assertRaisesRegex(CanvasError, 'address'):
            channels(self.client, include_addresses=True)

    def test_other_users_bad_ids_retired_channels_and_duplicates_fail_closed(self):
        bad = [{**self.channel, 'user_id': 8}, {**self.channel, 'user_id': True},
               {**self.channel, 'id': True}, {**self.channel, 'id': 0},
               {**self.channel, 'type': None}, {**self.channel, 'workflow_state': 'retired'}, []]
        for record in bad:
            with self.subTest(record=record), self.assertRaises(CanvasError):
                self.client.list.return_value = [record]
                self.client.request.side_effect = [({'id': 7}, '')]
                channels(self.client)
        self.client.list.return_value = [self.channel, self.channel]
        self.client.request.side_effect = [({'id': 7}, '')]
        with self.assertRaisesRegex(CanvasError, 'duplicate'):
            channels(self.client)

    def test_wrapped_preferences_omit_addresses_hrefs_and_unknown_fields(self):
        result = preferences(self.client, '19', 3)
        self.assertEqual(len(result['notification_preferences']), 3)
        self.assertEqual(result['categories'], ['announcement', 'submission_comment'])
        self.assertIn('default notification-policy', result['note'])
        self.assertNotIn('synthetic@example.edu', str(result))
        self.assertNotIn('href', str(result))
        self.assertIsNone(next(row for row in result['notification_preferences']
                               if row['notification'] == 'special_notice')['category'])
        self.client.request.assert_called_with('/api/v1/users/self/communication_channels/19/notification_preferences')
        self.client.list.assert_called_once_with('/api/v1/users/self/communication_channels?per_page=100', 3)

    def test_category_filters_follow_the_full_inventory_and_unknown_is_not_empty_success(self):
        result = preferences(self.client, '19', category='announcement')
        self.assertEqual([row['notification'] for row in result['notification_preferences']], ['new_announcement'])
        self.responses()
        with self.assertRaisesRegex(CanvasError, 'Category is not reported'):
            preferences(self.client, '19', category='unknown_category')

    def test_malformed_or_duplicate_preference_responses_and_pagination_are_not_emitted(self):
        for response in ([], {}, {'notification_preferences': {}},
                         {'notification_preferences': [self.prefs['notification_preferences'][0]] * 2},
                         {'notification_preferences': [{'notification': 'unknown', 'frequency': 'asap'}]},
                         {'notification_preferences': [{'notification': None, 'frequency': 'never'}]},
                         {'notification_preferences': [{'notification': 'bad/path', 'frequency': 'never'}]},
                         {'notification_preferences': [{'notification': 'okay', 'frequency': 'never', 'category': {}}]}):
            with self.subTest(response=response), self.assertRaises(CanvasError):
                self.responses(response)
                preferences(self.client, '19')
        self.responses(links='<https://canvas.example.edu/api/v1/next>; rel="next"')
        with self.assertRaisesRegex(CanvasError, 'pagination'):
            preferences(self.client, '19')

    def test_pairs_accept_exact_native_frequencies_and_distinct_keys_only(self):
        self.assertEqual(pairs(['new_announcement=immediately', 'submission_comment=never']),
                         {'new_announcement': 'immediately', 'submission_comment': 'never'})
        for values in ([], [None], ['email=x'], ['new_announcement=asap'], ['new_announcement=Daily'],
                       ['new_announcement=never', 'new_announcement=daily'], ['../escape=never'],
                       ['a=never=weekly'], ['notification daily'], [' notification=never']):
            with self.subTest(values=values), self.assertRaises(CanvasError):
                pairs(values)

    def test_invalid_changes_ids_or_flags_fail_before_any_request(self):
        for options in ({'channel_id': '0', 'changes': {'new_announcement': 'daily'}},
                        {'channel_id': '01', 'changes': {'new_announcement': 'daily'}},
                        {'channel_id': '١', 'changes': {'new_announcement': 'daily'}},
                        {'channel_id': '../19', 'changes': {'new_announcement': 'daily'}},
                        {'channel_id': '19', 'changes': {}}, {'channel_id': '19', 'changes': []},
                        {'channel_id': '19', 'changes': {'new_announcement': True}},
                        {'channel_id': '19', 'changes': {'Bad Key': 'daily'}},
                        {'channel_id': '19', 'changes': {'new_announcement': 'daily'}, 'yes': True}):
            with self.subTest(options=options), self.assertRaises(CanvasError):
                change(self.client, **options)
        self.client.request.assert_not_called()
        self.client.list.assert_not_called()

    def test_absent_own_channel_or_notification_is_refused_before_writing(self):
        self.client.list.return_value = []
        self.responses()
        with self.assertRaisesRegex(CanvasError, 'own-channel inventory'):
            change(self.client, '19', {'new_announcement': 'weekly'})
        self.client.request.assert_called_once_with('/api/v1/users/self/profile')
        self.client.list.return_value = [self.channel]
        self.responses()
        with self.assertRaisesRegex(CanvasError, 'not reported'):
            change(self.client, '19', {'unknown_notice': 'never'})
        self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))

    def test_exact_batch_preview_hides_addresses_and_acknowledges_only_selected_changes(self):
        changes = {'new_announcement': 'immediately', 'submission_comment': 'weekly'}
        preview = change(self.client, '19', changes, max_pages=3)
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['body'], {'notification_preferences': {
            'new_announcement': {'frequency': 'immediately'}, 'submission_comment': {'frequency': 'weekly'}}})
        self.assertEqual(set(preview['current_preferences']), set(changes))
        self.assertIn('partially apply', preview['warning'])
        self.assertNotIn('synthetic@example.edu', str(preview))
        accepted = {'notification_preferences': [{**row, 'frequency': changes[row['notification']]}
                    for row in self.prefs['notification_preferences'] if row['notification'] in changes]}
        self.responses()
        self.client.request.side_effect = [({'id': 7}, ''), (self.prefs, ''), (accepted, '')]
        result = change(self.client, '19', changes, yes=True, confirm=preview['confirm'])
        self.assertTrue(result['acknowledged'])
        self.assertEqual(len(result['notification_changes']), 2)
        self.client.request.assert_called_with(preview['route'], 'PUT', preview['body'])

    def test_account_origin_channel_identity_address_state_or_preference_change_invalidates(self):
        changes = {'new_announcement': 'weekly'}
        preview = change(self.client, '19', changes)
        original = deepcopy(self.prefs)
        for field, value in (('frequency', 'never'), ('category', 'other_category')):
            self.prefs = deepcopy(original)
            self.prefs['notification_preferences'][0][field] = value
            self.responses()
            with self.assertRaisesRegex(CanvasError, 'Preview changed'):
                change(self.client, '19', changes, yes=True, confirm=preview['confirm'])
        self.prefs = original
        for field, value in (('address', 'another@example.edu'), ('workflow_state', 'unconfirmed'), ('type', 'sms')):
            old = self.channel[field]
            self.channel[field] = value
            self.responses()
            with self.assertRaisesRegex(CanvasError, 'Preview changed'):
                change(self.client, '19', changes, yes=True, confirm=preview['confirm'])
            self.channel[field] = old
        self.client.list.return_value = [{**self.channel, 'user_id': 8}]
        self.responses(profile={'id': 8})
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            change(self.client, '19', changes, yes=True, confirm=preview['confirm'])
        self.client.list.return_value = [self.channel]
        self.client.host = 'https://other.example.edu'
        self.responses()
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            change(self.client, '19', changes, yes=True, confirm=preview['confirm'])
        self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))

    def test_unselected_preferences_do_not_invalidate_an_exact_partial_update(self):
        preview = change(self.client, '19', {'new_announcement': 'weekly'})
        self.prefs['notification_preferences'][1]['frequency'] = 'daily'
        self.responses()
        self.assertEqual(change(self.client, '19', {'new_announcement': 'weekly'})['confirm'], preview['confirm'])

    def test_ambiguous_acknowledgements_are_never_retried_or_dumped(self):
        changes = {'new_announcement': 'weekly'}
        preview = change(self.client, '19', changes)
        for response in (None, [], {}, {'notification_preferences': []},
                         {'notification_preferences': self.prefs['notification_preferences']},
                         {'notification_preferences': [{'notification': 'new_announcement', 'frequency': 'daily'}]},
                         {'notification_preferences': [{'notification': 'new_announcement', 'frequency': 'weekly',
                                                        'category': 'different', 'body': 'private unexpected body'}]}):
            self.client.request.reset_mock()
            self.client.request.side_effect = [({'id': 7}, ''), (self.prefs, ''), (response, '')]
            with self.subTest(response=response), self.assertRaisesRegex(CanvasError, 'partially applied') as error:
                change(self.client, '19', changes, yes=True, confirm=preview['confirm'])
            self.assertNotIn('private unexpected body', str(error.exception))
            self.assertEqual(self.client.request.call_count, 3)
        self.client.request.reset_mock()
        self.client.request.side_effect = [({'id': 7}, ''), (self.prefs, ''), CanvasError('Denied', status=403)]
        with self.assertRaises(CanvasError) as error:
            change(self.client, '19', changes, yes=True, confirm=preview['confirm'])
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(self.client.request.call_count, 3)


if __name__ == '__main__':
    unittest.main()
