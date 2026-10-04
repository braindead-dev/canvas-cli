"""Installed initial announcement targeting against independent synthetic HTTPS."""

import copy
import json
from pathlib import Path

from canvas_cli.formatting import brief

from . import announcement_authoring
from .fixture import CanvasFixture


class AnnouncementCreationSectionE2E(CanvasFixture):
    def setUp(self):
        self.reset()
        self.message = Path(self.tmp.name) / 'announcement.txt'
        self.message.write_text('Synthetic update <team>\n🌿', encoding='utf-8')

    def reset(self):
        announcement_authoring.initialize(type(self), enabled=True)

    def command(self, *, selection=('--section-id', '34', '--section-id', '33'), extra=(), audience=True):
        return ('announcement-create', '123', '--title', 'Synthetic targeted announcement', '--message-file', str(self.message),
                *selection, '--acknowledge-shared-announcement', '--acknowledge-broadcast',
                *(('--acknowledge-audience-change',) if audience else ()), *extra)

    def approved(self, command):
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def writes(self, before):
        return [call for call in self.calls[before:] if call[0] != 'GET']

    def test_targeted_immediate_and_scheduled_all_creation_have_exact_new_ids_and_readback_without_old_record_edits(self):
        original = copy.deepcopy(self.announcements)
        before = len(self.calls)
        command = self.command()
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertEqual(data['body'], {'title': 'Synthetic targeted announcement',
                                        'message': '<p>Synthetic update &lt;team&gt;<br>🌿</p>',
                                        'specific_sections': '33,34', 'is_announcement': True, 'lock_comment': True})
        self.assertEqual(data['active_section_ids'], [33, 34])
        self.assertNotIn('synthetic-private', preview.stdout)
        self.assertEqual(self.writes(before), [])
        result = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['created_announcement']['id'], 11)
        self.assertEqual(data['created_announcement']['author_id'], 7)
        self.assertEqual(data['announcement_section_filter']['section_ids'], [33, 34])
        self.assertTrue(data['announcement_section_filter']['verified'])
        self.assertFalse(data['announcement_section_filter']['effective_participant_visibility_verified'])
        self.assertFalse(data['announcement_section_filter']['participant_record_effects_verified'])
        repeated = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertNotEqual(repeated.returncode, 0, repeated.stderr)
        self.assertIn('Preview changed', repeated.stderr)
        self.assertEqual(len(self.writes(before)), 1)
        result = self.approved(self.command(selection=('--all-sections',), extra=('--post-at', '2099-10-01T09:00:00-07:00', '--comments')))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['created_announcement']['id'], 12)
        self.assertEqual(data['stored_posting_at'], '2099-10-01T16:00:00Z')
        self.assertFalse(data['comments_locked'])
        self.assertFalse(data['announcement_section_filter']['is_section_specific'])
        self.assertEqual(data['announcement_section_filter']['section_ids'], [])
        self.assertFalse(data['future_execution_verified'])
        self.assertFalse(data['notification_delivery_verified'])
        self.assertTrue(data['created_announcement']['published'])
        self.assertIn('Section filter: all sections', brief(data))
        self.assertEqual({key: self.announcements[key] for key in original}, original)
        self.assertEqual(len(self.writes(before)), 2)
        self.assertTrue(all(method == 'POST' for method, _ in self.writes(before)))
        self.assertEqual(self.announcement_preference_writes, 0)
        self.assertFalse(any('/entries' in route or '/view' in route or '/enrollments' in route for _, route in self.calls[before:]))
        self.assertTrue(any('/sections?' in route and 'page=2' in route for _, route in self.calls[before:]))
        self.assertTrue(any('/discussion_topics?' in route and 'page=3' in route for _, route in self.calls[before:]))
        self.assertNotIn('synthetic-private', result.stdout)

    def test_default_course_or_group_creation_needs_no_catalog_or_extra_audience_consent(self):
        for context in ('course', 'group'):
            self.reset()
            before = len(self.calls)
            result = self.approved(self.command(selection=(), audience=False, extra=('--context', context, '--format', 'brief')))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('Section filter:', result.stdout)
            self.assertFalse(any('/sections?' in route for _, route in self.calls[before:]))
            self.assertEqual(len(self.writes(before)), 1)
            self.assertNotIn('specific_sections', self.announcement_mutations[0][2])

    def test_bad_selection_group_missing_consent_unknown_catalog_or_page_limit_never_post(self):
        for mode in ('group', 'both', 'duplicate', 'absent', 'consent', 'extraneous', 'catalog', 'pages'):
            self.reset()
            command = self.command()
            if mode == 'group':
                command += ('--context', 'group')
            elif mode == 'both':
                command += ('--all-sections',)
            elif mode == 'duplicate':
                command = self.command(selection=('--section-id', '33', '--section-id', '33'))
            elif mode == 'absent':
                command = self.command(selection=('--section-id', '999'))
            elif mode == 'consent':
                command = self.command(audience=False)
            elif mode == 'extraneous':
                command = self.command(selection=())
            elif mode == 'catalog':
                type(self).announcement_sections_denied = True
            else:
                command += ('--max-pages', '1')
            before = len(self.calls)
            result = self.invoke(*command)
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertEqual(result.stdout, '')
            self.assertEqual(self.writes(before), [])
            self.assertNotIn('synthetic-private', result.stderr)

    def test_changed_catalog_identity_context_inventory_permission_or_choice_invalidates_digest_before_post(self):
        for mode in ('catalog', 'identity', 'context', 'inventory', 'permission', 'choice'):
            self.reset()
            command = self.command()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'catalog':
                self.announcement_sections[0]['name'] = 'Changed section'
            elif mode == 'identity':
                type(self).announcement_viewer = 8
            elif mode == 'context':
                self.announcement_context['name'] = 'Changed context'
            elif mode == 'inventory':
                self.announcements[10]['title'] = 'Changed prior announcement'
            elif mode == 'permission':
                type(self).announcement_creation = False
            else:
                command = self.command(selection=('--section-id', '33'))
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertNotIn('may already have succeeded', result.stderr)
            self.assertEqual(self.writes(before), [])

    def test_native_visibility_or_validation_denials_are_one_uncertain_attempt_without_creation_or_retry(self):
        for mode in ('visibility', 'validation', 'permission'):
            self.reset()
            command = self.command()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'visibility':
                type(self).announcement_section_visible_ids = [33]
            elif mode == 'validation':
                type(self).announcement_sections_error_after_apply = True
            else:
                type(self).announcement_denied = True
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertIn('may already have succeeded', result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)
            self.assertEqual(set(self.announcements), {9, 10})

    def test_wrong_or_ignored_audience_and_inaccessible_catalog_or_new_record_are_not_repaired(self):
        for mode in ('ignored', 'ack', 'metadata', 'readback', 'catalog', 'catalog_change', 'inventory', 'identity', 'context'):
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
            elif mode == 'readback':
                type(self).announcement_read_denied = True
            elif mode == 'catalog':
                type(self).announcement_sections_denied_after = True
            elif mode == 'catalog_change':
                type(self).announcement_sections_after = copy.deepcopy(self.announcement_sections)
                self.announcement_sections_after[0]['name'] = 'Changed section'
            elif mode == 'inventory':
                type(self).announcement_inventory_denied = True
            elif mode == 'identity':
                type(self).announcement_account_changed = True
            else:
                type(self).announcement_context_changed = True
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertIn('may already have succeeded', result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)
            self.assertIn(11, self.announcements)
