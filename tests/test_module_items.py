"""Independent own progression state, scoped parents and non-proof acknowledgements."""

import copy
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from canvas_cli.client import CanvasError
from canvas_cli.formatting import brief
from canvas_cli.module_items import change, read


class ModuleClient:
    host = 'https://canvas.example.edu'

    def __init__(self):
        self.calls = []
        self.identity = 7
        self.course = {'id': 123, 'name': 'Synthetic course', 'workflow_state': 'available',
                       'private': 'synthetic-private-course'}
        self.rights = {'participate_as_student': True}
        self.module = {'id': 2, 'name': 'Synthetic module', 'position': 1, 'state': 'started',
                       'completed_at': None, 'requirement_type': 'all', 'require_sequential_progress': False,
                       'prerequisite_module_ids': [], 'items_count': 2, 'publish_final_grade': False,
                       'private': 'synthetic-private-module', 'items_url': 'https://foreign.example/?token=synthetic-private'}
        self.items = [
            {'id': 3, 'module_id': 2, 'title': 'Synthetic checkbox', 'type': 'Page', 'position': 1,
             'indent': 0, 'page_url': 'welcome', 'completion_requirement': {'type': 'must_mark_done', 'completed': False},
             'content_details': {'locked_for_user': False, 'due_at': None, 'body': 'synthetic-private-body',
                                 'thumbnail_url': 'https://foreign.example/?token=synthetic-private'},
             'url': 'https://foreign.example/?token=synthetic-private', 'html_url': 'https://foreign.example/?token=synthetic-private',
             'external_url': 'https://foreign.example/?token=synthetic-private'},
            {'id': 4, 'module_id': 2, 'title': 'Synthetic optional', 'type': 'ExternalTool',
             'position': 2, 'content_id': 88, 'content_details': {'locked_for_user': False}},
        ]
        self.written = self.ignored = self.denied = self.inventory_failure = self.readback_denied = False
        self.acknowledgement = {'message': 'D’accord', 'private': 'synthetic-private-ack'}
        self.after_write = self.before_inventory = None
        self.module_reads = self.profile_reads = self.written_profile_reads = 0
        self.module_drift = self.preflight_switch = self.final_switch = False
        self.planner_checkbox = False

    def request(self, route, method='GET', body=None):
        self.calls.append((method, route, copy.deepcopy(body)))
        url = urlsplit(route)
        if method != 'GET':
            self.assert_event(method, url.path, body)
            if self.denied:
                raise CanvasError('synthetic-private-denial', status=403)
            self.written = True
            criterion = self.items[0].get('completion_requirement')
            if not self.ignored:
                if method == 'DELETE' and criterion:
                    criterion['completed'] = False
                    self.planner_checkbox = False
                if method == 'PUT' and criterion and criterion['type'] == 'must_mark_done':
                    criterion['completed'] = True
                    self.planner_checkbox = True
                if method == 'POST' and criterion and criterion['type'] == 'must_view':
                    criterion['completed'] = True
                if criterion and criterion.get('completed') is True:
                    self.module.update(state='completed', completed_at='2026-10-03T12:00:00Z')
                else:
                    self.module.update(state='started', completed_at=None)
            if self.after_write:
                self.after_write(self)
            return copy.deepcopy(self.acknowledgement), ''
        if url.path == '/api/v1/users/self/profile':
            self.profile_reads += 1
            self.written_profile_reads += int(self.written)
            if self.preflight_switch and self.profile_reads > 1 or self.final_switch and self.written_profile_reads > 1:
                return {'id': 8}, ''
            return {'id': self.identity, 'email': 'synthetic-private@example.edu'}, ''
        if url.path == '/api/v1/courses/123':
            return copy.deepcopy(self.course), ''
        if url.path == '/api/v1/courses/123/permissions':
            assert parse_qs(url.query) == {'permissions[]': ['participate_as_student']}
            return copy.deepcopy(self.rights), ''
        if url.path == '/api/v1/courses/123/modules/2':
            assert parse_qs(url.query) in ({}, {'student_id': [str(self.identity)]})
            self.module_reads += 1
            if self.readback_denied and self.written:
                raise CanvasError('synthetic-private-readback', status=403)
            row = copy.deepcopy(self.module)
            if self.module_drift and self.module_reads % 2 == 0:
                row['name'] = 'Changed'
            return row, ''
        raise AssertionError(('No single-item GET or content follow allowed', method, route))

    def assert_event(self, method, path, body):
        assert (method, path) in (('PUT', '/api/v1/courses/123/modules/2/items/3/done'),
                                  ('DELETE', '/api/v1/courses/123/modules/2/items/3/done'),
                                  ('POST', '/api/v1/courses/123/modules/2/items/3/mark_read'))
        assert body is None

    def list(self, route, max_pages):
        self.calls.append(('GET', route, None))
        url = urlsplit(route)
        assert url.path == '/api/v1/courses/123/modules/2/items'
        assert parse_qs(url.query) in (
            {'per_page': ['100'], 'include[]': ['content_details']},
            {'per_page': ['100'], 'include[]': ['content_details'], 'student_id': [str(self.identity)]})
        if self.inventory_failure:
            raise CanvasError('Page limit reached')
        if self.before_inventory:
            self.before_inventory(self)
        return copy.deepcopy(self.items)


class ModuleItemTests(unittest.TestCase):
    def setUp(self):
        self.client = ModuleClient()

    def preview(self, operation='done', **options):
        return change(self.client, '123', '2', '3', operation, acknowledge_progress=True,
                      acknowledge_viewed=operation == 'read', **options)

    def approve(self, operation='done'):
        preview = self.preview(operation)
        return self.preview(operation, yes=True, confirm=preview['confirm'])

    def writes(self):
        return [row for row in self.client.calls if row[0] != 'GET']

    def test_inspection_list_only_minimal_student_metadata_and_safe_constructed_link(self):
        result = read(self.client, '123', '2', '3')
        self.assertTrue(result['complete_item_inventory'])
        self.assertEqual(result['module_item']['completion'], 'incomplete')
        self.assertEqual(result['module_item']['html_url'], 'https://canvas.example.edu/courses/123/modules/items/3')
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertIn('Synthetic checkbox', brief(result))
        self.assertFalse(any('items/3' in route for _, route, _ in self.client.calls))
        self.assertEqual(self.writes(), [])

    def test_read_preserves_unknown_optional_threshold_and_locked_metadata(self):
        item = self.client.items[0]
        for criterion, completion in ((None, 'not_required'), ({'type': 'must_view'}, 'unknown'),
                                      ({'type': 'min_score', 'min_score': 0, 'completed': True}, 'completed'),
                                      ({'type': 'min_percentage', 'min_percentage': 80.5, 'completed': False}, 'incomplete')):
            with self.subTest(criterion=criterion):
                item['completion_requirement'] = criterion
                result = read(self.client, '123', '2', '3')
                self.assertEqual(result['module_item']['completion'], completion)
        item['content_details']['locked_for_user'] = True
        self.assertIn('locked', brief(read(self.client, '123', '2', '3')))

    def test_preview_is_own_bound_and_emits_no_event(self):
        preview = self.preview()
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['method'], 'PUT')
        self.assertEqual(preview['route'], '/api/v1/courses/123/modules/2/items/3/done')
        self.assertEqual(preview['user_id'], 7)
        self.assertNotIn('body', preview)
        self.assertEqual(self.writes(), [])
        self.assertNotIn('synthetic-private', json.dumps(preview))
        self.assertIn('student_id=7', next(route for _, route, _ in self.client.calls if '/modules/2?' in route))

    def test_done_and_not_done_verify_readback_and_report_native_state_not_infer_it(self):
        result = self.approve()
        self.assertTrue(result['requirement_status_verified'])
        self.assertTrue(self.client.planner_checkbox)
        self.assertFalse(result['planner_synchronization_verified'])
        self.assertEqual(result['module']['state'], 'completed')
        self.assertEqual(self.writes(), [('PUT', '/api/v1/courses/123/modules/2/items/3/done', None)])
        result = self.approve('not-done')
        self.assertFalse(result['module_item']['requirement']['completed'])
        self.assertEqual(result['module']['state'], 'started')
        self.assertFalse(self.client.planner_checkbox)
        self.assertEqual(len(self.writes()), 2)
        self.assertEqual(self.writes()[-1][0], 'DELETE')
        self.assertIn('verified', brief(result))
        self.assertNotIn('synthetic-private', json.dumps(result))

    def test_read_verifies_only_must_view_and_handles_other_or_absent_requirements(self):
        for criterion in ({'type': 'must_view', 'completed': False},
                          {'type': 'must_submit', 'completed': False}, None):
            self.setUp()
            self.client.items[0]['completion_requirement'] = criterion
            result = self.approve('read')
            self.assertEqual(self.writes(), [('POST', '/api/v1/courses/123/modules/2/items/3/mark_read', None)])
            self.assertTrue(result['event_acknowledged'])
            if criterion and criterion['type'] == 'must_view':
                self.assertTrue(result['requirement_status_verified'])
                self.assertTrue(result['module_item']['requirement']['completed'])
            else:
                self.assertIsNone(result['requirement_status_verified'])
                self.assertIn('not verifiable', brief(result))
                self.assertEqual(result['module_item']['requirement'], criterion)

    def test_native_one_rule_and_sis_policy_are_preserved_and_bound(self):
        self.client.module.update(requirement_type='one', publish_final_grade=True,
                                  require_sequential_progress=True, requirement_count=1)
        preview = self.preview()
        self.assertTrue(preview['module']['publish_final_grade'])
        self.assertIn('SIS', preview['warning'])
        result = self.preview(yes=True, confirm=preview['confirm'])
        self.assertEqual(result['module']['requirement_type'], 'one')

    def test_validation_and_required_acknowledgements_fail_before_requests(self):
        cases = [dict(acknowledge_progress=False), dict(operation='read', acknowledge_progress=True),
                 dict(operation='invalid', acknowledge_progress=True), dict(acknowledge_progress=True, max_pages=0),
                 dict(acknowledge_progress=True, max_pages=True), dict(acknowledge_progress=True, yes=True),
                 dict(acknowledge_progress=True, confirm='digest')]
        for options in cases:
            operation = options.pop('operation', 'done')
            with self.subTest(options=options), self.assertRaises(CanvasError):
                change(self.client, '123', '2', '3', operation, **options)
        for ids in (('0', '2', '3'), ('123', '../2', '3'), ('123', '2', True)):
            with self.subTest(ids=ids), self.assertRaises(CanvasError):
                read(self.client, *ids)
        with self.assertRaises(CanvasError):
            read(self.client, '123', '2', '3', max_pages='1')
        self.assertEqual(self.client.calls, [])

    def test_course_and_explicit_student_permission_gates_do_not_infer_a_role(self):
        for patch in ({'workflow_state': 'completed'}, {'workflow_state': 'unpublished'},
                      {'concluded': True}, {'access_restricted_by_date': True}, {'id': 124}, {'id': True}):
            self.setUp()
            self.client.course.update(patch)
            with self.subTest(patch=patch), self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.writes(), [])
        for rights in ({}, {'participate_as_student': 'true'}, {'participate_as_student': False}):
            self.setUp()
            self.client.rights = rights
            with self.subTest(rights=rights), self.assertRaises(CanvasError):
                self.preview()
            self.assertFalse(any('/modules/' in route for _, route, _ in self.client.calls))

    def test_locked_unpublished_mismatched_or_malformed_module_never_lists_items(self):
        for patch in ({'id': 9}, {'id': True}, {'state': 'locked'}, {'locked_for_user': True},
                      {'published': False}, {'workflow_state': 'deleted'}, {'hidden_for_user': True},
                      {'publish_final_grade': 'yes'}, {'locked_for_user': 1}, {'published': 1}):
            self.setUp()
            self.client.module.update(patch)
            with self.subTest(patch=patch), self.assertRaises(CanvasError):
                read(self.client, '123', '2', '3')
            self.assertFalse(any('/items?' in route for _, route, _ in self.client.calls))

    def test_item_shape_parent_id_requirements_and_visibility_fail_closed_without_body_logging(self):
        for patch in ({'id': True}, {'module_id': 99}, {'module_id': True}, {'title': ''}, {'type': None},
                      {'published': 'yes'}, {'locked_for_user': 'yes'}, {'hidden_for_user': True},
                      {'published': False}, {'completion_requirement': 'synthetic-private'},
                      {'completion_requirement': {'completed': False}},
                      {'completion_requirement': {'type': 'must_view', 'completed': 1}},
                      {'completion_requirement': {'type': 'min_score', 'min_score': True}},
                      {'completion_requirement': {'type': 'min_percentage', 'min_percentage': float('inf')}},
                      {'content_details': None}, {'content_details': 'synthetic-private'},
                      {'content_details': {'locked_for_user': 'true'}}, {'content_details': {'hidden': True}}):
            self.setUp()
            self.client.items[0].update(patch)
            with self.subTest(patch=patch), self.assertRaises(CanvasError) as error:
                read(self.client, '123', '2', '3')
            self.assertNotIn('synthetic-private', str(error.exception))
            self.assertEqual(self.writes(), [])

    def test_inventory_requires_all_pages_unique_ids_and_stable_module_state(self):
        for mode in ('missing', 'duplicate', 'count', 'count_boolean', 'pagination', 'drift'):
            self.setUp()
            if mode == 'missing':
                self.client.items[0]['id'] = 5
            elif mode == 'duplicate':
                self.client.items[1]['id'] = 3
            elif mode == 'count':
                self.client.module['items_count'] = 3
            elif mode == 'count_boolean':
                self.client.module['items_count'] = True
            elif mode == 'pagination':
                self.client.inventory_failure = True
            else:
                self.client.module_drift = True
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.writes(), [])

    def test_projected_dates_points_identifiers_and_policy_reject_nested_or_invalid_values(self):
        for patch in ({'content_id': True}, {'position': 0}, {'indent': -1}, {'page_url': {'body': 'synthetic-private'}},
                      {'publish_at': []}, {'content_details': {'locked_for_user': False, 'due_at': {}}},
                      {'content_details': {'locked_for_user': False, 'points_possible': True}},
                      {'content_details': {'locked_for_user': False, 'points_possible': float('nan')}},
                      {'completion_requirement': {'type': 'min_score', 'min_score': 'synthetic-private'}}):
            self.setUp()
            self.client.items[0].update(patch)
            with self.subTest(patch=patch), self.assertRaises(CanvasError) as error:
                read(self.client, '123', '2', '3')
            self.assertNotIn('synthetic-private', str(error.exception))
        self.setUp()
        self.client.module['prerequisite_module_ids'] = [1]
        self.client.items[0]['content_details']['points_possible'] = 1.5
        self.client.items[0]['completion_requirement'] = {'type': 'min_score', 'min_score': 10 ** 400}
        self.assertEqual(read(self.client, '123', '2', '3')['module_item']['completion'], 'unknown')

    def test_write_requires_known_policy_lock_state_and_real_checkbox_not_assessment(self):
        for mode in ('unknown_state', 'unknown_policy', 'unknown_sis', 'unknown_rule', 'locked',
                     'missing_lock', 'heading', 'submit', 'unknown_completion', 'already_done', 'already_not_done', 'absent_requirement'):
            self.setUp()
            operation = 'not-done' if mode == 'already_not_done' else 'done'
            if mode == 'unknown_state':
                self.client.module.pop('state')
            elif mode == 'unknown_policy':
                self.client.module.pop('require_sequential_progress')
            elif mode == 'unknown_sis':
                self.client.module.pop('publish_final_grade')
            elif mode == 'unknown_rule':
                self.client.module['requirement_type'] = None
            elif mode == 'locked':
                self.client.items[0]['content_details']['locked_for_user'] = True
            elif mode == 'missing_lock':
                self.client.items[0]['content_details'].pop('locked_for_user')
            elif mode == 'heading':
                self.client.items[0]['type'] = 'SubHeader'
            elif mode == 'submit':
                self.client.items[0]['completion_requirement']['type'] = 'must_submit'
            elif mode == 'unknown_completion':
                self.client.items[0]['completion_requirement'].pop('completed')
            elif mode == 'already_done':
                self.client.items[0]['completion_requirement']['completed'] = True
            elif mode == 'absent_requirement':
                self.client.items[0]['completion_requirement'] = None
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(operation)
            self.assertEqual(self.writes(), [])

    def test_stale_previews_bind_other_items_account_permission_and_module_policy(self):
        for mode in ('other_item', 'policy', 'account', 'permission'):
            self.setUp()
            preview = self.preview()
            if mode == 'other_item':
                self.client.items[1]['title'] = 'Changed'
            elif mode == 'policy':
                self.client.module['publish_final_grade'] = True
            elif mode == 'account':
                self.client.identity = 8
            else:
                self.client.rights['participate_as_student'] = False
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.preview(yes=True, confirm=preview['confirm'])
            self.assertEqual(self.writes(), [])
        self.setUp()
        self.client.preflight_switch = True
        with self.assertRaises(CanvasError):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_localized_ack_not_state_proof_and_no_retry_on_ignored_write_or_readback_denial(self):
        for mode in ('ignored', 'denied', 'readback', 'ack_list', 'ack_missing', 'ack_empty'):
            self.setUp()
            if mode == 'ignored':
                self.client.ignored = True
            elif mode == 'denied':
                self.client.denied = True
            elif mode == 'readback':
                self.client.readback_denied = True
            else:
                self.client.acknowledgement = [] if mode == 'ack_list' else {} if mode == 'ack_missing' else {'message': ''}
            with self.subTest(mode=mode), self.assertRaises(CanvasError) as error:
                self.approve()
            self.assertEqual(len(self.writes()), 1)
            if mode != 'denied':
                self.assertIn('may have changed', str(error.exception))
                self.assertNotIn('synthetic-private', str(error.exception))

    def test_post_event_identity_permission_policy_target_and_requirement_drift_are_uncertain(self):
        changes = [lambda client: client.course.update(name='Changed'),
                   lambda client: client.rights.update(participate_as_student=False),
                   lambda client: setattr(client, 'identity', 8),
                   lambda client: client.module.update(requirement_type='one'),
                   lambda client: client.items[0].update(title='Changed'),
                   lambda client: client.items[0]['completion_requirement'].update(type='must_submit'),
                   lambda client: client.items[0].update(completion_requirement=None),
                   lambda client: setattr(client, 'final_switch', True)]
        for mutation in changes:
            self.setUp()
            self.client.after_write = mutation
            with self.subTest(mutation=mutation), self.assertRaisesRegex(CanvasError, 'may have changed'):
                self.approve()
            self.assertEqual(len(self.writes()), 1)


if __name__ == '__main__':
    unittest.main()
