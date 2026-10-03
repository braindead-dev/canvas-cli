"""Native topic permissions, metadata-only previews and independent mutation evidence."""

import copy
import unittest
from urllib.parse import urlsplit

from canvas_cli.cli import brief, parser, run
from canvas_cli.client import CanvasError
from canvas_cli.topic_management import change


def topic(identifier=9):
    return {'id': identifier, 'title': 'Synthetic prompt', 'message': '<p>synthetic-private-prior-prompt</p>',
            'published': True, 'locked': False, 'pinned': True, 'position': 1,
            'created_at': '2026-10-01T12:00:00Z', 'posted_at': '2026-10-01T12:00:00Z',
            'last_reply_at': None, 'delayed_post_at': None, 'lock_at': None, 'todo_date': None,
            'discussion_type': 'threaded', 'discussion_subentry_count': 0, 'require_initial_post': False,
            'is_section_specific': False, 'allow_rating': True, 'only_graders_can_rate': False,
            'sort_order': 'asc', 'sort_order_locked': False, 'expanded': False, 'expanded_locked': False,
            'permissions': {'update': True, 'delete': True, 'reply': True}, 'assignment_id': None,
            'root_topic_id': None, 'group_category_id': None, 'topic_children': [], 'group_topic_children': [],
            'is_announcement': False, 'anonymous_state': None, 'author': {'id': 7, 'email': 'synthetic-private-author@example.edu'},
            'attachments': [{'id': 51, 'filename': 'synthetic.txt', 'display_name': 'Synthetic', 'size': 20,
                             'url': 'https://storage.example.edu/?token=synthetic-private-attachment'}],
            'podcast_url': 'https://example.edu/feed/synthetic-private-feed', 'secure_params': 'synthetic-private-token',
            'ungraded_discussion_overrides': [{'student_ids': [7], 'secret': 'synthetic-private-audience'}]}


class TopicClient:
    host = 'https://canvas.example.edu'

    def __init__(self):
        self.calls = []
        self.identity = 7
        self.context = {'name': 'Synthetic context', 'workflow_state': 'available'}
        self.topics = {9: topic(), 10: topic(10)}
        self.denied = self.written = self.ignore = self.after_denied = False
        self.sanitize = self.account_changed = self.context_changed = False
        self.ack_patch = self.after_patch = None
        self.list_patch = None
        self.list_fail = self.after_list_fail = False
        self.preflight_mutation = None
        self.reads = self.profiles = 0
        self.account_changed_at = None
        self.missing_status = 404
        self.ignored_fields = set()
        self.native_effects = []
        self.readable_after_delete = False
        self.deleted_topic = None

    def request(self, route, method='GET', body=None):
        self.calls.append((method, route, copy.deepcopy(body)))
        path = urlsplit(route).path
        if method != 'GET':
            if self.denied:
                raise CanvasError('Native editing restriction', status=403)
            identifier = int(path.rsplit('/', 1)[1])
            current = self.topics[identifier]
            self.written = True
            self.native_effects.append('activity')
            if method == 'DELETE':
                self.deleted_topic = copy.deepcopy(current)
                response = {'id': identifier, 'context_id': int(path.split('/')[4]),
                            'context_type': path.split('/')[3][:-1].title(), 'workflow_state': 'deleted',
                            'message': current['message'], 'user': {'name': 'synthetic-private-author'}}
                if not self.ignore:
                    self.topics.pop(identifier)
            else:
                if not self.ignore:
                    for key, value in body.items():
                        if key not in self.ignored_fields:
                            current[key] = value
                    if self.sanitize:
                        current['message'] = current['message'].replace('<br>', '<br />')
                response = copy.deepcopy(current)
            if self.ack_patch is not None:
                response = {**response, **self.ack_patch} if isinstance(self.ack_patch, dict) else self.ack_patch
            return response, ''
        if path == '/api/v1/users/self/profile':
            self.profiles += 1
            changed = self.written and self.account_changed or self.profiles == self.account_changed_at
            return {'id': 8 if changed else self.identity}, ''
        if '/discussion_topics/' in path:
            self.reads += 1
            if self.reads == 2 and self.preflight_mutation:
                self.preflight_mutation(self)
            if self.written and self.after_denied:
                raise CanvasError('synthetic-private-readback-denial', status=403)
            identifier = int(path.rsplit('/', 1)[1])
            if identifier not in self.topics:
                if self.readable_after_delete:
                    return copy.deepcopy(self.deleted_topic), ''
                raise CanvasError('Missing topic', status=self.missing_status)
            row = copy.deepcopy(self.topics[identifier])
            if self.written and self.after_patch:
                row.update(self.after_patch)
            return row, ''
        return {'id': int(path.rsplit('/', 1)[1]), **self.context,
                **({'name': 'Changed context'} if self.written and self.context_changed else {})}, ''

    def list(self, route, max_pages):
        self.calls.append(('GET', route, None))
        if self.list_fail or self.written and self.after_list_fail or max_pages < 2:
            raise CanvasError('Page limit reached')
        return copy.deepcopy(self.list_patch if self.list_patch is not None else list(self.topics.values()))


class TopicManagementTests(unittest.TestCase):
    def setUp(self):
        self.client = TopicClient()

    def preview(self, **options):
        return change(self.client, '123', '9', acknowledge_shared=True,
                      **({'title': 'New 🌿 title'} | options))

    def execute(self, **options):
        preview = self.preview(**options)
        return self.preview(yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [row for row in self.client.calls if row[0] != 'GET']

    def test_preview_contains_selected_changes_not_prior_prompt_signed_attachments_or_audience(self):
        result = self.preview(message='Hello <world>\n🌿')
        self.assertEqual(result['body'], {'title': 'New 🌿 title', 'message': '<p>Hello &lt;world&gt;<br>🌿</p>'})
        self.assertEqual(result['route'], '/api/v1/courses/123/discussion_topics/9?no_verifiers=true')
        self.assertEqual(result['topic']['author_id'], 7)
        self.assertNotIn('synthetic-private', str(result))
        self.assertEqual(self.writes(), [])
        self.assertFalse(any('/entries' in route or '/view' in route for _, route, _ in self.client.calls))

    def test_title_only_exact_put_preserves_prompt_attachment_and_other_topic(self):
        result = self.execute()
        self.assertTrue(result['acknowledgement_matches_readback'])
        self.assertEqual(result['changed_fields'], ['title'])
        self.assertEqual(result['unrequested_changed_fields'], [])
        self.assertEqual(result['stored_text_matches_request'], {'title': True})
        self.assertEqual(self.client.topics[10]['title'], 'Synthetic prompt')
        self.assertEqual(self.client.topics[9]['message'], topic()['message'])
        self.assertNotIn('synthetic-private', str(result))
        self.assertEqual(self.writes(), [('PUT', '/api/v1/courses/123/discussion_topics/9?no_verifiers=true', {'title': 'New 🌿 title'})])

    def test_native_permission_not_authorship_enrollment_or_draft_guesses(self):
        self.client.topics[9].update(published=False, locked=True, author={'id': 8}, locked_for_user=True)
        result = self.execute()
        self.assertFalse(result['edited_topic']['published'])
        self.assertTrue(result['edited_topic']['locked'])
        self.assertEqual(result['edited_topic']['author_id'], 8)
        for value in (False, None, 1, 'true'):
            self.setUp()
            self.client.topics[9]['permissions']['update'] = value
            with self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.writes(), [])

    def test_group_context_is_explicit_not_a_course_namespace(self):
        self.client.topics[9].update(context_id=18, context_type='Group')
        preview = change(self.client, '18', '9', context_type='group', title='Group prompt', acknowledge_shared=True)
        result = change(self.client, '18', '9', context_type='group', title='Group prompt', acknowledge_shared=True,
                        yes=True, confirm=preview['confirm'])
        self.assertEqual(result['group_id'], 18)
        self.assertEqual(result['edited_topic']['section_ids'], [])
        self.assertEqual(result['edited_topic']['html_url'], self.client.host + '/groups/18/discussion_topics/9')

    def test_course_section_audience_ids_are_bound_without_names_and_group_sections_are_refused(self):
        self.client.topics[9].update(is_section_specific=True,
                                    sections=[{'id': 33, 'name': 'synthetic-private-section', 'user_count': 4}])
        result = self.execute()
        self.assertEqual(result['edited_topic']['section_ids'], [33])
        self.assertNotIn('synthetic-private', str(result))
        self.setUp()
        self.client.topics[9].update(is_section_specific=True, sections=[{'id': 33}])
        with self.assertRaisesRegex(CanvasError, 'section-specific'):
            change(self.client, '18', '9', context_type='group', title='New', acknowledge_shared=True)
        self.assertEqual(self.writes(), [])

    def test_native_html_normalization_ignored_fields_and_collateral_changes_are_labeled(self):
        self.client.sanitize = True
        self.client.ignored_fields = {'title'}
        result = self.execute(message='First\nSecond')
        self.assertEqual(result['stored_text_matches_request'], {'title': False, 'message': False})
        self.assertIn('differs from the request', brief(result))
        self.setUp()
        self.client.ack_patch = {'posted_at': '2026-10-03T12:00:00Z'}
        self.client.after_patch = copy.deepcopy(self.client.ack_patch)
        result = self.execute()
        self.assertEqual(result['unrequested_changed_fields'], ['posted_at'])
        self.assertIn('Other observed changes', brief(result))

    def test_soft_delete_needs_delete_not_update_permission_and_preserves_other_topics(self):
        self.client.topics[9]['permissions']['update'] = False
        result = self.execute(title=None, delete=True, acknowledge_removal=True)
        self.assertTrue(result['removed_from_active_inventory'])
        self.assertEqual(result['exact_id_read_status'], 404)
        self.assertEqual(set(self.client.topics), {10})
        self.assertEqual(self.writes(), [('DELETE', '/api/v1/courses/123/discussion_topics/9?no_verifiers=true', None)])
        self.assertNotIn('synthetic-private', str(result))
        self.assertIn('soft-deleted', brief(result))
        self.setUp()
        self.client.topics[9]['permissions']['delete'] = False
        with self.assertRaisesRegex(CanvasError, 'delete'):
            self.preview(title=None, delete=True, acknowledge_removal=True)
        self.assertEqual(self.writes(), [])

    def test_delete_does_not_call_permission_denial_or_still_visible_topic_verified_absence(self):
        for mode in ('ignored', 'denied_read', 'missing403', 'still_readable', 'list_fail', 'bad_ack', 'account', 'context'):
            self.setUp()
            if mode == 'ignored':
                self.client.ignore = True
            elif mode == 'denied_read':
                self.client.after_denied = True
            elif mode == 'missing403':
                self.client.missing_status = 403
            elif mode == 'still_readable':
                self.client.readable_after_delete = True
            elif mode == 'list_fail':
                self.client.after_list_fail = True
            elif mode == 'bad_ack':
                self.client.ack_patch = {'workflow_state': 'active'}
            elif mode == 'account':
                self.client.account_changed = True
            else:
                self.client.context_changed = True
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'may already have succeeded'):
                self.execute(title=None, delete=True, acknowledge_removal=True)
            self.assertEqual(len(self.writes()), 1)

    def test_stale_content_permission_author_audience_counts_inventory_account_and_context_never_write(self):
        for mode in ('message', 'title', 'permissions', 'author', 'audience', 'count', 'attachment', 'inventory', 'account', 'context'):
            self.setUp()
            before = self.preview()
            row = self.client.topics[9]
            if mode in ('message', 'title'):
                row[mode] = 'Changed'
            elif mode == 'permissions':
                row['permissions']['delete'] = False
            elif mode == 'author':
                row['author']['id'] = 8
            elif mode == 'audience':
                row['ungraded_discussion_overrides'] = []
            elif mode == 'count':
                row['discussion_subentry_count'] = 1
            elif mode == 'attachment':
                row['attachments'][0]['id'] = 52
            elif mode == 'inventory':
                self.client.topics[10]['title'] = 'Changed'
            elif mode == 'account':
                self.client.identity = 8
            else:
                self.client.context['name'] = 'Changed'
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'Preview changed'):
                self.preview(yes=True, confirm=before['confirm'])
            self.assertEqual(self.writes(), [])

    def test_preflight_races_missing_inventory_and_page_limits_never_write(self):
        for mode in ('race', 'account', 'missing', 'duplicate', 'foreign', 'deleted', 'context_deleted', 'denied', 'limit'):
            self.setUp()
            if mode == 'race':
                self.client.preflight_mutation = lambda client: client.topics[9].update(message='Changed')
            elif mode == 'account':
                self.client.account_changed_at = 2
            elif mode in ('missing', 'duplicate', 'foreign'):
                self.client.list_patch = [topic(10)] if mode == 'missing' else [topic(), topic()]
                if mode == 'foreign':
                    self.client.list_patch = [{**topic(), 'context_id': 124}]
            elif mode == 'deleted':
                self.client.list_patch = [{**topic(), 'workflow_state': 'deleted'}]
            elif mode == 'context_deleted':
                self.client.context['workflow_state'] = 'deleted'
            elif mode == 'denied':
                self.client.list_fail = True
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(max_pages=1 if mode == 'limit' else 100)
            self.assertEqual(self.writes(), [])

    def test_foreign_linked_anonymous_announcements_and_incomplete_native_metadata_refused(self):
        for patch in ({'id': True}, {'id': 10}, {'context_id': 124}, {'context_type': 'Group'}, {'course_id': '123'},
                      {'assignment_id': 81}, {'assignment': {'id': 81}}, {'root_topic_id': 19}, {'group_category_id': 3},
                      {'topic_children': [19]}, {'group_topic_children': [{'id': 19}]}, {'anonymous_state': 'full_anonymity'},
                      {'is_announcement': True}, {'is_announcement': None}, {'published': 1}, {'locked': 'false'},
                      {'hidden_for_user': True}, {'workflow_state': 'deleted'}, {'message': []}, {'title': ''},
                      {'permissions': {}}, {'lock_info': {'can_view': False}}, {'lock_info': []},
                      {'attachments': {}}, {'attachments': [None]}, {'attachments': [{'id': 51, 'size': -1}]},
                      {'attachments': [{'id': 51, 'filename': {'url': 'synthetic-private'}}]},
                      {'attachments': [{'id': 51, 'updated_at': 'not-a-date'}]},
                      {'attachments': [topic()['attachments'][0], topic()['attachments'][0]]},
                      {'is_section_specific': True}, {'sections': [{'id': 31}, {'id': 31}]},
                      {'discussion_subentry_count': False}, {'position': -1}, {'created_at': 'not-a-date'},
                      {'sort_order': {}}, {'expanded': 1}, {'author': {'id': False}}):
            self.setUp()
            self.client.topics[9].update(patch)
            with self.subTest(patch=patch), self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.writes(), [])

    def test_unsupported_modes_and_invalid_inputs_are_rejected_before_network(self):
        for options in ({'acknowledge_shared': False}, {'acknowledge_removal': True}, {'delete': True},
                        {'delete': True, 'acknowledge_removal': True, 'title': 'Not deletion'},
                        {'title': None}, {'title': ''}, {'title': 'x' * 256}, {'title': '\x1b'}, {'title': '\ud800'},
                        {'message': ''}, {'message': '\x00'}, {'message': '\ud800'}, {'message': '<' * 10000},
                        {'max_pages': False}, {'max_pages': 0}, {'context_type': 'user'}, {'yes': True}, {'confirm': 'fake'}):
            self.setUp()
            with self.subTest(options=options), self.assertRaises(CanvasError):
                change(self.client, '123', '9', **({'title': 'New', 'acknowledge_shared': True} | options))
            self.assertEqual(self.client.calls, [])

    def test_no_op_and_empty_native_prompt_do_not_invent_changes(self):
        with self.assertRaisesRegex(CanvasError, 'no edit needed'):
            self.preview(title='Synthetic prompt')
        self.assertEqual(self.writes(), [])
        self.client.topics[9]['message'] = None
        self.client.topics[9]['attachments'] = None
        self.client.topics[9]['author'] = None
        result = self.execute(title=None, message='New prompt')
        self.assertEqual(result['stored_text_matches_request'], {'message': True})

    def test_native_attachment_revision_dates_are_metadata_only_and_missing_inventory_is_unknown(self):
        self.client.topics[9]['attachments'][0]['updated_at'] = '2026-10-01T12:00:00Z'
        self.assertTrue(self.execute()['acknowledgement_matches_readback'])
        self.setUp()
        self.client.topics[9].pop('attachments')
        with self.assertRaisesRegex(CanvasError, 'attachment inventory'):
            self.preview()
        self.assertEqual(self.writes(), [])
        self.setUp()
        self.client.context['name'] = {'secret': 'synthetic-private-name'}
        with self.assertRaisesRegex(CanvasError, 'context metadata'):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_after_write_uncertainty_hides_responses_and_never_retries(self):
        for mode in ('bad_id', 'bad_parent', 'bad_ack', 'readback', 'permission', 'denied_read', 'account', 'context', 'late_account'):
            self.setUp()
            if mode == 'bad_id':
                self.client.ack_patch = {'id': 10, 'secret': 'synthetic-private-ack'}
            elif mode == 'bad_parent':
                self.client.ack_patch = {'context_id': 124}
            elif mode == 'bad_ack':
                self.client.ack_patch = []
            elif mode == 'readback':
                self.client.after_patch = {'title': 'Different readback'}
            elif mode == 'permission':
                self.client.ack_patch = self.client.after_patch = {'permissions': {'update': False, 'delete': True}}
            elif mode == 'denied_read':
                self.client.after_denied = True
            elif mode == 'account':
                self.client.account_changed = True
            elif mode == 'context':
                self.client.context_changed = True
            else:
                self.client.account_changed_at = 6
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'may already have succeeded') as raised:
                self.execute()
            self.assertNotIn('synthetic-private', str(raised.exception))
            self.assertEqual(len(self.writes()), 1)

    def test_native_denial_is_not_retried_and_parser_help_schema_need_no_authentication(self):
        self.client.denied = True
        with self.assertRaisesRegex(CanvasError, 'Native editing restriction'):
            self.execute()
        self.assertEqual(len(self.writes()), 1)
        for command in ('topic-edit', 'topic-delete'):
            self.assertIn('--acknowledge-shared-topic', run(parser().parse_args(['help', command]))['help_text'])
            result = run(parser().parse_args(['schema', command]))
            self.assertEqual(result['commands'][0]['safety'], 'Canvas writes (preview-first)')
