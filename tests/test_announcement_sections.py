"""Native course announcement audiences, not ungraded participant overrides."""

import copy
import json
import unittest
from unittest.mock import patch

from test_announcement_authoring import AnnouncementClient

from canvas_cli.announcement_authoring import change
from canvas_cli.cli import brief, parser, run
from canvas_cli.client import CanvasError
from canvas_cli.dispatch import execute


class AnnouncementSectionTests(unittest.TestCase):
    def setUp(self):
        self.client = AnnouncementClient()

    def preview(self, **options):
        return change(self.client, '123', '9', **({'sections': {'specific_sections': [34, 33]},
                      'acknowledge_shared': True, 'acknowledge_broadcast': True,
                      'acknowledge_audience': True} | options))

    def approved(self, **options):
        preview = self.preview(**options)
        return self.preview(yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [call for call in self.client.calls if call[0] != 'GET']

    def test_preview_binds_sorted_full_catalog_and_uses_only_selected_filter_and_preserved_comment_lock(self):
        preview = self.preview()
        self.assertEqual(preview['body'], {'specific_sections': '33,34', 'is_announcement': True, 'lock_comment': True})
        self.assertEqual(preview['active_section_ids'], [33, 34])
        self.assertTrue(preview['acknowledge_audience_change'])
        self.assertEqual(self.client.section_reads, 2)
        self.assertEqual(self.writes(), [])
        self.assertNotIn('synthetic-private', json.dumps(preview))
        self.assertIn('HTTP error is not proof', preview['warning'])
        self.assertFalse(any('/entries' in route or '/view' in route or '/enrollments' in route for _, route, _ in self.client.calls))

    def test_exact_filter_readback_preserves_content_and_open_or_closed_comments_without_creator_preferences(self):
        for locked in (True, False):
            self.setUp()
            self.client.topics[9]['locked'] = locked
            original = copy.deepcopy(self.client.topics)
            result = self.approved()
            selection = result['announcement_section_filter']
            self.assertEqual(selection['section_ids'], [33, 34])
            self.assertTrue(selection['is_section_specific'])
            self.assertTrue(selection['verified'])
            self.assertFalse(selection['effective_participant_visibility_verified'])
            self.assertFalse(selection['participant_record_effects_verified'])
            self.assertTrue(result['comment_lock_preserved'])
            self.assertEqual(result['stored_text_matches_request'], {})
            self.assertEqual(result['unrequested_changed_fields'], [])
            self.assertEqual(self.writes(), [('PUT', '/api/v1/courses/123/discussion_topics/9?no_verifiers=true',
                                             {'specific_sections': '33,34', 'is_announcement': True, 'lock_comment': locked})])
            for field in ('message', 'title', 'attachments', 'author', 'pinned', 'position', 'delayed_post_at', 'lock_at'):
                self.assertEqual(self.client.topics[9][field], original[9][field])
            self.assertIsNone(self.client.topics[9]['ungraded_discussion_overrides'])
            self.assertEqual(self.client.topics[10], original[10])
            self.assertNotIn('synthetic-private', json.dumps(result))
            self.assertIn('Section filter: 33, 34', brief(result))
            self.assertEqual(self.client.section_reads, 5)

    def test_all_sections_restores_filter_but_does_not_claim_universal_visibility(self):
        self.client.topics[9].update(is_section_specific=True, sections=[copy.deepcopy(self.client.sections[0])])
        result = self.approved(sections={'specific_sections': 'all'})
        self.assertEqual(result['announcement_section_filter']['section_ids'], [])
        self.assertFalse(result['announcement_section_filter']['is_section_specific'])
        self.assertFalse(result['announcement_section_filter']['effective_participant_visibility_verified'])
        self.assertIn('all sections', brief(result))
        self.assertIn('not every participant', result['note'])

    def test_native_update_not_creation_assign_to_permission_or_guessed_ownership_controls_operation(self):
        self.client.creation = False
        self.client.topics[9]['author'] = {'id': 8}
        self.client.topics[9]['permissions']['manage_assign_to'] = False
        self.client.lose_update = True
        result = self.approved()
        self.assertTrue(result['announcement_section_filter']['verified'])
        self.assertFalse(result['edited_announcement']['permissions']['update'])
        self.assertFalse(any('include%5B%5D=permissions' in route for _, route, _ in self.client.calls))
        self.setUp()
        self.client.topics[9]['permissions']['update'] = False
        with self.assertRaisesRegex(CanvasError, 'exact announcement'):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_noop_filter_does_not_broadcast_or_mutate(self):
        for selection in ({'specific_sections': 'all'}, {'specific_sections': [34, 33]}):
            self.setUp()
            if selection['specific_sections'] != 'all':
                self.client.topics[9].update(is_section_specific=True, sections=copy.deepcopy(self.client.sections))
            with self.assertRaisesRegex(CanvasError, 'already matches'):
                self.preview(sections=selection)
            self.assertEqual(self.writes(), [])

    def test_invalid_choices_acks_group_and_mixed_operations_make_no_network_calls(self):
        for value in ([], [True], [0], ['33'], [33, 33], None, '33', 33, {'id': 33}):
            self.setUp()
            with self.subTest(value=value), self.assertRaises(CanvasError):
                self.preview(sections={'specific_sections': value})
            self.assertEqual(self.client.calls, [])
        for options in ({'sections': {}}, {'sections': []}, {'sections': {'student_ids': [7]}},
                        {'sections': None}, {'acknowledge_audience': False}, {'acknowledge_audience': 1},
                        {'acknowledge_shared': False}, {'acknowledge_broadcast': False}, {'context_type': 'group'},
                        {'title': 'Conflict'}, {'message': 'Conflict'}, {'comments': True, 'acknowledge_comments': True},
                        {'schedule': {'lock_at': None}, 'acknowledge_availability': True},
                        {'delete': True, 'acknowledge_removal': True, 'acknowledge_broadcast': False},
                        {'max_pages': 0}, {'yes': True}, {'confirm': 'unpaired'}):
            self.setUp()
            with self.subTest(options=options), self.assertRaises(CanvasError):
                self.preview(**options)
            self.assertEqual(self.client.calls, [])

    def test_null_native_override_metadata_is_required_not_discussion_override_list_or_missing_data(self):
        for value in ([], {}, True, [{'student_ids': [7]}], 'missing'):
            self.setUp()
            if value == 'missing':
                self.client.topics[9].pop('ungraded_discussion_overrides')
            else:
                self.client.topics[9]['ungraded_discussion_overrides'] = value
            with self.subTest(value=value), self.assertRaisesRegex(CanvasError, 'native announcement audience'):
                self.preview()
            self.assertEqual(self.writes(), [])
        self.setUp()
        self.client.topics[9].update(is_section_specific=True, sections=[{'id': 33, 'course_id': 124}])
        with self.assertRaisesRegex(CanvasError, 'outside'):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_absent_foreign_deleted_duplicate_malformed_or_incomplete_catalog_prevents_put(self):
        for mode in ('absent', 'foreign', 'deleted', 'duplicate', 'malformed', 'denied', 'limit'):
            self.setUp()
            if mode == 'absent':
                self.client.sections.pop()
            elif mode == 'foreign':
                self.client.sections[0]['course_id'] = 124
            elif mode == 'deleted':
                self.client.sections[0]['workflow_state'] = 'deleted'
            elif mode == 'duplicate':
                self.client.sections.append(self.client.sections[0])
            elif mode == 'malformed':
                self.client.sections[0]['start_at'] = 'tomorrow'
            elif mode == 'denied':
                self.client.sections_denied = True
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(max_pages=1 if mode == 'limit' else 100)
            self.assertEqual(self.writes(), [])

    def test_sorted_catalog_crosslisting_and_selection_order_have_stable_confirmation(self):
        preview = self.preview()
        self.client.sections.reverse()
        self.assertEqual(self.preview(sections={'specific_sections': [33, 34]})['confirm'], preview['confirm'])

    def test_stale_account_context_content_audience_sections_inventory_and_rights_prevent_put(self):
        for mode in ('account', 'context', 'content', 'audience', 'section', 'inventory', 'rights'):
            self.setUp()
            preview = self.preview()
            if mode == 'account':
                self.client.identity = 8
            elif mode == 'context':
                self.client.context['name'] = 'Changed context'
            elif mode == 'content':
                self.client.topics[9]['message'] = '<p>Changed content</p>'
            elif mode == 'audience':
                self.client.topics[9].update(is_section_specific=True, sections=[copy.deepcopy(self.client.sections[0])])
            elif mode == 'section':
                self.client.sections[0]['name'] = 'Changed section'
            elif mode == 'inventory':
                self.client.topics[10]['title'] = 'Changed other announcement'
            else:
                self.client.topics[9]['permissions']['update'] = False
            with self.subTest(mode=mode), self.assertRaises(CanvasError) as caught:
                self.preview(yes=True, confirm=preview['confirm'])
            self.assertNotIn('may already', str(caught.exception))
            self.assertEqual(self.writes(), [])
        self.setUp()
        self.client.section_mutation = lambda client: client.sections.pop()
        with self.assertRaisesRegex(CanvasError, 'changed during preflight'):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_native_denial_can_persist_associations_and_is_uncertain_not_safely_rolled_back(self):
        for mode in ('old', 'new', 'permission', 'validation'):
            self.setUp()
            self.client.topics[9].update(is_section_specific=True, sections=[copy.deepcopy(self.client.sections[0])])
            preview = self.preview(sections={'specific_sections': [34]})
            if mode == 'old':
                self.client.section_visible_ids = [34]
            elif mode == 'new':
                self.client.section_visible_ids = [33]
            elif mode == 'permission':
                self.client.denied = True
            else:
                self.client.sections_error_after_apply = True
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'may already have succeeded') as caught:
                self.preview(sections={'specific_sections': [34]}, yes=True, confirm=preview['confirm'])
            self.assertEqual([section['id'] for section in self.client.topics[9]['sections']], [34])
            self.assertEqual(len(self.writes()), 1)
            self.assertNotIn('synthetic-private', str(caught.exception))

    def test_bad_ack_ignored_filter_denied_readback_catalog_changes_or_postwrite_identity_drift_are_uncertain(self):
        for mode in ('ack', 'wrong_ids', 'foreign', 'metadata', 'ignored', 'readback', 'catalog', 'catalog_change',
                     'inventory', 'account', 'context', 'comment_lock'):
            self.setUp()
            if mode == 'ack':
                self.client.ack_patch = []
            elif mode == 'wrong_ids':
                self.client.ack_patch = self.client.after_patch = {'sections': [copy.deepcopy(self.client.sections[0])]}
            elif mode == 'foreign':
                self.client.ack_patch = {'sections': [{'id': 33, 'course_id': 124}, {'id': 34}]}
            elif mode == 'metadata':
                self.client.ack_patch = {'ungraded_discussion_overrides': []}
            elif mode == 'ignored':
                self.client.ignore_sections = True
            elif mode == 'readback':
                self.client.after_denied = True
            elif mode == 'catalog':
                self.client.sections_denied_after = True
            elif mode == 'catalog_change':
                self.client.sections_after = copy.deepcopy(self.client.sections)
                self.client.sections_after[0]['name'] = 'Changed section'
            elif mode == 'inventory':
                self.client.after_list_fail = True
            elif mode == 'account':
                self.client.account_changed = True
            elif mode == 'context':
                self.client.context_changed = True
            else:
                self.client.ignore_comment_lock = True
                self.client.topics[9]['locked'] = False
                self.client.force_comment_lock = True
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'may already have succeeded'):
                self.approved()
            self.assertEqual(len(self.writes()), 1)

    def test_course_only_parser_dispatch_and_offline_help_expose_exact_native_operation(self):
        flags = ('--acknowledge-shared-announcement', '--acknowledge-broadcast', '--acknowledge-audience-change')
        args = parser().parse_args(['announcement-sections', '123', '9', '--section-id', '34', '--section-id', '33', *flags])
        self.assertEqual(execute(self.client, args)['body']['specific_sections'], '33,34')
        args = parser().parse_args(['announcement-sections', '123', '9', '--all-sections', *flags])
        self.assertTrue(args.all_sections)
        with patch('canvas_cli.cli.auth.connect', side_effect=AssertionError('Offline help must not authenticate')):
            help_text = brief(run(parser().parse_args(['help', 'announcement-sections', '--format', 'brief'])))
        self.assertIn('--section-id', help_text)
        self.assertIn('--all-sections', help_text)
        self.assertIn('COURSE_ID', help_text)
        self.assertNotIn('--context', help_text)
