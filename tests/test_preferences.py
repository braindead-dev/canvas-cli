import unittest
from unittest.mock import Mock

from canvas_cli.client import CanvasError
from canvas_cli.preferences import (
    change_color,
    change_nickname,
    change_positions,
    change_settings,
    color,
    colors,
    nickname,
    nicknames,
    ordered_positions,
    positions,
    setting_pairs,
    settings,
)


class PreferencesTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.record = {'course_id': 101, 'name': 'Synthetic course', 'nickname': 'Old nickname'}
        self.target = {'id': 101, 'name': 'Synthetic course'}
        self.color_map = {'custom_colors': {'course_101': '#aBc', 'group_11': '#123456'}}
        self.client.list.return_value = [self.record]

    def nickname_preview(self, **kwargs):
        self.client.request.side_effect = [({'id': 7}, ''), (self.record, '')]
        return change_nickname(self.client, '101', **kwargs)

    def color_preview(self, context='course', item='101', value='ABC'):
        responses = [({'id': 7}, '')]
        if context != 'user':
            responses.append(({**self.target, 'id': int(item)}, ''))
        responses.append((self.color_map, ''))
        self.client.request.side_effect = responses
        return change_color(self.client, item, value, context_type=context)

    def test_nickname_reads_paginate_and_validate_identity_and_missing_fields(self):
        self.assertEqual(nicknames(self.client, 2), [self.record])
        self.client.list.assert_called_with('/api/v1/users/self/course_nicknames?per_page=100', 2)
        self.client.request.return_value = (self.record, '')
        self.assertEqual(nickname(self.client, '101'), self.record)
        self.client.request.assert_called_with('/api/v1/users/self/course_nicknames/101')
        for record in ({**self.record, 'course_id': 102}, {**self.record, 'course_id': True},
                       {**self.record, 'nickname': False}, {'course_id': 101, 'name': 'Missing nickname'}, []):
            with self.subTest(record=record), self.assertRaises(CanvasError):
                self.client.request.return_value = (record, '')
                nickname(self.client, '101')
        self.client.list.return_value = [self.record, self.record]
        with self.assertRaisesRegex(CanvasError, 'duplicate'):
            nicknames(self.client)

    def test_nickname_preview_binds_actual_name_current_preference_and_one_field(self):
        preview = self.nickname_preview(name='  New nickname 🌿  ')
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['current'], self.record)
        self.assertEqual(preview['body'], {'nickname': 'New nickname 🌿'})
        self.assertEqual(preview['method'], 'PUT')
        self.assertEqual(preview['route'], '/api/v1/users/self/course_nicknames/101')
        self.assertIn('API responses', preview['warning'])
        self.assertEqual(self.client.request.call_count, 2)

    def test_set_clear_and_reset_use_native_acknowledgements_without_retry(self):
        for options, method, result in (({'name': 'New'}, 'PUT', {**self.record, 'nickname': 'New'}),
                                        ({'clear': True}, 'DELETE', {**self.record, 'nickname': None})):
            preview = self.nickname_preview(**options)
            self.client.request.reset_mock()
            self.client.request.side_effect = [({'id': 7}, ''), (self.record, ''), (result, '')]
            written = change_nickname(self.client, '101', **options, yes=True, confirm=preview['confirm'])
            self.assertTrue(written['acknowledged'])
            self.assertEqual(written['nickname_change'], result)
            self.assertEqual(self.client.request.call_count, 3)
            self.client.request.assert_called_with(preview['route'], method, preview['body'])
        self.client.request.side_effect = [({'id': 7}, '')]
        reset = change_nickname(self.client, reset=True, max_pages=2)
        self.assertIn('ALL', reset['effect'])
        self.client.request.side_effect = [({'id': 7}, ''), ({'message': 'OK'}, '')]
        self.assertTrue(change_nickname(self.client, reset=True, max_pages=2,
                                       yes=True, confirm=reset['confirm'])['reset_all'])
        self.client.request.assert_called_with('/api/v1/users/self/course_nicknames', 'DELETE', None)

    def test_nickname_state_account_site_or_reset_inventory_change_invalidates_preview(self):
        preview = self.nickname_preview(name='New')
        for profile, record, host in (({'id': 8}, self.record, self.client.host),
                                      ({'id': 7}, {**self.record, 'nickname': 'Changed'}, self.client.host),
                                      ({'id': 7}, {**self.record, 'name': 'Renamed course'}, self.client.host),
                                      ({'id': 7}, self.record, 'https://other.example.edu')):
            self.client.host = host
            self.client.request.reset_mock()
            self.client.request.side_effect = [(profile, ''), (record, '')]
            with self.assertRaisesRegex(CanvasError, 'Preview changed'):
                change_nickname(self.client, '101', 'New', yes=True, confirm=preview['confirm'])
            self.assertEqual(self.client.request.call_count, 2)
        self.client.request.side_effect = [({'id': 7}, '')]
        reset = change_nickname(self.client, reset=True)
        self.client.list.return_value = []
        self.client.request.reset_mock()
        self.client.request.side_effect = [({'id': 7}, '')]
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            change_nickname(self.client, reset=True, yes=True, confirm=reset['confirm'])
        self.assertEqual(self.client.request.call_count, 1)

    def test_missing_nickname_cannot_be_cleared_or_falsely_acknowledged(self):
        self.record['nickname'] = None
        with self.assertRaisesRegex(CanvasError, 'nothing to remove'):
            self.nickname_preview(clear=True)
        self.record['nickname'] = 'Old nickname'
        preview = self.nickname_preview(clear=True)
        self.client.request.side_effect = [({'id': 7}, ''), (self.record, ''),
                                          ({'course_id': 101, 'name': 'Synthetic course'}, '')]
        with self.assertRaisesRegex(CanvasError, 'verify Canvas'):
            change_nickname(self.client, '101', clear=True, yes=True, confirm=preview['confirm'])

    def test_bad_nickname_values_and_flag_combinations_fail_before_network(self):
        for name in ('', '  ', 'x' * 60, 'has\nnewline', 'has\x00null', 'has\x7fdelete', None):
            with self.subTest(name=name), self.assertRaises(CanvasError):
                change_nickname(self.client, '101', name)
        for options in ({'course_id': '01', 'name': 'A'}, {'course_id': '١', 'name': 'A'},
                        {'course_id': '0', 'clear': True}, {'course_id': '101', 'reset': True},
                        {'reset': True, 'name': 'A'}, {'reset': True, 'clear': True},
                        {'course_id': '101', 'name': 'A', 'clear': True}, {'reset': True, 'yes': True}):
            with self.subTest(options=options), self.assertRaises(CanvasError):
                change_nickname(self.client, **options)
        self.client.request.assert_not_called()
        self.client.list.assert_not_called()
        self.assertEqual(self.nickname_preview(name='x' * 59)['body'], {'nickname': 'x' * 59})

    def test_invalid_nickname_acknowledgements_are_not_retried_or_dumped(self):
        preview = self.nickname_preview(name='New')
        for response in (None, [], {'message': 'OK'}, {**self.record, 'nickname': 'Different'},
                         {**self.record, 'course_id': 102, 'private': 'never print this'}):
            self.client.request.reset_mock()
            self.client.request.side_effect = [({'id': 7}, ''), (self.record, ''), (response, '')]
            with self.assertRaisesRegex(CanvasError, 'verify Canvas') as error:
                change_nickname(self.client, '101', 'New', yes=True, confirm=preview['confirm'])
            self.assertEqual(self.client.request.call_count, 3)
            self.assertNotIn('never print this', str(error.exception))
        self.client.request.side_effect = [({'id': 7}, '')]
        reset = change_nickname(self.client, reset=True)
        self.client.request.side_effect = [({'id': 7}, ''), ({'status': 'ok'}, '')]
        with self.assertRaisesRegex(CanvasError, 'verify Canvas'):
            change_nickname(self.client, reset=True, yes=True, confirm=reset['confirm'])

    def test_color_reads_report_saved_preferences_not_unknown_ui_defaults(self):
        self.client.request.return_value = (self.color_map, '')
        self.assertEqual(colors(self.client), self.color_map)
        self.assertEqual(color(self.client, '101')['hexcode'], '#aBc')
        self.assertIsNone(color(self.client, '102')['hexcode'])
        self.assertIn('default UI color', color(self.client, '7', 'user')['note'])
        for result in ([], {}, {'custom_colors': []}, {'custom_colors': {'course_1': None}},
                       {'custom_colors': {'course_1': 'red'}}):
            self.client.request.return_value = (result, '')
            with self.assertRaises(CanvasError):
                colors(self.client)

    def test_course_group_and_own_calendar_color_changes_have_one_exact_field(self):
        for context, item in (('course', '101'), ('group', '11'), ('user', '7')):
            preview = self.color_preview(context, item, '#ABC')
            self.assertEqual(preview['body'], {'hexcode': '#abc'})
            self.assertEqual(preview['route'], f'/api/v1/users/self/colors/{context}_{item}')
            self.client.request.reset_mock()
            responses = [({'id': 7}, '')]
            if context != 'user':
                responses.append(({**self.target, 'id': int(item)}, ''))
            responses += [(self.color_map, ''), ({'hexcode': '#ABC'}, '')]
            self.client.request.side_effect = responses
            result = change_color(self.client, item, '#ABC', context_type=context,
                                  yes=True, confirm=preview['confirm'])
            self.assertTrue(result['acknowledged'])
            self.client.request.assert_called_with(preview['route'], 'PUT', {'hexcode': '#abc'})
            self.assertEqual(self.client.request.call_count, 3 if context == 'user' else 4)

    def test_color_changes_refuse_other_users_wrong_contexts_or_changed_preferences(self):
        self.client.request.side_effect = [({'id': 7}, '')]
        with self.assertRaisesRegex(CanvasError, 'own personal calendar'):
            change_color(self.client, '8', '#abc', context_type='user')
        self.client.request.side_effect = [({'id': 7}, ''), ({'id': 102}, '')]
        with self.assertRaisesRegex(CanvasError, 'different color destination'):
            change_color(self.client, '101', '#abc')
        preview = self.color_preview()
        self.client.request.side_effect = [({'id': 7}, ''), (self.target, ''),
                                          ({'custom_colors': {'course_101': '#def'}}, '')]
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            change_color(self.client, '101', 'ABC', yes=True, confirm=preview['confirm'])

    def test_bad_hex_inputs_fail_early_and_bad_acknowledgements_never_retry(self):
        for value in (None, '', 'blue', '#abcd', '00112233', '#12', '#12g', '#abc\n', ' #abc'):
            with self.subTest(value=value), self.assertRaises(CanvasError):
                change_color(self.client, '101', value)
        self.client.request.assert_not_called()
        for value in ('ABC', '#aBc', 'AABBCC', '#aAbbCC'):
            preview = self.color_preview(value=value)
            self.assertEqual(preview['body']['hexcode'], '#' + value.lstrip('#').lower())
        preview = self.color_preview()
        for response in (None, [], {}, {'hexcode': '#def'}, {'hexcode': 'private response body'}):
            self.client.request.reset_mock()
            self.client.request.side_effect = [({'id': 7}, ''), (self.target, ''), (self.color_map, ''), (response, '')]
            with self.assertRaisesRegex(CanvasError, 'verify Canvas') as error:
                change_color(self.client, '101', 'ABC', yes=True, confirm=preview['confirm'])
            self.assertEqual(self.client.request.call_count, 4)
            self.assertNotIn('private response body', str(error.exception))

    def test_settings_reads_filter_unknown_fields_and_never_request_mobile_keys(self):
        self.client.request.return_value = ({'manual_mark_as_read': False, 'collapse_global_nav': True,
                                             'pendo_mobile_api_key': 'not for output', 'unknown_future_option': False}, '')
        result = settings(self.client)
        self.assertEqual(result['settings'], {'manual_mark_as_read': False, 'collapse_global_nav': True})
        self.assertIn('widget_dashboard_dark_mode', result['unreported_keys'])
        self.assertNotIn('not for output', str(result))
        self.client.request.assert_called_once_with('/api/v1/users/self/settings')
        for record in ([], {'manual_mark_as_read': 1}, {'manual_mark_as_read': 'true'}):
            self.client.request.return_value = (record, '')
            with self.assertRaises(CanvasError):
                settings(self.client)

    def test_settings_options_are_exact_unique_booleans_before_network(self):
        self.assertEqual(setting_pairs(['manual_mark_as_read=true', 'collapse_global_nav=false']),
                         {'manual_mark_as_read': True, 'collapse_global_nav': False})
        for values in (['email=true'], ['manual_mark_as_read=TRUE'], ['manual_mark_as_read=1'],
                       ['manual_mark_as_read'], ['manual_mark_as_read=true=false'],
                       ['manual_mark_as_read=true', 'manual_mark_as_read=false'], [None]):
            with self.subTest(values=values), self.assertRaises(CanvasError):
                setting_pairs(values)
        for changes in ({}, [], {'manual_mark_as_read': 1}, {'time_zone': 'Example'}, {'unknown': True}):
            with self.subTest(changes=changes), self.assertRaises(CanvasError):
                change_settings(self.client, changes)
        self.client.request.assert_not_called()

    def test_settings_set_sends_only_requested_fields_and_binds_current_state(self):
        state = {'manual_mark_as_read': False, 'collapse_global_nav': True}
        change = {'manual_mark_as_read': True}
        self.client.request.side_effect = [({'id': 7}, ''), (state, '')]
        preview = change_settings(self.client, change)
        self.assertEqual(preview['body'], change)
        self.assertEqual(self.client.request.call_count, 2)
        self.client.request.side_effect = [({'id': 7}, ''), (state, ''), ({**state, **change}, '')]
        result = change_settings(self.client, change, yes=True, confirm=preview['confirm'])
        self.assertTrue(result['acknowledged'])
        self.client.request.assert_called_with('/api/v1/users/self/settings', 'PUT', change)
        self.client.request.reset_mock()
        self.client.request.side_effect = [({'id': 7}, ''), ({**state, 'collapse_global_nav': False}, '')]
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            change_settings(self.client, change, yes=True, confirm=preview['confirm'])
        self.assertEqual(self.client.request.call_count, 2)

    def test_settings_refuse_unreported_or_unacknowledged_values_without_retry(self):
        state = {'manual_mark_as_read': False}
        self.client.request.side_effect = [({'id': 7}, ''), (state, '')]
        with self.assertRaisesRegex(CanvasError, 'not reported'):
            change_settings(self.client, {'collapse_global_nav': True})
        self.client.request.side_effect = [({'id': 7}, ''), (state, '')]
        preview = change_settings(self.client, {'manual_mark_as_read': True})
        for response in (None, [], {}, state, {'manual_mark_as_read': 1}):
            self.client.request.reset_mock()
            self.client.request.side_effect = [({'id': 7}, ''), (state, ''), (response, '')]
            with self.assertRaisesRegex(CanvasError, 'verify Canvas'):
                change_settings(self.client, {'manual_mark_as_read': True}, yes=True, confirm=preview['confirm'])
            self.assertEqual(self.client.request.call_count, 3)

    def test_dashboard_reads_preserve_native_values_without_claiming_visible_cards(self):
        record = {'dashboard_positions': {'course_101': '01', 'group_11': -2}}
        self.client.request.return_value = (record, '')
        self.assertEqual(positions(self.client), record)
        self.client.request.assert_called_with('/api/v1/users/self/dashboard_positions')
        for record in ([], {}, {'dashboard_positions': []}, {'dashboard_positions': {'course_1': True}},
                       {'dashboard_positions': {'course_1': 1001}}, {'dashboard_positions': {'course_1': 'abc'}}):
            self.client.request.return_value = (record, '')
            with self.assertRaises(CanvasError):
                positions(self.client)

    def test_ordering_inputs_are_unique_and_never_guess_contexts(self):
        self.assertEqual(ordered_positions(['course_101', 'group_11', 'user_7']),
                         {'course_101': 0, 'group_11': 1, 'user_7': 2})
        for assets in ([], ['course_101', 'course_101'], ['101'], ['course_01'], ['course_0'],
                       ['account_1'], ['course_١'], 'course_101'):
            with self.subTest(assets=assets), self.assertRaises(CanvasError):
                ordered_positions(assets)
        for changes in ({}, [], {'course_101': True}, {'course_101': 1.0}, {'course_101': 1001},
                        {'group_11': -1001}, {'account_1': 0}, {'course_01': 0}):
            with self.subTest(changes=changes), self.assertRaises(CanvasError):
                change_positions(self.client, changes)
        self.client.request.assert_not_called()

    def test_position_merge_preserves_unspecified_values_and_all_destination_identities(self):
        current = {'dashboard_positions': {'course_102': '9', 'course_101': 2}}
        change = {'course_101': -1, 'group_11': 0, 'user_7': 1}
        reads = [({'id': 7}, ''), (self.target, ''), ({'id': 11, 'name': 'Synthetic group'}, ''), (current, '')]
        self.client.request.side_effect = reads
        preview = change_positions(self.client, change)
        self.assertEqual(preview['body'], {'dashboard_positions': change})
        self.assertEqual(len(preview['targets']), 3)
        self.assertIn('Unspecified', preview['warning'])
        self.assertEqual(self.client.request.call_count, 4)
        self.client.request.reset_mock()
        self.client.request.side_effect = [*reads, ({'dashboard_positions': {**current['dashboard_positions'], **change}}, '')]
        result = change_positions(self.client, change, yes=True, confirm=preview['confirm'])
        self.assertTrue(result['acknowledged'])
        self.assertEqual(self.client.request.call_count, 5)
        self.client.request.assert_called_with('/api/v1/users/self/dashboard_positions', 'PUT',
                                              {'dashboard_positions': change})

    def test_positions_refuse_other_users_different_targets_and_changed_order(self):
        self.client.request.side_effect = [({'id': 7}, '')]
        with self.assertRaisesRegex(CanvasError, 'own user ID'):
            change_positions(self.client, {'user_8': 0})
        self.client.request.side_effect = [({'id': 7}, ''), ({'id': 102}, '')]
        with self.assertRaisesRegex(CanvasError, 'different dashboard destination'):
            change_positions(self.client, {'course_101': 0})
        current = {'dashboard_positions': {'course_101': 1}}
        reads = [({'id': 7}, ''), (self.target, ''), (current, '')]
        self.client.request.side_effect = reads
        preview = change_positions(self.client, {'course_101': 0})
        self.client.request.reset_mock()
        self.client.request.side_effect = [*reads[:2], ({'dashboard_positions': {'course_101': 2}}, '')]
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            change_positions(self.client, {'course_101': 0}, yes=True, confirm=preview['confirm'])
        self.assertEqual(self.client.request.call_count, 3)
        for response in ({}, {'dashboard_positions': {}}, {'dashboard_positions': {'course_101': 1}},
                         {'dashboard_positions': {'course_101': False}}):
            self.client.request.reset_mock()
            self.client.request.side_effect = [*reads, (response, '')]
            with self.assertRaisesRegex(CanvasError, 'verify Canvas'):
                change_positions(self.client, {'course_101': 0}, yes=True, confirm=preview['confirm'])
            self.assertEqual(self.client.request.call_count, 4)
