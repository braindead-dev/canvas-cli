"""Initial native course announcement audiences and creation-specific evidence."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_announcement_authoring import AnnouncementClient

from canvas_cli.announcement_authoring import create
from canvas_cli.cli import brief, parser, run
from canvas_cli.client import CanvasError
from canvas_cli.dispatch import execute


class AnnouncementCreationSectionTests(unittest.TestCase):
    def setUp(self):
        self.client = AnnouncementClient()

    def preview(self, **options):
        return create(self.client, '123', **({'title': 'Synthetic targeted update', 'message': 'Hello <team>\n🌿',
                      'sections': {'specific_sections': [34, 33]}, 'acknowledge_audience': True,
                      'acknowledge_shared': True, 'acknowledge_broadcast': True} | options))

    def approved(self, **options):
        preview = self.preview(**options)
        return self.preview(yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [call for call in self.client.calls if call[0] != 'GET']

    def test_preview_binds_initial_sorted_audience_without_catalog_names_roster_or_peer_reads(self):
        preview = self.preview()
        self.assertEqual(preview['body'], {'title': 'Synthetic targeted update', 'message': '<p>Hello &lt;team&gt;<br>🌿</p>',
                                         'specific_sections': '33,34', 'is_announcement': True, 'lock_comment': True})
        self.assertEqual(preview['active_section_ids'], [33, 34])
        self.assertTrue(preview['acknowledge_audience_change'])
        self.assertEqual(self.client.section_reads, 2)
        self.assertEqual(self.writes(), [])
        self.assertNotIn('synthetic-private', json.dumps(preview))
        self.assertFalse(any('/entries' in route or '/view' in route or '/enrollments' in route for _, route, _ in self.client.calls))

    def test_one_post_new_own_id_exact_initial_filter_and_independent_readback_preserve_old_records(self):
        original = copy.deepcopy(self.client.topics)
        result = self.approved()
        selection = result['announcement_section_filter']
        self.assertEqual(result['created_announcement']['id'], 11)
        self.assertEqual(result['created_announcement']['author_id'], 7)
        self.assertTrue(result['new_id_verified'])
        self.assertTrue(selection['verified'])
        self.assertTrue(selection['is_section_specific'])
        self.assertEqual(selection['section_ids'], [33, 34])
        self.assertFalse(selection['effective_participant_visibility_verified'])
        self.assertFalse(selection['participant_record_effects_verified'])
        self.assertFalse(result['notification_delivery_verified'])
        self.assertEqual(self.client.section_reads, 5)
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(self.writes()[0][0], 'POST')
        self.assertEqual(self.writes()[0][1], '/api/v1/courses/123/discussion_topics?no_verifiers=true')
        self.assertNotIn('locked', self.writes()[0][2])
        self.assertEqual({key: self.client.topics[key] for key in original}, original)
        self.assertIsNone(self.client.topics[11]['ungraded_discussion_overrides'])
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertIn('Section filter: 33, 34', brief(result))

    def test_explicit_all_sections_and_scheduled_open_comments_verify_selected_state_not_delivery(self):
        for sections in ({'specific_sections': 'all'}, {'specific_sections': [33]}):
            self.setUp()
            result = self.approved(sections=sections, post_at='2099-10-01T09:00:00-07:00', comments=True)
            self.assertEqual(result['stored_posting_at'], '2099-10-01T16:00:00Z')
            self.assertFalse(result['comments_locked'])
            self.assertTrue(result['created_announcement']['published'])
            self.assertFalse(result['future_execution_verified'])
            self.assertFalse(result['notification_delivery_verified'])
            self.assertEqual(result['announcement_section_filter']['section_ids'], [] if sections['specific_sections'] == 'all' else [33])
            self.assertEqual(len(self.writes()), 1)
        self.assertIn('Stored posting date', brief(result))

    def test_omission_keeps_native_default_without_section_lookup_or_audience_consent(self):
        result = self.approved(sections=None, acknowledge_audience=False)
        self.assertNotIn('announcement_section_filter', result)
        self.assertNotIn('specific_sections', self.writes()[0][2])
        self.assertEqual(self.client.section_reads, 0)
        self.setUp()
        self.client.context['workflow_state'] = 'available'
        for row in self.client.topics.values():
            row['context_type'] = 'Group'
        result = self.approved(sections=None, acknowledge_audience=False, context_type='group')
        self.assertEqual(result['context_type'], 'group')
        self.assertEqual(self.client.section_reads, 0)
        self.assertNotIn('specific_sections', self.writes()[0][2])

    def test_bad_selection_group_or_nonexact_consent_fails_without_network(self):
        for value in ([], [True], [0], ['33'], [33, 33], None, '33', 33, {'id': 33}):
            self.setUp()
            with self.subTest(value=value), self.assertRaises(CanvasError):
                self.preview(sections={'specific_sections': value})
            self.assertEqual(self.client.calls, [])
        for options in ({'sections': {}}, {'sections': []}, {'sections': {'student_ids': [7]}},
                        {'sections': None}, {'acknowledge_audience': False}, {'acknowledge_audience': 1},
                        {'context_type': 'group'}, {'context_type': 'group', 'sections': {'specific_sections': 'all'}},
                        {'acknowledge_shared': False}, {'acknowledge_broadcast': False},
                        {'post_at': '2020-10-01T12:00:00Z'}, {'max_pages': 0}, {'yes': True}, {'confirm': 'unpaired'}):
            self.setUp()
            with self.subTest(options=options), self.assertRaises(CanvasError):
                self.preview(**options)
            self.assertEqual(self.client.calls, [])

    def test_denied_creation_or_incomplete_invalid_foreign_catalog_prevents_post(self):
        for mode in ('creation', 'absent', 'foreign', 'duplicate', 'denied', 'pages'):
            self.setUp()
            if mode == 'creation':
                self.client.creation = False
            elif mode == 'absent':
                self.client.sections.pop()
            elif mode == 'foreign':
                self.client.sections[0]['course_id'] = 124
            elif mode == 'duplicate':
                self.client.sections.append(self.client.sections[0])
            elif mode == 'denied':
                self.client.sections_denied = True
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(max_pages=1 if mode == 'pages' else 100)
            self.assertEqual(self.writes(), [])

    def test_confirmation_is_order_independent_but_binds_catalog_context_inventory_and_identity(self):
        preview = self.preview()
        self.client.sections.reverse()
        self.assertEqual(self.preview(sections={'specific_sections': [33, 34]})['confirm'], preview['confirm'])
        for mode in ('catalog', 'context', 'inventory', 'identity', 'permission', 'choice'):
            self.setUp()
            preview = self.preview()
            options = {}
            if mode == 'catalog':
                self.client.sections[0]['name'] = 'Changed section'
            elif mode == 'context':
                self.client.context['name'] = 'Changed context'
            elif mode == 'inventory':
                self.client.topics[10]['title'] = 'Changed prior announcement'
            elif mode == 'identity':
                self.client.identity = 8
            elif mode == 'permission':
                self.client.creation = False
            else:
                options['sections'] = {'specific_sections': [33]}
            with self.subTest(mode=mode), self.assertRaises(CanvasError) as caught:
                self.preview(yes=True, confirm=preview['confirm'], **options)
            self.assertNotIn('may already', str(caught.exception))
            self.assertEqual(self.writes(), [])
        self.setUp()
        self.client.section_mutation = lambda client: client.sections.pop()
        with self.assertRaisesRegex(CanvasError, 'creation preflight'):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_native_visibility_validation_or_permission_denial_is_one_uncertain_post_without_retry(self):
        for mode in ('visibility', 'validation', 'permission'):
            self.setUp()
            preview = self.preview()
            if mode == 'visibility':
                self.client.section_visible_ids = [33]
            elif mode == 'validation':
                self.client.sections_error_after_apply = True
            else:
                self.client.denied = True
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'may already have succeeded') as caught:
                self.preview(yes=True, confirm=preview['confirm'])
            self.assertEqual(len(self.writes()), 1)
            self.assertNotIn('synthetic-private', str(caught.exception))

    def test_ignored_filter_bad_metadata_or_unverifiable_catalog_and_readback_never_trigger_cleanup(self):
        for mode in ('ignored', 'foreign', 'metadata', 'ack', 'readback', 'catalog', 'catalog_change', 'inventory', 'identity', 'context'):
            self.setUp()
            if mode == 'ignored':
                self.client.ignore_sections = True
            elif mode == 'foreign':
                self.client.ack_patch = {'sections': [{'id': 33, 'course_id': 124}, {'id': 34}]}
            elif mode == 'metadata':
                self.client.ack_patch = {'ungraded_discussion_overrides': []}
            elif mode == 'ack':
                self.client.ack_patch = []
            elif mode == 'readback':
                self.client.after_denied = True
            elif mode == 'catalog':
                self.client.sections_denied_after = True
            elif mode == 'catalog_change':
                self.client.sections_after = copy.deepcopy(self.client.sections)
                self.client.sections_after[0]['name'] = 'Changed section'
            elif mode == 'inventory':
                self.client.after_list_fail = True
            elif mode == 'identity':
                self.client.account_changed = True
            else:
                self.client.context_changed = True
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'may already have succeeded'):
                self.approved()
            self.assertEqual(len(self.writes()), 1)

    def test_native_ignored_all_sections_is_valid_stored_default_not_parameter_acceptance_proof(self):
        self.client.ignore_sections = True
        result = self.approved(sections={'specific_sections': 'all'})
        self.assertFalse(result['announcement_section_filter']['is_section_specific'])
        self.assertEqual(result['announcement_section_filter']['section_ids'], [])
        self.assertTrue(result['announcement_section_filter']['verified'])

    def test_reusing_a_creation_preview_after_the_first_post_prevents_an_accidental_duplicate(self):
        preview = self.preview()
        self.preview(yes=True, confirm=preview['confirm'])
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            self.preview(yes=True, confirm=preview['confirm'])
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(set(self.client.topics), {9, 10, 11})

    def test_creation_clock_is_rechecked_after_catalog_preflight_without_posting_when_expired(self):
        with patch('canvas_cli.announcement_authoring._posting',
                   side_effect=['2099-10-01T16:00:00Z', CanvasError('Scheduled time expired')]), self.assertRaisesRegex(CanvasError, 'expired'):
            self.preview(post_at='2099-10-01T09:00:00-07:00')
        self.assertEqual(self.client.section_reads, 2)
        self.assertEqual(self.writes(), [])

    def test_parser_and_dispatch_expose_optional_course_targeting_without_requiring_default_consent(self):
        flags = ('--acknowledge-shared-announcement', '--acknowledge-broadcast')
        with tempfile.TemporaryDirectory() as directory:
            message_file = Path(directory) / 'message.txt'
            with patch('canvas_cli.dispatch.read_utf8', return_value='Synthetic message'):
                args = parser().parse_args(['announcement-create', '123', '--title', 'Synthetic', '--message-file', str(message_file),
                                            '--section-id', '34', '--section-id', '33', '--acknowledge-audience-change', *flags])
                self.assertEqual(execute(self.client, args)['body']['specific_sections'], '33,34')
                args = parser().parse_args(['announcement-create', '123', '--title', 'Synthetic', '--message-file', str(message_file), *flags])
                self.assertNotIn('specific_sections', execute(self.client, args)['body'])
        with patch('canvas_cli.cli.auth.connect', side_effect=AssertionError('Offline help must not authenticate')):
            help_text = brief(run(parser().parse_args(['help', 'announcement-create', '--format', 'brief'])))
        self.assertIn('--section-id', help_text)
        self.assertIn('--all-sections', help_text)
        self.assertIn('--acknowledge-audience-change', help_text)
