import unittest
from unittest.mock import Mock

from canvas_pocket.client import CanvasError
from canvas_pocket.preferences import (
    change_color,
    change_nickname,
    color,
    colors,
    nickname,
    nicknames,
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
