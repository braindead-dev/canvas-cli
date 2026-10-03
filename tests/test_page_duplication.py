"""Independent native duplication, lineage, content differences and readback model."""

import copy
import unittest
from urllib.parse import urlsplit

from canvas_cli.cli import brief, parser
from canvas_cli.client import CanvasError
from canvas_cli.page_duplication import duplicate


class CopyClient:
    host = 'https://canvas.example.edu'

    def __init__(self):
        self.calls = []
        self.user = 7
        self.profile_reads = self.page_reads = 0
        self.context = {'name': 'Synthetic context', 'workflow_state': 'available'}
        self.permissions = {'manage_wiki_create': True, 'participate_as_student': False}
        self.student_wiki = False
        self.settings_patch = {}
        self.pages = {9: {'page_id': 9, 'title': 'Target', 'url': 'current', 'body': '<p>synthetic-private-source</p>',
                          'editing_roles': 'teachers', 'published': True, 'front_page': False,
                          'updated_at': '2026-10-01T12:00:00Z', 'publish_at': None, 'todo_date': '2026-10-16T12:00:00Z'},
                      10: {'page_id': 10, 'title': 'Front', 'url': '9', 'body': '<p>synthetic-private-front</p>',
                           'editing_roles': 'teachers', 'published': True, 'front_page': True,
                           'updated_at': '2026-10-01T12:00:00Z', 'publish_at': None}}
        self.revision = {'revision_id': 3, 'updated_at': '2026-10-01T12:00:00Z', 'latest': True}
        self.assignments = {81: {'id': 81, 'course_id': 123, 'name': 'Synthetic assignment',
                                 'submission_types': ['wiki_page'], 'published': True, 'workflow_state': 'published',
                                 'updated_at': '2026-10-01T12:00:00Z', 'can_duplicate': True,
                                 'original_assignment_id': None, 'original_course_id': None,
                                 'description': '<p>synthetic-private-assignment-description</p>',
                                 'points_possible': 15, 'grading_type': 'points', 'peer_review_count': 2,
                                 'submission': {'body': 'synthetic-private-submission'},
                                 'rubric': [{'description': 'synthetic-private-rubric', 'points': 15}]}}
        self.written = self.deny_write = self.deny_copy_read = self.keep_source_assignment_id = False
        self.source_changed = self.front_changed = self.account_changed = self.permission_lost = False
        self.context_changed = self.inventory_denied_after = False
        self.copy_page_patch = {}
        self.copy_assignment_patch = {}
        self.copy_content_patch = {}
        self.ack_patch = {}
        self.ack_response = None
        self.copy_read_patch = {}
        self.list_patch = None
        self.preflight_mutation = None
        self.account_changed_at = None
        self.copy_title = 'Copie de Target 🌿'

    def linked(self):
        self.pages[9]['assignment'] = copy.deepcopy(self.assignments[81])

    def request(self, route, method='GET', body=None):
        self.calls.append((method, route, copy.deepcopy(body)))
        path = urlsplit(route).path
        if method != 'GET':
            if self.deny_write:
                raise CanvasError('Native copy denied', status=403)
            self.written = True
            row = copy.deepcopy(self.pages[9])
            row.update(page_id=11, title=self.copy_title, url='copy-2', published=False, front_page=False,
                       publish_at=None, updated_at='2026-10-03T12:00:00Z')
            if row.get('block_editor_attributes'):
                row['block_editor_attributes']['id'] += 1
            row.update(self.copy_content_patch)
            if row.get('assignment'):
                linked = copy.deepcopy(self.assignments[81])
                linked.update(id=81 if self.keep_source_assignment_id else 82, name=row['title'], published=False,
                              workflow_state='unpublished', updated_at='2026-10-03T12:00:00Z',
                              original_assignment_id=81, original_course_id=123, peer_review_count=0)
                row['assignment'] = copy.deepcopy(linked)
                self.assignments[linked['id']] = {**linked, **self.copy_assignment_patch}
            row.update(self.copy_page_patch)
            self.pages[11] = copy.deepcopy(row)
            if self.source_changed:
                self.pages[9]['body'] = 'Changed source'
            if self.front_changed:
                self.pages[10]['front_page'] = False
            return self.ack_response if self.ack_response is not None else {**row, **self.ack_patch}, ''
        if path == '/api/v1/users/self/profile':
            self.profile_reads += 1
            changed = self.written and self.account_changed or self.profile_reads == self.account_changed_at
            return {'id': 8 if changed else self.user}, ''
        if path.endswith('/permissions'):
            return {'manage_wiki_create': False, 'participate_as_student': False} if self.written and self.permission_lost else self.permissions, ''
        if '/assignments/' in path:
            identifier = int(path.rsplit('/', 1)[1])
            if identifier not in self.assignments:
                raise CanvasError('Missing scoped assignment', status=404)
            row = self.assignments[identifier]
            return copy.deepcopy(row), ''
        if '/pages/' not in path:
            row = {'id': int(path.rsplit('/', 1)[1]), **self.context,
                   **({'name': 'Changed course'} if self.written and self.context_changed else {})}
            if 'include%5B%5D=allow_student_wiki_edits' in route:
                row['allow_student_wiki_edits'] = self.student_wiki
                row.update(self.settings_patch)
            return row, ''
        identifier = int(path.split('page_id:')[1].split('/')[0])
        if identifier not in self.pages:
            raise CanvasError('Missing scoped page', status=404)
        if '/revisions/' in path:
            if not path.endswith('/latest'):
                raise CanvasError('No native history permission', status=403)
            return {**self.revision, 'edited_by': {'email': 'synthetic-private-editor@example.edu'}}, ''
        if identifier == 11 and self.deny_copy_read:
            raise CanvasError('Native draft read denied', status=403)
        if identifier == 9:
            self.page_reads += 1
            if self.page_reads == 2 and self.preflight_mutation:
                self.preflight_mutation(self)
        row = copy.deepcopy(self.pages[identifier])
        if identifier == 11:
            row.update(self.copy_read_patch)
        return {**row, 'last_edited_by': {'email': 'synthetic-private-page-editor@example.edu'}}, ''

    def list(self, route, max_pages):
        self.calls.append(('GET', route, None))
        if max_pages < 2 or self.written and self.inventory_denied_after:
            raise CanvasError('Incomplete wiki-copy inventory')
        return copy.deepcopy(self.list_patch if self.list_patch is not None else list(self.pages.values()))


class PageDuplicationTests(unittest.TestCase):
    def setUp(self):
        self.client = CopyClient()

    def duplicate(self, **options):
        return duplicate(self.client, '123', '9', acknowledge_shared=True, **options)

    def execute(self, **options):
        preview = self.duplicate(**options)
        return self.duplicate(yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [row for row in self.client.calls if row[0] != 'GET']

    def test_native_preview_has_no_content_payload_and_binds_private_data_without_exposing_it(self):
        self.client.linked()
        preview = self.duplicate(acknowledge_assignment=True)
        self.assertEqual(preview['route'], '/api/v1/courses/123/pages/page_id:9/duplicate?no_verifiers=true')
        self.assertEqual(preview['body'], {})
        self.assertEqual(preview['method'], 'POST')
        self.assertEqual(preview['linked_assignment']['id'], 81)
        self.assertEqual(preview['current_revision']['revision_id'], 3)
        self.assertNotIn('synthetic-private', str(preview))
        self.assertEqual(self.writes(), [])
        self.assertFalse(any('/revisions?' in route for _, route, _ in self.client.calls))

    def test_creation_permission_alone_is_sufficient_without_edit_history_or_update(self):
        self.client.context.update(workflow_state='completed', concluded=True)
        result = self.execute()
        self.assertTrue(result['source_unchanged'])
        self.assertTrue(result['acknowledgement_matches_readback'])
        self.assertEqual(result['copied_page']['title'], 'Copie de Target 🌿')
        self.assertEqual(len(self.writes()), 1)
        self.assertNotIn('manage_wiki_update', str(self.client.calls))

    def test_course_wide_student_opt_in_not_ownership_or_editing_confers_creation(self):
        self.client.permissions = {'manage_wiki_create': False, 'participate_as_student': True}
        with self.assertRaisesRegex(CanvasError, 'wiki opt-in'):
            self.duplicate()
        self.client.student_wiki = True
        result = self.execute()
        self.assertEqual(result['copied_page']['page_id'], 11)
        self.assertTrue(any('allow_student_wiki_edits' in route for _, route, _ in self.client.calls))
        self.client = CopyClient()
        self.client.permissions = {'manage_wiki_create': False, 'participate_as_student': False, 'manage_wiki_update': True}
        with self.assertRaisesRegex(CanvasError, 'not editing alone'):
            self.duplicate()
        self.assertEqual(self.writes(), [])

    def test_front_page_source_can_be_copied_without_deselecting_it_or_selecting_new_front(self):
        self.client.pages[9]['front_page'] = True
        self.client.pages[10]['front_page'] = False
        result = self.execute()
        self.assertFalse(result['copied_page']['front_page'])
        self.assertTrue(self.client.pages[9]['front_page'])
        self.assertEqual(self.writes(), [('POST', '/api/v1/courses/123/pages/page_id:9/duplicate?no_verifiers=true', {})])

    def test_draft_and_future_scheduled_source_preserve_todo_roles_but_copy_is_unscheduled_draft(self):
        self.client.pages[9].update(published=False, publish_at='2027-01-01T12:00:00Z', editing_roles='teachers,students')
        result = self.execute()
        copied = result['copied_page']
        self.assertFalse(copied['published'])
        self.assertIsNone(copied['publish_at'])
        self.assertEqual(copied['editing_roles'], 'teachers,students')
        self.assertEqual(copied['todo_date'], '2026-10-16T12:00:00Z')
        self.assertEqual(self.client.pages[9]['publish_at'], '2027-01-01T12:00:00Z')

    def test_linked_assignment_copy_ack_and_exact_separate_lineage_are_required(self):
        self.client.linked()
        with self.assertRaisesRegex(CanvasError, 'acknowledge-linked-assignment-copy'):
            self.duplicate()
        result = self.execute(acknowledge_assignment=True)
        self.assertEqual(result['copied_assignment']['id'], 82)
        self.assertTrue(result['assignment_lineage_verified'])
        self.assertEqual(result['assignment_configuration_changed_fields'], ['peer_review_count'])
        self.assertNotIn('synthetic-private', str(result))
        self.assertEqual(len(self.writes()), 1)
        self.assertNotIn('/assignments/', self.writes()[0][1])
        self.assertTrue(any('/assignments/82?' in route for _, route, _ in self.client.calls))
        self.assertIn('exact source lineage verified', brief(result))
        self.assertIn('points_possible', result['assignment_configuration_compared_fields'])
        self.assertIn('turnitin_settings', result['assignment_configuration_unknown_fields'])
        self.assertNotIn('turnitin_settings', result['assignment_configuration_compared_fields'])

    def test_unedited_html_and_native_blocks_copy_without_reusing_block_id_or_sending_payload(self):
        for patch in ({'body': None},
                      {'editor': 'block_editor', 'block_editor_attributes': {'id': 17, 'blocks': 'synthetic-private-blocks', 'version': '0.2'}},
                      {'editor': 'block_content_editor', 'block_editor_attributes': {'id': 17, 'blocks': [{'text': 'synthetic-private-blocks'}]}}):
            self.client = CopyClient()
            self.client.pages[9].update(patch)
            result = self.execute()
            self.assertTrue(result['content_matches_source'])
            self.assertNotIn('synthetic-private', str(result))
            self.assertEqual(self.writes()[0][2], {})
            if 'block_editor_attributes' in patch:
                self.assertEqual(self.client.pages[11]['block_editor_attributes']['id'], 18)
                self.assertEqual(self.client.pages[9]['block_editor_attributes']['id'], 17)

    def test_native_content_and_configuration_rewrites_are_labeled_not_presented_as_literal_copy(self):
        self.client.copy_content_patch = {'body': '<p>Normalized</p>'}
        self.client.linked()
        self.client.copy_assignment_patch = {'description': 'Native rewritten description'}
        result = self.execute(acknowledge_assignment=True)
        self.assertFalse(result['content_matches_source'])
        self.assertIn('description', result['assignment_configuration_changed_fields'])
        self.assertNotIn('Native rewritten', str(result))
        self.assertIn('Stored content differs', brief(result))

    def test_external_block_data_is_bound_even_when_native_copy_changes_representation(self):
        self.client.pages[9].update(editor='block_editor', block_editor_data={'synthetic-private-external': 'content'})
        self.client.copy_content_patch = {'editor': None, 'block_editor_data': None, 'body': None}
        result = self.execute()
        self.assertFalse(result['content_matches_source'])
        self.assertEqual((result['source_content_kind'], result['copied_content_kind']), ('external', 'html'))
        self.assertNotIn('synthetic-private', str(result))

    def test_stale_source_revision_todo_blocks_inventory_permissions_account_and_assignment_config_never_write(self):
        mutations = {
            'body': lambda c: c.pages[9].update(body='Changed'),
            'todo': lambda c: c.pages[9].update(todo_date='2026-10-17T12:00:00Z'),
            'revision': lambda c: c.revision.update(revision_id=4),
            'inventory': lambda c: c.pages[10].update(title='Changed'),
            'account': lambda c: setattr(c, 'user', 8),
            'context': lambda c: c.context.update(name='Changed'),
            'rights': lambda c: c.permissions.update(participate_as_student=True),
            'assignment': lambda c: c.assignments[81].update(points_possible=25),
            'rubric': lambda c: c.assignments[81].update(rubric=[{'description': 'Changed'}]),
            'external': lambda c: c.pages[9].update(editor='block_editor', block_editor_data={'new': 'content'}),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                self.client = CopyClient()
                self.client.linked()
                preview = self.duplicate(acknowledge_assignment=True)
                mutate(self.client)
                with self.assertRaisesRegex(CanvasError, 'Preview changed'):
                    self.duplicate(acknowledge_assignment=True, yes=True, confirm=preview['confirm'])
                self.assertEqual(self.writes(), [])

    def test_source_change_mid_preflight_or_unavailable_inventory_revision_never_posts(self):
        for mode in ('source', 'assignment', 'account', 'inventory', 'revision', 'limit', 'deleted_course'):
            self.client = CopyClient()
            self.client.linked()
            if mode == 'source':
                self.client.preflight_mutation = lambda c: c.pages[9].update(body='Changed')
            elif mode == 'assignment':
                self.client.preflight_mutation = lambda c: c.assignments[81].update(points_possible=25)
            elif mode == 'account':
                self.client.preflight_mutation = lambda c: setattr(c, 'user', 8)
            elif mode == 'inventory':
                self.client.list_patch = [self.client.pages[10]]
            elif mode == 'revision':
                self.client.revision['updated_at'] = '2026-10-02T12:00:00Z'
            elif mode == 'deleted_course':
                self.client.context['workflow_state'] = 'deleted'
            with self.assertRaises(CanvasError):
                self.duplicate(acknowledge_assignment=True, max_pages=1 if mode == 'limit' else 100)
            self.assertEqual(self.writes(), [])

    def test_linked_assignment_native_duplicate_denial_and_malformed_lineage_refuse_preflight(self):
        for patch in ({'can_duplicate': False}, {'can_duplicate': 1}, {'original_assignment_id': True},
                      {'original_course_id': 0}, {'course_id': 124}, {'workflow_state': 'deleted'}):
            self.client = CopyClient()
            self.client.linked()
            self.client.assignments[81].update(patch)
            with self.assertRaises(CanvasError):
                self.duplicate(acknowledge_assignment=True)
            self.assertEqual(self.writes(), [])

    def test_local_invalid_inputs_and_parser_do_not_allow_group_or_missing_audience_ack(self):
        for item, page, shared, linked, limit in (('0', '9', True, False, 100), ('123', '09', True, False, 100),
                                               ('123', '9', False, False, 100), ('123', '9', 1, False, 100),
                                               ('123', '9', True, 1, 100), ('123', '9', True, False, True)):
            self.client = CopyClient()
            with self.assertRaises(CanvasError):
                duplicate(self.client, item, page, acknowledge_shared=shared, acknowledge_assignment=linked, max_pages=limit)
            self.assertEqual(self.client.calls, [])
        args = parser().parse_args(['page-duplicate', '123', '9', '--acknowledge-shared-page'])
        self.assertEqual(args.course_id, '123')
        self.assertFalse(hasattr(args, 'context'))
        with self.assertRaises(CanvasError):
            self.duplicate(yes=True)
        self.assertEqual(self.client.calls, [])

    def test_native_denial_is_one_post_never_a_retry_or_html_create_fallback(self):
        self.client.deny_write = True
        with self.assertRaisesRegex(CanvasError, 'Native copy denied'):
            self.execute()
        self.assertEqual(len(self.writes()), 1)

    def test_native_ack_must_be_a_new_unscheduled_draft_with_preserved_roles_todo_and_new_block(self):
        for patch in ({'page_id': 9}, {'published': True}, {'front_page': True},
                      {'publish_at': '2027-01-01T12:00:00Z'}, {'editing_roles': 'public'}, {'todo_date': None}):
            self.client = CopyClient()
            self.client.copy_page_patch = patch
            with self.assertRaisesRegex(CanvasError, 'New content may already exist'):
                self.execute()
            self.assertEqual(len(self.writes()), 1)
        self.client = CopyClient()
        self.client.pages[9].update(editor='block_editor', block_editor_attributes={'id': 17, 'blocks': 'content'})
        self.client.copy_content_patch = {'block_editor_attributes': {'id': 17, 'blocks': 'content'}}
        with self.assertRaisesRegex(CanvasError, 'New content may already exist'):
            self.execute()
        self.client = CopyClient()
        self.client.ack_response = ['synthetic-private-invalid-ack']
        with self.assertRaisesRegex(CanvasError, 'New content may already exist') as caught:
            self.execute()
        self.assertNotIn('synthetic-private', str(caught.exception))

    def test_copied_assignment_must_be_independent_with_exact_source_lineage_and_title(self):
        for patch in ({'original_assignment_id': None}, {'original_assignment_id': 80}, {'original_course_id': 124},
                      {'original_assignment_id': '81'}, {'name': 'Different'}, {'published': True}):
            self.client = CopyClient()
            self.client.linked()
            self.client.copy_assignment_patch = patch
            with self.assertRaisesRegex(CanvasError, 'New content may already exist'):
                self.execute(acknowledge_assignment=True)
            self.assertEqual(len(self.writes()), 1)
        self.client = CopyClient()
        self.client.linked()
        self.client.keep_source_assignment_id = True
        with self.assertRaisesRegex(CanvasError, 'New content may already exist'):
            self.execute(acknowledge_assignment=True)

    def test_missing_or_unexpected_copied_assignment_is_not_silently_accepted(self):
        self.client.linked()
        self.client.copy_page_patch = {'assignment': None}
        with self.assertRaisesRegex(CanvasError, 'New content may already exist'):
            self.execute(acknowledge_assignment=True)
        self.client = CopyClient()
        self.client.copy_page_patch = {'assignment': copy.deepcopy(self.client.assignments[81])}
        with self.assertRaisesRegex(CanvasError, 'New content may already exist'):
            self.execute(acknowledge_assignment=True)

    def test_lost_draft_readback_never_publishes_or_deletes_as_a_workaround(self):
        self.client.permissions = {'manage_wiki_create': False, 'participate_as_student': True}
        self.client.student_wiki = self.client.deny_copy_read = True
        with self.assertRaisesRegex(CanvasError, 'New content may already exist'):
            self.execute()
        self.assertEqual(len(self.writes()), 1)
        self.assertTrue(all(row[0] == 'POST' for row in self.writes()))
        self.assertFalse(self.client.pages[11]['published'])

    def test_source_account_course_front_permissions_or_inventory_change_after_copy_is_uncertain(self):
        for flag in ('source_changed', 'front_changed', 'account_changed', 'permission_lost', 'context_changed', 'inventory_denied_after'):
            self.client = CopyClient()
            setattr(self.client, flag, True)
            with self.assertRaisesRegex(CanvasError, 'New content may already exist'):
                self.execute()
            self.assertEqual(len(self.writes()), 1)
        self.client = CopyClient()
        self.client.account_changed_at = 6
        with self.assertRaisesRegex(CanvasError, 'New content may already exist'):
            self.execute()

    def test_inconsistent_page_ack_and_readback_do_not_leak_private_content(self):
        self.client.ack_patch = {'body': 'synthetic-private-different-ack'}
        with self.assertRaisesRegex(CanvasError, 'New content may already exist') as caught:
            self.execute()
        self.assertNotIn('synthetic-private', str(caught.exception))
        self.assertEqual(len(self.writes()), 1)

    def test_foreign_new_page_or_assignment_id_is_never_verified_through_global_reads(self):
        self.client.ack_patch = {'page_id': 12}
        with self.assertRaisesRegex(CanvasError, 'New content may already exist'):
            self.execute()
        self.assertTrue(any('/courses/123/pages/page_id:12?' in route for _, route, _ in self.client.calls))
        self.assertEqual(len(self.writes()), 1)
        self.client = CopyClient()
        self.client.linked()
        wrong = {**copy.deepcopy(self.client.assignments[81]), 'id': 83, 'name': self.client.copy_title, 'published': False}
        self.client.copy_page_patch = {'assignment': wrong}
        with self.assertRaisesRegex(CanvasError, 'New content may already exist'):
            self.execute(acknowledge_assignment=True)
        self.assertTrue(any('/courses/123/assignments/83?' in route for _, route, _ in self.client.calls))
        self.assertEqual(len(self.writes()), 1)
        self.assertFalse(any(route.startswith('/api/v1/assignments/') for _, route, _ in self.client.calls))

    def test_malformed_native_permissions_or_content_do_not_start_copy(self):
        for permissions in ({}, {'manage_wiki_create': 1, 'participate_as_student': False}, []):
            self.client = CopyClient()
            self.client.permissions = permissions
            with self.assertRaises(CanvasError):
                self.duplicate()
            self.assertEqual(self.writes(), [])
        for patch in ({'id': 124}, {'allow_student_wiki_edits': None}, {'allow_student_wiki_edits': 1}):
            self.client = CopyClient()
            self.client.permissions = {'manage_wiki_create': False, 'participate_as_student': True}
            self.client.settings_patch = patch
            with self.assertRaises(CanvasError):
                self.duplicate()
            self.assertEqual(self.writes(), [])
        for patch in ({'todo_date': 'invalid'}, {'locked_for_user': True}, {'body': 42}, {'editor': 'unknown'}):
            self.client = CopyClient()
            self.client.pages[9].update(patch)
            with self.assertRaises(CanvasError):
                self.duplicate()
            self.assertEqual(self.writes(), [])
