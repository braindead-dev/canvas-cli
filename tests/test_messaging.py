import unittest
from unittest.mock import Mock

from canvas_pocket.client import CanvasError
from canvas_pocket.messaging import compose, recipients


class MessagingTests(unittest.TestCase):
    def test_search_encodes_course_and_user_only(self):
        client = Mock(host='https://canvas.example.edu')
        client.list.return_value = []
        recipients(client, 20, search='Jane Doe', course_id='3')
        client.list.assert_called_with(
            '/api/v1/search/recipients?type=user&per_page=100&search=Jane+Doe&context=course_3', 20)
        recipients(client, 20, user_id='7')
        client.list.assert_called_with(
            '/api/v1/search/recipients?type=user&per_page=100&user_id=7', 20)
        with self.assertRaises(CanvasError):
            recipients(client, 20, user_id='7', course_id='3')

    def test_compose_preview_requires_confirmed_individual(self):
        client = Mock(host='https://canvas.example.edu')
        client.request.return_value = ({'id': 1}, '')
        client.list.return_value = [{'id': 7, 'name': 'Synthetic recipient', 'type': 'user'}]
        preview = compose(client, 100, '7', 'Question', 'Hello', '3')
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['body'], {'recipients': ['7'], 'subject': 'Question',
                                           'body': 'Hello', 'context_code': 'course_3'})
        client.request.assert_called_once_with('/api/v1/users/self/profile')
        with self.assertRaisesRegex(CanvasError, 'both --yes and --confirm'):
            compose(client, 100, '7', 'Question', 'Hello', yes=True)
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            compose(client, 100, '7', 'Question', 'Changed', '3',
                    yes=True, confirm=preview['confirm'])
        self.assertTrue(all(len(call.args) == 1 for call in client.request.call_args_list))
        client.request.side_effect = [({'id': 1}, ''), ([{'id': 55}], '')]
        result = compose(client, 100, '7', 'Question', 'Hello', '3',
                         yes=True, confirm=preview['confirm'])
        self.assertEqual(result[0]['id'], 55)
        client.request.assert_called_with('/api/v1/conversations', 'POST', preview['body'])

    def test_composition_account_change_refuses_to_send(self):
        client = Mock(host='https://canvas.example.edu')
        client.list.return_value = [{'id': 7, 'name': 'Synthetic recipient', 'type': 'user'}]
        client.request.return_value = ({'id': 1}, '')
        preview = compose(client, 100, '7', 'Question', 'Synthetic')
        client.request.reset_mock()
        client.request.return_value = ({'id': 2}, '')
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            compose(client, 100, '7', 'Question', 'Synthetic', yes=True, confirm=preview['confirm'])
        client.request.assert_called_once_with('/api/v1/users/self/profile')

    def test_compose_refuses_unresolved_or_broadcast_recipient(self):
        client = Mock()
        for people in ([], [{'id': 'course_7', 'type': 'context'}],
                       [{'id': 8, 'name': 'Wrong user'}]):
            with self.subTest(people=people):
                client.list.return_value = people
                with self.assertRaises(CanvasError):
                    compose(client, 100, '7', 'Question', 'Hello')
        client.request.assert_not_called()

    def test_compose_rejects_known_wrong_course_context(self):
        client = Mock()
        client.list.return_value = [{'id': 7, 'type': 'user',
                                     'common_courses': {'8': ['StudentEnrollment']}}]
        with self.assertRaisesRegex(CanvasError, 'sharing that course'):
            compose(client, 100, '7', 'Question', 'Hello', course_id='3')
        client.request.assert_not_called()


if __name__ == '__main__': unittest.main()
