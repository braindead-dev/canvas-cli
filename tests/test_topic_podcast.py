"""Native feed flag coupling, moderation and credential-free mutation evidence."""

import copy
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from test_announcement_authoring import announcement as native_announcement
from test_topic_management import TopicClient

from canvas_cli import announcement_authoring, topic_management, topic_podcast
from canvas_cli.cli import brief, parser, run
from canvas_cli.client import CanvasError
from canvas_cli.writes import digest


class PodcastClient(TopicClient):
    def __init__(self, *, announcement=False, context='course'):
        super().__init__()
        self.announcement = announcement
        self.context_type = context
        if announcement:
            self.topics = {identifier: native_announcement(identifier) for identifier in (9, 10)}
        for row in self.topics.values():
            row.update(podcast_url=None, podcast_has_student_posts=False,
                       context_type=context.title(), context_id=123)
        self.moderator = True
        self.permission_report = None
        self.permission_reads = 0
        self.permission_change_at = None
        self.granular_denied = self.error_after_write = self.lose_moderation = self.lose_update = False
        self.force_lock = False

    def request(self, route, method='GET', body=None):
        path = urlsplit(route).path
        if method == 'GET' and path.endswith('/permissions'):
            self.calls.append((method, route, body))
            self.permission_reads += 1
            if self.permission_reads == self.permission_change_at:
                self.moderator = False
            report = {'moderate_forum': self.moderator, 'private': 'synthetic-private-permission'}
            return copy.deepcopy(report if self.permission_report is None else self.permission_report), ''
        if method == 'PUT':
            self.calls.append((method, route, copy.deepcopy(body)))
            if self.denied or self.topics[9]['permissions']['update'] is not True:
                raise CanvasError('synthetic-private-native-denial', status=403)
            self.written = True
            self.native_effects.append('activity/notifications')
            row = self.topics[9]
            selected = dict(body)
            if self.context_type == 'group':
                selected.pop('podcast_has_student_posts', None)
            if self.moderator is not True or self.context_type == 'course' and self.granular_denied:
                selected = {}
            if not self.ignore:
                if selected.get('podcast_has_student_posts') is True:
                    selected['podcast_enabled'] = True
                if 'podcast_has_student_posts' in selected and 'podcast_has_student_posts' not in self.ignored_fields:
                    row['podcast_has_student_posts'] = selected['podcast_has_student_posts']
                if 'podcast_enabled' in selected and 'podcast_enabled' not in self.ignored_fields:
                    row['podcast_url'] = ('/feeds/topics/9/enrollment_synthetic-private-feed.rss'
                                          if selected['podcast_enabled'] else None)
                if self.announcement:
                    row['locked'] = body.get('lock_comment', False)
                if self.force_lock:
                    row['locked'] = not row['locked']
            if self.lose_moderation:
                self.moderator = False
            if self.lose_update:
                row['permissions']['update'] = False
            if self.error_after_write:
                raise CanvasError('synthetic-private-error-after-storing-feed', status=500)
            result = copy.deepcopy(row)
            if self.ack_patch is not None:
                result = result | self.ack_patch if isinstance(self.ack_patch, dict) else self.ack_patch
            return result, ''
        return super().request(route, method, body)


class PodcastTests(unittest.TestCase):
    def reset(self, *, announcement=False, context='course'):
        self.client = PodcastClient(announcement=announcement, context=context)

    def setUp(self):
        self.reset()

    def preview(self, **options):
        change = announcement_authoring.change if self.client.announcement else topic_management.change
        defaults = {'context_type': self.client.context_type, 'podcast': 'enabled' if self.client.context_type == 'group' else 'all-posts',
                    'acknowledge_shared': True, 'acknowledge_podcast': True}
        if self.client.announcement:
            defaults['acknowledge_broadcast'] = True
        return change(self.client, '123', '9', **(defaults | options))

    def approved(self, **options):
        preview = self.preview(**options)
        return self.preview(yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [call for call in self.client.calls if call[0] != 'GET']

    def test_exact_course_modes_and_group_modes_follow_native_coupling_not_generic_booleans(self):
        self.assertEqual(topic_podcast.validate('disabled', 'course'), {'podcast_enabled': False, 'podcast_has_student_posts': False})
        self.assertEqual(topic_podcast.validate('moderator-posts', 'course'), {'podcast_enabled': True, 'podcast_has_student_posts': False})
        self.assertEqual(topic_podcast.validate('all-posts', 'course'), {'podcast_enabled': True, 'podcast_has_student_posts': True})
        self.assertEqual(topic_podcast.validate('enabled', 'group'), {'podcast_enabled': True})
        self.assertEqual(topic_podcast.validate('disabled', 'group'), {'podcast_enabled': False})
        for mode, context in ((None, 'course'), (True, 'course'), ({}, 'course'), ('other', 'course'),
                              ('enabled', 'course'), ('all-posts', 'group'), ('moderator-posts', 'group'), ('disabled', 'user')):
            with self.subTest(mode=mode, context=context), self.assertRaises(CanvasError):
                topic_podcast.validate(mode, context)

    def test_preview_checks_exact_moderation_without_feed_urls_peer_reads_or_mutation(self):
        for kind in (False, True):
            self.reset(announcement=kind)
            self.client.topics[9]['podcast_url'] = '/feeds/topics/9/enrollment_synthetic-private-old-feed.rss'
            result = self.preview()
            expected = {'podcast_enabled': True, 'podcast_has_student_posts': True}
            if kind:
                expected.update(is_announcement=True, lock_comment=True)
            self.assertEqual(result['body'], expected)
            self.assertEqual(result['podcast_permissions'], {'moderate_forum': True})
            self.assertTrue(result['acknowledge_podcast_feed_change'])
            row = result['announcement' if kind else 'topic']
            self.assertEqual(row['podcast_url_digest'], digest(self.client.topics[9]['podcast_url']))
            self.assertNotIn('podcast_url', row)
            self.assertNotIn('synthetic-private', json.dumps(result))
            self.assertEqual(self.client.permission_reads, 2)
            self.assertEqual(self.writes(), [])
            self.assertFalse(any('/feeds/' in route or '/entries' in route or '/view' in route for _, route, _ in self.client.calls))

    def test_course_modes_one_put_verify_exact_flags_with_other_authors_and_no_create_delete_rights(self):
        for kind in (False, True):
            for mode in ('moderator-posts', 'all-posts', 'disabled'):
                self.reset(announcement=kind)
                self.client.topics[9]['author']['id'] = 8
                self.client.topics[9]['permissions']['delete'] = False
                if mode == 'disabled':
                    self.client.topics[9].update(podcast_url='/feeds/topics/9/enrollment_synthetic-private-old.rss', podcast_has_student_posts=True)
                before = copy.deepcopy(self.client.topics)
                result = self.approved(podcast=mode)
                stored = topic_podcast.validate(mode, 'course')
                self.assertEqual(result['podcast_settings'], {'mode': mode, 'stored': stored, 'verified': True,
                                 'course_student_filter_selected': True, 'feed_access_verified': False, 'feed_code_revocation_verified': False})
                self.assertEqual(self.client.topics[9]['locked'], before[9]['locked'])
                self.assertEqual(self.client.topics[10], before[10])
                self.assertEqual(len(self.writes()), 1)
                self.assertEqual(self.writes()[0][:2], ('PUT', '/api/v1/courses/123/discussion_topics/9?no_verifiers=true'))
                self.assertEqual(self.writes()[0][2], stored | ({'is_announcement': True, 'lock_comment': True} if kind else {}))
                self.assertIn('Stored podcast mode verified: ' + mode, brief(result))
                self.assertNotIn('synthetic-private', json.dumps(result))

    def test_group_only_changes_enable_flag_and_preserves_stored_but_inapplicable_student_filter(self):
        for kind in (False, True):
            for mode in ('enabled', 'disabled'):
                self.reset(announcement=kind, context='group')
                self.client.topics[9]['podcast_has_student_posts'] = True
                if mode == 'disabled':
                    self.client.topics[9]['podcast_url'] = '/feeds/topics/9/group_synthetic-private-feed.rss'
                result = self.approved(podcast=mode)
                self.assertEqual(result['podcast_settings']['stored'], {'podcast_enabled': mode == 'enabled'})
                self.assertFalse(result['podcast_settings']['course_student_filter_selected'])
                self.assertTrue(self.client.topics[9]['podcast_has_student_posts'])
                self.assertNotIn('podcast_has_student_posts', self.writes()[0][2])
                self.assertIn('/groups/123/', self.writes()[0][1])

    def test_noop_refuses_and_course_disabled_clears_a_retained_student_filter(self):
        for kind in (False, True):
            self.reset(announcement=kind)
            with self.assertRaisesRegex(CanvasError, 'already matches'):
                self.preview(podcast='disabled')
            self.assertEqual(self.writes(), [])
            self.client.topics[9]['podcast_has_student_posts'] = True
            result = self.approved(podcast='disabled')
            self.assertEqual(result['changed_fields'], ['podcast_has_student_posts'])
            self.assertFalse(self.client.topics[9]['podcast_has_student_posts'])

    def test_local_consent_wrong_context_modes_and_combined_operations_refuse_before_api(self):
        for kind in (False, True):
            for options in ({'acknowledge_podcast': False}, {'acknowledge_podcast': 1}, {'podcast': None},
                            {'podcast': 'enabled'}, {'context_type': 'user'}, {'podcast': 'other'},
                            {'title': 'Combined'}, {'message': 'Combined'}, {'sections': {'specific_sections': 'all'}, 'acknowledge_audience': True},
                            {'schedule': {'lock_at': None}, 'acknowledge_availability': True},
                            {'yes': True}, {'confirm': 'unpaired'}, {'max_pages': 0}, {'acknowledge_shared': False}):
                self.reset(announcement=kind)
                with self.subTest(kind=kind, options=options), self.assertRaises(CanvasError):
                    self.preview(**options)
                self.assertEqual(self.client.calls, [])
            if kind:
                for options in ({'comments': True, 'acknowledge_comments': True}, {'acknowledge_broadcast': False},
                                {'remove_attachment': True, 'acknowledge_attachment_removal': True}):
                    self.reset(announcement=kind)
                    with self.assertRaises(CanvasError):
                        self.preview(**options)
                    self.assertEqual(self.client.calls, [])

    def test_missing_denied_nonboolean_moderation_update_or_incomplete_inventory_never_write(self):
        for kind in (False, True):
            for mode in ('moderation', 'missing', 'nonboolean', 'list', 'update', 'pages', 'permission-preflight'):
                self.reset(announcement=kind)
                if mode == 'moderation':
                    self.client.moderator = False
                elif mode == 'missing':
                    self.client.permission_report = {}
                elif mode == 'nonboolean':
                    self.client.permission_report = {'moderate_forum': 1}
                elif mode == 'list':
                    self.client.permission_report = []
                elif mode == 'update':
                    self.client.topics[9]['permissions']['update'] = False
                elif mode == 'permission-preflight':
                    self.client.permission_change_at = 2
                with self.subTest(kind=kind, mode=mode), self.assertRaises(CanvasError):
                    self.preview(max_pages=1 if mode == 'pages' else 100)
                self.assertEqual(self.writes(), [])

    def test_malformed_missing_foreign_feed_metadata_is_refused_and_not_disclosed(self):
        for row in ({'podcast_has_student_posts': None}, {'podcast_has_student_posts': 1}, {'podcast_has_student_posts': 'true'},
                    {'podcast_url': True}, {'podcast_url': []}, {'podcast_url': ''},
                    {'podcast_url': '/feeds/topics/10/enrollment_synthetic-private.rss'},
                    {'podcast_url': 'https://foreign.example/feeds/topics/9/enrollment_synthetic-private.rss'},
                    {'podcast_url': '/feeds/topics/9/enrollment_synthetic-private.rss?token=secret'},
                    {'podcast_url': '/feeds/topics/9/../../synthetic-private.rss'},
                    {'podcast_url': '/feeds/topics/9/' + 'a' * 2049 + '.rss'}):
            self.reset()
            self.client.topics[9].update(row)
            with self.subTest(row=row), self.assertRaises(CanvasError) as result:
                self.preview()
            self.assertNotIn('synthetic-private', str(result.exception))
            self.assertEqual(self.writes(), [])
        for key in ('podcast_url', 'podcast_has_student_posts'):
            self.reset()
            self.client.topics[9].pop(key)
            with self.assertRaises(CanvasError):
                self.preview()

    def test_stale_feed_code_flags_prompt_author_context_inventory_account_or_rights_never_put(self):
        for kind in (False, True):
            for mode in ('feed', 'flag', 'prompt', 'author', 'context', 'inventory', 'account', 'update', 'moderation'):
                self.reset(announcement=kind)
                self.client.topics[9]['podcast_url'] = '/feeds/topics/9/enrollment_synthetic-private-before.rss'
                preview = self.preview()
                if mode == 'feed':
                    self.client.topics[9]['podcast_url'] = '/feeds/topics/9/enrollment_synthetic-private-changed.rss'
                elif mode == 'flag':
                    self.client.topics[9]['podcast_has_student_posts'] = True
                elif mode == 'prompt':
                    self.client.topics[9]['message'] = 'Changed'
                elif mode == 'author':
                    self.client.topics[9]['author']['id'] = 8
                elif mode == 'context':
                    self.client.context['name'] = 'Changed'
                elif mode == 'inventory':
                    self.client.topics[10]['title'] = 'Changed'
                elif mode == 'account':
                    self.client.identity = 8
                elif mode == 'update':
                    self.client.topics[9]['permissions']['update'] = False
                else:
                    self.client.moderator = False
                with self.subTest(kind=kind, mode=mode), self.assertRaises(CanvasError) as result:
                    self.preview(yes=True, confirm=preview['confirm'])
                self.assertNotIn('may already have succeeded', str(result.exception))
                self.assertEqual(self.writes(), [])

    def test_native_ignored_flags_late_permission_loss_or_write_error_are_uncertain_never_retried(self):
        for kind in (False, True):
            for mode in ('ignored', 'granular', 'moderation', 'update', 'error', 'denied', 'lock', 'one-flag'):
                self.reset(announcement=kind)
                preview = self.preview()
                if mode == 'ignored':
                    self.client.ignore = True
                elif mode == 'granular':
                    self.client.granular_denied = True
                elif mode == 'moderation':
                    self.client.lose_moderation = True
                elif mode == 'update':
                    self.client.lose_update = True
                elif mode == 'error':
                    self.client.error_after_write = True
                elif mode == 'denied':
                    self.client.denied = True
                elif mode == 'lock':
                    self.client.force_lock = True
                else:
                    self.client.ignored_fields = {'podcast_has_student_posts'}
                with self.subTest(kind=kind, mode=mode), self.assertRaisesRegex(CanvasError, 'may already have succeeded') as result:
                    self.preview(yes=True, confirm=preview['confirm'])
                self.assertNotIn('synthetic-private', str(result.exception))
                self.assertEqual(len(self.writes()), 1)

    def test_bad_ack_independent_readback_inventory_account_context_or_metadata_fail_after_one_attempt(self):
        for kind in (False, True):
            for mode in ('ack', 'readback', 'feed-readback', 'inventory', 'account', 'context', 'missing-field'):
                self.reset(announcement=kind)
                if mode == 'ack':
                    self.client.ack_patch = {'id': 10}
                elif mode == 'readback':
                    self.client.after_denied = True
                elif mode == 'feed-readback':
                    self.client.after_patch = {'podcast_url': '/feeds/topics/9/enrollment_synthetic-private-different.rss'}
                elif mode == 'inventory':
                    self.client.after_list_fail = True
                elif mode == 'account':
                    self.client.account_changed = True
                elif mode == 'context':
                    self.client.context_changed = True
                else:
                    self.client.ack_patch = {'podcast_has_student_posts': None}
                with self.subTest(kind=kind, mode=mode), self.assertRaisesRegex(CanvasError, 'may already have succeeded'):
                    self.approved()
                self.assertEqual(len(self.writes()), 1)

    def test_normal_topic_and_announcement_edits_do_not_require_podcast_fields_or_moderation(self):
        for kind in (False, True):
            self.reset(announcement=kind)
            self.client.moderator = False
            self.client.topics[9].pop('podcast_has_student_posts')
            result = self.preview(podcast=None, acknowledge_podcast=False, title='Changed')
            self.assertNotIn('podcast_mode', result)
            self.assertEqual(self.client.permission_reads, 0)
            self.assertNotIn('podcast_enabled', result['body'])

    def test_parser_dispatch_help_schema_and_safety_are_derived_offline(self):
        for kind in ('topic', 'announcement'):
            command = [kind + '-podcast', '123', '9', '--mode', 'all-posts', '--acknowledge-shared-' + kind,
                       '--acknowledge-podcast-feed-change']
            if kind == 'announcement':
                command.append('--acknowledge-broadcast')
            with patch('canvas_cli.' + ('topic_management' if kind == 'topic' else 'announcement_authoring') + '.change') as change:
                from canvas_cli.dispatch import execute
                execute(object(), parser().parse_args(command))
                self.assertEqual(change.call_args.args[1:], ('123', '9'))
                self.assertEqual(change.call_args.kwargs['podcast'], 'all-posts')
                self.assertTrue(change.call_args.kwargs['acknowledge_podcast'])
            with patch('canvas_cli.auth.connect') as connect:
                help_data = run(parser().parse_args(['help', kind + '-podcast']))
                schema = run(parser().parse_args(['schema', kind + '-podcast']))
                self.assertIn('--mode', str(schema))
                self.assertIn('Canvas writes (preview-first)', str(help_data))
                connect.assert_not_called()
