"""Course-date validation, acknowledged native state effects and exact instant proof."""

import copy
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from test_topic_management import TopicClient

from canvas_cli.cli import brief, parser, run
from canvas_cli.client import CanvasError
from canvas_cli.topic_dates import matches, validate, validate_current
from canvas_cli.topic_management import change


class SchedulingClient(TopicClient):
    def __init__(self):
        super().__init__()
        self.context['time_zone'] = 'America/Los_Angeles'
        self.store_offset = self.lose_update = self.date_shift = False

    def request(self, route, method='GET', body=None):
        if method == 'PUT':
            self.calls.append((method, route, copy.deepcopy(body)))
            if self.denied:
                raise CanvasError('Native date restriction', status=403)
            self.written = True
            row = self.topics[9]
            if not self.ignore:
                row.update({key: value for key, value in body.items() if key not in self.ignored_fields})
                row['published'] = True
                row['locked'] = row['lock_at'] is not None and datetime.fromisoformat(row['lock_at'].replace('Z', '+00:00')) < datetime.now(timezone.utc)
                if self.store_offset and row['lock_at']:
                    row['lock_at'] = datetime.fromisoformat(row['lock_at'].replace('Z', '+00:00')).isoformat()
                if self.date_shift:
                    row['lock_at'] = '2040-10-02T22:00:00Z'
                if self.lose_update:
                    row['permissions']['update'] = False
            response = copy.deepcopy(row)
            if self.ack_patch is not None:
                response = {**response, **self.ack_patch} if isinstance(self.ack_patch, dict) else self.ack_patch
            return response, ''
        return super().request(route, method, body)


class TopicSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.client = SchedulingClient()

    def preview(self, **options):
        return change(self.client, '123', '9', **({'schedule': {'lock_at': '2040-10-02T12:00:00-07:00'},
                      'acknowledge_shared': True, 'acknowledge_availability': True} | options))

    def execute(self, **options):
        preview = self.preview(**options)
        return self.preview(yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [row for row in self.client.calls if row[0] != 'GET']

    def test_preview_binds_selected_utc_instants_context_zone_and_native_state_warning_without_private_content(self):
        preview = self.preview()
        self.assertEqual(preview['body'], {'lock_at': '2040-10-02T19:00:00Z'})
        self.assertEqual(preview['context']['time_zone'], 'America/Los_Angeles')
        self.assertTrue(preview['acknowledge_availability_change'])
        self.assertIn('publish a draft', preview['warning'])
        self.assertIn('reopen replies', preview['warning'])
        self.assertEqual(self.writes(), [])
        self.assertNotIn('synthetic-private', str(preview))
        self.assertFalse(any('/entries' in route or '/view' in route for _, route, _ in self.client.calls))

    def test_single_exact_put_and_independent_readback_verifies_dates_not_future_execution(self):
        result = self.execute()
        self.assertEqual(self.writes(), [('PUT', '/api/v1/courses/123/discussion_topics/9?no_verifiers=true',
                                         {'lock_at': '2040-10-02T19:00:00Z'})])
        dates = result['scheduled_topic_dates']
        self.assertTrue(dates['verified'])
        self.assertFalse(dates['future_execution_verified'])
        self.assertEqual(dates['stored'], dates['requested'])
        self.assertEqual(result['stored_text_matches_request'], {})
        self.assertIn('Stored instants verified', brief(result))
        self.assertNotIn('synthetic-private', str(result))

    def test_native_date_change_can_publish_a_draft_reopen_replies_and_lose_future_edit_permission(self):
        self.client.topics[9].update(published=False, locked=True)
        self.client.lose_update = True
        result = self.execute()
        self.assertEqual(result['scheduled_topic_dates']['observed_states'],
                         {'published': {'before': False, 'after': True}, 'locked': {'before': True, 'after': False}})
        self.assertFalse(result['edited_topic']['permissions']['update'])
        self.assertIn('published', result['unrequested_changed_fields'])
        self.assertIn('locked', result['unrequested_changed_fields'])

    def test_past_closing_and_explicit_clearing_are_supported_without_a_future_only_guess(self):
        result = self.execute(schedule={'lock_at': '2020-10-02T19:00:00Z'})
        self.assertTrue(result['edited_topic']['locked'])
        self.setUp()
        self.client.topics[9].update(delayed_post_at='2040-10-01T19:00:00Z', lock_at='2040-10-02T19:00:00Z', locked=True)
        result = self.execute(schedule={'delayed_post_at': None, 'lock_at': None})
        self.assertEqual(result['scheduled_topic_dates']['stored'], {'delayed_post_at': None, 'lock_at': None})
        self.assertFalse(result['edited_topic']['locked'])

    def test_equivalent_offset_storage_is_an_exact_instant_and_noop_is_not_a_state_control(self):
        self.client.store_offset = True
        result = self.execute()
        self.assertEqual(result['scheduled_topic_dates']['stored']['lock_at'], '2040-10-02T19:00:00+00:00')
        self.setUp()
        self.client.topics[9].update(lock_at='2040-10-02T19:00:00+00:00', locked=True, published=False)
        with self.assertRaisesRegex(CanvasError, 'already match'):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_invalid_local_shapes_timestamps_contexts_acknowledgements_and_mixed_operations_fail_before_network(self):
        for options in ({'schedule': {}}, {'schedule': []}, {'schedule': {'todo_date': None}},
                        {'schedule': {'lock_at': True}}, {'schedule': {'lock_at': '2040-10-02'}},
                        {'schedule': {'lock_at': '2040-10-02T12:00:00-00:00'}},
                        {'schedule': {'lock_at': '2040-10-02T12:00:00.1Z'}},
                        {'schedule': {'lock_at': '0001-01-01T00:00:00+23:59'}},
                        {'schedule': {'lock_at': '9999-12-31T23:59:59-23:59'}},
                        {'context_type': 'group'}, {'title': 'Mixed'}, {'delete': True, 'acknowledge_removal': True},
                        {'action': 'publish'}, {'options': {'allow_rating': False}},
                        {'acknowledge_availability': False}, {'acknowledge_availability': 1},
                        {'schedule': None}, {'acknowledge_shared': False}, {'yes': True}, {'confirm': 'unpaired'}):
            self.setUp()
            with self.subTest(options=options), self.assertRaises(CanvasError):
                self.preview(**options)
            self.assertEqual(self.client.calls, [])

    def test_selected_and_preserved_date_ranges_are_checked_without_implicit_clearing(self):
        for schedule, current in (({'delayed_post_at': '2040-10-02T20:00:00Z'}, {'lock_at': '2040-10-02T19:00:00Z'}),
                                  ({'lock_at': '2040-10-02T19:00:00Z'}, {'delayed_post_at': '2040-10-02T19:00:00Z'})):
            self.setUp()
            self.client.topics[9].update(current)
            with self.assertRaisesRegex(CanvasError, 'later than opening'):
                self.preview(schedule=schedule)
            self.assertEqual(self.writes(), [])
        self.setUp()
        self.client.topics[9]['delayed_post_at'] = '2040-10-01T19:00:00Z'
        result = self.execute()
        self.assertEqual(result['edited_topic']['delayed_post_at'], '2040-10-01T19:00:00Z')

    def test_course_midnight_is_refused_after_converting_absolute_instant_and_unknown_zones_are_not_guessed(self):
        for value in ('2040-10-02T00:00:00-07:00', '2040-10-02T07:00:00Z'):
            self.setUp()
            with self.assertRaisesRegex(CanvasError, 'course-midnight'):
                self.preview(schedule={'lock_at': value})
            self.assertEqual(self.writes(), [])
        for value in (None, 'not-a-zone', 12):
            self.setUp()
            self.client.context['time_zone'] = value
            with self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.writes(), [])
        self.setUp()
        self.client.context.pop('time_zone')
        result = self.execute(schedule={'delayed_post_at': '2040-10-01T07:00:00Z'})
        self.assertTrue(result['scheduled_topic_dates']['verified'])

    def test_missing_current_date_metadata_is_not_assumed_unset(self):
        for key in ('lock_at', 'delayed_post_at'):
            self.setUp()
            self.client.topics[9].pop(key)
            with self.assertRaisesRegex(CanvasError, 'incomplete'):
                self.preview()
            self.assertEqual(self.writes(), [])

    def test_stale_zone_dates_state_prompt_audience_identity_and_inflight_metadata_never_put(self):
        for mode in ('zone', 'date', 'state', 'prompt', 'audience', 'identity'):
            self.setUp()
            preview = self.preview()
            if mode == 'zone':
                self.client.context['time_zone'] = 'UTC'
            elif mode == 'date':
                self.client.topics[9]['delayed_post_at'] = '2040-10-01T19:00:00Z'
            elif mode == 'state':
                self.client.topics[9]['locked'] = True
            elif mode == 'prompt':
                self.client.topics[9]['message'] = 'Changed'
            elif mode == 'audience':
                self.client.topics[9]['ungraded_discussion_overrides'] = []
            else:
                self.client.identity = 8
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(yes=True, confirm=preview['confirm'])
            self.assertEqual(self.writes(), [])
        self.setUp()
        self.client.preflight_mutation = lambda client: client.topics[9].update(lock_at='2040-10-02T20:00:00Z')
        with self.assertRaisesRegex(CanvasError, 'during preflight'):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_ignored_shifted_partial_acknowledgements_and_unavailable_readback_never_retry_or_leak(self):
        for mode in ('ignore', 'date_shift', 'after_denied', 'context_changed', 'account_changed', 'after_list_fail'):
            self.setUp()
            setattr(self.client, mode, True)
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'may already have succeeded') as caught:
                self.execute()
            self.assertEqual(len(self.writes()), 1)
            self.assertNotIn('synthetic-private', str(caught.exception))
        self.setUp()
        self.client.ignored_fields = {'lock_at'}
        with self.assertRaisesRegex(CanvasError, 'may already have succeeded'):
            self.execute(schedule={'delayed_post_at': '2040-10-01T19:00:00Z', 'lock_at': '2040-10-02T19:00:00Z'})
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(self.client.topics[9]['delayed_post_at'], '2040-10-01T19:00:00Z')
        self.setUp()
        self.client.denied = True
        with self.assertRaises(CanvasError) as caught:
            self.execute()
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(len(self.writes()), 1)

    def test_pure_date_helpers_handle_none_whole_seconds_offsets_and_exact_midnight(self):
        self.assertEqual(validate({'delayed_post_at': '2040-10-01T12:00:00.000Z'}, 'course'),
                         {'delayed_post_at': '2040-10-01T12:00:00Z'})
        self.assertTrue(matches({'lock_at': None}, 'lock_at', None))
        self.assertFalse(matches({'lock_at': None}, 'lock_at', '2040-10-01T12:00:00Z'))
        self.assertFalse(matches({'lock_at': '2040-10-01T12:00:00Z'}, 'lock_at', None))
        validate_current({'lock_at': '2040-10-02T00:00:01-07:00'}, {'delayed_post_at': None, 'lock_at': None},
                         {'time_zone': 'America/Los_Angeles'})
        with self.assertRaisesRegex(CanvasError, 'course time-zone date range'):
            validate_current({'lock_at': '0001-01-01T00:00:00Z'}, {'delayed_post_at': None, 'lock_at': None},
                             {'time_zone': 'America/Los_Angeles'})

    @patch('canvas_cli.auth.connect')
    def test_parser_dispatch_and_offline_help_preserve_explicit_clear_and_date_selection(self, connect):
        connect.return_value = self.client
        command = ['topic-schedule', '123', '9', '--opens-at', '2040-10-01T12:00:00Z',
                   '--clear-closing', '--acknowledge-shared-topic', '--acknowledge-availability-change']
        preview = run(parser().parse_args(command))
        self.assertEqual(preview['body'], {'delayed_post_at': '2040-10-01T12:00:00Z', 'lock_at': None})
        result = run(parser().parse_args([*command, '--yes', '--confirm', preview['confirm']]))
        self.assertTrue(result['scheduled_topic_dates']['verified'])
        self.assertIn('usage: canvas topic-schedule', run(parser().parse_args(['help', 'topic-schedule']))['help_text'])
