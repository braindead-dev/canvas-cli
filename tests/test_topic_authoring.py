"""Dynamic creation rights, native publication defaults and new-topic evidence."""

import copy
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from test_topic_management import TopicClient, topic

from canvas_cli.cli import brief, parser, run
from canvas_cli.client import CanvasError
from canvas_cli.topic_authoring import create


class CreationClient(TopicClient):
    def __init__(self):
        super().__init__()
        self.create_permission = True
        self.moderate = self.own_edit = False
        self.publication_override = self.permission_patch = self.moderation_patch = None
        self.during_preflight = None
        self.permission_reads = 0
        self.include_context_patch = None
        self.after_inventory_missing = False
        self.post_creation_permission = None

    def request(self, route, method='GET', body=None):
        url = urlsplit(route)
        if url.path.endswith('/permissions'):
            self.calls.append((method, route, body))
            return self.moderation_patch if self.moderation_patch is not None else {'moderate_forum': self.moderate}, ''
        if parse_qs(url.query).get('include[]') == ['permissions']:
            row, link = super().request(route, method, body)
            self.permission_reads += 1
            if self.permission_reads == 2 and self.during_preflight:
                self.during_preflight(self)
            row['permissions'] = self.permission_patch if self.permission_patch is not None else {
                'create_discussion_topic': self.create_permission, 'create_announcement': False}
            if self.include_context_patch:
                row.update(self.include_context_patch)
            return row, link
        if method == 'POST':
            self.calls.append((method, route, copy.deepcopy(body)))
            if self.denied or not self.create_permission or body['published'] is False and not self.moderate:
                raise CanvasError('synthetic-private-native-denial', status=403)
            self.written = True
            identifier = max(self.topics) + 1
            row = topic(identifier)
            row.update(title=body['title'], message=body.get('message'), published=body['published'],
                       pinned=False, position=len(self.topics) + 1, attachments=None, author={'id': self.identity},
                       ungraded_discussion_overrides=[], permissions={'update': self.own_edit, 'delete': self.own_edit})
            if self.sanitize and row['message'] is not None:
                row['message'] = row['message'].replace('<br>', '<br />')
            if self.publication_override is not None:
                row['published'] = self.publication_override
            self.topics[identifier] = row
            if self.post_creation_permission is not None:
                self.create_permission = self.post_creation_permission
            self.native_effects.append('activity')
            response = copy.deepcopy(row)
            if self.ack_patch is not None:
                response = {**response, **self.ack_patch} if isinstance(self.ack_patch, dict) else self.ack_patch
            return response, ''
        return super().request(route, method, body)

    def list(self, route, max_pages):
        rows = super().list(route, max_pages)
        return [row for row in rows if row['id'] != max(self.topics)] if self.written and self.after_inventory_missing else rows


class TopicAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.client = CreationClient()

    def preview(self, **options):
        return create(self.client, '123', **({'title': 'New 🌿', 'acknowledge_shared': True} | options))

    def execute(self, **options):
        preview = self.preview(**options)
        return self.preview(yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [row for row in self.client.calls if row[0] != 'GET']

    def test_preview_native_student_default_and_dynamic_permission_not_guessed_role(self):
        preview = self.preview(message='Hello <world>\n🌿')
        self.assertEqual(preview['body'], {'title': 'New 🌿', 'message': '<p>Hello &lt;world&gt;<br>🌿</p>', 'published': True})
        self.assertEqual(preview['publication_choice'], 'native_default')
        self.assertEqual(preview['permissions'], {'create_discussion_topic': True, 'moderate_forum': False})
        self.assertTrue(any('include%5B%5D=permissions' in route for _, route, _ in self.client.calls))
        self.assertFalse(any('/permissions?' in route and 'create_discussion_topic' in route for _, route, _ in self.client.calls))
        self.assertNotIn('synthetic-private', str(preview))
        self.assertEqual(json.loads(brief(preview))['confirm'], preview['confirm'])
        self.assertEqual(self.writes(), [])

    def test_native_moderator_default_draft_explicit_publication_and_student_draft_denial(self):
        self.client.moderate = True
        self.assertFalse(self.preview()['body']['published'])
        for state in (True, False):
            preview = self.preview(published=state)
            self.assertEqual(preview['body']['published'], state)
            self.assertEqual(preview['publication_choice'], 'explicit')
        self.client.moderate = False
        with self.assertRaisesRegex(CanvasError, 'moderation permission'):
            self.preview(published=False)
        self.assertEqual(self.writes(), [])

    def test_one_post_new_id_own_author_readback_inventory_and_no_required_edit_right(self):
        result = self.execute()
        self.assertEqual(result['created_topic']['id'], 11)
        self.assertEqual(result['created_topic']['author_id'], 7)
        self.assertEqual(result['created_topic']['permissions'], {'update': False, 'delete': False})
        self.assertEqual(result['stored_fields_match_request'], {'title': True, 'published': True})
        self.assertTrue(result['new_id_verified'])
        self.assertTrue(result['acknowledgement_matches_readback'])
        self.assertEqual(self.writes(), [('POST', '/api/v1/courses/123/discussion_topics?no_verifiers=true',
                                          {'title': 'New 🌿', 'published': True})])
        self.assertEqual(self.client.topics[9], topic())
        self.assertIsNone(self.client.topics[11]['message'])
        self.assertFalse(any('/entries' in route or '/view' in route for _, route, _ in self.client.calls))
        self.assertNotIn('synthetic-private', str(result))

    def test_group_creation_and_native_html_publication_rewriting_are_labeled_not_repaired(self):
        self.client.moderate = self.client.sanitize = True
        self.client.publication_override = True
        result = self.execute(context_type='group', message='One\nTwo')
        self.assertEqual(result['group_id'], 123)
        self.assertIn('/groups/123/', result['created_topic']['html_url'])
        self.assertEqual(result['stored_fields_match_request'], {'title': True, 'message': False, 'published': False})
        self.assertIn('Stored fields differ', brief(result))
        self.assertEqual(len(self.writes()), 1)

    def test_duplicate_titles_are_allowed_but_existing_ids_are_not_creation_proof(self):
        self.client.topics[9]['title'] = 'New 🌿'
        self.assertEqual(self.execute()['created_topic']['id'], 11)
        self.assertEqual(self.client.topics[9]['title'], 'New 🌿')

    def test_invalid_local_inputs_and_confirmation_pair_fail_before_network(self):
        for options in ({'title': None}, {'title': ''}, {'title': 'x' * 256}, {'title': 'Bad\x1b'},
                        {'message': ''}, {'message': '\ud800'}, {'published': 1}, {'published': 'false'},
                        {'acknowledge_shared': False}, {'context_type': 'user'}, {'max_pages': 0},
                        {'max_pages': True}, {'yes': True}, {'confirm': 'not-approved'}):
            self.client = CreationClient()
            with self.subTest(options=repr(options)), self.assertRaises(CanvasError):
                self.preview(**options)
            self.assertEqual(self.client.calls, [])

    def test_exact_native_permission_shapes_fail_closed(self):
        for field, value in (('create_permission', False), ('create_permission', None), ('create_permission', 1),
                             ('create_permission', 'true'), ('permission_patch', {}), ('permission_patch', []),
                             ('moderation_patch', {}), ('moderation_patch', {'moderate_forum': 1}), ('moderation_patch', [])):
            self.client = CreationClient()
            setattr(self.client, field, value)
            with self.subTest(field=field, value=value), self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.writes(), [])
        for value in ({'id': 124}, {'id': True}, {'name': 'Different context'}, {'workflow_state': 'deleted'}):
            self.client = CreationClient()
            self.client.include_context_patch = value
            with self.subTest(value=value), self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.writes(), [])

    def test_stale_permissions_context_inventory_account_text_and_publication_never_post(self):
        for mode in ('moderation', 'creation', 'context', 'inventory', 'account', 'message', 'publication'):
            self.client = CreationClient()
            preview = self.preview()
            options = {}
            if mode == 'moderation':
                self.client.moderate = True
            elif mode == 'creation':
                self.client.create_permission = False
            elif mode == 'context':
                self.client.context['name'] = 'Changed'
            elif mode == 'inventory':
                self.client.topics[9]['title'] = 'Changed'
            elif mode == 'account':
                self.client.identity = 8
            elif mode == 'message':
                options['message'] = 'Changed'
            else:
                options['published'] = True  # Same value, but newly explicit consent.
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(yes=True, confirm=preview['confirm'], **options)
            self.assertEqual(self.writes(), [])

    def test_changes_during_preflight_and_incomplete_inventory_never_post(self):
        self.client.during_preflight = lambda client: setattr(client, 'moderate', True)
        with self.assertRaisesRegex(CanvasError, 'changed during preflight'):
            self.preview()
        self.assertEqual(self.writes(), [])
        self.client = CreationClient()
        with self.assertRaisesRegex(CanvasError, 'Page limit'):
            self.preview(max_pages=1)
        self.assertEqual(self.writes(), [])

    def test_foreign_existing_malformed_and_different_author_acknowledgements_are_uncertain(self):
        for value in ([], {'id': 9}, {'id': True}, {'context_id': 999}, {'author': {'id': 8}},
                      {'assignment_id': 3}, {'anonymous_state': 'partial_anonymity'}, {'is_announcement': True},
                      {'permissions': {}}, {'attachments': 'bad'}, {'published': 'true'}):
            self.client = CreationClient()
            self.client.ack_patch = value
            with self.subTest(value=value), self.assertRaisesRegex(CanvasError, 'may already have succeeded'):
                self.execute()
            self.assertEqual(len(self.writes()), 1)

    def test_post_write_verification_failures_never_retry_or_cleanup_or_leak_bodies(self):
        for field, value in (('after_patch', {'title': 'Changed independently'}), ('after_denied', True),
                             ('after_list_fail', True), ('account_changed', True), ('context_changed', True),
                             ('after_patch', {'author': None}), ('after_inventory_missing', True),
                             ('account_changed_at', 6), ('post_creation_permission', False)):
            self.client = CreationClient()
            setattr(self.client, field, value)
            with self.subTest(field=field), self.assertRaisesRegex(CanvasError, 'may already have succeeded') as caught:
                self.execute()
            self.assertNotIn('synthetic-private', str(caught.exception))
            self.assertEqual(len(self.writes()), 1)
            self.assertEqual(set(self.client.topics), {9, 10, 11})

    def test_denied_native_post_is_not_retried(self):
        self.client.denied = True
        with self.assertRaises(CanvasError) as caught:
            self.execute()
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(set(self.client.topics), {9, 10})

    @patch('canvas_cli.auth.connect')
    def test_parser_dispatch_and_offline_help_use_canvas(self, connect):
        connect.return_value = self.client
        command = ['topic-create', '123', '--title', 'New 🌿', '--acknowledge-shared-topic']
        self.assertIsNone(parser().parse_args(command).published)
        preview = run(parser().parse_args(command))
        result = run(parser().parse_args([*command, '--yes', '--confirm', preview['confirm']]))
        self.assertIn('Course 123 topic 11 created', brief(result))
        self.assertIn('usage: canvas topic-create', run(parser().parse_args(['help', 'topic-create']))['help_text'])
