"""One exact-source copy, native eligibility and serialize-before-insert evidence."""

import copy
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from test_topic_authoring import CreationClient

from canvas_cli.cli import brief, parser, run
from canvas_cli.client import CanvasError
from canvas_cli.topic_duplication import duplicate


class DuplicationClient(CreationClient):
    def __init__(self):
        super().__init__()
        self.context_admin = True
        self.instructor = False
        self.admin_report = None
        self.topics[10]['position'] = 2
        self.positions_override = None
        self.extra_position = self.source_changed = self.existing_copy = False
        self.initial_position = None
        self.copied_pin = None
        self.associated_posted = False

    def request(self, route, method='GET', body=None):
        url = urlsplit(route)
        if method == 'POST' and url.path.endswith('/duplicate'):
            self.calls.append((method, route, body))
            course = '/courses/' in url.path
            source = self.topics[9]
            if (self.denied or not self.create_permission or course and not (self.context_admin or self.instructor) or
                    source['require_initial_post'] and source.get('user_can_see_posts') is not True and not self.associated_posted):
                raise CanvasError('Native copy restriction', status=403)
            if self.existing_copy:
                return copy.deepcopy(source), ''
            identifier = max(self.topics) + 1
            row = copy.deepcopy(source)
            row.update(id=identifier, title='Synthetic Copy ' + source['title'], attachments=[],
                       author={'id': self.identity}, discussion_subentry_count=0, ungraded_discussion_overrides=[],
                       published=not self.moderate, position=3)
            if self.copied_pin is not None:
                row['pinned'] = self.copied_pin
            self.topics[identifier] = row
            self.written = True
            response = copy.deepcopy(row)
            if source['pinned']:
                for other in self.topics.values():
                    if other['id'] != identifier and other['pinned'] and other['position'] > source['position']:
                        other['position'] += 1
                row['position'] = source['position'] + 1
                response['new_positions'] = {str(other['id']): other['position'] for other in self.topics.values() if other['pinned']}
                if self.extra_position:
                    response['new_positions']['99'] = 20
                if self.positions_override is not None:
                    response['new_positions'] = self.positions_override
            if self.initial_position is not None:
                response['position'] = self.initial_position
            if self.source_changed:
                source['title'] = 'synthetic-private-concurrent-source'
            if self.publication_override is not None:
                row['published'] = response['published'] = self.publication_override
            if self.ack_patch is not None:
                response = {**response, **self.ack_patch} if isinstance(self.ack_patch, dict) else self.ack_patch
            return response, ''
        if parse_qs(url.query).get('permissions[]') == ['read_as_admin']:
            self.calls.append((method, route, body))
            return copy.deepcopy(self.admin_report) if self.admin_report is not None else {'read_as_admin': self.context_admin}, ''
        return super().request(route, method, body)


class TopicDuplicationTests(unittest.TestCase):
    def setUp(self):
        self.client = DuplicationClient()

    def preview(self, **options):
        return duplicate(self.client, '123', '9', **({'acknowledge_shared': True, 'acknowledge_copy': True} | options))

    def execute(self, **options):
        preview = self.preview(**options)
        return self.preview(yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [row for row in self.client.calls if row[0] != 'GET']

    def test_preview_exact_source_native_creation_and_copy_effects_without_private_prompt_or_peer_reads(self):
        preview = self.preview()
        self.assertEqual(preview['route'], '/api/v1/courses/123/discussion_topics/9/duplicate?no_verifiers=true')
        self.assertIsNone(preview['body'])
        self.assertEqual(preview['native_duplicate_eligibility'], 'context admin reported')
        self.assertIn('widening the new audience', preview['warning'])
        self.assertNotIn('synthetic-private', str(preview))
        self.assertEqual(self.writes(), [])
        self.assertFalse(any('/entries' in route or '/view' in route for _, route, _ in self.client.calls))

    def test_pinned_copy_uses_native_position_map_not_pre_insertion_acknowledgement_as_stored_position(self):
        result = self.execute()
        self.assertEqual(self.writes(), [('POST', '/api/v1/courses/123/discussion_topics/9/duplicate?no_verifiers=true', None)])
        self.assertEqual(result['copied_topic']['id'], 11)
        self.assertEqual(result['copied_topic']['position'], 2)
        self.assertEqual(result['pinned_ordering'], {'accessible_positions_verified': True,
                         'native_pre_insertion_position': 3, 'stored_copy_position': 2, 'unverified_position_count': 0})
        self.assertEqual(self.client.topics[10]['position'], 3)
        self.assertTrue(result['source_metadata_unchanged_at_readback'])
        self.assertTrue(result['new_id_verified'])
        self.assertEqual(result['source_attachment_count'], 1)
        self.assertEqual(result['copy_attachment_count'], 0)
        self.assertFalse(result['stored_fields_match_source']['audience_digest'])
        self.assertIn('Attachment associations: 1 in source, 0 in copy.', brief(result))
        self.assertNotIn('synthetic-private', str(result))

    def test_unpinned_copy_and_full_course_instructor_or_context_admin_predicate_remain_native_authoritative(self):
        self.client.topics[9]['pinned'] = False
        self.client.context_admin = False
        self.client.instructor = True
        preview = self.preview()
        self.assertIn('native-endpoint authoritative', preview['native_duplicate_eligibility'])
        result = self.execute()
        self.assertIsNone(result['pinned_ordering'])
        self.assertTrue(result['copied_topic']['published'])
        self.assertEqual(len(self.writes()), 1)
        self.setUp()
        self.client.context_admin = self.client.instructor = False
        self.client.moderate = True  # moderation alone is not native course duplication eligibility
        self.assertIsNotNone(self.preview()['confirm'])
        with self.assertRaises(CanvasError) as caught:
            self.execute()
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(set(self.client.topics), {9, 10})

    def test_group_uses_native_creation_without_course_role_guess_and_source_update_permission_is_not_required(self):
        self.client.context_admin = self.client.instructor = False
        self.client.topics[9]['permissions'].update(update=False, delete=False)
        result = self.execute(context_type='group')
        self.assertTrue(result['copied_topic']['published'])
        self.assertEqual(result['group_id'], 123)
        self.assertFalse(any('read_as_admin' in route for _, route, _ in self.client.calls))
        self.setUp()
        self.client.moderate = True
        self.assertFalse(self.execute()['copied_topic']['published'])

    def test_initial_post_gate_never_uses_cached_entries_or_a_role_based_bypass(self):
        self.client.topics[9]['require_initial_post'] = True
        self.client.topics[9]['subscription_hold'] = 'initial_post_required'
        for value in (None, False):
            self.client.topics[9]['user_can_see_posts'] = value
            with self.assertRaisesRegex(CanvasError, 'initial-post'):
                self.preview()
            self.assertEqual(self.writes(), [])
        self.client.topics[9]['user_can_see_posts'] = True
        self.client.topics[9].pop('subscription_hold')
        self.assertTrue(self.execute()['new_id_verified'])
        self.assertFalse(any('/entries' in route or '/view' in route for _, route, _ in self.client.calls))
        self.setUp()
        self.client.topics[9].update(require_initial_post=True, user_can_see_posts=False)
        self.client.associated_posted = True
        self.assertTrue(self.execute()['new_id_verified'])
        self.assertFalse(any('/entries' in route or '/view' in route for _, route, _ in self.client.calls))
        self.setUp()
        self.client.topics[9]['require_initial_post'] = True
        with self.assertRaises(CanvasError) as caught:
            self.execute()
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(set(self.client.topics), {9, 10})

    def test_invalid_local_flags_context_ids_and_inventory_limit_fail_before_network(self):
        for options in ({'context_type': 'user'}, {'acknowledge_shared': False}, {'acknowledge_copy': False},
                        {'acknowledge_copy': 1}, {'max_pages': 0}, {'max_pages': True}, {'yes': True}, {'confirm': 'unpaired'}):
            self.setUp()
            with self.subTest(options=options), self.assertRaises(CanvasError):
                self.preview(**options)
            self.assertEqual(self.client.calls, [])
        with self.assertRaises(CanvasError):
            duplicate(self.client, '123', '09')
        self.assertEqual(self.client.calls, [])

    def test_dynamic_creation_and_context_admin_metadata_are_exact_booleans_not_role_labels(self):
        for value in (False, None, 1, 'true'):
            self.setUp()
            self.client.create_permission = value
            with self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.writes(), [])
        for value in ({}, [], {'read_as_admin': None}, {'read_as_admin': 1}, {'read_as_admin': 'true'}):
            self.setUp()
            self.client.admin_report = value
            with self.assertRaisesRegex(CanvasError, 'context-admin'):
                self.preview()
            self.assertEqual(self.writes(), [])

    def test_unknown_pinned_source_and_graded_anonymous_child_or_group_set_topics_never_copy(self):
        for field, value in (('position', None), ('assignment_id', 88), ('root_topic_id', 89),
                             ('group_category_id', 90), ('anonymous_state', 'full_anonymity'),
                             ('is_announcement', True), ('topic_children', [91]), ('user_can_see_posts', 1), ('subscription_hold', True)):
            self.setUp()
            self.client.topics[9][field] = value
            with self.subTest(field=field), self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.writes(), [])

    def test_stale_source_context_rights_account_audience_or_inventory_never_posts(self):
        for mode in ('source', 'context', 'admin', 'account', 'audience', 'inventory', 'creation', 'moderation'):
            self.setUp()
            preview = self.preview()
            if mode == 'source':
                self.client.topics[9]['message'] = 'Changed'
            elif mode == 'context':
                self.client.context['name'] = 'Changed'
            elif mode == 'admin':
                self.client.context_admin = False
            elif mode == 'account':
                self.client.identity = 8
            elif mode == 'audience':
                self.client.topics[9]['ungraded_discussion_overrides'] = []
            elif mode == 'inventory':
                self.client.topics[10]['title'] = 'Changed'
            elif mode == 'creation':
                self.client.create_permission = False
            else:
                self.client.moderate = True
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(yes=True, confirm=preview['confirm'])
            self.assertEqual(self.writes(), [])
        self.setUp()
        self.client.preflight_mutation = lambda client: client.topics[9].update(title='Changed')
        with self.assertRaisesRegex(CanvasError, 'during preflight'):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_partial_or_malformed_position_maps_wrong_ids_and_unverified_copy_never_retry_or_leak(self):
        for values in ({}, [], {'11': 2}, {'9': 1, '10': 3, '11': True}, {'9': 1, '10': 2, '11': 2},
                       {'9': 1, '10': 3, '011': 2}, {'9': 1, '10': 3, '11': -1}):
            self.setUp()
            self.client.positions_override = values
            with self.subTest(values=values), self.assertRaisesRegex(CanvasError, 'may already have succeeded'):
                self.execute()
            self.assertEqual(len(self.writes()), 1)
        for field, value in (('existing_copy', True), ('source_changed', True), ('after_denied', True),
                             ('context_changed', True), ('account_changed', True), ('after_list_fail', True),
                             ('after_inventory_missing', True), ('initial_position', True), ('copied_pin', False),
                             ('ack_patch', []), ('ack_patch', {'author': {'id': 8}}), ('ack_patch', {'title': 'synthetic-private-wrong-title'})):
            self.setUp()
            setattr(self.client, field, value)
            with self.subTest(field=field), self.assertRaisesRegex(CanvasError, 'may already have succeeded') as caught:
                self.execute()
            self.assertNotIn('synthetic-private', str(caught.exception))
            self.assertEqual(len(self.writes()), 1)

    def test_unseen_native_positions_and_publication_differences_are_labeled_not_asserted_complete(self):
        self.client.extra_position = True
        self.client.moderate = True
        self.client.publication_override = True
        result = self.execute()
        self.assertEqual(result['pinned_ordering']['unverified_position_count'], 1)
        self.assertTrue(result['copied_topic']['published'])
        self.assertNotIn(99, result['observed_inventory_changes']['added_ids'])
        self.assertNotIn('new_positions', result)
        self.assertIn('not a perfect-copy', result['note'])

    @patch('canvas_cli.auth.connect')
    def test_parser_dispatch_and_offline_help_keep_native_copy_separate_from_create_or_reply(self, connect):
        connect.return_value = self.client
        command = ['topic-duplicate', '123', '9', '--acknowledge-shared-topic', '--acknowledge-copy-effects']
        preview = run(parser().parse_args(command))
        result = run(parser().parse_args([*command, '--yes', '--confirm', preview['confirm']]))
        self.assertTrue(result['new_id_verified'])
        self.assertIn('usage: canvas topic-duplicate', run(parser().parse_args(['help', 'topic-duplicate']))['help_text'])
