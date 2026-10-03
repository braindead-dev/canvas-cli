import unittest
from unittest.mock import Mock

from canvas_pocket.cli import brief
from canvas_pocket.client import CanvasError
from canvas_pocket.ratings import change, read


class RatingTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.profile = {'id': 7}
        self.topic = {'id': 202, 'context_id': 101, 'title': 'Synthetic discussion', 'message': 'Private prompt',
                      'published': True, 'allow_rating': True, 'only_graders_can_rate': False}
        self.entry = {'id': 301, 'user_id': 8, 'message': 'Private target reply', 'updated_at': '2026-10-02T12:00:00Z'}
        self.snapshot = {'entry_ratings': {'301': 1}, 'participants': [{'private': 'Never echo'}],
                         'view': [{'id': 302, 'message': 'Private other reply', 'replies': [{'id': 301}]}],
                         'new_entries': [{'id': 303}]}
        self.client.request.side_effect = self.response
        self.client.list.return_value = [self.entry]

    def response(self, route, method='GET', body=None, **kwargs):
        if route == '/api/v1/users/self/profile':
            return self.profile, ''
        if route.endswith('/view?include_new_entries=1'):
            return self.snapshot, ''
        if method == 'POST':
            return None, ''
        return self.topic, ''

    def test_read_only_native_map_returns_no_bodies_and_preserves_unrated_vs_zero(self):
        result = read(self.client, '101', '202')
        self.assertEqual(result['own_entry_ratings'], {'301': 1})
        self.assertEqual(result['snapshot_entry_ids'], [301, 302, 303])
        self.assertNotIn('Private', str(result))
        self.assertNotIn('Never echo', str(result))
        self.assertIn('301: liked', brief(result))
        self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))
        self.client.list.assert_not_called()
        self.snapshot['entry_ratings'] = {'301': 0}
        self.assertEqual(read(self.client, '101', '202')['own_entry_ratings']['301'], 0)

    def test_disabled_ratings_do_not_fetch_cached_bodies_or_claim_a_current_vote(self):
        self.topic['allow_rating'] = False
        result = read(self.client, '101', '202')
        self.assertFalse(result['ratings_enabled'])
        self.assertIsNone(result['snapshot_entry_ids'])
        self.assertEqual(self.client.request.call_count, 2)
        with self.assertRaisesRegex(CanvasError, 'disabled'):
            change(self.client, '101', '202', '301', 1)
        self.client.list.assert_not_called()

    def test_like_and_remove_use_same_native_endpoint_and_strict_empty_ack_contract(self):
        for value in (1, 0):
            preview = change(self.client, '101', '202', '301', value, max_pages=4)
            self.assertTrue(preview['dry_run'])
            self.assertEqual(preview['current_own_rating'], 1)
            self.assertEqual(preview['body'], {'rating': value})
            self.assertNotIn('Private', str(preview))
            self.client.list.assert_called_with(
                '/api/v1/courses/101/discussion_topics/202/entry_list?ids%5B%5D=301&per_page=100', 4)
            self.client.request.reset_mock()
            result = change(self.client, '101', '202', '301', value, max_pages=4,
                            yes=True, confirm=preview['confirm'])
            self.assertTrue(result['acknowledged'])
            self.client.request.assert_called_with('/api/v1/courses/101/discussion_topics/202/entries/301/rating',
                                                  'POST', {'rating': value}, expect_no_content=True)

    def test_account_site_target_content_and_own_rating_are_bound_to_preview(self):
        for alteration in ('account', 'host', 'entry', 'topic', 'rating'):
            with self.subTest(alteration=alteration):
                self.setUp()
                preview = change(self.client, '101', '202', '301', 0)
                if alteration == 'account':
                    self.profile['id'] = 9
                elif alteration == 'host':
                    self.client.host = 'https://other.example.edu'
                elif alteration == 'entry':
                    self.entry['message'] = 'Changed body, same timestamp'
                elif alteration == 'topic':
                    self.topic['message'] = 'Changed prompt, same timestamp'
                else:
                    self.snapshot['entry_ratings'] = {}
                self.client.request.reset_mock()
                with self.assertRaisesRegex(CanvasError, 'Preview changed'):
                    change(self.client, '101', '202', '301', 0, yes=True, confirm=preview['confirm'])
                self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))

    def test_post_first_locked_unpublished_explicit_denial_and_unknown_enabled_fail_closed(self):
        for flags in ({'require_initial_post': True, 'user_can_see_posts': False},
                      {'require_initial_post': False, 'user_can_see_posts': False}, {'locked': True},
                      {'published': False}, {'allow_rating': 1}, {'allow_rating': None}):
            self.topic.update(flags)
            self.client.request.reset_mock()
            with self.subTest(flags=flags), self.assertRaises(CanvasError):
                read(self.client, '101', '202')
            self.assertEqual(self.client.request.call_count, 2)
            self.setUp()

    def test_invalid_snapshots_and_unmaterialized_targets_are_not_false_zero_ratings(self):
        for snapshot in (None, {}, {'view': [], 'entry_ratings': {'301': 1}},
                         {'view': [{'id': 301}], 'entry_ratings': {'301': True}},
                         {'view': [{'id': True}], 'entry_ratings': {}},
                         {'view': [{'id': 301, 'replies': {}}], 'entry_ratings': {}},
                         {'view': [], 'new_entries': {}, 'entry_ratings': {}}):
            self.snapshot = snapshot
            with self.subTest(snapshot=snapshot), self.assertRaises(CanvasError):
                read(self.client, '101', '202')
        self.snapshot = {'view': [], 'entry_ratings': {}}
        with self.assertRaisesRegex(CanvasError, 'not yet in the rating snapshot'):
            change(self.client, '101', '202', '301', 1)

    def test_invalid_deleted_hidden_wrong_topic_and_denied_entry_do_not_write(self):
        for flags in ({'deleted': True}, {'workflow_state': 'deleted'}, {'hidden_for_user': True},
                      {'locked_for_user': True}, {'permissions': {'rate': False}}, {'discussion_topic_id': 203}):
            self.client.list.return_value = [{**self.entry, **flags}]
            with self.subTest(flags=flags), self.assertRaises(CanvasError):
                change(self.client, '101', '202', '301', 1)
        self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))

    def test_group_namespace_and_invalid_input_before_network(self):
        for args in (('0', '202', '301', 1), ('101', '02', '301', 1), ('101', '202', '١', 1),
                     ('101', '202', '301', True), ('101', '202', '301', 2)):
            with self.assertRaises(CanvasError):
                change(self.client, *args)
        with self.assertRaises(CanvasError):
            change(self.client, '101', '202', '301', 1, yes=True)
        self.client.request.assert_not_called()
        self.client.list.assert_not_called()
        self.topic.update(context_id=11, context_type='Group')
        preview = change(self.client, '11', '202', '301', 1, context_type='group')
        self.assertIn('/groups/11/', preview['route'])
        self.assertEqual(preview['group_id'], 11)

    def test_native_unavailable_cache_and_write_errors_propagate_without_retry(self):
        original = self.response
        for method_to_fail, status in (('view', 503), ('view', 403), ('POST', 403), ('POST', 429)):
            self.client.request.side_effect = original
            preview = change(self.client, '101', '202', '301', 1)
            def fail(route, method='GET', body=None, **kwargs):
                if (method_to_fail == 'view' and '/view?' in route or method == method_to_fail):
                    raise CanvasError('Native denial', status=status)
                return original(route, method, body, **kwargs)
            self.client.request.side_effect = fail
            self.client.request.reset_mock()
            with self.assertRaises(CanvasError):
                change(self.client, '101', '202', '301', 1, yes=True, confirm=preview['confirm'])
            self.assertLessEqual(sum(len(call.args) > 1 for call in self.client.request.call_args_list), 1)
