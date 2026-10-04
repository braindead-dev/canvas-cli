"""Explicit shared announcement comment access, implicit date clearing and native limits."""

import json
import unittest
from unittest.mock import patch

from test_announcement_authoring import AnnouncementClient

from canvas_cli.announcement_authoring import change
from canvas_cli.cli import brief, parser, run
from canvas_cli.client import CanvasError
from canvas_cli.dispatch import execute


class AnnouncementCommentTests(unittest.TestCase):
    def setUp(self):
        self.client = AnnouncementClient()

    def preview(self, **options):
        return change(self.client, '123', '9', **({'comments': True, 'acknowledge_shared': True,
                                                 'acknowledge_broadcast': True, 'acknowledge_comments': True} | options))

    def approved(self, **options):
        preview = self.preview(**options)
        return self.preview(yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [row for row in self.client.calls if row[0] != 'GET']

    def test_comment_only_preview_has_no_prior_body_peer_data_text_or_preference_write(self):
        result = self.preview()
        self.assertEqual(result['body'], {'is_announcement': True, 'lock_comment': False})
        self.assertEqual(result['comment_choice'], 'open')
        self.assertTrue(result['acknowledge_comment_access_change'])
        self.assertFalse(result['acknowledge_closing_schedule_removal'])
        self.assertIn('existing replies', result['warning'])
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertEqual(self.writes(), [])

    def test_open_close_and_combined_text_edits_use_one_put_with_independent_state_readback(self):
        for options in ({}, {'comments': False}, {'title': 'Combined title', 'message': 'New <message>'}):
            self.client = AnnouncementClient()
            closing = options.get('comments') is False
            if closing:
                self.client.topics[9]['locked'] = False
                self.client.topics[9]['lock_at'] = '2099-10-01T19:00:00Z'
            old_body = self.client.topics[9]['message']
            result = self.approved(**options)
            state = result['announcement_comment_state']
            self.assertIs(state['comments_locked'], closing)
            self.assertFalse(state['closing_schedule_cleared'])
            self.assertFalse(state['participant_reply_access_verified'])
            self.assertIs(state['reported_context_comments_disabled'], False)
            self.assertTrue(result['acknowledgement_matches_readback'])
            self.assertFalse(result['comment_lock_preserved'])
            self.assertNotIn('locked', self.writes()[0][2])
            self.assertNotIn('lock_at', self.writes()[0][2])
            self.assertEqual(len(self.writes()), 1)
            self.assertNotIn('synthetic-private', json.dumps(result))
            if closing:
                self.assertEqual(self.client.topics[9]['lock_at'], '2099-10-01T19:00:00Z')
            if 'message' not in options:
                self.assertEqual(self.client.topics[9]['message'], old_body)
            else:
                self.assertEqual(result['stored_text_matches_request'], {'title': True, 'message': True})
            self.assertIn('Stored comments: closed' if closing else 'Stored comments: open', brief(result))
            self.assertNotIn('locked', result['unrequested_changed_fields'])

    def test_opening_dated_closed_announcement_requires_and_verifies_implicit_clearing(self):
        self.client.topics[9]['lock_at'] = '2099-10-01T19:00:00Z'
        with self.assertRaisesRegex(CanvasError, 'closing date'):
            self.preview()
        self.assertEqual(self.writes(), [])
        result = self.approved(acknowledge_schedule_removal=True)
        self.assertTrue(result['announcement_comment_state']['closing_schedule_cleared'])
        self.assertIsNone(self.client.topics[9]['lock_at'])
        self.assertIn('Closing schedule cleared', brief(result))
        self.assertNotIn('lock_at', result['unrequested_changed_fields'])
        self.assertNotIn('lock_at', self.writes()[0][2])

    def test_already_open_is_not_cancellation_of_a_future_closing_date(self):
        self.client.topics[9].update(locked=False, lock_at='2099-10-01T19:00:00Z')
        for options in ({}, {'acknowledge_schedule_removal': True}):
            with self.assertRaises(CanvasError):
                self.preview(**options)
        self.assertEqual(self.writes(), [])
        result = self.approved(title='Changed title')
        self.assertFalse(result['announcement_comment_state']['closing_schedule_cleared'])
        self.assertTrue(result['comment_lock_preserved'])
        self.assertEqual(self.client.topics[9]['lock_at'], '2099-10-01T19:00:00Z')

    def test_reported_global_disabled_state_does_not_get_confused_with_stored_lock_or_access(self):
        for row in self.client.topics.values():
            row['context_type'] = 'Group'
        self.client.topics[9]['comments_disabled'] = True
        result = self.approved(context_type='group')
        self.assertFalse(result['announcement_comment_state']['comments_locked'])
        self.assertTrue(result['announcement_comment_state']['reported_context_comments_disabled'])
        self.assertFalse(result['announcement_comment_state']['participant_reply_access_verified'])

    def test_invalid_local_comment_and_ack_combinations_never_make_reads_or_writes(self):
        for options in ({'comments': 1}, {'comments': 'true'}, {'acknowledge_comments': False},
                        {'acknowledge_comments': 1}, {'comments': None},
                        {'comments': None, 'acknowledge_comments': False, 'acknowledge_schedule_removal': True},
                        {'acknowledge_schedule_removal': 1}, {'delete': True, 'acknowledge_removal': True,
                                                            'acknowledge_broadcast': False}):
            self.client = AnnouncementClient()
            with self.subTest(options=options), self.assertRaises(CanvasError):
                self.preview(**options)
            self.assertEqual(self.client.calls, [])

    def test_close_transition_needs_exact_native_lock_eligibility_without_role_inference(self):
        for value in (None, False, 1, 'true'):
            self.client = AnnouncementClient()
            self.client.topics[9].update(locked=False, can_lock=value)
            with self.subTest(value=value), self.assertRaises(CanvasError):
                self.preview(comments=False)
            self.assertEqual(self.writes(), [])

    def test_stale_comment_choice_closing_date_native_eligibility_and_global_policy_do_not_write(self):
        for mode in ('choice', 'date', 'eligibility', 'global', 'consent'):
            self.client = AnnouncementClient()
            preview = self.preview()
            options = {}
            if mode == 'choice':
                self.client.topics[9]['locked'] = False
            elif mode == 'date':
                self.client.topics[9]['lock_at'] = '2099-10-01T19:00:00Z'
                options['acknowledge_schedule_removal'] = True
            elif mode == 'eligibility':
                self.client.topics[9]['can_lock'] = False
            elif mode == 'global':
                self.client.topics[9]['comments_disabled'] = True
            else:
                options['acknowledge_schedule_removal'] = True
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(yes=True, confirm=preview['confirm'], **options)
            self.assertEqual(self.writes(), [])

    def test_native_ignored_lock_forced_close_or_retained_date_is_uncertain_and_not_repaired(self):
        for mode in ('ignored_close', 'forced_close', 'retained_date', 'different_readback'):
            self.client = AnnouncementClient()
            options = {}
            if mode == 'ignored_close':
                self.client.topics[9]['locked'] = False
                self.client.ignore_comment_lock = True
                options['comments'] = False
            elif mode == 'forced_close':
                self.client.force_comment_lock = True
            elif mode == 'retained_date':
                self.client.topics[9]['lock_at'] = '2099-10-01T19:00:00Z'
                self.client.keep_closing_date = True
                options['acknowledge_schedule_removal'] = True
            else:
                self.client.after_patch = {'locked': True}
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'may already have succeeded') as error:
                self.approved(**options)
            self.assertEqual(len(self.writes()), 1)
            self.assertNotIn('synthetic-private', str(error.exception))

    def test_parser_dispatch_passes_choices_and_consent_and_discovery_remains_native(self):
        args = parser().parse_args(['announcement-edit', '123', '9', '--no-comments',
                                   '--acknowledge-shared-announcement', '--acknowledge-broadcast',
                                   '--acknowledge-comment-access-change'])
        with patch('canvas_cli.announcement_authoring.change') as operation:
            execute(self.client, args)
            self.assertIs(operation.call_args.kwargs['comments'], False)
            self.assertIs(operation.call_args.kwargs['acknowledge_comments'], True)
            self.assertIs(operation.call_args.kwargs['acknowledge_schedule_removal'], False)
        schema = run(parser().parse_args(['schema', 'announcement-edit']))['commands'][0]
        flags = [flag for argument in schema['arguments'] for flag in argument['flags']]
        self.assertIn('--comments', flags)
        self.assertIn('--no-comments', flags)
        self.assertIn('--acknowledge-closing-schedule-removal', flags)
        self.assertEqual(schema['safety'], 'Canvas writes (preview-first)')


if __name__ == '__main__':
    unittest.main()
