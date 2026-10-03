import unittest
from unittest.mock import Mock

from canvas_cli.cli import brief
from canvas_cli.client import CanvasError
from canvas_cli.thread import read_thread


class ThreadTests(unittest.TestCase):
    def test_uses_recent_replies_only_when_complete_and_fetches_rest_when_needed(self):
        client = Mock()
        client.request.return_value = ({'id': 9, 'context_id': 8, 'title': 'Introductions',
                                        'published': True, 'message': '<p>Say hello</p>'}, '')

        def listing(route, _max_pages):
            if route.endswith('/entries?per_page=100'):
                return [{'id': 1, 'user_name': 'Ada', 'message': 'Hello',
                         'recent_replies': [{'id': 10, 'message': 'Hi'}],
                         'has_more_replies': False},
                        {'id': 2, 'user_name': 'Lin', 'message': 'World',
                         'recent_replies': [{'id': 20, 'message': 'Recent'}],
                         'has_more_replies': True}]
            if route.endswith('/entries/2/replies?per_page=100'):
                return [{'id': 20, 'message': 'Recent'}, {'id': 19, 'message': 'Older'}]
            raise AssertionError(route)

        client.list.side_effect = listing
        data = read_thread(client, '8', '9', 100)
        self.assertTrue(data['complete'])
        self.assertEqual([item['id'] for item in data['entries'][0]['replies']], [10])
        self.assertEqual([item['id'] for item in data['entries'][1]['replies']], [20, 19])
        self.assertEqual(client.list.call_count, 2)
        self.assertIn('2 top-level entry(s)', brief(data))

    def test_respects_post_first_restriction_before_entries_request(self):
        client = Mock()
        client.request.return_value = ({'id': 9, 'context_id': 8, 'published': True,
                                        'require_initial_post': True,
                                        'user_can_see_posts': False}, '')
        with self.assertRaisesRegex(CanvasError, 'initial post'):
            read_thread(client, '8', '9', 100)
        client.list.assert_not_called()

    def test_refuses_locked_topic_before_entries_request(self):
        client = Mock()
        client.request.return_value = ({'id': 9, 'context_id': 8, 'published': True,
                                        'locked_for_user': True}, '')
        with self.assertRaisesRegex(CanvasError, 'locked'):
            read_thread(client, '8', '9', 100)
        client.list.assert_not_called()

    def test_refuses_unpublished_workflow_before_entries_request(self):
        client = Mock()
        client.request.return_value = ({'id': 9, 'context_id': 8,
                                        'workflow_state': 'unpublished'}, '')
        with self.assertRaisesRegex(CanvasError, 'unpublished'):
            read_thread(client, '8', '9', 100)
        client.list.assert_not_called()

    def test_denied_replies_leave_partial_result_without_retrying(self):
        client = Mock()
        client.request.return_value = ({'id': 9, 'context_id': 8, 'published': True}, '')

        def listing(route, _max_pages):
            if route.endswith('/entries?per_page=100'):
                return [{'id': 2, 'recent_replies': [{'id': 20}], 'has_more_replies': True}]
            raise CanvasError('denied', status=403)

        client.list.side_effect = listing
        data = read_thread(client, '8', '9', 100)
        self.assertFalse(data['complete'])
        self.assertEqual(data['entries'][0]['replies'], [{'id': 20}])
        self.assertEqual(data['unavailable'], [{'entry_id': 2, 'status': 403}])

    def test_rate_limit_is_not_hidden(self):
        client = Mock()
        client.request.return_value = ({'id': 9, 'context_id': 8, 'published': True}, '')
        client.list.side_effect = CanvasError('rate limit', status=429)
        with self.assertRaises(CanvasError):
            read_thread(client, '8', '9', 100)


if __name__ == '__main__':
    unittest.main()
