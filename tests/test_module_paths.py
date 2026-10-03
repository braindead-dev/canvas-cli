"""Independent native choices, posted grades, switches and non-proof acknowledgements."""

import copy
import json
import unittest
from urllib.parse import urlsplit

from test_module_items import ModuleClient

from canvas_cli.client import CanvasError
from canvas_cli.formatting import brief
from canvas_cli.module_paths import read, select


def native_paths():
    return {'locked': False, 'awaiting_choice': True, 'selected_set_id': None,
            'assignment_sets': [
                {'id': identifier, 'assignment_set_associations': [
                    {'assignment_set_id': identifier, 'assignment_id': assignment,
                     'model': {'body': 'synthetic-private-path-body', 'token': 'synthetic-private-path-token'}}
                    for assignment in assignments]}
                for identifier, assignments in ((801, [91, 92]), (802, [92, 93]))],
            'choose_url': 'https://foreign.example/?token=synthetic-private'}


class PathClient(ModuleClient):
    def __init__(self):
        super().__init__()
        self.items[0].update(type='Assignment', content_id=88)
        self.items[0].pop('page_url')
        self.paths = native_paths()
        self.source = {'id': 77, 'course_id': 123, 'assignment_id': 88, 'body': 'synthetic-private-source'}
        self.assignment = {'id': 88, 'course_id': 123, 'name': 'Synthetic trigger', 'points_possible': 100,
                           'updated_at': '2026-10-03T12:00:00Z', 'description': 'synthetic-private-trigger'}
        self.submission = {'id': 188, 'assignment_id': 88, 'user_id': 7, 'workflow_state': 'graded',
                           'posted_at': '2026-10-03T12:00:00Z', 'score': 0, 'attempt': 1,
                           'body': 'synthetic-private-answer', 'submission_comments': [{'comment': 'synthetic-private-comment'}]}
        self.pages = [{'page_id': 66, 'url': 'welcome', 'published': True,
                       'assignment': {'id': 88, 'course_id': 123, 'description': 'synthetic-private-assignment'}}]
        self.ack_override = None
        self.current_patch = {}
        self.sequence_empty = self.sequence_denied = self.page_limit = False

    def request(self, route, method='GET', body=None):
        path = urlsplit(route).path
        if '/submissions/' in path and not path.endswith('/submissions/7'):
            self.calls.append((method, route, body))
            raise CanvasError('Canvas request failed (403)', status=403)
        if method != 'GET':
            self.calls.append((method, route, copy.deepcopy(body)))
            assert method == 'POST' and path == '/api/v1/courses/123/modules/2/items/3/select_mastery_path'
            assert set(body) == {'assignment_set_id', 'student_id'} and body['student_id'] == 7
            selected = next(row for row in self.paths['assignment_sets'] if row['id'] == body['assignment_set_id'])
            if self.denied:
                raise CanvasError('Canvas request failed (403)', status=403)
            self.written = True
            if not self.ignored:
                self.paths.update(selected_set_id=selected['id'], awaiting_choice=False)
            if self.after_write:
                self.after_write(self)
            ack = self.ack_override if self.ack_override is not None else {
                'meta': {'primaryCollection': 'assignments'}, 'items': [],
                'assignments': [{'id': row['assignment_id'], 'course_id': 123, 'description': 'synthetic-private-ack'}
                                for row in selected['assignment_set_associations']]}
            return copy.deepcopy(ack), ''
        extra = path.endswith(('/module_item_sequence', '/quizzes/77', '/discussion_topics/77',
                                '/assignments/88', '/assignments/88/submissions/7'))
        if not extra:
            return super().request(route, method, body)
        self.calls.append((method, route, body))
        if path.endswith('/module_item_sequence'):
            if self.sequence_denied and self.written:
                raise CanvasError('synthetic-private-readback', status=403)
            item = {key: value for key, value in self.items[0].items() if key != 'content_details'}
            item.update(self.current_patch)
            return {'modules': [copy.deepcopy(self.module)], 'items': [] if self.sequence_empty else [
                {'prev': None, 'current': item, 'next': None, 'mastery_path': copy.deepcopy(self.paths)}]}, ''
        if path.endswith(('/quizzes/77', '/discussion_topics/77')):
            return copy.deepcopy(self.source), ''
        return copy.deepcopy(self.submission if '/submissions/' in path else self.assignment), ''

    def list(self, route, max_pages):
        if urlsplit(route).path == '/api/v1/courses/123/pages':
            self.calls.append(('GET', route, None))
            if self.page_limit:
                raise CanvasError('Page limit reached')
            return copy.deepcopy(self.pages)
        return super().list(route, max_pages)


class MasteryPathTests(unittest.TestCase):
    def setUp(self):
        self.client = PathClient()

    def lookup(self, **kwargs):
        return read(self.client, '123', '2', '3', **kwargs)

    def choose(self, set_id='801', **kwargs):
        return select(self.client, '123', '2', '3', set_id, acknowledge_change=True, **kwargs)

    def approve(self, set_id='801', **kwargs):
        preview = self.choose(set_id, **kwargs)
        return self.choose(set_id, yes=True, confirm=preview['confirm'], **kwargs)

    def writes(self):
        return [row for row in self.client.calls if row[0] != 'GET']

    def test_own_metadata_projection_grade_zero_and_native_unknown_processing(self):
        result = self.lookup()
        self.assertEqual(result['mastery_paths']['assignment_sets'][0]['assignment_ids'], [91, 92])
        self.assertEqual(result['trigger']['submission']['score'], 0)
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertIn('processing: unknown', brief(result))
        self.assertIn('Set 801 | assignments: 91, 92', brief(result))
        self.assertEqual(self.writes(), [])

    def test_absent_and_locked_paths_are_reported_without_reading_trigger_or_bypassing_grade(self):
        for paths in (None, {'locked': True, 'awaiting_choice': False, 'selected_set_id': None, 'assignment_sets': []}):
            self.setUp()
            self.client.paths = paths
            result = self.lookup()
            self.assertIsNone(result['trigger'])
            self.assertFalse(any('/assignments/' in route for _, route, _ in self.client.calls))
            self.assertIn('mastery paths', brief(result))

    def test_all_native_graded_item_types_resolve_without_page_view_or_assessment_attempt(self):
        for kind in ('Assignment', 'Quiz', 'Discussion', 'Page'):
            self.setUp()
            self.client.items[0].update(type=kind, content_id=88 if kind == 'Assignment' else 77)
            if kind == 'Page':
                self.client.items[0]['page_url'] = 'welcome'
            with self.subTest(kind=kind):
                result = self.approve()
                self.assertTrue(result['choice_verified'])
                self.assertEqual(len(self.writes()), 1)
                self.assertNotIn('synthetic-private', json.dumps(result))
                self.assertFalse(any('/pages/' in route or '/quizzes/77/submissions' in route for _, route, _ in self.client.calls))

    def test_preview_exact_identity_route_and_conservative_potential_effects(self):
        preview = self.choose()
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['body'], {'assignment_set_id': 801, 'student_id': 7})
        self.assertEqual(preview['effects']['potentially_removed_assignment_ids'], [93])
        self.assertEqual(preview['effects']['shared_with_other_choices_assignment_ids'], [92])
        self.assertNotIn('synthetic-private', json.dumps(preview))
        self.assertEqual(self.writes(), [])

    def test_switch_requires_additional_ack_preserves_shared_and_verifies_separate_choice(self):
        self.client.paths.update(selected_set_id=801, awaiting_choice=False)
        with self.assertRaisesRegex(CanvasError, 'acknowledge-path-switch'):
            self.choose('802')
        result = self.approve('802', acknowledge_switch=True)
        self.assertEqual(result['effects']['potentially_removed_assignment_ids'], [91])
        self.assertEqual(result['effects']['shared_with_other_choices_assignment_ids'], [92])
        self.assertTrue(result['effects']['switching'])
        self.assertEqual(result['status'], 'choice_verified')
        self.assertFalse(result['assignment_availability_verified'])
        self.assertFalse(result['due_dates_verified'])
        self.assertIn('independently verified', brief(result))

    def test_same_selected_choice_and_ineligible_sets_send_nothing(self):
        self.client.paths.update(selected_set_id=801, awaiting_choice=False)
        for identifier in ('801', '999'):
            with self.assertRaises(CanvasError):
                self.choose(identifier, acknowledge_switch=True)
        self.assertEqual(self.writes(), [])

    def test_explicit_same_set_reapplication_is_not_an_automatic_retry_or_switch(self):
        self.client.paths.update(selected_set_id=801, awaiting_choice=False)
        with self.assertRaisesRegex(CanvasError, 'already-reported'):
            self.choose('802', reapply_selected=True)
        result = self.approve(reapply_selected=True)
        self.assertTrue(result['effects']['reapplying'])
        self.assertFalse(result['effects']['switching'])
        self.assertTrue(result['choice_verified'])
        self.assertEqual(len(self.writes()), 1)

    def test_pending_single_automatic_path_can_be_reapplied_but_is_never_stored_choice_proof(self):
        self.client.paths['assignment_sets'].pop()
        self.client.paths.update(selected_set_id=801, awaiting_choice=False, still_processing=True)
        result = self.approve(reapply_selected=True)
        self.assertTrue(result['choice_reported'])
        self.assertTrue(result['automatic_path_reported'])
        self.assertFalse(result['choice_verified'])
        self.assertIn('single automatic path', result['note'])
        self.assertEqual(len(self.writes()), 1)

    def test_concurrently_single_eligible_path_is_not_a_false_multiple_choice_proof(self):
        self.client.after_write = lambda c: c.paths['assignment_sets'].pop()
        result = self.approve()
        self.assertTrue(result['choice_reported'])
        self.assertFalse(result['choice_verified'])
        self.assertTrue(result['automatic_path_reported'])

    def test_compound_ack_omissions_and_legitimate_inventory_changes_are_not_false_failures(self):
        self.client.ack_override = {'meta': {'primaryCollection': 'assignments'}, 'assignments': [], 'items': [],
                                    'body': 'synthetic-private-ack'}
        self.client.after_write = lambda client: client.module.update(items_count=3)
        result = self.approve()
        self.assertTrue(result['choice_verified'])
        self.assertEqual(result['acknowledged']['assignment_ids'], [])

    def test_delayed_cached_or_ignored_choice_is_accepted_but_never_falsely_verified_or_retried(self):
        self.client.ignored = True
        result = self.approve()
        self.assertTrue(result['request_acknowledged'])
        self.assertFalse(result['choice_verified'])
        self.assertEqual(result['status'], 'accepted_choice_unverified')
        self.assertIn('choice not yet verified', brief(result))
        self.assertEqual(len(self.writes()), 1)
        self.assertIsNone(result['mastery_paths']['selected_set_id'])

    def test_processing_flag_is_preserved_not_an_availability_claim(self):
        self.client.paths['still_processing'] = True
        result = self.approve()
        self.assertTrue(result['mastery_paths']['still_processing'])
        self.assertFalse(result['assignment_availability_verified'])

    def test_missing_or_inconsistent_eligibility_and_associations_fail_before_any_write(self):
        mutations = [lambda p: p.pop('locked'), lambda p: p.pop('awaiting_choice'), lambda p: p.pop('selected_set_id'),
                     lambda p: p.update(locked=True), lambda p: p.update(selected_set_id=999),
                     lambda p: p.update(awaiting_choice=False), lambda p: p.update(assignment_sets=[]),
                     lambda p: p['assignment_sets'][0].pop('assignment_set_associations'),
                     lambda p: p['assignment_sets'][0].update(assignment_set_associations='synthetic-private'),
                     lambda p: p['assignment_sets'][0]['assignment_set_associations'].append(None),
                     lambda p: p['assignment_sets'][0]['assignment_set_associations'][0].update(assignment_set_id=802),
                     lambda p: p['assignment_sets'][0]['assignment_set_associations'].append(
                         copy.deepcopy(p['assignment_sets'][0]['assignment_set_associations'][0]))]
        for mutate in mutations:
            self.setUp()
            mutate(self.client.paths)
            with self.subTest(mutate=mutate), self.assertRaises(CanvasError) as error:
                self.choose()
            self.assertNotIn('synthetic-private', str(error.exception))
            self.assertEqual(self.writes(), [])

    def test_unknown_association_ids_are_displayed_as_unknown_not_empty(self):
        self.client.paths['assignment_sets'][0].pop('assignment_set_associations')
        self.assertIn('Set 801 | assignments: unknown', brief(self.lookup()))
        self.client.paths['assignment_sets'][0]['assignment_set_associations'] = []
        self.assertIn('Set 801 | assignments: none', brief(self.lookup()))

    def test_wrong_grade_identity_metadata_nonfinite_values_or_unposted_grade_fail_closed(self):
        for patch in ({'user_id': 8}, {'assignment_id': 89}, {'id': True}, {'score': True}, {'score': float('nan')},
                      {'workflow_state': {}}, {'posted_at': []}, {'graded_at': False}, {'attempt': True}, {'attempt': -1},
                      {'posted_at': None}, {'workflow_state': 'submitted'}, {'score': None}):
            self.setUp()
            self.client.submission.update(patch)
            with self.subTest(patch=patch), self.assertRaises(CanvasError):
                self.choose()
            self.assertEqual(self.writes(), [])

    def test_wrong_trigger_resource_ids_parents_publication_or_metadata_fail_closed(self):
        for patch in ({'id': 89}, {'course_id': 124}, {'course_id': True}, {'published': False},
                      {'name': {}}, {'updated_at': []}, {'points_possible': True}, {'points_possible': float('inf')}):
            self.setUp()
            self.client.assignment.update(patch)
            with self.subTest(patch=patch), self.assertRaises(CanvasError):
                self.choose()
        for patch in ({'id': 78}, {'course_id': 124}, {'assignment_id': True}):
            self.setUp()
            self.client.items[0].update(type='Quiz', content_id=77)
            self.client.source.update(patch)
            with self.subTest(patch=patch), self.assertRaises(CanvasError):
                self.choose()

    def test_pages_scope_ambiguity_absence_visibility_missing_link_and_pagination_fail_closed(self):
        for mode in ('foreign', 'foreign_link', 'duplicate', 'missing', 'unpublished', 'unlinked', 'limit', 'bad_slug'):
            self.setUp()
            self.client.items[0].update(type='Page', page_url='welcome')
            if mode == 'foreign':
                self.client.pages[0]['course_id'] = 124
            elif mode == 'foreign_link':
                self.client.pages[0]['assignment']['course_id'] = 124
            elif mode == 'duplicate':
                self.client.pages *= 2
            elif mode == 'missing':
                self.client.pages.clear()
            elif mode == 'unpublished':
                self.client.pages[0]['published'] = False
            elif mode == 'unlinked':
                self.client.pages[0].pop('assignment')
            elif mode == 'limit':
                self.client.page_limit = True
            else:
                self.client.items[0]['page_url'] = '../welcome'
            with self.subTest(mode=mode), self.assertRaises(CanvasError):
                self.choose()
            self.assertEqual(self.writes(), [])

    def test_unknown_graded_asset_and_exact_sequence_parent_identity_or_empty_occurrence_fail(self):
        for patch in ({'type': 'File'}, {'id': 4}, {'module_id': 9}, {'title': 'Changed'}):
            self.setUp()
            if patch.get('type'):
                self.client.items[0].update(patch)
            else:
                self.client.current_patch = patch
            with self.subTest(patch=patch), self.assertRaises(CanvasError):
                self.lookup()
        self.setUp()
        self.client.sequence_empty = True
        with self.assertRaises(CanvasError):
            self.lookup()

    def test_changed_account_course_rights_grade_inventory_and_choices_invalidate_saved_digest(self):
        changes = [lambda c: setattr(c, 'identity', 8), lambda c: c.course.update(name='Changed'),
                   lambda c: c.rights.update(participate_as_student=False), lambda c: c.submission.update(score=1),
                   lambda c: c.items[1].update(title='Changed'),
                   lambda c: c.paths['assignment_sets'][0]['assignment_set_associations'][0].update(assignment_id=94)]
        for mutate in changes:
            self.setUp()
            preview = self.choose()
            mutate(self.client)
            with self.subTest(mutate=mutate), self.assertRaises(CanvasError):
                self.choose(yes=True, confirm=preview['confirm'])
            self.assertEqual(self.writes(), [])

    def test_preflight_account_switch_and_invalid_flags_values_need_no_write(self):
        self.client.preflight_switch = True
        with self.assertRaisesRegex(CanvasError, 'Account changed'):
            self.lookup()
        self.setUp()
        for kwargs in ({'yes': True}, {'confirm': 'fake'}, {'max_pages': 0}, {'max_pages': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                self.choose(**kwargs)
        for identifier in ('0', '../801', True):
            with self.subTest(identifier=identifier), self.assertRaises(CanvasError):
                self.choose(identifier)
        with self.assertRaisesRegex(CanvasError, 'acknowledge-path-change'):
            select(self.client, '123', '2', '3', '801')
        self.assertEqual(self.client.calls, [])

    def test_denial_and_all_uncertain_post_write_failures_send_exactly_once_and_hide_body(self):
        for mode in ('denied', 'bad_ack', 'foreign_assignment', 'duplicate_assignment', 'foreign_item', 'unrelated_item',
                     'duplicate_item', 'bad_asset', 'account', 'rights', 'course', 'readback', 'final_account'):
            self.setUp()
            if mode == 'denied':
                self.client.denied = True
            elif mode in ('bad_ack', 'foreign_assignment', 'duplicate_assignment', 'foreign_item', 'unrelated_item',
                          'duplicate_item', 'bad_asset'):
                ack = {'meta': {'primaryCollection': 'assignments'}, 'assignments': [{'id': 91, 'course_id': 123}],
                       'items': [{'id': 13, 'module_id': 2, 'title': 'Synthetic selected', 'type': 'Assignment', 'content_id': 91}]}
                if mode == 'bad_ack':
                    ack = {'body': 'synthetic-private-ack'}
                elif mode == 'foreign_assignment':
                    ack['assignments'][0]['course_id'] = 124
                elif mode == 'duplicate_assignment':
                    ack['assignments'] *= 2
                elif mode == 'foreign_item':
                    ack['items'][0]['module_id'] = 9
                elif mode == 'unrelated_item':
                    ack['items'][0]['content_id'] = 92
                elif mode == 'duplicate_item':
                    ack['items'] *= 2
                else:
                    ack['items'][0]['type'] = 'ExternalTool'
                self.client.ack_override = ack
            elif mode == 'account':
                self.client.after_write = lambda c: setattr(c, 'identity', 8)
            elif mode == 'rights':
                self.client.after_write = lambda c: c.rights.update(participate_as_student=False)
            elif mode == 'course':
                self.client.after_write = lambda c: c.course.update(name='Changed')
            elif mode == 'readback':
                self.client.sequence_denied = True
            else:
                self.client.final_switch = True
            with self.subTest(mode=mode), self.assertRaises(CanvasError) as error:
                self.approve()
            if mode != 'denied':
                self.assertIn('may have changed', str(error.exception))
            self.assertNotIn('synthetic-private', str(error.exception))
            self.assertEqual(len(self.writes()), 1)

    def test_valid_compound_assignment_and_associated_asset_items_are_projected_to_ids_only(self):
        for kind in ('Assignment', 'Quiz', 'Discussion', 'Page'):
            self.setUp()
            item = {'id': 13, 'module_id': 2, 'title': 'Synthetic selected', 'type': kind,
                    'content_id': 91 if kind == 'Assignment' else 77, 'page_url': 'welcome'}
            self.client.source['assignment_id'] = 91
            self.client.pages[0]['assignment']['id'] = 91
            self.client.ack_override = {'meta': {'primaryCollection': 'assignments'}, 'assignments': [{'id': 91}], 'items': [item]}
            with self.subTest(kind=kind):
                result = self.approve()
                self.assertEqual(result['acknowledged'], {'assignment_ids': [91], 'module_item_ids': [13]})
