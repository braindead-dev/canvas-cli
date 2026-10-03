import unittest
from unittest.mock import Mock

from canvas_cli.activity import dismiss, feed, summary
from canvas_cli.cli import brief
from canvas_cli.client import CanvasError


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.message = {'id': 31, 'type': 'Conversation', 'title': 'Synthetic message', 'read_state': False,
                        'conversation_id': 12, 'message': 'Private body',
                        'latest_messages': [{'body': 'Private latest message', 'access_token': 'never print'}]}
        self.review = {'id': 32, 'type': 'AssessmentRequest', 'title': 'Synthetic review',
                       'assessment_request_id': 61, 'read_state': True, 'course_id': 101,
                       'html_url': 'https://canvas.example.edu/courses/101/assignments/88?verifier=not-for-output'}
        self.topic = {'id': 33, 'type': 'DiscussionTopic', 'title': 'Synthetic topic', 'course_id': 101,
                      'context_type': 'course', 'discussion_topic_id': 202, 'require_initial_post': True,
                      'user_has_posted': False, 'message': 'Stale cached prompt',
                      'root_discussion_entries': [{'message': 'Cached peer reply'}]}
        self.client.list.return_value = [self.message, self.review]

    def test_default_feed_paginates_metadata_only_and_does_not_claim_all_tasks(self):
        result = feed(self.client, 3)
        self.assertEqual([row['id'] for row in result['activity']], [31, 32])
        self.assertNotIn('message', result['activity'][0])
        self.assertNotIn('latest_messages', result['activity'][0])
        self.assertNotIn('not-for-output', str(result))
        self.assertFalse(result['complete_coursework_inventory'])
        self.assertTrue(result['complete_for_endpoint'])
        self.client.list.assert_called_once_with('/api/v1/users/self/activity_stream?per_page=100', 3)
        self.client.request.assert_not_called()
        self.assertIn('AssessmentRequest', brief(result))
        self.assertNotIn('Private body', brief(result))

    def test_course_active_and_exact_type_filters_preserve_endpoint_coverage(self):
        result = feed(self.client, course_id='101', type_filter='AssessmentRequest')
        self.assertEqual([row['id'] for row in result['activity']], [32])
        self.assertEqual(result['endpoint_record_count'], 2)
        self.assertEqual(result['excluded_by_type'], 1)
        self.client.list.assert_called_with('/api/v1/courses/101/activity_stream?per_page=100', 100)
        feed(self.client, active=True)
        self.client.list.assert_called_with('/api/v1/users/self/activity_stream?per_page=100&only_active_courses=true', 100)
        with self.assertRaises(CanvasError):
            feed(self.client, active=True, course_id='101')

    def test_opt_in_bodies_are_redacted_and_current_topic_access_gates_cached_entries(self):
        self.client.list.return_value = [self.message, self.topic]
        current = {'id': 202, 'context_id': 101, 'published': True, 'message': 'Current prompt',
                   'require_initial_post': True, 'user_can_see_posts': False}
        self.client.request.return_value = (current, '')
        result = feed(self.client, include_content=True)
        self.assertEqual(result['activity'][0]['message'], 'Private body')
        self.assertNotIn('never print', str(result))
        self.assertEqual(result['activity'][1]['message'], 'Current prompt')
        self.assertNotIn('Stale cached prompt', str(result))
        self.assertNotIn('Cached peer reply', str(result))
        self.assertIn('entries_withheld', result['activity'][1])
        self.client.request.assert_called_with('/api/v1/courses/101/discussion_topics/202')
        self.client.request.return_value = ({**current, 'user_can_see_posts': True}, '')
        self.assertIn('Cached peer reply', str(feed(self.client, include_content=True)))
        for flags in ({'require_initial_post': False}, {'user_has_posted': True}):
            self.client.request.return_value = ({**current, **flags}, '')
            self.assertNotIn('Cached peer reply', str(feed(self.client, include_content=True)))

    def test_standalone_entry_unknown_access_and_denied_topics_cannot_leak_cached_bodies(self):
        self.client.list.return_value = [{'id': 34, 'type': 'DiscussionEntry', 'message': 'Unverified entry'},
                                         {**self.topic, 'course_id': None}]
        result = feed(self.client, include_content=True)
        self.assertNotIn('Unverified entry', str(result))
        self.assertNotIn('Stale cached prompt', str(result))
        self.client.request.assert_not_called()
        self.client.list.return_value = [self.topic]
        self.client.request.side_effect = CanvasError('Not accessible', status=403)
        self.assertIn('content_withheld', str(feed(self.client, include_content=True)))
        self.client.request.side_effect = CanvasError('Rate limited', status=429)
        with self.assertRaises(CanvasError):
            feed(self.client, include_content=True)
        self.client.request.side_effect = None
        self.client.request.return_value = ({'id': 202, 'published': False}, '')
        with self.assertRaisesRegex(CanvasError, 'unpublished'):
            feed(self.client, include_content=True)

    def test_summary_counts_are_native_not_deadlines_and_same_type_can_have_categories(self):
        rows = [{'type': 'Message', 'notification_category': 'Assignment Graded', 'count': 3, 'unread_count': 1},
                {'type': 'Message', 'notification_category': 'Other notice', 'count': 2, 'unread_count': 0}]
        self.client.request.return_value = (rows, '')
        self.assertEqual(summary(self.client, active=True)['activity_summary'], rows)
        self.client.request.assert_called_with('/api/v1/users/self/activity_stream/summary?only_active_courses=true')
        summary(self.client, course_id='101')
        self.client.request.assert_called_with('/api/v1/courses/101/activity_stream/summary')
        for rows in ([rows[0], rows[0]], [{}], [{'type': 'Message', 'count': 1, 'unread_count': 2}],
                     [{'type': 'Message', 'count': True, 'unread_count': 0}],
                     [{'type': '', 'count': 0, 'unread_count': 0}], {}):
            self.client.request.return_value = (rows, '')
            with self.assertRaises(CanvasError):
                summary(self.client)

    def test_dismiss_one_and_all_are_bound_to_current_feed_without_body_echo(self):
        for item_id, all_items in (('31', False), (None, True)):
            self.client.request.side_effect = [({'id': 7}, '')]
            preview = dismiss(self.client, item_id, all_items=all_items, max_pages=3)
            self.assertTrue(preview['dry_run'])
            self.assertNotIn('Private body', str(preview))
            self.assertNotIn('Private latest message', str(preview))
            self.assertIn('not deleted', preview['warning'])
            self.assertEqual(len(preview['visible_items']), 2 if all_items else 1)
            self.client.request.reset_mock()
            self.client.request.side_effect = [({'id': 7}, ''), ({'hidden': True}, '')]
            result = dismiss(self.client, item_id, all_items=all_items, max_pages=3,
                             yes=True, confirm=preview['confirm'])
            self.assertTrue(result['acknowledged'])
            self.client.request.assert_called_with('/api/v1/users/self/activity_stream' + ('' if all_items else '/31'),
                                                  'DELETE', None)
            self.assertEqual(self.client.request.call_count, 2)

    def test_changed_message_or_account_invalidates_hide_even_without_timestamp_change(self):
        self.client.request.side_effect = [({'id': 7}, '')]
        preview = dismiss(self.client, '31')
        for profile, rows, host in (({'id': 8}, [self.message, self.review], self.client.host),
                                    ({'id': 7}, [{**self.message, 'message': 'New private body'}], self.client.host),
                                    ({'id': 7}, [self.message, self.review], 'https://other.example.edu')):
            self.client.host = host
            self.client.list.return_value = rows
            self.client.request.reset_mock()
            self.client.request.side_effect = [(profile, '')]
            with self.assertRaisesRegex(CanvasError, 'Preview changed'):
                dismiss(self.client, '31', yes=True, confirm=preview['confirm'])
            self.assertEqual(self.client.request.call_count, 1)
        self.client.list.return_value = [self.review]
        self.client.request.side_effect = [({'id': 7}, '')]
        with self.assertRaisesRegex(CanvasError, 'not in your current'):
            dismiss(self.client, '31')

    def test_invalid_hidden_acknowledgement_never_retries_or_prints_raw_response(self):
        self.client.request.side_effect = [({'id': 7}, '')]
        preview = dismiss(self.client, '31')
        for response in (None, [], {}, {'hidden': False}, {'hidden': 1, 'private': 'do not print'}):
            self.client.request.reset_mock()
            self.client.request.side_effect = [({'id': 7}, ''), (response, '')]
            with self.assertRaisesRegex(CanvasError, 'verify Canvas') as error:
                dismiss(self.client, '31', yes=True, confirm=preview['confirm'])
            self.assertNotIn('do not print', str(error.exception))
            self.assertEqual(self.client.request.call_count, 2)

    def test_invalid_options_and_malformed_or_wrong_course_records_fail_closed(self):
        for options in ({'course_id': '01'}, {'course_id': '١'}, {'active': 1},
                        {'include_content': 'true'}, {'type_filter': ''}):
            with self.subTest(options=options), self.assertRaises(CanvasError):
                feed(self.client, **options)
        for options in ({'item_id': '0'}, {'item_id': '01'}, {'item_id': '31', 'all_items': True},
                        {'all_items': 'all'}, {'item_id': '31', 'yes': True}):
            with self.subTest(options=options), self.assertRaises(CanvasError):
                dismiss(self.client, **options)
        self.client.list.assert_not_called()
        self.client.request.assert_not_called()
        for rows in ([None], [{**self.review, 'id': True}], [{**self.review, 'read_state': 1}],
                     [self.review, self.review], [{**self.review, 'course_id': 102}]):
            self.client.list.return_value = rows
            with self.subTest(rows=rows), self.assertRaises(CanvasError):
                feed(self.client, course_id='101')
