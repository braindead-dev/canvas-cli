"""Native shared controls reuse the prompt pipeline, not guessed roles or peer reads."""

import copy
import json
import unittest
from unittest.mock import patch

from test_topic_management import TopicClient

from canvas_cli.cli import brief, parser, run
from canvas_cli.client import CanvasError
from canvas_cli.topic_management import ACTIONS, change


class StateClient(TopicClient):
    def __init__(self):
        super().__init__()
        for row in self.topics.values():
            row.update(can_unpublish=True, can_lock=True, comments_disabled=False)
        self.topics[9]['position'] = 2
        self.topics[10]['position'] = 3
        self.lose_edit = self.keep_schedule = False
        self.inventory_changed = self.final_identity_changed = False
        self.preflight_inventory_change = self.preflight_context_change = False
        self.concurrent_inventory_transition = False
        self.lists = 0

    def request(self, route, method='GET', body=None):
        if method == 'PUT' and set(body) <= {'published', 'locked', 'pinned'}:
            self.calls.append((method, route, copy.deepcopy(body)))
            if self.denied:
                raise CanvasError('Native state restriction', status=403)
            row = self.topics[int(route.split('?')[0].rsplit('/', 1)[1])]
            if (body.get('published') is False and row.get('can_unpublish') is not True or
                    body.get('locked') is True and row.get('can_lock') is not True):
                raise CanvasError('Native state ineligible', status=403)
            self.written = True
            self.native_effects.append('activity')
            if not self.ignore:
                if body.get('locked') is False and row['locked'] and not self.keep_schedule:
                    row['lock_at'] = None
                if 'pinned' in body and row['pinned'] != body['pinned']:
                    siblings = [topic for topic in self.topics.values() if topic['id'] != row['id']]
                    for sibling in siblings:
                        if sibling['pinned'] == row['pinned'] and sibling['position'] > row['position']:
                            sibling['position'] -= 1
                    row['position'] = max((topic['position'] for topic in siblings if topic['pinned'] == body['pinned']), default=0) + 1
                row.update(body)
                if self.lose_edit:
                    row['permissions']['update'] = False
                if self.concurrent_inventory_transition:
                    other = self.topics.pop(10)
                    self.topics[12] = {**other, 'id': 12}
            response = copy.deepcopy(row)
            if self.ack_patch is not None:
                response = {**response, **self.ack_patch} if isinstance(self.ack_patch, dict) else self.ack_patch
            return response, ''
        if self.preflight_context_change and self.lists == 1 and '/discussion_topics' not in route and '/profile' not in route:
            self.context['name'] = 'Changed during state preflight'
        return super().request(route, method, body)

    def list(self, route, max_pages):
        self.lists += 1
        if self.lists == 2 and self.preflight_inventory_change:
            self.topics[10]['title'] = 'Changed during state preflight'
        rows = super().list(route, max_pages)
        if self.written and self.final_identity_changed:
            self.identity = 8
        return [row for row in rows if row['id'] != 9] if self.written and self.inventory_changed else rows


class TopicStatesTests(unittest.TestCase):
    def setUp(self):
        self.client = StateClient()

    def preview(self, action='close', **options):
        return change(self.client, '123', '9', **({'action': action, 'acknowledge_shared': True,
                                                  'acknowledge_ordering': action in ('pin', 'unpin')} | options))

    def execute(self, action='close', **options):
        preview = self.preview(action, **options)
        return self.preview(action, yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [row for row in self.client.calls if row[0] != 'GET']

    def prepare(self, action):
        field, value = ACTIONS[action]
        self.client.topics[9][field] = not value

    def test_every_control_previews_only_one_field_without_peer_bodies_or_role_requests(self):
        for action, (field, value) in ACTIONS.items():
            self.client = StateClient()
            self.prepare(action)
            result = self.preview(action)
            self.assertEqual(result['body'], {field: value})
            self.assertEqual(result['topic_state_action'], action)
            self.assertEqual(json.loads(brief(result))['confirm'], result['confirm'])
            self.assertNotIn('synthetic-private', str(result))
            self.assertEqual(self.writes(), [])
            self.assertFalse(any('/entries' in route or '/view' in route or '/permissions' in route
                                 for _, route, _ in self.client.calls))

    def test_every_control_verifies_one_put_exact_state_and_separate_inventory_readback(self):
        for action, (field, value) in ACTIONS.items():
            self.client = StateClient()
            self.prepare(action)
            prior = copy.deepcopy(self.client.topics[9])
            result = self.execute(action)
            self.assertIs(result['edited_topic'][field], value)
            self.assertEqual(result['topic_state']['action'], action)
            self.assertTrue(result['topic_state']['verified'])
            self.assertEqual(result['stored_text_matches_request'], {})
            self.assertEqual(self.writes(), [('PUT', '/api/v1/courses/123/discussion_topics/9?no_verifiers=true', {field: value})])
            self.assertEqual(self.client.topics[9]['message'], prior['message'])
            self.assertEqual(self.client.topics[9]['attachments'], prior['attachments'])
            self.assertNotIn('synthetic-private', str(result))
            self.assertIn('verified', brief(result))

    def test_group_state_update_can_legitimately_remove_future_update_permission(self):
        self.client.lose_edit = True
        result = self.execute(context_type='group')
        self.assertFalse(result['edited_topic']['permissions']['update'])
        self.assertEqual(result['group_id'], 123)
        self.assertIn('/groups/123/', result['edited_topic']['html_url'])
        self.assertIn('permissions', result['unrequested_changed_fields'])

    def test_can_unpublish_not_total_entry_count_is_authoritative_and_never_reads_peer_posts(self):
        self.client.topics[9]['discussion_subentry_count'] = 4
        result = self.execute('unpublish')
        self.assertFalse(result['edited_topic']['published'])
        self.assertFalse(any('/entries' in route or '/view' in route for _, route, _ in self.client.calls))
        for key, action in (('can_unpublish', 'unpublish'), ('can_lock', 'close')):
            for value in (False, None, 1, 'true'):
                self.client = StateClient()
                self.client.topics[9][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(CanvasError):
                    self.preview(action)
                self.assertEqual(self.writes(), [])

    def test_open_clears_closing_date_only_with_bound_explicit_acknowledgement(self):
        self.client.topics[9].update(locked=True, lock_at='2026-11-01T12:00:00Z')
        with self.assertRaisesRegex(CanvasError, 'closing-schedule-removal'):
            self.preview('open')
        self.assertEqual(self.writes(), [])
        result = self.execute('open', acknowledge_schedule_removal=True)
        self.assertIsNone(result['edited_topic']['lock_at'])
        self.assertTrue(result['topic_state']['closing_schedule_cleared'])
        self.assertIn('Closing schedule cleared', brief(result))
        self.assertIn('lock_at', result['unrequested_changed_fields'])
        self.assertEqual(self.writes()[0][2], {'locked': False})

    def test_pin_and_unpin_show_collateral_positions_without_attributing_concurrency_or_echoing_titles(self):
        self.client.inventory_changed = False
        result = self.execute('unpin')
        self.assertEqual(result['observed_inventory_changes']['added_ids'], [])
        self.assertEqual(result['observed_inventory_changes']['removed_ids'], [])
        self.assertEqual(result['observed_inventory_changes']['changed'],
                         [{'id': 9, 'fields': ['pinned', 'position']}, {'id': 10, 'fields': ['position']}])
        self.assertIn('position', result['unrequested_changed_fields'])
        self.assertIn('not causal proof', brief(result))

    def test_observed_inventory_can_add_and_remove_other_topics_without_claiming_the_put_caused_it(self):
        self.client.concurrent_inventory_transition = True
        result = self.execute()
        self.assertEqual(result['observed_inventory_changes'],
                         {'added_ids': [12], 'removed_ids': [10], 'changed': [{'id': 9, 'fields': ['locked']}]})
        self.assertIn('not attributed exclusively', result['note'])
        self.assertNotIn('synthetic-private', str(result))
        self.assertEqual(len(self.writes()), 1)

    def test_invalid_combinations_acknowledgements_and_flags_fail_before_network(self):
        for options in ({'action': 'unknown'}, {'action': []}, {'action': 'close', 'title': 'New'},
                        {'action': 'close', 'message': 'New'}, {'action': 'close', 'delete': True, 'acknowledge_removal': True},
                        {'acknowledge_shared': False}, {'acknowledge_ordering': True}, {'acknowledge_ordering': 1},
                        {'acknowledge_schedule_removal': True}, {'acknowledge_schedule_removal': 1},
                        {'yes': True}, {'confirm': 'unpaired'}):
            self.client = StateClient()
            with self.subTest(options=options), self.assertRaises(CanvasError):
                self.preview(**options)
            self.assertEqual(self.client.calls, [])
        self.client = StateClient()
        with self.assertRaises(CanvasError):
            self.preview('unpin', acknowledge_ordering=False)
        self.assertEqual(self.client.calls, [])

    def test_noops_fail_without_turning_an_already_open_topic_into_schedule_cancellation(self):
        for action in ACTIONS:
            self.client = StateClient()
            field, value = ACTIONS[action]
            self.client.topics[9][field] = value
            with self.subTest(action=action), self.assertRaisesRegex(CanvasError, 'already matches'):
                self.preview(action)
            self.assertEqual(self.writes(), [])
        self.client = StateClient()
        self.client.topics[9]['lock_at'] = '2026-11-01T12:00:00Z'
        with self.assertRaisesRegex(CanvasError, 'already matches'):
            self.preview('open', acknowledge_schedule_removal=True)
        self.assertEqual(self.writes(), [])

    def test_stale_control_flags_content_inventory_scope_identity_and_audience_never_put(self):
        for mode in ('control', 'eligibility', 'content', 'inventory', 'scope', 'identity', 'audience', 'permission'):
            self.client = StateClient()
            preview = self.preview()
            if mode == 'control':
                self.client.topics[9]['locked'] = True
            elif mode == 'eligibility':
                self.client.topics[9]['can_lock'] = False
            elif mode == 'content':
                self.client.topics[9]['message'] = 'Changed'
            elif mode == 'inventory':
                self.client.topics[10]['title'] = 'Changed'
            elif mode == 'scope':
                self.client.context['name'] = 'Changed'
            elif mode == 'identity':
                self.client.identity = 8
            elif mode == 'audience':
                self.client.topics[9]['ungraded_discussion_overrides'] = []
            else:
                self.client.topics[9]['permissions']['update'] = False
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(yes=True, confirm=preview['confirm'])
            self.assertEqual(self.writes(), [])

    def test_inflight_context_inventory_and_topic_changes_are_not_sent(self):
        for field in ('preflight_context_change', 'preflight_inventory_change'):
            self.client = StateClient()
            setattr(self.client, field, True)
            with self.subTest(field=field), self.assertRaisesRegex(CanvasError, 'state preflight'):
                self.preview()
            self.assertEqual(self.writes(), [])
        self.client = StateClient()
        self.client.preflight_mutation = lambda client: client.topics[9].update(can_lock=False)
        with self.assertRaisesRegex(CanvasError, 'changed during preflight'):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_ignored_controls_bad_acknowledgements_readback_and_inventory_never_retry_or_cleanup(self):
        for field, value in (('ignore', True), ('ack_patch', {'id': 10}), ('ack_patch', []),
                             ('after_patch', {'locked': False}), ('after_denied', True), ('after_list_fail', True),
                             ('inventory_changed', True), ('context_changed', True), ('account_changed', True),
                             ('final_identity_changed', True)):
            self.client = StateClient()
            setattr(self.client, field, value)
            with self.subTest(field=field), self.assertRaisesRegex(CanvasError, 'may already have succeeded') as caught:
                self.execute()
            self.assertNotIn('synthetic-private', str(caught.exception))
            self.assertEqual(len(self.writes()), 1)
        self.client = StateClient()
        self.client.topics[9].update(locked=True, lock_at='2026-11-01T12:00:00Z')
        self.client.keep_schedule = True
        with self.assertRaisesRegex(CanvasError, 'may already have succeeded'):
            self.execute('open', acknowledge_schedule_removal=True)
        self.assertEqual(len(self.writes()), 1)

    def test_denied_native_state_put_never_retries(self):
        self.client.denied = True
        with self.assertRaises(CanvasError) as caught:
            self.execute()
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(len(self.writes()), 1)

    @patch('canvas_cli.auth.connect')
    def test_six_parser_actions_route_to_the_same_verified_pipeline_and_offline_help(self, connect):
        for action in ACTIONS:
            self.client = StateClient()
            connect.return_value = self.client
            self.prepare(action)
            command = ['topic-' + action, '123', '9', '--acknowledge-shared-topic']
            if action in ('pin', 'unpin'):
                command.append('--acknowledge-topic-ordering-change')
            preview = run(parser().parse_args(command))
            result = run(parser().parse_args([*command, '--yes', '--confirm', preview['confirm']]))
            self.assertTrue(result['topic_state']['verified'])
            self.assertIn('usage: canvas topic-' + action, run(parser().parse_args(['help', 'topic-' + action]))['help_text'])
