"""Installed topic/announcement podcast settings against synthetic native HTTPS."""

import copy
import json

from . import announcement_authoring, topic_management
from .fixture import CanvasFixture


class PodcastE2E(CanvasFixture):
    def setUp(self):
        self.reset()

    def reset(self, *, announcement=False, group=False):
        self.kind = 'announcement' if announcement else 'topic'
        self.group = group
        announcement_authoring.initialize(type(self), enabled=announcement)
        topic_management.initialize(type(self), enabled=not announcement)
        self.context_id = '123' if announcement else '119' if group else '111'
        self.identifier = '9' if announcement else '901'
        if not announcement:
            type(self).topic_moderator = True
            type(self).topic_podcast_enabled = type(self).topic_state_enabled = True
        self.rows()[int(self.identifier)].update(podcast_url=None, podcast_has_student_posts=False)

    def rows(self):
        return self.announcements if self.kind == 'announcement' else self.managed_topics

    def selected(self):
        return self.rows()[int(self.identifier)]

    def command(self, *extra, mode=None, consent=True):
        selected = mode or ('enabled' if self.group else 'all-posts')
        return (self.kind + '-podcast', self.context_id, self.identifier, '--context', 'group' if self.group else 'course',
                '--mode', selected, '--acknowledge-shared-' + self.kind,
                *(('--acknowledge-broadcast',) if self.kind == 'announcement' else ()),
                *(('--acknowledge-podcast-feed-change',) if consent else ()), *extra)

    def approved(self, command):
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def writes(self, before):
        return [call for call in self.calls[before:] if call[0] != 'GET']

    def configure(self, announcement_option, topic_option, value):
        setattr(type(self), announcement_option if self.kind == 'announcement' else topic_option, value)

    def test_course_and_group_topic_and_announcement_one_put_exact_mode_lock_and_sibling_preservation(self):
        for announcement in (False, True):
            for group in (False, True):
                self.reset(announcement=announcement, group=group)
                source = copy.deepcopy(self.rows())
                before = len(self.calls)
                preview = self.invoke(*self.command())
                self.assertEqual(preview.returncode, 0, preview.stderr)
                data = json.loads(preview.stdout)
                body = {'podcast_enabled': True} | ({} if group else {'podcast_has_student_posts': True})
                if announcement:
                    body.update(is_announcement=True, lock_comment=True)
                self.assertEqual(data['body'], body)
                self.assertEqual(data['podcast_permissions'], {'moderate_forum': True})
                self.assertEqual(self.writes(before), [])
                result = self.invoke(*self.command(), '--yes', '--confirm', data['confirm'])
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)
                settings = data['podcast_settings']
                self.assertEqual(settings['stored'], {'podcast_enabled': True} | ({} if group else {'podcast_has_student_posts': True}))
                self.assertTrue(settings['verified'])
                self.assertFalse(settings['feed_access_verified'])
                self.assertFalse(settings['feed_code_revocation_verified'])
                self.assertEqual(settings['course_student_filter_selected'], not group)
                for identifier, row in self.rows().items():
                    if identifier != int(self.identifier):
                        self.assertEqual(row, source[identifier])
                self.assertEqual({key: value for key, value in self.selected().items()
                                  if key not in ('podcast_url', 'podcast_has_student_posts')},
                                 {key: value for key, value in source[int(self.identifier)].items()
                                  if key not in ('podcast_url', 'podcast_has_student_posts')})
                self.assertEqual(self.writes(before), [('PUT', f"/api/v1/{'groups' if group else 'courses'}/{self.context_id}/discussion_topics/{self.identifier}?no_verifiers=true")])
                self.assertTrue(any('page=2' in route for _, route in self.calls[before:]))
                self.assertFalse(any('/feeds/' in route or '/entries' in route or '/view' in route or '/files/' in route for _, route in self.calls[before:]))
                self.assertNotIn('synthetic-private', preview.stdout + result.stdout + result.stderr)

    def test_course_moderator_only_and_disabling_clear_coupled_flags_but_group_preserves_inapplicable_filter(self):
        for announcement in (False, True):
            for mode in ('moderator-posts', 'disabled'):
                self.reset(announcement=announcement)
                self.selected().update(podcast_url=f'/feeds/topics/{self.identifier}/enrollment_synthetic-private-before.rss',
                                       podcast_has_student_posts=True)
                result = self.approved(self.command(mode=mode, *('--format', 'brief')))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(self.selected()['podcast_has_student_posts'])
                self.assertEqual(self.selected()['podcast_url'] is not None, mode != 'disabled')
                self.assertIn('Stored podcast mode verified: ' + mode, result.stdout)
                self.assertNotIn('synthetic-private', result.stdout)
            self.reset(announcement=announcement, group=True)
            self.selected().update(podcast_url=f'/feeds/topics/{self.identifier}/group_synthetic-private-before.rss',
                                   podcast_has_student_posts=True)
            result = self.approved(self.command(mode='disabled'))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsNone(self.selected()['podcast_url'])
            self.assertTrue(self.selected()['podcast_has_student_posts'])

    def test_missing_consent_unsupported_group_filter_noop_metadata_permissions_and_inventory_cap_never_write(self):
        for announcement in (False, True):
            for mode in ('consent', 'group-filter', 'course-enabled', 'noop', 'url', 'flag', 'moderation', 'missing', 'boolean', 'update', 'pages'):
                self.reset(announcement=announcement, group=mode == 'group-filter')
                command = self.command(consent=mode != 'consent', mode='all-posts' if mode == 'group-filter' else
                                       'enabled' if mode == 'course-enabled' else 'disabled' if mode == 'noop' else None)
                if mode == 'url':
                    self.selected()['podcast_url'] = '/feeds/topics/999/unknown_synthetic-private.rss'
                elif mode == 'flag':
                    self.selected()['podcast_has_student_posts'] = 1
                elif mode == 'moderation':
                    self.configure('announcement_moderator', 'topic_moderator', False)
                elif mode in ('missing', 'boolean'):
                    self.configure('announcement_moderation_report', 'topic_podcast_permission_report',
                                   {} if mode == 'missing' else {'moderate_forum': 1})
                elif mode == 'update':
                    self.selected()['permissions']['update'] = False
                elif mode == 'pages':
                    command += ('--max-pages', '1')
                before = len(self.calls)
                result = self.invoke(*command)
                self.assertNotEqual(result.returncode, 0, mode)
                self.assertEqual(self.writes(before), [])
                self.assertEqual(result.stdout, '')
                self.assertNotIn('synthetic-private', result.stderr)

    def test_stale_feed_code_flags_prompt_context_account_inventory_or_permission_refuse_before_put(self):
        for announcement in (False, True):
            for mode in ('feed', 'flag', 'prompt', 'context', 'account', 'inventory', 'moderation'):
                self.reset(announcement=announcement)
                self.selected()['podcast_url'] = f'/feeds/topics/{self.identifier}/enrollment_synthetic-private-before.rss'
                command = self.command()
                preview = self.invoke(*command)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                if mode == 'feed':
                    self.selected()['podcast_url'] = f'/feeds/topics/{self.identifier}/enrollment_synthetic-private-changed.rss'
                elif mode == 'flag':
                    self.selected()['podcast_has_student_posts'] = True
                elif mode == 'prompt':
                    self.selected()['message'] = 'Changed'
                elif mode == 'context':
                    (self.announcement_context if announcement else self.topic_context)['name'] = 'Changed'
                elif mode == 'account':
                    self.configure('announcement_viewer', 'topic_viewer', 8)
                elif mode == 'inventory':
                    self.rows()[10 if announcement else 902]['title'] = 'Changed'
                else:
                    self.configure('announcement_moderator', 'topic_moderator', False)
                before = len(self.calls)
                result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
                self.assertNotEqual(result.returncode, 0, mode)
                self.assertEqual(self.writes(before), [])
                self.assertNotIn('may already have succeeded', result.stderr)

    def test_granular_or_late_moderation_omission_and_error_after_storing_are_uncertain_not_retried(self):
        for announcement in (False, True):
            for mode in ('granular', 'moderation', 'error', 'denied'):
                self.reset(announcement=announcement)
                if mode == 'granular':
                    if announcement:
                        type(self).announcement_podcast_granular_denied = True
                    else:
                        type(self).topic_granular_options_enabled = True
                        type(self).topic_edit_options = False
                elif mode == 'moderation':
                    self.configure('announcement_podcast_drop_moderation', 'topic_podcast_drop_moderation', True)
                elif mode == 'error':
                    self.configure('announcement_podcast_error', 'topic_podcast_error', True)
                else:
                    self.configure('announcement_denied', 'topic_denied', True)
                before = len(self.calls)
                result = self.approved(self.command())
                self.assertNotEqual(result.returncode, 0, mode)
                self.assertIn('may already have succeeded', result.stderr)
                self.assertEqual(len(self.writes(before)), 1)
                self.assertNotIn('synthetic-private', result.stdout + result.stderr)
                if mode == 'error':
                    self.assertTrue(self.selected()['podcast_has_student_posts'])
                    self.assertIsNotNone(self.selected()['podcast_url'])

    def test_bad_ack_readback_context_account_inventory_or_retained_permission_fail_after_one_attempt(self):
        for announcement in (False, True):
            for mode in ('ack', 'readback', 'feed-readback', 'account', 'context', 'inventory', 'permission', 'update'):
                self.reset(announcement=announcement)
                if mode == 'ack':
                    self.configure('announcement_ack_patch', 'topic_ack_patch', {'podcast_has_student_posts': False})
                elif mode == 'readback':
                    self.configure('announcement_read_denied', 'topic_readback_denied', True)
                elif mode == 'feed-readback':
                    self.configure('announcement_read_patch', 'topic_readback_patch',
                                   {'podcast_url': f'/feeds/topics/{self.identifier}/enrollment_synthetic-private-different.rss'})
                elif mode == 'account':
                    self.configure('announcement_account_changed', 'topic_account_changed', True)
                elif mode == 'context':
                    if announcement:
                        type(self).announcement_context_changed = True
                    else:
                        type(self).topic_schedule_time_zone_after = 'America/Denver'
                elif mode == 'inventory':
                    self.configure('announcement_inventory_denied', 'topic_state_inventory_denied', True)
                elif mode == 'permission':
                    self.configure('announcement_moderation_after', 'topic_podcast_permission_after', {'moderate_forum': False})
                else:
                    self.configure('announcement_lose_update', 'topic_state_lose_edit', True)
                before = len(self.calls)
                result = self.approved(self.command())
                self.assertNotEqual(result.returncode, 0, mode)
                self.assertIn('may already have succeeded', result.stderr)
                self.assertEqual(len(self.writes(before)), 1)
                self.assertNotIn('synthetic-private', result.stdout + result.stderr)
