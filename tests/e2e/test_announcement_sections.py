"""Installed announcement audiences against independent synthetic HTTPS state."""

import copy
import json

from . import announcement_authoring
from .fixture import CanvasFixture


class AnnouncementSectionE2E(CanvasFixture):
    def setUp(self):
        self.reset()

    def reset(self):
        announcement_authoring.initialize(type(self), enabled=True)

    def command(self, *, selection=('--section-id', '34', '--section-id', '33'), extra=()):
        return ('announcement-sections', '123', '9', *selection, '--acknowledge-shared-announcement',
                '--acknowledge-broadcast', '--acknowledge-audience-change', *extra)

    def approved(self, command):
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def writes(self, before):
        return [call for call in self.calls[before:] if call[0] != 'GET']

    def test_select_and_restore_all_sections_preserve_prompt_comments_and_other_announcements(self):
        original = copy.deepcopy(self.announcements)
        before = len(self.calls)
        command = self.command()
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertEqual(data['body'], {'specific_sections': '33,34', 'is_announcement': True, 'lock_comment': True})
        self.assertEqual(data['active_section_ids'], [33, 34])
        self.assertNotIn('synthetic-private', preview.stdout)
        self.assertEqual(self.writes(before), [])
        result = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(result.returncode, 0, result.stderr)
        selection = json.loads(result.stdout)['announcement_section_filter']
        self.assertEqual(selection['section_ids'], [33, 34])
        self.assertTrue(selection['verified'])
        self.assertFalse(selection['effective_participant_visibility_verified'])
        self.assertFalse(selection['participant_record_effects_verified'])
        result = self.approved(self.command(selection=('--all-sections',), extra=('--format', 'brief')))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Section filter: all sections', result.stdout)
        self.assertFalse(self.announcements[9]['is_section_specific'])
        self.assertEqual(self.announcements[9]['sections'], [])
        for field in ('message', 'title', 'attachments', 'author', 'pinned', 'position', 'locked', 'delayed_post_at', 'lock_at'):
            self.assertEqual(self.announcements[9][field], original[9][field])
        self.assertIsNone(self.announcements[9]['ungraded_discussion_overrides'])
        self.assertEqual(self.announcements[10], original[10])
        self.assertEqual(self.announcement_preference_writes, 0)
        self.assertEqual(len(self.writes(before)), 2)
        self.assertFalse(any('/entries' in route or '/view' in route or '/enrollments' in route for _, route in self.calls[before:]))
        self.assertTrue(any('/sections?' in route and 'page=2' in route for _, route in self.calls[before:]))
        self.assertTrue(any('/discussion_topics?' in route and 'page=2' in route for _, route in self.calls[before:]))
        self.assertNotIn('synthetic-private', result.stdout)

    def test_own_native_update_does_not_require_creation_and_lost_postwrite_update_right_is_observed(self):
        type(self).announcement_creation = False
        type(self).announcement_lose_update = True
        self.announcements[9].update(locked=False, author={'id': 8})
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['comment_lock_preserved'])
        self.assertFalse(data['edited_announcement']['locked'])
        self.assertFalse(data['edited_announcement']['permissions']['update'])
        self.assertTrue(data['announcement_section_filter']['verified'])

    def test_noop_group_missing_or_mixed_selection_consent_and_incomplete_pagination_never_write(self):
        for mode in ('noop', 'group', 'empty', 'both', 'duplicate', 'absent', 'consent', 'broadcast', 'shared', 'mixed', 'pages'):
            self.reset()
            command = self.command()
            if mode == 'noop':
                command = self.command(selection=('--all-sections',))
            elif mode == 'group':
                command += ('--context', 'group')
            elif mode == 'empty':
                command = self.command(selection=())
            elif mode == 'both':
                command += ('--all-sections',)
            elif mode == 'duplicate':
                command = self.command(selection=('--section-id', '33', '--section-id', '33'))
            elif mode == 'absent':
                command = self.command(selection=('--section-id', '999'))
            elif mode in ('consent', 'broadcast', 'shared'):
                flag = {'consent': '--acknowledge-audience-change', 'broadcast': '--acknowledge-broadcast',
                        'shared': '--acknowledge-shared-announcement'}[mode]
                command = tuple(value for value in command if value != flag)
            elif mode == 'mixed':
                command += ('--title', 'Unexpected text')
            else:
                command += ('--max-pages', '1')
            before = len(self.calls)
            result = self.invoke(*command)
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertEqual(result.stdout, '')
            self.assertEqual(self.writes(before), [])

    def test_unknown_null_override_metadata_foreign_sections_and_denied_catalog_are_not_safe_preflight(self):
        for mode in ('metadata', 'missing', 'foreign', 'catalog'):
            self.reset()
            if mode == 'metadata':
                self.announcements[9]['ungraded_discussion_overrides'] = []
            elif mode == 'missing':
                self.announcements[9].pop('ungraded_discussion_overrides')
            elif mode == 'foreign':
                self.announcement_sections[0]['course_id'] = 124
            else:
                type(self).announcement_sections_denied = True
            before = len(self.calls)
            result = self.invoke(*self.command())
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertEqual(self.writes(before), [])
            self.assertNotIn('synthetic-private', result.stderr)

    def test_stale_catalog_account_context_prompt_filter_and_inventory_invalidate_confirmation(self):
        for mode in ('section', 'account', 'context', 'content', 'filter', 'inventory'):
            self.reset()
            command = self.command()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'section':
                self.announcement_sections[0]['name'] = 'Changed section'
            elif mode == 'account':
                type(self).announcement_viewer = 8
            elif mode == 'context':
                self.announcement_context['name'] = 'Changed context'
            elif mode == 'content':
                self.announcements[9]['message'] = '<p>Changed prompt</p>'
            elif mode == 'filter':
                self.announcements[9].update(is_section_specific=True, sections=[copy.deepcopy(self.announcement_sections[0])])
            else:
                self.announcements[10]['title'] = 'Changed other announcement'
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertNotIn('may already have succeeded', result.stderr)
            self.assertEqual(self.writes(before), [])

    def test_native_old_new_visibility_permission_or_validation_errors_can_follow_persisted_associations(self):
        for mode in ('old', 'new', 'permission', 'validation'):
            self.reset()
            self.announcements[9].update(is_section_specific=True, sections=[copy.deepcopy(self.announcement_sections[0])])
            command = self.command(selection=('--section-id', '34'))
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'old':
                type(self).announcement_section_visible_ids = [34]
            elif mode == 'new':
                type(self).announcement_section_visible_ids = [33]
            elif mode == 'permission':
                type(self).announcement_denied = True
            else:
                type(self).announcement_sections_error_after_apply = True
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertIn('may already have succeeded', result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual([section['id'] for section in self.announcements[9]['sections']], [34])
            self.assertEqual(len(self.writes(before)), 1)
            self.assertEqual(self.announcement_notifications, [])

    def test_ignored_filter_bad_ack_inaccessible_readback_or_catalog_drift_is_uncertain_without_repair(self):
        for mode in ('ignored', 'ack', 'metadata', 'read', 'catalog', 'catalog_change', 'inventory', 'context', 'account'):
            self.reset()
            command = self.command()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'ignored':
                type(self).announcement_ignore_sections = True
            elif mode == 'ack':
                type(self).announcement_ack_patch = {'sections': [{'id': 33, 'course_id': 123}]}
            elif mode == 'metadata':
                type(self).announcement_ack_patch = {'ungraded_discussion_overrides': []}
            elif mode == 'read':
                type(self).announcement_read_denied = True
            elif mode == 'catalog':
                type(self).announcement_sections_denied_after = True
            elif mode == 'catalog_change':
                type(self).announcement_sections_after = copy.deepcopy(self.announcement_sections)
                self.announcement_sections_after[0]['name'] = 'Changed section'
            elif mode == 'inventory':
                type(self).announcement_inventory_denied = True
            elif mode == 'context':
                type(self).announcement_context_changed = True
            else:
                type(self).announcement_account_changed = True
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertIn('may already have succeeded', result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)
