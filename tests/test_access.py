import unittest
from unittest.mock import Mock

from canvas_pocket.access import query, read
from canvas_pocket.client import CanvasError


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')

    def test_exact_course_rights_are_encoded_and_not_an_admin_claim(self):
        self.client.request.side_effect = [({'id': 101, 'name': 'Synthetic course'}, ''),
                                           ({'read_roster': True, 'send_messages': False, 'private': 'synthetic-private'}, '')]
        result = read(self.client, '101', names=['send_messages', 'read_roster'])
        self.client.request.assert_called_with('/api/v1/courses/101/permissions?permissions%5B%5D=read_roster&permissions%5B%5D=send_messages')
        self.assertEqual(result['permissions'], {'read_roster': True, 'send_messages': False})
        self.assertNotIn('synthetic-private', str(result))
        self.assertIn('unsupported', result['note'])
        self.assertIn('No permission', result['note'])

    def test_group_rights_use_group_namespace_and_are_not_course_aliases(self):
        self.client.request.side_effect = [({'id': 11, 'name': 'Synthetic group'}, ''), ({'join': True}, '')]
        result = read(self.client, '11', 'group', names=['join'])
        self.assertEqual(result['group_id'], 11)
        self.client.request.assert_called_with('/api/v1/groups/11/permissions?permissions%5B%5D=join')
        self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))

    def test_bad_names_and_contexts_fail_before_network(self):
        for names in ([], ['join', 'join'], ['../join'], ['Join'], ['join&as_user_id=8'], ['join\n'],
                      [True], ['a' + str(index) for index in range(51)], 'join'):
            with self.subTest(names=names), self.assertRaises(CanvasError):
                read(self.client, '11', 'group', names=names)
        with self.assertRaises(CanvasError):
            read(self.client, '11', 'account', names=['join'])
        with self.assertRaises(CanvasError):
            read(self.client, '../11', 'group', names=['join'])
        self.client.request.assert_not_called()

    def test_missing_nonboolean_and_paginated_rights_are_not_false_success(self):
        for data, links in (({}, ''), ({'join': 'true'}, ''), ({'join': 1}, ''), ([], ''),
                            ({'join': True}, '</api/v1/groups/11/permissions?page=2>; rel="next"')):
            self.client.request.return_value = (data, links)
            with self.subTest(data=data, links=links), self.assertRaisesRegex(CanvasError, 'explicit booleans'):
                query(self.client, '/api/v1/groups/11', ['join'])

    def test_foreign_context_and_api_denials_are_errors_without_fallback(self):
        self.client.request.return_value = ({'id': 12}, '')
        with self.assertRaisesRegex(CanvasError, 'different content context'):
            read(self.client, '11', 'group', names=['join'])
        self.client.request.reset_mock()
        for status in (401, 403, 404, 429):
            self.client.request.side_effect = CanvasError('Synthetic denied', status)
            with self.subTest(status=status), self.assertRaises(CanvasError) as error:
                read(self.client, '11', 'group', names=['join'])
            self.assertEqual(error.exception.status, status)
        self.assertEqual(self.client.request.call_count, 4)


if __name__ == '__main__':
    unittest.main()
