"""Native shared to-do permission asymmetry, exact instants and independent evidence."""

import copy
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from test_topic_management import TopicClient

from canvas_cli.cli import brief, parser, run
from canvas_cli.client import CanvasError
from canvas_cli.topic_management import change
from canvas_cli.topic_todo import validate


class TodoClient(TopicClient):
    def __init__(self):
        super().__init__()
        self.add_permission = True
        self.permission_report = None
        self.permission_denied_after = self.lose_update = self.offset_storage = False
        self.shift_date = False
        self.hide_after = False
        self.permission_reads = 0

    def request(self, route, method='GET', body=None):
        if parse_qs(urlsplit(route).query).get('permissions[]') == ['manage_course_content_add']:
            self.calls.append((method, route, body))
            self.permission_reads += 1
            value = False if self.permission_denied_after and self.permission_reads > 1 else self.add_permission
            return copy.deepcopy(self.permission_report) if self.permission_report is not None else {'manage_course_content_add': value}, ''
        if method == 'PUT':
            self.calls.append((method, route, copy.deepcopy(body)))
            if self.denied or body['todo_date'] is not None and self.add_permission is not True:
                raise CanvasError('Native shared to-do permission', status=403)
            self.written = True
            row = self.topics[9]
            if not self.ignore and 'todo_date' not in self.ignored_fields:
                row.update(body)
                if self.offset_storage and row['todo_date']:
                    row['todo_date'] = row['todo_date'].replace('Z', '+00:00')
                if self.shift_date:
                    row['todo_date'] = '2040-10-02T19:00:01Z'
                if self.lose_update:
                    row['permissions']['update'] = False
            response = copy.deepcopy(row)
            if self.ack_patch is not None:
                response = {**response, **self.ack_patch} if isinstance(self.ack_patch, dict) else self.ack_patch
            return response, ''
        return super().request(route, method, body)

    def list(self, route, max_pages):
        rows = super().list(route, max_pages)
        return [row for row in rows if row['id'] != 9] if self.written and self.hide_after else rows


class TopicTodoTests(unittest.TestCase):
    def setUp(self):
        self.client = TodoClient()

    def preview(self, **options):
        return change(self.client, '123', '9', **({'todo': {'todo_date': '2040-10-02T12:00:00-07:00'},
                      'acknowledge_shared': True, 'acknowledge_todo': True} | options))

    def execute(self, **options):
        preview = self.preview(**options)
        return self.preview(yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [row for row in self.client.calls if row[0] != 'GET']

    def test_preview_requires_exact_context_add_permission_and_acknowledges_shared_student_effects(self):
        result = self.preview()
        self.assertEqual(result['body'], {'todo_date': '2040-10-02T19:00:00Z'})
        self.assertTrue(result['additional_context_permission_required'])
        self.assertEqual(result['todo_permissions'], {'manage_course_content_add': True})
        self.assertTrue(result['acknowledge_student_todo_change'])
        self.assertIn('not a private reminder', result['warning'])
        self.assertEqual(self.client.permission_reads, 2)
        self.assertEqual(self.writes(), [])
        self.assertNotIn('synthetic-private', str(result))
        self.assertFalse(any('/entries' in route or '/view' in route for _, route, _ in self.client.calls))

    def test_course_and_group_setting_use_one_exact_put_and_independent_readback_without_grading(self):
        for context in ('course', 'group'):
            self.setUp()
            before = copy.deepcopy(self.client.topics[9])
            result = self.execute(context_type=context)
            self.assertEqual(self.writes(), [('PUT', f'/api/v1/{context}s/123/discussion_topics/9?no_verifiers=true',
                                             {'todo_date': '2040-10-02T19:00:00Z'})])
            self.assertEqual(result['student_todo_date'], {'requested': '2040-10-02T19:00:00Z',
                             'stored': '2040-10-02T19:00:00Z', 'verified': True, 'shared_change_acknowledged': True,
                             'planner_effects_verified': False})
            self.assertEqual(result['stored_text_matches_request'], {})
            self.assertEqual(self.client.topics[9], before | {'todo_date': '2040-10-02T19:00:00Z'})
            self.assertIn('Shared student to-do date', brief(result))

    def test_clearing_needs_update_but_no_extra_add_permission_or_permission_request(self):
        self.client.add_permission = False
        self.client.topics[9]['todo_date'] = '2040-10-02T19:00:00Z'
        preview = self.preview(todo={'todo_date': None})
        self.assertFalse(preview['additional_context_permission_required'])
        self.assertIsNone(preview['todo_permissions'])
        result = self.execute(todo={'todo_date': None})
        self.assertIsNone(result['student_todo_date']['stored'])
        self.assertEqual(self.client.permission_reads, 0)
        self.setUp()
        self.client.topics[9]['todo_date'] = '2040-10-02T19:00:00Z'
        self.client.topics[9]['permissions']['update'] = False
        with self.assertRaisesRegex(CanvasError, 'exact discussion-topic update'):
            self.preview(todo={'todo_date': None})
        self.assertEqual(self.writes(), [])

    def test_todo_dates_allow_midnight_past_and_dates_outside_availability_without_a_fake_due_date_rule(self):
        for value in ('2020-10-02T00:00:00Z', '2040-10-02T00:00:00-07:00'):
            self.setUp()
            self.client.topics[9].update(published=False, locked=True, delayed_post_at='2045-01-01T00:00:00Z')
            result = self.execute(todo={'todo_date': value})
            self.assertTrue(result['student_todo_date']['verified'])
            self.assertFalse(result['edited_topic']['published'])
            self.assertTrue(result['edited_topic']['locked'])
            self.assertNotIn('time_zone', self.client.context)

    def test_equivalent_offsets_are_verified_instants_and_noop_does_not_write(self):
        self.client.offset_storage = True
        result = self.execute()
        self.assertEqual(result['student_todo_date']['stored'], '2040-10-02T19:00:00+00:00')
        with self.assertRaisesRegex(CanvasError, 'already matches'):
            self.preview()
        self.assertEqual(len(self.writes()), 1)
        self.setUp()
        with self.assertRaisesRegex(CanvasError, 'already matches'):
            self.preview(todo={'todo_date': None})
        self.assertEqual(self.writes(), [])

    def test_local_selection_acknowledgements_and_date_errors_fail_before_network(self):
        for options in ({'todo': {}}, {'todo': []}, {'todo': {'lock_at': None}}, {'acknowledge_shared': False},
                        {'acknowledge_todo': False}, {'acknowledge_todo': 1}, {'todo': None},
                        {'schedule': {'lock_at': None}}, {'options': {'expanded': True}}, {'action': 'close'},
                        {'title': 'Conflicting'}, {'max_pages': 0}, {'max_pages': True}, {'yes': True}, {'confirm': 'unpaired'}):
            self.setUp()
            with self.subTest(options=options), self.assertRaises(CanvasError):
                self.preview(**options)
            self.assertEqual(self.client.calls, [])
        for value in (True, '', 'tomorrow', '2040-10-02', '2040-10-02T12:00:00', '2040-10-02T12:00:00.001Z',
                      '0001-01-01T00:00:00+14:00'):
            self.setUp()
            with self.subTest(value=value), self.assertRaises(CanvasError):
                self.preview(todo={'todo_date': value})
            self.assertEqual(self.client.calls, [])
        self.assertEqual(validate({'todo_date': '2040-10-02T12:00:00.000Z'}), {'todo_date': '2040-10-02T12:00:00Z'})

    def test_missing_malformed_or_denied_add_permission_and_native_context_types_are_not_guessed(self):
        for value in (False, None, 1, 'true'):
            self.setUp()
            self.client.add_permission = value
            with self.assertRaisesRegex(CanvasError, 'manage_course_content_add'):
                self.preview()
            self.assertEqual(self.writes(), [])
        for report in ({}, [], {'manage_course_content_add': 1}):
            self.setUp()
            self.client.permission_report = report
            with self.assertRaisesRegex(CanvasError, 'manage_course_content_add'):
                self.preview()
            self.assertEqual(self.writes(), [])
        self.setUp()
        self.client.permission_denied_after = True
        with self.assertRaisesRegex(CanvasError, 'manage_course_content_add'):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_missing_todo_metadata_and_graded_anonymous_group_set_or_root_topics_are_refused(self):
        for field, value in (('assignment_id', 88), ('anonymous_state', 'full_anonymity'), ('root_topic_id', 89),
                             ('group_category_id', 90), ('is_announcement', True), ('todo_date', True)):
            self.setUp()
            self.client.topics[9][field] = value
            with self.subTest(field=field), self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.writes(), [])
        self.setUp()
        del self.client.topics[9]['todo_date']
        with self.assertRaisesRegex(CanvasError, 'incomplete'):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_stale_date_content_account_context_audience_inventory_or_rights_do_not_put(self):
        for mode in ('date', 'content', 'account', 'context', 'audience', 'inventory', 'rights'):
            self.setUp()
            preview = self.preview()
            if mode == 'date':
                self.client.topics[9]['todo_date'] = '2040-10-01T19:00:00Z'
            elif mode == 'content':
                self.client.topics[9]['message'] = 'Changed'
            elif mode == 'account':
                self.client.identity = 8
            elif mode == 'context':
                self.client.context['name'] = 'Changed'
            elif mode == 'audience':
                self.client.topics[9]['ungraded_discussion_overrides'] = []
            elif mode == 'inventory':
                self.client.topics[10]['title'] = 'Changed'
            else:
                self.client.add_permission = False
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(yes=True, confirm=preview['confirm'])
            self.assertEqual(self.writes(), [])
        self.setUp()
        self.client.preflight_mutation = lambda client: client.topics[9].update(todo_date='2040-10-01T19:00:00Z')
        with self.assertRaisesRegex(CanvasError, 'during preflight'):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_ignored_shifted_partial_or_uncertain_storage_fails_once_without_retry_or_private_echo(self):
        for mode in ('ignored', 'shifted', 'denied-read', 'context', 'account', 'inventory', 'missing-inventory', 'ack', 'readback'):
            self.setUp()
            if mode == 'ignored':
                self.client.ignore = True
            elif mode == 'shifted':
                self.client.shift_date = True
            elif mode == 'denied-read':
                self.client.after_denied = True
            elif mode == 'context':
                self.client.context_changed = True
            elif mode == 'account':
                self.client.account_changed = True
            elif mode == 'inventory':
                self.client.after_list_fail = True
            elif mode == 'missing-inventory':
                self.client.hide_after = True
            elif mode == 'ack':
                self.client.ack_patch = {'todo_date': 'synthetic-private-malformed'}
            else:
                self.client.after_patch = {'todo_date': '2040-10-01T19:00:00Z'}
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'may already have succeeded') as caught:
                self.execute()
            self.assertEqual(len(self.writes()), 1)
            self.assertNotIn('synthetic-private', str(caught.exception))
        self.setUp()
        self.client.denied = True
        with self.assertRaises(CanvasError) as caught:
            self.execute()
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(len(self.writes()), 1)

    def test_verified_write_can_lose_future_update_right_without_inventing_a_permission_persistence_guarantee(self):
        self.client.lose_update = True
        result = self.execute()
        self.assertFalse(result['edited_topic']['permissions']['update'])
        self.assertTrue(result['student_todo_date']['verified'])

    @patch('canvas_cli.auth.connect')
    def test_parser_dispatch_and_offline_help_keep_shared_todo_separate_from_personal_tasks(self, connect):
        connect.return_value = self.client
        command = ['topic-todo', '123', '9', '--todo-at', '2040-10-02T12:00:00Z',
                   '--acknowledge-shared-topic', '--acknowledge-student-todo-change']
        preview = run(parser().parse_args(command))
        result = run(parser().parse_args([*command, '--yes', '--confirm', preview['confirm']]))
        self.assertTrue(result['student_todo_date']['verified'])
