import unittest
from unittest.mock import Mock

from canvas_pocket.client import CanvasError
from canvas_pocket.contexts import discussion_base, read_topic
from canvas_pocket.discussion import post
from canvas_pocket.thread import read_thread


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.topic = {'id': 9, 'context_id': 8, 'context_type': 'Group',
                      'title': 'Synthetic group discussion', 'published': True}

    def test_group_topic_and_full_thread_use_group_namespace(self):
        self.client.request.return_value = (self.topic, '')
        self.client.list.side_effect = [
            [{'id': 31, 'message': 'Synthetic entry', 'has_more_replies': True}],
            [{'id': 32, 'message': 'Synthetic reply'}]]
        result = read_thread(self.client, '8', '9', 4, context_type='group')
        self.assertEqual(result['group_id'], 8)
        self.assertNotIn('course_id', result)
        self.assertEqual(result['entries'][0]['replies'][0]['id'], 32)
        self.client.request.assert_called_once_with('/api/v1/groups/8/discussion_topics/9')
        self.assertEqual([call.args[0] for call in self.client.list.call_args_list],
                         ['/api/v1/groups/8/discussion_topics/9/entries?per_page=100',
                          '/api/v1/groups/8/discussion_topics/9/entries/31/replies?per_page=100'])

    def test_group_post_previews_exact_context_and_confirmed_account(self):
        self.client.request.side_effect = [({'id': 7}, ''), (self.topic, '')]
        preview = post(self.client, '8', '9', None, 'Synthetic <message>', context_type='group')
        self.assertEqual(preview['group_id'], '8')
        self.assertEqual(preview['context_type'], 'group')
        self.assertNotIn('course_id', preview)
        self.assertEqual(preview['route'], '/api/v1/groups/8/discussion_topics/9/entries')
        self.client.request.side_effect = [({'id': 7}, ''), (self.topic, ''), ({'id': 31}, '')]
        post(self.client, '8', '9', None, 'Synthetic <message>', context_type='group',
             yes=True, confirm=preview['confirm'])
        self.client.request.assert_called_with('/api/v1/groups/8/discussion_topics/9/entries', 'POST', preview['body'])

    def test_namespace_switch_and_topic_context_mismatch_are_refused(self):
        unknown_type = {**self.topic, 'context_type': None}
        self.client.request.side_effect = [({'id': 7}, ''), (unknown_type, '')]
        preview = post(self.client, '8', '9', None, 'Synthetic', context_type='group')
        self.client.request.reset_mock()
        self.client.request.side_effect = [({'id': 7}, ''), (unknown_type, '')]
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            post(self.client, '8', '9', None, 'Synthetic', yes=True, confirm=preview['confirm'])
        self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))
        self.client.request.side_effect = None
        for fields in ({'context_type': 'Course'}, {'context_id': 7}, {'id': True}, {'id': 10}):
            self.client.request.return_value = ({**self.topic, **fields}, '')
            with self.subTest(fields=fields), self.assertRaises(CanvasError):
                read_topic(self.client, '8', '9', 'group')

    def test_invalid_context_and_post_first_visibility_fail_before_entry_fetches(self):
        for context in ('account', '../courses'):
            with self.subTest(context=context), self.assertRaises(CanvasError):
                discussion_base('8', '9', context)
        for context_id in ('0', '../8', '8?access_token=secret'):
            with self.subTest(context_id=context_id), self.assertRaises(CanvasError):
                discussion_base(context_id, '9', 'group')
        self.client.request.assert_not_called()
        self.client.request.return_value = ({**self.topic, 'require_initial_post': True,
                                             'user_can_see_posts': False}, '')
        with self.assertRaisesRegex(CanvasError, 'initial post'):
            read_thread(self.client, '8', '9', 4, context_type='group')
        self.client.list.assert_not_called()
        # A top-level initial post is allowed; a reply cannot evade visibility restrictions.
        self.client.request.side_effect = [({'id': 7}, ''),
                                           ({**self.topic, 'require_initial_post': True, 'user_can_see_posts': False}, '')]
        preview = post(self.client, '8', '9', None, 'Initial post', context_type='group')
        self.assertTrue(preview['dry_run'])


if __name__ == '__main__': unittest.main()
