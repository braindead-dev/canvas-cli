"""Installed course section-filter workflows against independent synthetic HTTPS."""

import copy
import json

from . import topic_management
from .fixture import CanvasFixture


class TopicSectionsE2E(CanvasFixture):
    def setUp(self):
        self.reset()

    def reset(self):
        topic_management.initialize(type(self), enabled=True)
        type(self).topic_sections_enabled = True
        self.managed_topics[901]['permissions']['manage_assign_to'] = False

    def command(self, *extra, all_sections=False):
        selection = ('--all-sections',) if all_sections else ('--section-id', '332', '--section-id', '331')
        return ('topic-sections', '111', '901', *selection,
                '--acknowledge-shared-topic', '--acknowledge-audience-change', *extra)

    def approved(self, command):
        preview = self.invoke(*command, '--format', 'json')
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def writes(self, before):
        return [row for row in self.calls[before:] if row[0] != 'GET']

    def test_preview_paginates_all_sections_without_emitting_names_sis_or_peer_content(self):
        self.topic_sections[0]['sis_section_id'] = 'synthetic-private-sis'
        before = len(self.calls)
        result = self.invoke(*self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['body'], {'specific_sections': '331,332'})
        self.assertTrue(data['acknowledge_audience_change'])
        self.assertEqual(data['active_section_ids'], [331, 332])
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertEqual(self.writes(before), [])
        self.assertTrue(any('/sections?' in route and 'page=2' in route for _, route in self.calls[before:]))
        self.assertFalse(any('/users' in route and '/self/profile' not in route or '/entries' in route or '/view' in route
                             for _, route in self.calls[before:]))

    def test_setting_and_clearing_preserve_modern_overrides_content_other_topics_and_peer_entries(self):
        source = copy.deepcopy(self.managed_topics[901])
        sibling = copy.deepcopy(self.managed_topics[902])
        entries = copy.deepcopy(self.topic_entries)
        before = len(self.calls)
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['topic_section_filter']['section_ids'], [331, 332])
        self.assertTrue(data['topic_section_filter']['observed_override_metadata_changed'])
        self.assertFalse(data['topic_section_filter']['effective_participant_visibility_verified'])
        self.assertEqual(self.writes(before), [('PUT', '/api/v1/courses/111/discussion_topics/901?no_verifiers=true')])
        self.assertEqual(self.managed_topics[901]['message'], source['message'])
        self.assertEqual(self.managed_topics[901]['attachments'], source['attachments'])
        self.assertEqual(self.managed_topics[901]['ungraded_discussion_overrides'][0], source['ungraded_discussion_overrides'][0])
        self.assertEqual(self.managed_topics[902], sibling)
        self.assertEqual(self.topic_entries, entries)
        self.assertFalse(self.topic_attachment_deleted)
        before = len(self.calls)
        result = self.approved(self.command('--format', 'brief', all_sections=True))
        # Confirmation must come from a JSON preview, while execution may use brief output.
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Section filter: all sections', result.stdout)
        self.assertIn('effective participant visibility is not verified', result.stdout)
        self.assertEqual(self.managed_topics[901]['sections'], [])
        self.assertFalse(self.managed_topics[901]['is_section_specific'])
        self.assertEqual(self.managed_topics[901]['ungraded_discussion_overrides'], source['ungraded_discussion_overrides'])
        self.assertEqual(len(self.writes(before)), 1)
        self.assertNotIn('synthetic-private', result.stdout)

    def test_modern_manage_assign_to_false_does_not_replace_native_update_and_section_checks(self):
        self.assertFalse(self.managed_topics[901]['permissions']['manage_assign_to'])
        self.assertFalse(self.topic_moderator)
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['topic_section_filter']['verified'])

    def test_native_old_or_new_visibility_denial_stays_one_authoritative_request_without_retry(self):
        for old in (False, True):
            self.reset()
            type(self).topic_section_visible_ids = [332]
            if old:
                self.managed_topics[901].update(is_section_specific=True, sections=[copy.deepcopy(self.topic_sections[0])])
            command = self.command(all_sections=old)
            before = len(self.calls)
            result = self.approved(command)
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn('400', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertFalse(self.topic_written)

    def test_missing_foreign_duplicate_denied_or_partial_section_lists_fail_before_put(self):
        for mode in ('absent', 'foreign', 'duplicate', 'denied', 'partial'):
            self.reset()
            if mode == 'absent':
                self.topic_sections.pop()
            elif mode == 'foreign':
                self.topic_sections[0]['course_id'] = 112
            elif mode == 'duplicate':
                self.topic_sections.append(copy.deepcopy(self.topic_sections[0]))
            elif mode == 'denied':
                type(self).topic_sections_list_denied = True
            before = len(self.calls)
            result = self.invoke(*self.command(*('--max-pages', '1') if mode == 'partial' else ()))
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertEqual(self.writes(before), [])
            self.assertNotIn('synthetic-private', result.stderr)

    def test_stale_source_catalog_override_rights_account_context_or_topic_inventory_prevents_put(self):
        for mode in ('content', 'sections', 'overrides', 'rights', 'account', 'context', 'inventory'):
            self.reset()
            preview = self.invoke(*self.command())
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'content':
                self.managed_topics[901]['message'] = '<p>Changed</p>'
            elif mode == 'sections':
                self.topic_sections[0]['name'] = 'Changed section'
            elif mode == 'overrides':
                self.managed_topics[901]['ungraded_discussion_overrides'].append({'student_ids': [8]})
            elif mode == 'rights':
                self.managed_topics[901]['permissions']['update'] = False
            elif mode == 'account':
                type(self).topic_viewer = 8
            elif mode == 'context':
                self.topic_context['name'] = 'Changed context'
            else:
                self.managed_topics[902]['title'] = 'Changed other topic'
            before = len(self.calls)
            result = self.invoke(*self.command(), '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertEqual(self.writes(before), [])

    def test_partial_ignored_malformed_or_unreadable_results_are_uncertain_and_not_retried(self):
        for mode in ('ignore', 'ack', 'wrong_sections', 'foreign', 'overrides', 'readback', 'catalog', 'catalog_change', 'account'):
            self.reset()
            if mode == 'ignore':
                type(self).topic_ignore = True
            elif mode == 'ack':
                type(self).topic_ack_patch = []
            elif mode == 'wrong_sections':
                patch = {'sections': [{'id': 332}]}
                type(self).topic_ack_patch = type(self).topic_readback_patch = patch
            elif mode == 'foreign':
                type(self).topic_ack_patch = {'sections': [{'id': 331, 'course_id': 112}, {'id': 332}]}
            elif mode == 'overrides':
                type(self).topic_ack_patch = {'ungraded_discussion_overrides': None}
            elif mode == 'readback':
                type(self).topic_readback_denied = True
            elif mode == 'catalog':
                type(self).topic_sections_list_denied_after = True
            elif mode == 'catalog_change':
                type(self).topic_sections_after = copy.deepcopy(self.topic_sections)
                self.topic_sections_after[0]['name'] = 'Changed section'
            else:
                type(self).topic_account_changed = True
            before = len(self.calls)
            result = self.approved(self.command())
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn('may already have succeeded', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)
            self.assertNotIn('synthetic-private', result.stdout + result.stderr)

    def test_verified_result_can_lose_future_update_permission_and_matching_filter_is_noop(self):
        type(self).topic_state_lose_edit = True
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['edited_topic']['permissions']['update'])
        self.reset()
        before = len(self.calls)
        result = self.invoke(*self.command(all_sections=True))
        self.assertEqual(result.returncode, 1)
        self.assertIn('already matches', result.stderr)
        self.assertEqual(self.writes(before), [])

    def test_http_error_after_native_association_change_does_not_claim_unchanged_state_or_retry(self):
        type(self).topic_sections_error_after_apply = True
        before = len(self.calls)
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 1)
        self.assertIn('verify a write in Canvas before repeating', result.stderr)
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)
        self.assertEqual(len(self.writes(before)), 1)
        self.assertTrue(self.managed_topics[901]['is_section_specific'])
        self.assertEqual([row['id'] for row in self.managed_topics[901]['sections']], [331, 332])

    def test_acknowledgements_conflicts_and_group_context_fail_without_canvas_writes(self):
        for command in (('topic-sections', '111', '901', '--section-id', '331'),
                        self.command('--all-sections'), self.command('--context', 'group'),
                        ('topic-sections', '111', '901', '--section-id', '331', '--section-id', '331',
                         '--acknowledge-shared-topic', '--acknowledge-audience-change')):
            before = len(self.calls)
            result = self.invoke(*command)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual(self.writes(before), [])
