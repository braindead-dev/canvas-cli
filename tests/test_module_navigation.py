"""Native occurrence limits, neighboring parents and associated assignments are not inferred."""

import copy
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from canvas_cli.client import CanvasError
from canvas_cli.formatting import brief
from canvas_cli.module_navigation import sequence


class SequenceClient:
    host = 'https://canvas.example.edu'

    def __init__(self):
        self.calls = []
        self.context = {'id': 123, 'name': 'Synthetic course'}
        self.result = {'items': [{'prev': None, 'current': {'id': 3, 'module_id': 2, 'title': 'Synthetic current',
                                                         'type': 'Page', 'page_url': 'welcome'},
                                 'next': {'id': 4, 'module_id': 5, 'title': 'Synthetic next', 'type': 'Assignment', 'content_id': 88},
                                 'mastery_path': {'locked': False, 'awaiting_choice': True, 'still_processing': False,
                                                 'selected_set_id': None, 'modules_tab_disabled': False,
                                                 'assignment_sets': [{'id': 9, 'private': 'synthetic-private-path',
                                                                      'assignment_set_associations': [{'model': {'body': 'synthetic-private'}}]}],
                                                 'choose_url': 'https://foreign.example/?token=synthetic-private'}}],
                       'modules': [{'id': 2, 'name': 'Synthetic first'}, {'id': 5, 'name': 'Synthetic second'}],
                       'private': 'synthetic-private-envelope'}
        self.source = {'id': 77, 'course_id': 123, 'assignment_id': 88, 'body': 'synthetic-private-source'}
        self.links = ''

    def request(self, route, method='GET', body=None):
        self.calls.append((method, route, body))
        assert method == 'GET' and body is None
        url = urlsplit(route)
        if url.path == '/api/v1/courses/123':
            return copy.deepcopy(self.context), ''
        if url.path == '/api/v1/courses/123/module_item_sequence':
            assert set(parse_qs(url.query)) == {'asset_type', 'asset_id'}
            return copy.deepcopy(self.result), self.links
        assert url.path in ('/api/v1/courses/123/quizzes/77', '/api/v1/courses/123/discussion_topics/77')
        return copy.deepcopy(self.source), ''


class ModuleNavigationTests(unittest.TestCase):
    def setUp(self):
        self.client = SequenceClient()

    def lookup(self, asset_type='ModuleItem', asset_id='3'):
        return sequence(self.client, '123', asset_type, asset_id)

    def test_exact_occurrence_neighbors_cross_modules_and_private_metadata_projection(self):
        result = self.lookup()
        self.assertEqual(result['matched_occurrences'], 1)
        node = result['module_sequence'][0]
        self.assertIsNone(node['prev'])
        self.assertEqual(node['next']['module_id'], 5)
        self.assertIsNone(node['current']['locked_for_user'])
        self.assertEqual(node['current']['completion'], 'not_required')
        self.assertEqual(node['mastery_path']['assignment_set_ids'], [9])
        self.assertEqual(node['mastery_path']['choose_html_url'], 'https://canvas.example.edu/courses/123/modules/items/3/choose')
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertIn('current: Synthetic current', brief(result))
        self.assertIn('Mastery-path metadata', brief(result))
        self.assertEqual(len(self.client.calls), 2)

    def test_all_documented_asset_types_match_exact_native_ids_or_page_slug(self):
        for asset_type in ('File', 'Page', 'Discussion', 'Assignment', 'Quiz', 'ExternalTool'):
            self.setUp()
            current = self.client.result['items'][0]['current']
            current.update(type=asset_type, content_id=77)
            with self.subTest(asset_type=asset_type):
                result = self.lookup(asset_type, 'welcome' if asset_type == 'Page' else '77')
                self.assertEqual(result['matched_occurrences'], 1)
                self.assertEqual(len(self.client.calls), 2)

    def test_quiz_and_discussion_can_point_to_independently_verified_associated_assignments(self):
        for kind in ('Quiz', 'Discussion'):
            self.setUp()
            self.client.result['items'][0]['current'].update(type='Assignment', content_id=88)
            result = self.lookup(kind, '77')
            self.assertEqual(result['module_sequence'][0]['current']['content_id'], 88)
            self.assertEqual(len(self.client.calls), 3)
            self.assertNotIn('synthetic-private', json.dumps(result))

    def test_ten_occurrence_limit_is_not_a_complete_inventory_claim(self):
        template = self.client.result['items'][0]
        self.client.result['items'] = [dict(copy.deepcopy(template), current={**template['current'], 'id': 10 + index}) for index in range(10)]
        result = self.lookup('Page', 'welcome')
        self.assertEqual(result['native_occurrence_limit'], 10)
        self.assertTrue(result['at_native_limit'])
        self.assertIn('additional occurrences may exist', brief(result))

    def test_empty_sequence_and_absent_mastery_metadata_are_valid_not_completed_coursework(self):
        self.client.result['items'][0].pop('mastery_path')
        result = self.lookup()
        self.assertIsNone(result['module_sequence'][0]['mastery_path'])
        self.client.result = {'items': [], 'modules': []}
        result = self.lookup('Page', 'not-listed')
        self.assertEqual(result['matched_occurrences'], 0)
        self.assertFalse(result['at_native_limit'])
        self.assertIn('not a complete item inventory', result['note'])

    def test_validation_rejects_urls_controls_invalid_numeric_ids_or_undocumented_types_before_requests(self):
        for kind, identifier in (('unknown', '3'), ('File', '0'), ('Quiz', True), ('ModuleItem', '../3'),
                                 ('Page', ''), ('Page', '..'), ('Page', 'https://foreign.example'),
                                 ('Page', 'a?token=private'), ('Page', 'a#anchor'), ('Page', 'a\\b'),
                                 ('Page', 'a\n'), ('Page', '\ud800'), ('Page', 'a' * 256)):
            with self.subTest(kind=kind, identifier=identifier), self.assertRaises(CanvasError):
                self.lookup(kind, identifier)
        self.assertEqual(self.client.calls, [])

    def test_unicode_page_slug_is_one_encoded_query_value(self):
        self.client.result['items'][0]['current']['page_url'] = 'café & résumé'
        result = self.lookup('Page', 'café & résumé')
        self.assertEqual(result['asset_id'], 'café & résumé')
        self.assertEqual(parse_qs(urlsplit(self.client.calls[-1][1]).query)['asset_id'], ['café & résumé'])

    def test_malformed_envelope_limit_and_unexpected_pagination_are_errors(self):
        for mode in ('list', 'missing_items', 'bad_modules', 'too_many', 'pagination', 'wrong_course'):
            self.setUp()
            if mode == 'list':
                self.client.result = []
            elif mode == 'missing_items':
                self.client.result.pop('items')
            elif mode == 'bad_modules':
                self.client.result['modules'] = {}
            elif mode == 'too_many':
                self.client.result['items'] *= 11
            elif mode == 'pagination':
                self.client.links = '</api/v1/foreign>; rel="next"'
            else:
                self.client.context['id'] = 124
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.lookup()

    def test_invalid_module_ids_foreign_parents_or_malformed_metadata_fail_without_body_logging(self):
        for patch in ({'id': True}, {'course_id': 124}, {'course_id': True}, {'name': {'body': 'synthetic-private'}},
                      {'position': True}, {'items_count': -1}, {'prerequisite_module_ids': [True]},
                      {'prerequisite_module_ids': 'synthetic-private'}, {'prerequisite_module_ids': [1, 1]}):
            self.setUp()
            self.client.result['modules'][0].update(patch)
            with self.subTest(patch=patch), self.assertRaises(CanvasError) as error:
                self.lookup()
            self.assertNotIn('synthetic-private', str(error.exception))
        self.setUp()
        self.client.result['modules'].append(copy.deepcopy(self.client.result['modules'][0]))
        with self.assertRaisesRegex(CanvasError, 'duplicate'):
            self.lookup()

    def test_invalid_nodes_missing_referenced_modules_and_duplicate_currents_fail(self):
        for mode in ('not_object', 'null_current', 'missing_next', 'foreign_module', 'foreign_item', 'duplicate'):
            self.setUp()
            node = self.client.result['items'][0]
            if mode == 'not_object':
                self.client.result['items'][0] = []
            elif mode == 'null_current':
                node['current'] = None
            elif mode == 'missing_next':
                node.pop('next')
            elif mode == 'foreign_module':
                node['next']['module_id'] = 9
            elif mode == 'foreign_item':
                node['current']['id'] = 9
            else:
                self.client.result['items'].append(copy.deepcopy(node))
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.lookup()

    def test_page_or_content_asset_mismatch_fails_exact_association(self):
        for kind, identifier in (('Page', 'different'), ('File', '77'), ('Assignment', '77')):
            with self.subTest(kind=kind), self.assertRaises(CanvasError):
                self.lookup(kind, identifier)

    def test_foreign_source_id_parent_and_unproven_assignment_association_fail(self):
        for patch in ({'id': 78}, {'course_id': 124}, {'course_id': True}, {'assignment_id': True}, {'assignment_id': 89}):
            self.setUp()
            self.client.source.update(patch)
            self.client.result['items'][0]['current'].update(type='Assignment', content_id=88)
            with self.subTest(patch=patch), self.assertRaises(CanvasError):
                self.lookup('Quiz', '77')

    def test_malformed_mastery_flags_sets_or_selected_ids_are_not_raw_payload_output(self):
        for patch in ({'locked': 1}, {'assignment_sets': 'synthetic-private'}, {'assignment_sets': [{'id': True}]},
                      {'assignment_sets': [{'id': 9}, {'id': 9}]}, {'selected_set_id': True}):
            self.setUp()
            self.client.result['items'][0]['mastery_path'].update(patch)
            with self.subTest(patch=patch), self.assertRaises(CanvasError) as error:
                self.lookup()
            self.assertNotIn('synthetic-private', str(error.exception))
        self.setUp()
        self.client.result['items'][0]['mastery_path'] = []
        with self.assertRaises(CanvasError):
            self.lookup()

    def test_minimal_mastery_and_unknown_native_completion_stay_unknown(self):
        node = self.client.result['items'][0]
        node['mastery_path'] = {'selected_set_id': 9}
        node['current']['completion_requirement'] = {'type': 'must_view'}
        result = self.lookup()
        self.assertEqual(result['module_sequence'][0]['current']['completion'], 'unknown')
        self.assertEqual(result['module_sequence'][0]['mastery_path'], {'selected_set_id': 9})
        node['mastery_path'] = {'awaiting_choice': False, 'assignment_sets': []}
        self.assertEqual(self.lookup()['module_sequence'][0]['mastery_path'], {'awaiting_choice': False, 'assignment_set_ids': []})


if __name__ == '__main__':
    unittest.main()
