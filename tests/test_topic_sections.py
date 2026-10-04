"""Section filtering validates scope without inventing a modern assign-to permission."""

import copy
import unittest
from unittest.mock import patch

from test_topic_management import TopicClient

from canvas_cli.cli import brief, parser, run
from canvas_cli.client import CanvasError
from canvas_cli.topic_management import change
from canvas_cli.topic_sections import inventory, validate


class SectionClient(TopicClient):
    def __init__(self):
        super().__init__()
        self.sections = [{'id': value, 'course_id': 123, 'name': 'synthetic-private-section',
                          'start_at': None, 'end_at': None, 'nonxlist_course_id': 99,
                          'restrict_enrollments_to_section_dates': False} for value in (33, 34)]
        self.section_reads = 0
        self.sections_denied = self.sections_denied_after = False
        self.section_mutation = None
        self.sections_after = None
        self.old_section_denied = self.new_section_denied = False
        self.lose_update = False
        self.error_after_apply = False
        self.topics[9]['permissions']['manage_assign_to'] = False

    def list(self, route, max_pages):
        if route.endswith('/sections?per_page=100'):
            self.calls.append(('GET', route, None))
            self.section_reads += 1
            if self.sections_denied or self.written and self.sections_denied_after or max_pages < 2:
                raise CanvasError('synthetic-private-section-read-denial', status=403)
            if self.section_reads == 2 and self.section_mutation:
                self.section_mutation(self)
            return copy.deepcopy(self.sections_after if self.written and self.sections_after is not None else self.sections)
        return super().list(route, max_pages)

    def request(self, route, method='GET', body=None):
        if method == 'PUT':
            self.calls.append((method, route, copy.deepcopy(body)))
            if self.denied or self.old_section_denied or self.new_section_denied:
                raise CanvasError('Native old/new section visibility', status=400)
            self.written = True
            row = self.topics[9]
            if not self.ignore and 'specific_sections' not in self.ignored_fields:
                selected = [] if body['specific_sections'] == 'all' else [int(part) for part in body['specific_sections'].split(',')]
                row['is_section_specific'] = bool(selected)
                row['sections'] = [copy.deepcopy(section) for section in self.sections if section['id'] in selected]
                row['ungraded_discussion_overrides'] = [{'student_ids': [7], 'secret': 'synthetic-private-audience'},
                                                       *[{'set_id': value, 'set_type': 'CourseSection'} for value in selected]]
                if self.lose_update:
                    row['permissions']['update'] = False
            if self.error_after_apply:
                raise CanvasError('Native failed validation; verify the write in Canvas before repeating', status=400)
            response = copy.deepcopy(row)
            if self.ack_patch is not None:
                response = response | self.ack_patch if isinstance(self.ack_patch, dict) else self.ack_patch
            return response, ''
        return super().request(route, method, body)


class TopicSectionTests(unittest.TestCase):
    def setUp(self):
        self.client = SectionClient()

    def preview(self, **options):
        return change(self.client, '123', '9', **({'sections': {'specific_sections': [34, 33]},
                      'acknowledge_shared': True, 'acknowledge_audience': True} | options))

    def execute(self, **options):
        preview = self.preview(**options)
        return self.preview(yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [row for row in self.client.calls if row[0] != 'GET']

    def test_preview_canonicalizes_ids_binds_full_course_sections_without_names_sis_roster_or_peer_reads(self):
        preview = self.preview()
        self.assertEqual(preview['body'], {'specific_sections': '33,34'})
        self.assertEqual(preview['active_section_ids'], [33, 34])
        self.assertTrue(preview['acknowledge_audience_change'])
        self.assertEqual(self.client.section_reads, 2)
        self.assertNotIn('synthetic-private', str(preview))
        self.assertIn('not participant overrides', preview['warning'])
        self.assertEqual(self.writes(), [])
        self.assertFalse(any('/users' in route and '/self/profile' not in route or '/entries' in route or '/view' in route
                             for _, route, _ in self.client.calls))

    def test_exact_one_put_and_readback_preserve_content_other_topics_and_participant_overrides(self):
        before = copy.deepcopy(self.client.topics[9])
        result = self.execute()
        selected = result['topic_section_filter']
        self.assertEqual(selected['section_ids'], [33, 34])
        self.assertTrue(selected['is_section_specific'])
        self.assertTrue(selected['verified'])
        self.assertFalse(selected['effective_participant_visibility_verified'])
        self.assertTrue(selected['observed_override_metadata_changed'])
        self.assertEqual(self.writes(), [('PUT', '/api/v1/courses/123/discussion_topics/9?no_verifiers=true',
                                         {'specific_sections': '33,34'})])
        self.assertEqual(self.client.topics[9]['message'], before['message'])
        self.assertEqual(self.client.topics[9]['attachments'], before['attachments'])
        self.assertEqual(self.client.topics[9]['ungraded_discussion_overrides'][0], before['ungraded_discussion_overrides'][0])
        self.assertEqual(self.client.topics[10]['is_section_specific'], False)
        self.assertEqual(result['stored_text_matches_request'], {})
        self.assertEqual(result['unrequested_changed_fields'], ['audience_digest'])
        self.assertNotIn('synthetic-private', str(result))
        self.assertIn('Section filter: 33, 34', brief(result))

    def test_all_sections_clears_only_section_filter_not_modern_participant_overrides(self):
        self.client.topics[9].update(is_section_specific=True, sections=[self.client.sections[0]])
        result = self.execute(sections={'specific_sections': 'all'})
        self.assertFalse(result['topic_section_filter']['is_section_specific'])
        self.assertEqual(result['topic_section_filter']['section_ids'], [])
        self.assertFalse(result['topic_section_filter']['effective_participant_visibility_verified'])
        self.assertEqual(self.client.topics[9]['ungraded_discussion_overrides'][0]['student_ids'], [7])
        self.assertIn('all sections', brief(result))

    def test_own_native_update_with_false_modern_assign_to_permission_is_not_arbitrarily_restricted(self):
        result = self.execute()
        self.assertTrue(result['topic_section_filter']['verified'])
        self.assertFalse(any('/permissions' in route for _, route, _ in self.client.calls))
        self.setUp()
        self.client.topics[9]['permissions']['update'] = False
        with self.assertRaisesRegex(CanvasError, 'exact discussion-topic update'):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_native_old_and_new_visibility_denials_do_not_retry_or_invent_preflight_authority(self):
        for mode in ('old_section_denied', 'new_section_denied'):
            self.setUp()
            setattr(self.client, mode, True)
            with self.subTest(mode=mode), self.assertRaises(CanvasError) as caught:
                self.execute()
            self.assertEqual(caught.exception.status, 400)
            self.assertEqual(len(self.writes()), 1)

    def test_local_invalid_values_acknowledgements_and_conflicting_operations_make_no_network_calls(self):
        for value in ([], [33, 33], [True], [0], ['33'], None, 33, '33', {'id': 33}):
            self.setUp()
            with self.subTest(value=value), self.assertRaises(CanvasError):
                self.preview(sections={'specific_sections': value})
            self.assertEqual(self.client.calls, [])
        for options in ({'sections': {}}, {'sections': []}, {'sections': {'student_ids': [7]}},
                        {'acknowledge_audience': False}, {'acknowledge_audience': 1}, {'acknowledge_shared': False},
                        {'sections': None}, {'context_type': 'group'}, {'todo': {'todo_date': None}},
                        {'options': {'expanded': True}}, {'action': 'close'}, {'schedule': {'lock_at': None}},
                        {'title': 'Conflict'}, {'delete': True}, {'max_pages': 0}, {'yes': True}, {'confirm': 'unpaired'}):
            self.setUp()
            with self.subTest(options=options), self.assertRaises(CanvasError):
                self.preview(**options)
            self.assertEqual(self.client.calls, [])
        self.assertEqual(validate({'specific_sections': [34, 33]}, 'course'), {'specific_sections': '33,34'})
        self.assertEqual(validate({'specific_sections': list(range(1, 1002))}, 'course')['specific_sections'],
                         ','.join(str(value) for value in range(1, 1002)))

    def test_foreign_malformed_duplicate_or_incomplete_section_catalog_fails_before_put(self):
        for field, value in (('id', True), ('course_id', 124), ('course_id', '123'), ('name', None),
                             ('workflow_state', 'deleted'), ('start_at', 'today'), ('end_at', True),
                             ('restrict_enrollments_to_section_dates', 1), ('nonxlist_course_id', 0)):
            self.setUp()
            self.client.sections[0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.writes(), [])
        for mode in ('duplicate', 'absent', 'denied', 'limit'):
            self.setUp()
            if mode == 'duplicate':
                self.client.sections.append(self.client.sections[0])
            elif mode == 'absent':
                self.client.sections.pop()
            elif mode == 'denied':
                self.client.sections_denied = True
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(max_pages=1 if mode == 'limit' else 100)
            self.assertEqual(self.writes(), [])

    def test_section_reordering_is_canonical_and_crosslisted_original_course_is_not_a_foreign_parent(self):
        preview = self.preview()
        self.client.sections.reverse()
        self.assertEqual(self.preview()['confirm'], preview['confirm'])
        self.assertEqual(inventory(self.client, '/api/v1/courses/123', '123', 100)[0]['id'], 33)

    def test_noop_filter_does_not_write(self):
        self.client.topics[9].update(is_section_specific=True, sections=copy.deepcopy(self.client.sections))
        with self.assertRaisesRegex(CanvasError, 'already matches'):
            self.preview()
        self.setUp()
        with self.assertRaisesRegex(CanvasError, 'already matches'):
            self.preview(sections={'specific_sections': 'all'})
        self.assertEqual(self.writes(), [])

    def test_missing_override_metadata_foreign_returned_sections_and_linked_topics_are_unknown_not_safe(self):
        for field, value in (('ungraded_discussion_overrides', None), ('ungraded_discussion_overrides', {}),
                             ('assignment_id', 88), ('root_topic_id', 89), ('group_category_id', 90),
                             ('anonymous_state', 'full_anonymity'), ('is_announcement', True)):
            self.setUp()
            self.client.topics[9][field] = value
            with self.subTest(field=field), self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.writes(), [])
        self.setUp()
        self.client.topics[9].update(is_section_specific=True, sections=[{'id': 33, 'course_id': 124}])
        with self.assertRaisesRegex(CanvasError, 'outside'):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_stale_account_context_content_audience_catalog_inventory_and_rights_prevent_put(self):
        for mode in ('account', 'context', 'content', 'audience', 'section', 'inventory', 'rights'):
            self.setUp()
            preview = self.preview()
            if mode == 'account':
                self.client.identity = 8
            elif mode == 'context':
                self.client.context['name'] = 'Changed context'
            elif mode == 'content':
                self.client.topics[9]['message'] = '<p>Changed</p>'
            elif mode == 'audience':
                self.client.topics[9]['ungraded_discussion_overrides'].append({'student_ids': [8]})
            elif mode == 'section':
                self.client.sections[0]['name'] = 'Changed section'
            elif mode == 'inventory':
                self.client.topics[10]['title'] = 'Changed other topic'
            else:
                self.client.topics[9]['permissions']['update'] = False
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(yes=True, confirm=preview['confirm'])
            self.assertEqual(self.writes(), [])
        self.setUp()
        self.client.section_mutation = lambda client: client.sections.pop()
        with self.assertRaisesRegex(CanvasError, 'changed during preflight'):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_ack_readback_drift_ignored_filter_catalog_change_or_denial_is_uncertain_and_never_retried(self):
        for mode in ('ack', 'wrong_ids', 'foreign', 'metadata', 'ignored', 'readback', 'catalog', 'catalog_change',
                     'inventory', 'account', 'context'):
            self.setUp()
            if mode == 'ack':
                self.client.ack_patch = []
            elif mode == 'wrong_ids':
                self.client.ack_patch = {'sections': [{'id': 34}]}
                self.client.after_patch = self.client.ack_patch
            elif mode == 'foreign':
                self.client.ack_patch = {'sections': [{'id': 33, 'course_id': 124}, {'id': 34}]}
            elif mode == 'metadata':
                self.client.ack_patch = {'ungraded_discussion_overrides': None}
            elif mode == 'ignored':
                self.client.ignore = True
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
            else:
                self.client.context_changed = True
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'may already have succeeded') as caught:
                self.execute()
            self.assertEqual(len(self.writes()), 1)
            self.assertNotIn('synthetic-private', str(caught.exception))

    def test_verified_change_can_remove_future_update_permission_without_a_persistence_claim(self):
        self.client.lose_update = True
        result = self.execute()
        self.assertFalse(result['edited_topic']['permissions']['update'])
        self.assertTrue(result['topic_section_filter']['verified'])

    def test_http_error_after_association_change_is_not_retried_or_treated_as_unchanged(self):
        self.client.error_after_apply = True
        with self.assertRaises(CanvasError) as caught:
            self.execute()
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(len(self.writes()), 1)
        self.assertTrue(self.client.topics[9]['is_section_specific'])
        self.assertEqual([row['id'] for row in self.client.topics[9]['sections']], [33, 34])

    @patch('canvas_cli.auth.connect')
    def test_parser_dispatch_default_preview_and_brief_use_short_command(self, connect):
        connect.return_value = self.client
        args = parser().parse_args(['topic-sections', '123', '9', '--section-id', '34', '--section-id', '33',
                                  '--acknowledge-shared-topic', '--acknowledge-audience-change'])
        result = run(args)
        self.assertTrue(result['dry_run'])
        self.assertEqual(result['body'], {'specific_sections': '33,34'})
        self.assertEqual(self.writes(), [])
