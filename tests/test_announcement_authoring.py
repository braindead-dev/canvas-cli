"""Native announcement kind, broadcast, comment preservation and write evidence."""

import copy
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from test_topic_management import TopicClient, topic

from canvas_cli.announcement_authoring import change, create
from canvas_cli.cli import brief, parser, run
from canvas_cli.client import CanvasError


def announcement(identifier=9):
    return {**topic(identifier), 'is_announcement': True, 'can_unpublish': False,
            'can_lock': True, 'comments_disabled': False,
            'locked': True, 'type': 'Announcement', 'context_type': 'Course', 'context_id': 123}


class AnnouncementClient(TopicClient):
    def __init__(self):
        super().__init__()
        self.topics = {9: announcement(), 10: announcement(10)}
        self.creation = True
        self.permission_patch = self.creation_change_at = None
        self.permission_reads = 0
        self.force_comment_lock = self.ignore_posting = False
        self.ignore_comment_lock = self.keep_closing_date = False

    def request(self, route, method='GET', body=None):
        url = urlsplit(route)
        if method == 'GET' and parse_qs(url.query).get('include[]') == ['permissions']:
            result, link = super().request(route, method, body)
            self.permission_reads += 1
            if self.permission_reads == self.creation_change_at:
                self.creation = False
            result['permissions'] = self.permission_patch if self.permission_patch is not None else {'create_announcement': self.creation}
            return result, link
        if method == 'GET':
            return super().request(route, method, body)
        self.calls.append((method, route, copy.deepcopy(body)))
        if self.denied or method == 'POST' and not self.creation:
            raise CanvasError('synthetic-private-native-denial', status=403)
        self.written = True
        self.native_effects.append('participant/observer/activity')
        if method == 'DELETE':
            identifier = int(url.path.rsplit('/', 1)[1])
            self.deleted_topic = copy.deepcopy(self.topics[identifier])
            response = {'id': identifier, 'workflow_state': 'deleted', 'type': 'Announcement',
                        'context_type': 'Group' if '/groups/' in url.path else 'Course',
                        'context_id': 123, 'message': 'synthetic-private-delete-ack'}
            if not self.ignore:
                self.topics.pop(identifier)
        else:
            if method == 'POST':
                identifier = max(self.topics) + 1
                row = announcement(identifier)
                row['context_type'] = 'Group' if '/groups/' in url.path else 'Course'
                row.update(author={'id': self.identity}, attachments=None, pinned=False,
                           position=len(self.topics) + 1, delayed_post_at=None, title=body['title'], message=body['message'])
                self.topics[identifier] = row
            else:
                identifier = int(url.path.rsplit('/', 1)[1])
                row = self.topics[identifier]
            if not self.ignore:
                for key in ('title', 'message'):
                    if key in body:
                        row[key] = body[key]
                requested_lock = body.get('lock_comment', False)
                if row['locked'] and not requested_lock and not self.keep_closing_date:
                    row['lock_at'] = None
                if not self.ignore_comment_lock:
                    row['locked'] = True if self.force_comment_lock else requested_lock
                if 'delayed_post_at' in body and not self.ignore_posting:
                    row['delayed_post_at'] = body['delayed_post_at']
                if self.sanitize:
                    row['message'] = row['message'].replace('<br>', '<br />')
            response = copy.deepcopy(row)
        if self.ack_patch is not None:
            response = {**response, **self.ack_patch} if isinstance(self.ack_patch, dict) else self.ack_patch
        return response, ''

    def list(self, route, max_pages):
        if parse_qs(urlsplit(route).query).get('only_announcements') != ['true']:
            raise AssertionError('Unfiltered announcement inventory')
        return super().list(route, max_pages)


class AnnouncementTests(unittest.TestCase):
    def setUp(self):
        self.client = AnnouncementClient()

    def preview_create(self, **options):
        return create(self.client, '123', **({'title': 'Synthetic new announcement', 'message': 'Hello <team>\n🌿',
                                           'acknowledge_shared': True, 'acknowledge_broadcast': True} | options))

    def preview_change(self, **options):
        return change(self.client, '123', '9', **({'title': 'Synthetic updated announcement',
                                                'acknowledge_shared': True, 'acknowledge_broadcast': True} | options))

    def execute(self, operation, **options):
        preview = operation(**options)
        return operation(yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [row for row in self.client.calls if row[0] != 'GET']

    def test_create_preview_is_announcement_not_draft_and_does_not_edit_creator_preferences(self):
        preview = self.preview_create()
        self.assertEqual(preview['body'], {'title': 'Synthetic new announcement', 'message': '<p>Hello &lt;team&gt;<br>🌿</p>',
                                         'is_announcement': True, 'lock_comment': True})
        self.assertEqual(preview['posting_choice'], 'post_now')
        self.assertEqual(self.writes(), [])
        self.assertNotIn('synthetic-private', json.dumps(preview))
        self.assertNotIn('published', preview['body'])
        self.assertNotIn('locked', preview['body'])

    def test_create_one_post_new_id_own_author_exact_readback_and_inventory(self):
        result = self.execute(self.preview_create)
        self.assertEqual(result['created_announcement']['id'], 11)
        self.assertTrue(result['new_id_verified'])
        self.assertTrue(result['created_announcement']['is_announcement'])
        self.assertTrue(result['comments_locked'])
        self.assertEqual(result['stored_text_matches_request'], {'title': True, 'message': True})
        self.assertFalse(result['notification_delivery_verified'])
        self.assertFalse(result['future_execution_verified'])
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(self.writes()[0][0], 'POST')
        self.assertEqual(self.client.topics[9], announcement())
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertIn('announcement 11 created', brief(result))

    def test_future_course_posting_is_exact_and_published_is_not_delivery_proof(self):
        result = self.execute(self.preview_create, post_at='2030-10-01T09:00:00-07:00')
        self.assertEqual(result['stored_posting_at'], '2030-10-01T16:00:00Z')
        self.assertTrue(result['created_announcement']['published'])
        self.assertFalse(result['future_execution_verified'])
        self.assertIn('future execution and delivery are unverified', brief(result))
        self.assertEqual(self.writes()[0][2]['delayed_post_at'], '2030-10-01T16:00:00Z')

    def test_comments_choice_native_override_and_ignored_schedule_are_not_silently_repaired(self):
        result = self.execute(self.preview_create, comments=True)
        self.assertFalse(result['comments_locked'])
        for field, options in (('force_comment_lock', {'comments': True}),
                               ('ignore_posting', {'post_at': '2030-10-01T16:00:00Z'})):
            self.client = AnnouncementClient()
            setattr(self.client, field, True)
            with self.subTest(field=field), self.assertRaisesRegex(CanvasError, 'may already have succeeded'):
                self.execute(self.preview_create, **options)
            self.assertEqual(len(self.writes()), 1)

    def test_text_edit_preserves_open_and_closed_comments_without_locked_or_preference_write(self):
        for locked in (True, False):
            self.client = AnnouncementClient()
            self.client.topics[9]['locked'] = locked
            preview = self.preview_change()
            self.assertEqual(preview['body']['lock_comment'], locked)
            self.assertNotIn('locked', preview['body'])
            result = self.preview_change(yes=True, confirm=preview['confirm'])
            self.assertTrue(result['comment_lock_preserved'])
            self.assertEqual(result['edited_announcement']['locked'], locked)
            self.assertEqual(result['stored_text_matches_request'], {'title': True})
            self.assertEqual(len(self.writes()), 1)
            self.assertNotIn('synthetic-private', json.dumps(result))

    def test_html_normalization_is_labeled_and_existing_other_fields_are_not_sent(self):
        self.client.sanitize = True
        result = self.execute(self.preview_change, title=None, message='One\nTwo')
        self.assertFalse(result['stored_text_matches_request']['message'])
        self.assertIn('Stored text differs', brief(result))
        self.assertEqual(set(self.writes()[0][2]), {'message', 'is_announcement', 'lock_comment'})
        self.assertEqual(result['unrequested_changed_fields'], [])

    def test_soft_delete_is_exact_with_inventory_absence_id_not_found_and_no_recall_claim(self):
        result = self.execute(self.preview_change, title=None, delete=True, acknowledge_broadcast=False, acknowledge_removal=True)
        self.assertEqual(result['deleted_announcement']['id'], 9)
        self.assertEqual(result['exact_id_read_status'], 404)
        self.assertTrue(result['removed_from_active_inventory'])
        self.assertFalse(result['notification_delivery_verified'])
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(self.writes()[0][0], 'DELETE')
        self.assertNotIn('synthetic-private', json.dumps(result))

    def test_invalid_local_inputs_and_acknowledgements_never_touch_network(self):
        for options in ({'title': None}, {'title': ''}, {'message': None}, {'message': ''}, {'message': '\ud800'},
                        {'comments': 1}, {'comments': 'false'}, {'context_type': 'user'}, {'max_pages': 0}, {'max_pages': True},
                        {'acknowledge_shared': False}, {'acknowledge_broadcast': False}, {'yes': True}, {'confirm': 'fake'},
                        {'post_at': '2026-01-01T12:00:00Z'}, {'post_at': '2030-10-01T12:00:00'},
                        {'post_at': '2030-10-01T12:00:00.1Z'}, {'post_at': '2030-10-01T12:00:00Z', 'context_type': 'group'}):
            self.client = AnnouncementClient()
            with self.subTest(options=repr(options)), self.assertRaises(CanvasError):
                self.preview_create(**options)
            self.assertEqual(self.client.calls, [])
        for options in ({'delete': 1}, {'acknowledge_broadcast': False}, {'delete': True},
                        {'delete': True, 'acknowledge_broadcast': False, 'acknowledge_removal': True},
                        {'acknowledge_removal': True}, {'title': None}):
            self.client = AnnouncementClient()
            with self.subTest(options=options), self.assertRaises(CanvasError):
                self.preview_change(**options)
            self.assertEqual(self.client.calls, [])

    def test_dynamic_creation_permission_is_exact_and_different_from_discussion_creation(self):
        for value in ({}, [], {'create_announcement': False}, {'create_announcement': 1},
                      {'create_announcement': 'true'}, {'create_discussion_topic': True}):
            self.client = AnnouncementClient()
            self.client.permission_patch = value
            with self.subTest(value=value), self.assertRaises(CanvasError):
                self.preview_create()
            self.assertEqual(self.writes(), [])
        self.client = AnnouncementClient()
        self.client.creation_change_at = 2
        with self.assertRaises(CanvasError):
            self.preview_create()
        self.assertEqual(self.writes(), [])

    def test_unreadable_wrong_kind_foreign_draft_or_ineligible_delete_never_mutates(self):
        for changes in ({'is_announcement': False}, {'is_announcement': 1}, {'published': False}, {'can_unpublish': True},
                        {'assignment_id': 4}, {'anonymous_state': 'partial_anonymity'}, {'context_id': 124},
                        {'hidden_for_user': True}, {'permissions': {'update': False, 'delete': True}},
                        {'lock_info': {'can_view': False}}):
            self.client = AnnouncementClient()
            self.client.topics[9].update(changes)
            with self.subTest(changes=changes), self.assertRaises(CanvasError):
                self.preview_change()
            self.assertEqual(self.writes(), [])
        self.client = AnnouncementClient()
        self.client.topics[9]['permissions']['delete'] = False
        with self.assertRaises(CanvasError):
            self.preview_change(title=None, delete=True, acknowledge_broadcast=False, acknowledge_removal=True)

    def test_stale_account_context_content_comment_lock_inventory_and_permission_do_not_write(self):
        for field in ('account', 'context', 'title', 'message', 'locked', 'permission', 'inventory'):
            self.client = AnnouncementClient()
            preview = self.preview_change()
            if field == 'account':
                self.client.identity = 8
            elif field == 'context':
                self.client.context['name'] = 'Changed'
            elif field == 'permission':
                self.client.topics[9]['permissions']['update'] = False
            elif field == 'inventory':
                self.client.topics[10]['title'] = 'Changed'
            elif field == 'locked':
                self.client.topics[9]['locked'] = False
            else:
                self.client.topics[9][field] = 'Synthetic changed content'
            with self.subTest(field=field), self.assertRaises(CanvasError):
                self.preview_change(yes=True, confirm=preview['confirm'])
            self.assertEqual(self.writes(), [])

    def test_failed_post_write_acknowledgements_and_readback_are_uncertain_without_retry(self):
        for field, value in (('ack_patch', []), ('ack_patch', {'is_announcement': False}), ('ack_patch', {'author': {'id': 8}}),
                             ('ack_patch', {'id': 9}), ('after_denied', True), ('after_list_fail', True),
                             ('account_changed', True), ('context_changed', True), ('after_patch', {'locked': False})):
            self.client = AnnouncementClient()
            setattr(self.client, field, value)
            with self.subTest(field=field, value=value), self.assertRaisesRegex(CanvasError, 'may already have succeeded') as error:
                self.execute(self.preview_create)
            self.assertNotIn('synthetic-private', str(error.exception))
            self.assertEqual(len(self.writes()), 1)
        for value in ({'id': 10}, {'type': 'DiscussionTopic'}, {'workflow_state': 'active'}):
            self.client = AnnouncementClient()
            self.client.ack_patch = value
            with self.assertRaisesRegex(CanvasError, 'may already have succeeded'):
                self.execute(self.preview_change, title=None, delete=True, acknowledge_broadcast=False, acknowledge_removal=True)
            self.assertEqual(len(self.writes()), 1)

    def test_group_creation_and_edit_use_group_namespace_without_scheduling(self):
        for row in self.client.topics.values():
            row.update(context_type='Group', context_id=123)
        preview = self.preview_create(context_type='group')
        self.assertIn('/groups/123/', preview['route'])
        self.assertNotIn('delayed_post_at', preview['body'])
        self.assertEqual(self.writes(), [])
        preview = self.preview_change(context_type='group')
        self.assertIn('/groups/123/', preview['route'])

    def test_schedule_expiry_is_rechecked_after_preflight_and_before_post(self):
        with patch('canvas_cli.announcement_authoring.datetime') as clock:
            clock.now.side_effect = [datetime(2030, 10, 1, 15, 58, tzinfo=timezone.utc),
                                     datetime(2030, 10, 1, 15, 59, 30, tzinfo=timezone.utc)]
            with self.assertRaisesRegex(CanvasError, '60 seconds'):
                self.preview_create(post_at='2030-10-01T16:00:00Z')
        self.assertEqual(self.writes(), [])

    def test_context_permission_response_must_identify_the_same_context_revision(self):
        for changes in ({'id': 124}, {'name': 'Changed during permission read'}):
            self.client = AnnouncementClient()
            request = self.client.request

            def altered(route, method='GET', body=None):
                row, link = request(route, method, body)
                if parse_qs(urlsplit(route).query).get('include[]') == ['permissions']:
                    row.update(changes)
                return row, link

            with patch.object(self.client, 'request', side_effect=altered), self.assertRaisesRegex(CanvasError, 'context changed'):
                self.preview_create()
            self.assertEqual(self.writes(), [])

    def test_mid_preflight_inventory_account_or_exact_prompt_drift_never_writes(self):
        for mode in ('creation_inventory', 'creation_account', 'edit_prompt', 'edit_missing_inventory'):
            self.client = AnnouncementClient()
            if mode == 'creation_inventory':
                listing = self.client.list
                count = 0

                def changed_inventory(route, max_pages):
                    nonlocal count
                    count += 1
                    if count == 2:
                        self.client.topics[10]['title'] = 'Changed inventory revision'
                    return listing(route, max_pages)

                self.client.list = changed_inventory
            elif mode == 'creation_account':
                self.client.account_changed_at = 2
            elif mode == 'edit_prompt':
                self.client.preflight_mutation = lambda client: client.topics[9].update(locked=False)
            else:
                self.client.list_patch = [announcement(10)]
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'changed during preflight'):
                (self.preview_create if mode.startswith('creation') else self.preview_change)()
            self.assertEqual(self.writes(), [])

    def test_identical_text_refuses_a_redundant_broadcasting_update(self):
        with self.assertRaisesRegex(CanvasError, 'already matches'):
            self.preview_change(title='Synthetic prompt')
        self.assertEqual(self.writes(), [])

    def test_hidden_inventory_or_late_account_drift_after_creation_is_uncertain(self):
        for mode in ('inventory', 'account'):
            self.client = AnnouncementClient()
            if mode == 'inventory':
                listing = self.client.list

                def hidden_new_row(route, max_pages):
                    rows = listing(route, max_pages)
                    return [row for row in rows if row['id'] < 11] if self.client.written else rows

                self.client.list = hidden_new_row
            else:
                self.client.account_changed_at = 6
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'may already have succeeded'):
                self.execute(self.preview_create)
            self.assertEqual(len(self.writes()), 1)

    def test_edit_post_write_context_content_lock_inventory_and_last_account_are_verified(self):
        for mode in ('context', 'account', 'late_account', 'content', 'lock', 'inventory'):
            self.client = AnnouncementClient()
            if mode == 'context':
                self.client.context_changed = True
            elif mode == 'account':
                self.client.account_changed = True
            elif mode == 'late_account':
                self.client.account_changed_at = 6
            elif mode == 'content':
                self.client.after_patch = {'title': 'Different readback'}
            elif mode == 'lock':
                self.client.topics[9]['locked'] = False
                self.client.force_comment_lock = True
            else:
                listing = self.client.list

                def hidden_edited_row(route, max_pages):
                    rows = listing(route, max_pages)
                    return [row for row in rows if row['id'] != 9] if self.client.written else rows

                self.client.list = hidden_edited_row
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'may already have succeeded') as error:
                self.execute(self.preview_change)
            self.assertNotIn('synthetic-private', str(error.exception))
            self.assertEqual(len(self.writes()), 1)

    def test_delete_requires_inventory_absence_and_actual_not_found_not_just_ack_or_denial(self):
        for mode in ('ignored', 'denied', 'readable', 'foreign_ack', 'gone'):
            self.client = AnnouncementClient()
            if mode == 'ignored':
                self.client.ignore = True
            elif mode == 'denied':
                self.client.missing_status = 403
            elif mode == 'readable':
                self.client.readable_after_delete = True
            elif mode == 'foreign_ack':
                self.client.ack_patch = {'context_id': 124}
            else:
                self.client.missing_status = 410
            options = {'title': None, 'delete': True, 'acknowledge_broadcast': False, 'acknowledge_removal': True}
            if mode == 'gone':
                result = self.execute(self.preview_change, **options)
                self.assertEqual(result['exact_id_read_status'], 410)
                self.assertIn('announcement 9 deleted', brief(result))
            else:
                with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'may already have succeeded'):
                    self.execute(self.preview_change, **options)
            self.assertEqual(len(self.writes()), 1)

    def test_parser_dispatch_and_safety_catalog_have_preview_first_commands(self):
        for command in ('announcement-create', 'announcement-edit', 'announcement-delete'):
            schema = run(parser().parse_args(['schema', command]))['commands'][0]
            self.assertEqual(schema['safety'], 'Canvas writes (preview-first)')
        with patch('canvas_cli.announcement_authoring.change') as operation:
            args = parser().parse_args(['announcement-delete', '123', '9', '--acknowledge-shared-announcement',
                                       '--acknowledge-announcement-removal'])
            from canvas_cli.dispatch import execute
            execute(self.client, args)
            self.assertTrue(operation.call_args.kwargs['delete'])
            self.assertFalse(operation.call_args.kwargs['acknowledge_broadcast'])


if __name__ == '__main__':
    unittest.main()
