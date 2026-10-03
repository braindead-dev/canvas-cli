"""Exact shared configuration, including native visibility and expansion constraints."""

import unittest
from unittest.mock import patch

from test_topic_management import TopicClient

from canvas_cli.cli import brief, parser, run
from canvas_cli.client import CanvasError
from canvas_cli.topic_management import change
from canvas_cli.topic_options import FIELDS, validate, validate_current


class TopicOptionTests(unittest.TestCase):
    def setUp(self):
        self.client = TopicClient()

    def preview(self, options=None, **kwargs):
        selected = {'sort_order': 'desc'} if options is None else options
        return change(self.client, '123', '9', options=selected, acknowledge_shared=True,
                      **({'acknowledge_reply_visibility': 'require_initial_post' in selected} | kwargs))

    def execute(self, options=None, **kwargs):
        preview = self.preview(options, **kwargs)
        return self.preview(options, yes=True, confirm=preview['confirm'], **kwargs)

    def writes(self):
        return [row for row in self.client.calls if row[0] != 'GET']

    def test_all_options_have_exact_one_field_previews_and_independent_stored_values(self):
        for field, value in (('discussion_type', 'flat'), ('require_initial_post', True), ('allow_rating', False),
                             ('only_graders_can_rate', True), ('sort_order', 'desc'), ('sort_order_locked', True),
                             ('expanded', True), ('expanded_locked', True)):
            self.setUp()
            if field == 'expanded_locked':
                self.client.topics[9]['expanded'] = True
            selected = {field: value}
            preview = self.preview(selected)
            self.assertEqual(preview['body'], selected)
            self.assertNotIn('synthetic-private', str(preview))
            self.assertEqual(self.writes(), [])
            result = self.preview(selected, yes=True, confirm=preview['confirm'])
            self.assertEqual(result['configured_topic_settings']['values'], selected)
            self.assertTrue(result['configured_topic_settings']['verified'])
            self.assertEqual(result['edited_topic'][field], value)
            self.assertEqual(self.writes(), [('PUT', '/api/v1/courses/123/discussion_topics/9?no_verifiers=true', selected)])
            self.assertNotIn('synthetic-private', str(result))
            self.assertFalse(any('/entries' in route or '/view' in route for _, route, _ in self.client.calls))

    def test_combined_native_options_preserve_prompt_attachments_entries_and_other_topic(self):
        selected = {'discussion_type': 'side_comment', 'require_initial_post': True, 'allow_rating': False,
                    'only_graders_can_rate': True, 'sort_order': 'desc', 'sort_order_locked': True,
                    'expanded': True, 'expanded_locked': True}
        result = self.execute(selected)
        self.assertEqual(result['configured_topic_settings']['values'], selected)
        self.assertTrue(result['configured_topic_settings']['reply_visibility_change_acknowledged'])
        self.assertIn('Native options verified', brief(result))
        self.assertIn('not causal proof', brief(result))
        self.assertEqual(self.client.topics[9]['message'], '<p>synthetic-private-prior-prompt</p>')
        self.assertEqual(self.client.topics[9]['attachments'][0]['id'], 51)
        self.assertEqual(self.client.topics[10]['sort_order'], 'asc')
        self.assertEqual(len(self.writes()), 1)

    def test_explicit_reply_visibility_acknowledgement_is_not_a_post_first_bypass(self):
        for value in (True, False):
            self.setUp()
            self.client.topics[9]['require_initial_post'] = not value
            with self.assertRaisesRegex(CanvasError, 'reply-visibility-change'):
                self.preview({'require_initial_post': value}, acknowledge_reply_visibility=False)
            self.assertEqual(self.client.calls, [])
            result = self.execute({'require_initial_post': value})
            self.assertTrue(result['configured_topic_settings']['reply_visibility_change_acknowledged'])
            self.assertFalse(any('/entries' in route or '/view' in route for _, route, _ in self.client.calls))

    def test_group_options_are_native_not_a_course_namespace_and_post_first_is_refused_locally(self):
        result = self.execute(context_type='group')
        self.assertEqual(result['group_id'], 123)
        self.assertIn('/groups/123/', result['edited_topic']['html_url'])
        self.setUp()
        with self.assertRaisesRegex(CanvasError, 'group topic updates'):
            self.preview({'require_initial_post': True}, context_type='group')
        self.assertEqual(self.client.calls, [])

    def test_unknown_empty_bad_types_and_mixed_operations_fail_before_network(self):
        for options in ({}, {'title': 'No'}, {'published': False}, {'sort_order': 'inherit'}, {'discussion_type': 'unknown'},
                        {'allow_rating': 1}, {'expanded': 'true'}, {'expanded_locked': None}):
            self.setUp()
            with self.subTest(options=options), self.assertRaises(CanvasError):
                self.preview(options)
            self.assertEqual(self.client.calls, [])
        for extra in ({'title': 'No'}, {'message': 'No'}, {'action': 'close'},
                      {'delete': True, 'acknowledge_removal': True}, {'acknowledge_reply_visibility': True},
                      {'acknowledge_reply_visibility': 1}, {'acknowledge_ordering': True},
                      {'acknowledge_schedule_removal': True}, {'yes': True}, {'confirm': 'unpaired'}):
            self.setUp()
            with self.subTest(extra=extra), self.assertRaises(CanvasError):
                self.preview(**extra)
            self.assertEqual(self.client.calls, [])
        for options in ([], None, False, 'allow_rating=true'):
            with self.assertRaises(CanvasError):
                validate(options, 'course')

    def test_native_collapsed_lock_validation_uses_effective_final_state_not_one_flag(self):
        with self.assertRaisesRegex(CanvasError, 'collapsed'):
            self.preview({'expanded_locked': True})
        self.assertEqual(self.writes(), [])
        result = self.execute({'expanded': True, 'expanded_locked': True})
        self.assertTrue(result['edited_topic']['expanded_locked'])
        self.client.calls.clear()
        with self.assertRaisesRegex(CanvasError, 'collapsed'):
            self.preview({'expanded': False})
        self.assertEqual(self.writes(), [])
        result = self.execute({'expanded': False, 'expanded_locked': False})
        self.assertFalse(result['edited_topic']['expanded_locked'])

    def test_missing_selected_or_dependent_values_and_noops_are_not_assumed_defaults(self):
        for field in FIELDS:
            self.setUp()
            self.client.topics[9].pop(field)
            choices = FIELDS[field]
            value = choices[0] if choices is not None else True
            with self.subTest(field=field), self.assertRaises(CanvasError):
                self.preview({field: value})
            self.assertEqual(self.writes(), [])
        self.setUp()
        self.client.topics[9]['expanded_locked'] = None
        with self.assertRaisesRegex(CanvasError, 'both native expansion'):
            self.preview({'expanded': True})
        self.setUp()
        with self.assertRaisesRegex(CanvasError, 'already match'):
            self.preview({'sort_order': 'asc'})
        self.assertEqual(self.writes(), [])

    def test_stale_selected_options_prompt_permissions_identity_inventory_and_audience_never_put(self):
        for mode in ('selected', 'prompt', 'permission', 'identity', 'inventory', 'scope', 'audience'):
            self.setUp()
            preview = self.preview()
            if mode == 'selected':
                self.client.topics[9]['sort_order'] = 'desc'
            elif mode == 'prompt':
                self.client.topics[9]['message'] = 'Changed'
            elif mode == 'permission':
                self.client.topics[9]['permissions']['update'] = False
            elif mode == 'identity':
                self.client.identity = 8
            elif mode == 'inventory':
                self.client.topics[10]['position'] = 3
            elif mode == 'scope':
                self.client.context['name'] = 'Changed'
            else:
                self.client.topics[9]['ungraded_discussion_overrides'] = []
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(yes=True, confirm=preview['confirm'])
            self.assertEqual(self.writes(), [])

    def test_ignored_or_partial_options_foreign_acknowledgements_and_unverified_readback_never_retry(self):
        for field, value in (('ignore', True), ('ignored_fields', {'sort_order'}), ('ack_patch', {'id': 10}),
                             ('ack_patch', {'sort_order': 'asc'}), ('after_denied', True), ('after_list_fail', True),
                             ('context_changed', True), ('account_changed', True)):
            self.setUp()
            setattr(self.client, field, value)
            with self.subTest(field=field), self.assertRaisesRegex(CanvasError, 'may already have succeeded') as caught:
                self.execute({'sort_order': 'desc', 'allow_rating': False})
            self.assertNotIn('synthetic-private', str(caught.exception))
            self.assertEqual(len(self.writes()), 1)
        self.setUp()
        self.client.denied = True
        with self.assertRaises(CanvasError) as caught:
            self.execute()
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(len(self.writes()), 1)

    @patch('canvas_cli.auth.connect')
    def test_cli_boolean_pairs_and_enum_fields_dispatch_to_the_same_pipeline(self, connect):
        connect.return_value = self.client
        command = ['topic-configure', '123', '9', '--no-allow-rating', '--sort-order', 'desc',
                   '--expanded', '--expanded-locked', '--require-initial-post',
                   '--acknowledge-shared-topic', '--acknowledge-reply-visibility-change']
        preview = run(parser().parse_args(command))
        self.assertEqual(preview['body'], {'require_initial_post': True, 'allow_rating': False,
                                          'sort_order': 'desc', 'expanded': True, 'expanded_locked': True})
        result = run(parser().parse_args([*command, '--yes', '--confirm', preview['confirm']]))
        self.assertTrue(result['configured_topic_settings']['verified'])
        self.assertIn('usage: canvas topic-configure', run(parser().parse_args(['help', 'topic-configure']))['help_text'])

    def test_helper_local_validation_covers_named_choices_and_unchanged_expansion_dependencies(self):
        self.assertEqual(validate({'discussion_type': 'not_threaded', 'sort_order': 'asc'}, 'group'),
                         {'discussion_type': 'not_threaded', 'sort_order': 'asc'})
        with self.assertRaises(CanvasError):
            validate_current({'expanded_locked': False}, {'expanded_locked': True, 'expanded': None})
        validate_current({'allow_rating': True}, {'allow_rating': False})
