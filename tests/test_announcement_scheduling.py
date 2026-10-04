"""Course announcement dates, native comment effects and exact readback limits."""

import copy
import json
import unittest
from unittest.mock import patch

from test_announcement_authoring import AnnouncementClient

from canvas_cli.announcement_authoring import change
from canvas_cli.cli import brief, parser, run
from canvas_cli.client import CanvasError
from canvas_cli.dispatch import execute


class AnnouncementSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.client = AnnouncementClient()
        self.client.context['time_zone'] = 'America/Los_Angeles'

    def preview(self, **options):
        return change(self.client, '123', '9', **({'schedule': {'lock_at': '2099-10-02T12:00:00-07:00'},
                      'acknowledge_shared': True, 'acknowledge_broadcast': True,
                      'acknowledge_availability': True} | options))

    def approved(self, **options):
        preview = self.preview(**options)
        return self.preview(yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [call for call in self.client.calls if call[0] != 'GET']

    def test_preview_uses_exact_selected_dates_and_current_lock_with_native_effect_warning(self):
        preview = self.preview()
        self.assertEqual(preview['body'], {'lock_at': '2099-10-02T19:00:00Z',
                                         'is_announcement': True, 'lock_comment': True})
        self.assertTrue(preview['acknowledge_availability_change'])
        self.assertEqual(preview['comment_policy'], 'native_date_effects')
        self.assertEqual(preview['context']['time_zone'], 'America/Los_Angeles')
        self.assertIn('override', preview['warning'])
        self.assertIn('never private drafts', preview['warning'])
        self.assertNotIn('synthetic-private', json.dumps(preview))
        self.assertFalse(any('/entries' in route or '/view' in route for _, route, _ in self.client.calls))
        self.assertEqual(self.writes(), [])

    def test_changed_closing_date_can_reopen_comments_despite_requested_current_lock(self):
        original = copy.deepcopy(self.client.topics)
        result = self.approved()
        dates = result['scheduled_announcement_dates']
        self.assertTrue(dates['verified'])
        self.assertEqual(dates['stored'], dates['requested'])
        self.assertEqual(dates['observed_states']['locked'], {'before': True, 'after': False})
        self.assertFalse(dates['future_execution_verified'])
        self.assertFalse(dates['participant_visibility_verified'])
        self.assertFalse(dates['participant_reply_access_verified'])
        self.assertFalse(result['notification_delivery_verified'])
        self.assertFalse(result['comment_lock_preserved'])
        self.assertEqual(result['stored_text_matches_request'], {})
        self.assertIn('locked', result['unrequested_changed_fields'])
        self.assertEqual(self.client.topics[9]['message'], original[9]['message'])
        self.assertEqual(self.client.topics[9]['attachments'], original[9]['attachments'])
        self.assertEqual(self.client.topics[10], original[10])
        self.assertEqual(len(self.writes()), 1)
        self.assertIn('Stored instants verified', brief(result))
        self.assertIn('Observed comment lock: open', brief(result))
        self.assertNotIn('synthetic-private', json.dumps(result))

    def test_posting_only_preserves_requested_comment_lock_when_native_closing_is_unchanged(self):
        result = self.approved(schedule={'delayed_post_at': '2099-10-01T19:00:00Z'})
        self.assertTrue(result['comment_lock_preserved'])
        self.assertTrue(result['edited_announcement']['locked'])
        self.assertTrue(result['edited_announcement']['published'])
        self.assertIsNone(self.client.topics[9]['lock_at'])
        self.assertEqual(self.client.topics[9]['workflow_state'], 'post_delayed')

    def test_past_closing_global_comment_lock_and_lost_future_update_permission_are_observed(self):
        result = self.approved(schedule={'lock_at': '2020-10-02T19:00:00Z'})
        self.assertTrue(result['edited_announcement']['locked'])
        self.setUp()
        self.client.force_comment_lock = self.client.lose_update = True
        self.client.topics[9]['comments_disabled'] = True
        result = self.approved()
        self.assertTrue(result['edited_announcement']['locked'])
        self.assertFalse(result['edited_announcement']['permissions']['update'])
        self.assertTrue(result['scheduled_announcement_dates']['reported_context_comments_disabled'])
        self.assertFalse(result['scheduled_announcement_dates']['participant_reply_access_verified'])

    def test_explicit_clearing_activates_delayed_announcement_and_can_reopen_comments(self):
        self.client.topics[9].update(delayed_post_at='2099-10-01T19:00:00Z', lock_at='2099-10-02T19:00:00Z')
        result = self.approved(schedule={'delayed_post_at': None, 'lock_at': None})
        self.assertEqual(result['scheduled_announcement_dates']['stored'], {'delayed_post_at': None, 'lock_at': None})
        self.assertTrue(result['edited_announcement']['published'])
        self.assertFalse(result['edited_announcement']['locked'])
        self.assertEqual(self.client.topics[9]['workflow_state'], 'active')
        self.assertIn('lock_at: cleared', brief(result))

    def test_equivalent_offset_readback_is_verified_but_matching_instants_are_not_rebroadcast(self):
        self.client.store_date_offset = True
        result = self.approved()
        self.assertEqual(result['scheduled_announcement_dates']['stored']['lock_at'], '2099-10-02T19:00:00+00:00')
        self.setUp()
        self.client.topics[9]['lock_at'] = '2099-10-02T19:00:00+00:00'
        with self.assertRaisesRegex(CanvasError, 'already match'):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_native_unselected_closing_clearing_is_labeled_not_silently_assumed_preserved(self):
        self.client.topics[9].update(delayed_post_at='2019-10-01T19:00:00Z',
                                     lock_at='2020-10-02T19:00:00Z', locked=False)
        result = self.approved(schedule={'delayed_post_at': None})
        self.assertEqual(result['scheduled_announcement_dates']['stored'], {'delayed_post_at': None})
        self.assertIsNone(self.client.topics[9]['lock_at'])
        self.assertIn('lock_at', result['unrequested_changed_fields'])
        self.assertNotIn('lock_at', self.writes()[0][2])

    def test_invalid_shapes_timestamps_contexts_consents_and_mixed_edits_never_use_network(self):
        for options in ({'schedule': {}}, {'schedule': []}, {'schedule': {'todo_date': None}},
                        {'schedule': {'lock_at': True}}, {'schedule': {'lock_at': '2099-10-02'}},
                        {'schedule': {'lock_at': '2099-10-02T12:00:00-00:00'}},
                        {'schedule': {'lock_at': '2099-10-02T12:00:00.1Z'}},
                        {'context_type': 'group'}, {'title': 'Mixed'}, {'message': 'Mixed'},
                        {'comments': True, 'acknowledge_comments': True},
                        {'delete': True, 'acknowledge_removal': True, 'acknowledge_broadcast': False},
                        {'acknowledge_availability': False}, {'acknowledge_availability': 1}, {'schedule': None},
                        {'acknowledge_shared': False}, {'acknowledge_broadcast': False},
                        {'max_pages': 0}, {'yes': True}, {'confirm': 'unpaired'}):
            self.setUp()
            with self.subTest(options=options), self.assertRaises(CanvasError):
                self.preview(**options)
            self.assertEqual(self.client.calls, [])

    def test_selected_and_preserved_ranges_course_midnight_and_unknown_zone_are_not_guessed(self):
        for options, current in (({'delayed_post_at': '2099-10-03T19:00:00Z'}, {'lock_at': '2099-10-02T19:00:00Z'}),
                                 ({'lock_at': '2099-10-02T19:00:00Z'}, {'delayed_post_at': '2099-10-02T19:00:00Z'})):
            self.setUp()
            self.client.topics[9].update(current)
            with self.assertRaisesRegex(CanvasError, 'later than opening'):
                self.preview(schedule=options)
            self.assertEqual(self.writes(), [])
        for value in ('2099-10-02T00:00:00-07:00', '2099-10-02T07:00:00Z'):
            self.setUp()
            with self.assertRaisesRegex(CanvasError, 'course-midnight'):
                self.preview(schedule={'lock_at': value})
            self.assertEqual(self.writes(), [])
        for value in (None, 'not-a-zone'):
            self.setUp()
            self.client.context['time_zone'] = value
            with self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.writes(), [])
        self.setUp()
        self.client.context.pop('time_zone')
        self.assertTrue(self.approved(schedule={'delayed_post_at': '2099-10-01T07:00:00Z'})['scheduled_announcement_dates']['verified'])

    def test_stale_dates_zone_content_audience_native_rights_and_account_do_not_put(self):
        for mode in ('date', 'zone', 'content', 'audience', 'rights', 'account'):
            self.setUp()
            preview = self.preview()
            if mode == 'date':
                self.client.topics[9]['delayed_post_at'] = '2099-10-01T19:00:00Z'
            elif mode == 'zone':
                self.client.context['time_zone'] = 'UTC'
            elif mode == 'content':
                self.client.topics[9]['message'] = '<p>Changed prior content</p>'
            elif mode == 'audience':
                self.client.topics[9]['ungraded_discussion_overrides'] = []
            elif mode == 'rights':
                self.client.topics[9]['permissions']['update'] = False
            else:
                self.client.identity = 8
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(yes=True, confirm=preview['confirm'])
            self.assertEqual(self.writes(), [])

    def test_ignored_dates_wrong_ack_readback_or_account_are_uncertain_without_retry(self):
        for mode in ('ignore', 'partial', 'shift', 'ack', 'readback', 'account'):
            self.setUp()
            preview = self.preview(schedule={'delayed_post_at': '2099-10-01T19:00:00Z', 'lock_at': '2099-10-02T19:00:00Z'})
            if mode == 'ignore':
                self.client.ignore = True
            elif mode == 'partial':
                self.client.ignored_fields = {'lock_at'}
            elif mode == 'shift':
                self.client.shift_date = True
            elif mode == 'ack':
                self.client.ack_patch = {'is_announcement': False}
            elif mode == 'readback':
                self.client.after_patch = {'lock_at': '2099-10-03T19:00:00Z'}
            elif mode == 'account':
                self.client.account_changed = True
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'may already have succeeded') as error:
                self.preview(schedule={'delayed_post_at': '2099-10-01T19:00:00Z', 'lock_at': '2099-10-02T19:00:00Z'},
                             yes=True, confirm=preview['confirm'])
            self.assertEqual(len(self.writes()), 1)
            self.assertNotIn('synthetic-private', str(error.exception))

    def test_parser_dispatch_schema_and_completion_share_the_same_native_date_command(self):
        command = ['announcement-schedule', '123', '9', '--post-at', '2099-10-01T19:00:00Z', '--clear-closing',
                   '--acknowledge-shared-announcement', '--acknowledge-broadcast', '--acknowledge-availability-change']
        with patch('canvas_cli.announcement_authoring.change') as operation:
            execute(self.client, parser().parse_args(command))
            self.assertEqual(operation.call_args.kwargs['schedule'], {'delayed_post_at': '2099-10-01T19:00:00Z', 'lock_at': None})
            self.assertTrue(operation.call_args.kwargs['acknowledge_availability'])
        schema = run(parser().parse_args(['schema', 'announcement-schedule']))['commands'][0]
        self.assertEqual(schema['safety'], 'Canvas writes (preview-first)')
        self.assertEqual(len(schema['mutually_exclusive_groups']), 2)
        result = run(parser().parse_args(['complete', '--cword', '4', '--', 'canvas', 'announcement-schedule', '123', '9', '--clear-']))
        self.assertEqual(result['completion_candidates'], ['--clear-closing', '--clear-posting'])


if __name__ == '__main__':
    unittest.main()
