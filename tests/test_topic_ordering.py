"""Full native pinned ordering and exact context moderation, not authored-topic rights."""

import copy
import unittest
from unittest.mock import patch

from test_topic_management import TopicClient

from canvas_cli.cli import brief, parser, run
from canvas_cli.client import CanvasError
from canvas_cli.topic_ordering import _ordered, reorder


class OrderingClient(TopicClient):
    def __init__(self):
        super().__init__()
        self.topics[10]['position'] = 2
        self.topics[11] = copy.deepcopy(self.topics[9])
        self.topics[11].update(id=11, pinned=False, position=1)
        self.rights = {'read_forum': True, 'moderate_forum': True}
        self.order_ack = None
        self.order_ignore = self.rights_changed = self.final_identity_changed = False
        self.inflight_rights_change = self.inflight_inventory_change = False
        self.other_topic_changed = False
        self.right_reads = self.inventory_reads = 0

    def request(self, route, method='GET', body=None):
        if route.endswith('/discussion_topics/reorder') and method == 'POST':
            self.calls.append((method, route, copy.deepcopy(body)))
            if self.denied:
                raise CanvasError('Native ordering restriction', status=403)
            self.written = True
            if not self.order_ignore:
                for position, identifier in enumerate(body['order'], 1):
                    self.topics[identifier]['position'] = position
            if self.other_topic_changed:
                self.topics[11]['title'] = 'synthetic-private-concurrent-title'
            order = [row['id'] for row in sorted((row for row in self.topics.values() if row['pinned']),
                                                 key=lambda row: row['position'])]
            return (copy.deepcopy(self.order_ack) if self.order_ack is not None else
                    {'reorder': True, 'order': [str(identifier) for identifier in order], 'secret': 'synthetic-private-order-response'}), ''
        if '/permissions?' in route:
            self.calls.append((method, route, copy.deepcopy(body)))
            self.right_reads += 1
            if self.written and self.rights_changed or self.right_reads == 2 and self.inflight_rights_change:
                return {'read_forum': True, 'moderate_forum': False}, ''
            return copy.deepcopy(self.rights), ''
        if route == '/api/v1/users/self/profile' and self.written and self.final_identity_changed and self.inventory_reads > 4:
            return {'id': 8}, ''
        return super().request(route, method, body)

    def list(self, route, max_pages):
        self.inventory_reads += 1
        if self.inventory_reads == 2 and self.inflight_inventory_change:
            self.topics[11]['title'] = 'Changed'
        return super().list(route, max_pages)


class TopicOrderingTests(unittest.TestCase):
    def setUp(self):
        self.client = OrderingClient()

    def preview(self, **options):
        return reorder(self.client, '123', **({'order': ['10', '9'], 'acknowledge': True} | options))

    def execute(self, **options):
        preview = self.preview(**options)
        return self.preview(yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [row for row in self.client.calls if row[0] != 'GET']

    def test_preview_is_complete_explicit_order_and_metadata_only_without_prompt_or_peer_reads(self):
        preview = self.preview()
        self.assertEqual(preview['previous_order'], [9, 10])
        self.assertEqual(preview['body'], {'order': [10, 9]})
        self.assertEqual(preview['route'], '/api/v1/courses/123/discussion_topics/reorder')
        self.assertNotIn('synthetic-private', str(preview))
        self.assertEqual(self.writes(), [])
        self.assertFalse(any('/entries' in route or '/view' in route or '/discussion_topics/9' in route
                             for _, route, _ in self.client.calls))

    def test_one_post_and_independent_relative_order_proof_does_not_touch_pin_or_unpinned_position(self):
        result = self.execute()
        self.assertEqual(result['pinned_topic_order'], [10, 9])
        self.assertEqual(result['positions'], [{'id': 10, 'position': 1}, {'id': 9, 'position': 2}])
        self.assertTrue(result['order_verified'])
        self.assertEqual(self.client.topics[11]['position'], 1)
        self.assertEqual(self.writes(), [('POST', '/api/v1/courses/123/discussion_topics/reorder', {'order': [10, 9]})])
        self.assertNotIn('synthetic-private', str(result))
        self.assertIn('10 → 9', brief(result))

    def test_group_and_graded_pinned_topics_use_native_ordering_not_ungraded_prompt_edit_rules(self):
        self.client.topics[9].update(assignment_id=55, message=None, author=None)
        result = self.execute(context_type='group')
        self.assertEqual(result['group_id'], 123)
        self.assertIn('/groups/123/discussion_topics', result['html_url'])
        self.assertEqual(self.client.topics[9]['assignment_id'], 55)

    def test_context_rights_not_an_authored_topic_permission_or_creation_permission(self):
        for key in ('read_forum', 'moderate_forum'):
            for value in (False, None, 1, 'true'):
                self.setUp()
                self.client.rights[key] = value
                with self.subTest(key=key, value=value), self.assertRaisesRegex(CanvasError, 'context read/moderation'):
                    self.preview()
                self.assertEqual(self.writes(), [])
        self.setUp()
        self.client.rights = []
        with self.assertRaises(CanvasError):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_invalid_context_ack_order_flags_and_duplicates_fail_before_network(self):
        for options in ({'context_type': 'user'}, {'acknowledge': False}, {'order': []}, {'order': '10,9'},
                        {'order': [10, 9]}, {'order': ['10', '10']}, {'order': ['0', '9']},
                        {'order': ['01', '9']}, {'max_pages': 0}, {'max_pages': True},
                        {'yes': True}, {'confirm': 'unpaired'}):
            self.setUp()
            with self.subTest(options=options), self.assertRaises(CanvasError):
                self.preview(**options)
            self.assertEqual(self.client.calls, [])

    def test_noop_incomplete_unpinned_foreign_and_empty_pinned_inventories_do_not_post(self):
        for order in (['9', '10'], ['9'], ['10', '9', '11'], ['10', '12']):
            self.setUp()
            with self.subTest(order=order), self.assertRaises(CanvasError):
                self.preview(order=order)
            self.assertEqual(self.writes(), [])
        self.setUp()
        for row in self.client.topics.values():
            row['pinned'] = False
        with self.assertRaises(CanvasError):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_missing_or_ambiguous_pin_positions_are_never_sorted_as_defaults(self):
        for field, value in (('pinned', None), ('pinned', 1), ('position', None), ('position', 1),
                             ('position', True), ('position', -1)):
            self.setUp()
            self.client.topics[10][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.writes(), [])
        self.assertEqual(_ordered([]), [])

    def test_stale_order_inventory_rights_account_and_context_do_not_post(self):
        for mode in ('order', 'inventory', 'rights', 'account', 'context'):
            self.setUp()
            preview = self.preview()
            if mode == 'order':
                self.client.topics[10]['position'] = 3
            elif mode == 'inventory':
                self.client.topics[11]['title'] = 'Changed'
            elif mode == 'rights':
                self.client.rights['moderate_forum'] = False
            elif mode == 'account':
                self.client.identity = 8
            else:
                self.client.context['name'] = 'Changed'
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(yes=True, confirm=preview['confirm'])
            self.assertEqual(self.writes(), [])
        for field in ('inflight_rights_change', 'inflight_inventory_change'):
            self.setUp()
            setattr(self.client, field, True)
            with self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.writes(), [])

    def test_ignored_wrong_or_extra_native_order_and_unverified_outcomes_never_retry(self):
        for field, value in (('order_ignore', True), ('order_ack', []), ('order_ack', {'reorder': 1, 'order': ['10', '9']}),
                             ('order_ack', {'reorder': True, 'order': ['9', '10']}),
                             ('order_ack', {'reorder': True, 'order': ['10', '9', '12']}),
                             ('after_list_fail', True), ('context_changed', True), ('account_changed', True),
                             ('rights_changed', True), ('final_identity_changed', True)):
            self.setUp()
            setattr(self.client, field, value)
            with self.subTest(field=field), self.assertRaisesRegex(CanvasError, 'may already have succeeded') as caught:
                self.execute()
            self.assertEqual(len(self.writes()), 1)
            self.assertNotIn('synthetic-private', str(caught.exception))
        self.setUp()
        self.client.denied = True
        with self.assertRaises(CanvasError) as caught:
            self.execute()
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(len(self.writes()), 1)

    def test_concurrent_metadata_changes_are_observed_not_exclusive_causal_claims(self):
        self.client.other_topic_changed = True
        result = self.execute()
        self.assertIn({'id': 11, 'fields': ['title']}, result['observed_inventory_changes']['changed'])
        self.assertIn('not exclusive causal proof', result['note'])
        self.assertNotIn('synthetic-private', str(result))

    @patch('canvas_cli.auth.connect')
    def test_parser_and_offline_help_dispatch_to_the_same_native_order_pipeline(self, connect):
        connect.return_value = self.client
        command = ['topic-order', '123', '10', '9', '--acknowledge-all-pinned-topics']
        preview = run(parser().parse_args(command))
        self.assertEqual(preview['body'], {'order': [10, 9]})
        result = run(parser().parse_args([*command, '--yes', '--confirm', preview['confirm']]))
        self.assertTrue(result['order_verified'])
        self.assertIn('usage: canvas topic-order', run(parser().parse_args(['help', 'topic-order']))['help_text'])
