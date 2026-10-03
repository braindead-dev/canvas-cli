import unittest
from unittest.mock import Mock

from canvas_cli.client import CanvasError
from canvas_cli.discussion import post


class DiscussionTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.profile = {'id': 7}
        self.topic = {'id': 8, 'context_id': 7, 'title': 'Synthetic prompt',
                      'published': True, 'locked': False, 'locked_for_user': False}
        self.client.request.return_value = (self.topic, '')
        self.client.request.side_effect = lambda route, *args: (
            (self.profile, '') if route == '/api/v1/users/self/profile'
            else self.client.request.return_value)

    def test_topic_and_text_bound_to_preview(self):
        preview = post(self.client, '7', '8', None, '<script>hello</script>')
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['body']['message'],
                         '<p>&lt;script&gt;hello&lt;/script&gt;</p>')
        with self.assertRaisesRegex(CanvasError, 'both --yes and --confirm'):
            post(self.client, '7', '8', None, 'hello', yes=True)
        self.client.request.reset_mock()
        self.client.request.return_value = ({**self.topic, 'title': 'Changed prompt'}, '')
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            post(self.client, '7', '8', None, '<script>hello</script>',
                 yes=True, confirm=preview['confirm'])
        self.assertEqual(self.client.request.call_count, 2)
        self.client.request.assert_called_with('/api/v1/courses/7/discussion_topics/8')

    def test_locked_or_mismatched_topic_rejected(self):
        for change in ({'id': 9}, {'context_id': 6}, {'locked': True},
                       {'locked_for_user': True}, {'published': False},
                       {'workflow_state': 'unpublished'}):
            self.client.request.return_value = ({**self.topic, **change}, '')
            with self.assertRaises(CanvasError):
                post(self.client, '7', '8', None, 'hello')

    def test_account_or_origin_switch_requires_new_preview(self):
        preview = post(self.client, '7', '8', None, 'Synthetic')
        for user_id, host in [(99, self.client.host), (7, 'https://other.example.edu')]:
            self.profile['id'] = user_id
            self.client.host = host
            self.client.request.reset_mock()
            with self.assertRaisesRegex(CanvasError, 'Preview changed'):
                post(self.client, '7', '8', None, 'Synthetic', yes=True, confirm=preview['confirm'])
            self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))
