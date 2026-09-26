import unittest
from unittest.mock import Mock

from canvas_pocket.client import CanvasError
from canvas_pocket.discussion import post


class DiscussionTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.topic = {'id': 8, 'context_id': 7, 'title': 'Synthetic prompt',
                      'published': True, 'locked': False, 'locked_for_user': False}
        self.client.request.return_value = (self.topic, '')

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
        self.client.request.assert_called_once_with('/api/v1/courses/7/discussion_topics/8')

    def test_locked_or_mismatched_topic_rejected(self):
        for change in ({'id': 9}, {'context_id': 6}, {'locked': True},
                       {'locked_for_user': True}, {'published': False},
                       {'workflow_state': 'unpublished'}):
            self.client.request.return_value = ({**self.topic, **change}, '')
            with self.assertRaises(CanvasError):
                post(self.client, '7', '8', None, 'hello')
