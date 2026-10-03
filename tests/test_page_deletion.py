"""Independent native soft-delete model, cascade acknowledgement and readback."""

import copy
import unittest
from urllib.parse import unquote, urlsplit

from canvas_cli.cli import brief, parser
from canvas_cli.client import CanvasError
from canvas_cli.page_deletion import delete


class DeletionClient:
    host = 'https://canvas.example.edu'

    def __init__(self):
        self.calls = []
        self.user = 7
        self.context = {'name': 'Synthetic context', 'workflow_state': 'available'}
        self.permissions = {'manage_wiki_delete': True}
        self.pages = {9: {'page_id': 9, 'title': 'Target', 'url': 'target', 'body': '<p>synthetic-private-body</p>',
                          'editing_roles': 'teachers', 'published': True, 'front_page': False,
                          'updated_at': '2026-10-01T12:00:00Z', 'publish_at': None},
                      10: {'page_id': 10, 'title': 'Front', 'url': 'front', 'body': '<p>synthetic-private-front</p>',
                           'editing_roles': 'teachers', 'published': True, 'front_page': True,
                           'updated_at': '2026-10-01T12:00:00Z', 'publish_at': None}}
        self.revision = {'revision_id': 3, 'updated_at': '2026-10-01T12:00:00Z', 'latest': True}
        self.assignment = {'id': 81, 'course_id': 123, 'name': 'Synthetic assignment', 'submission_types': ['wiki_page'],
                           'published': True, 'updated_at': '2026-10-01T12:00:00Z', 'workflow_state': 'published',
                           'submission': {'body': 'synthetic-private-submission'}, 'secure_params': 'synthetic-private-token'}
        self.written = self.ignore_delete = self.deny_write = self.keep_assignment = False
        self.account_changed = self.permission_lost = self.context_changed = self.front_changed = False
        self.ack_patch = {}
        self.list_patch = None
        self.list_failure = self.after_list_failure = False
        self.exact_status = 403
        self.slug_status = self.assignment_status = None
        self.slug_patch = None
        self.preflight_mutation = None
        self.page_reads = 0
        self.profile_reads = 0
        self.account_changed_at = None
        self.ack_response = None
        self.exact_readable_after = False
        self.deleted_id = None
        self.deleted_page = None

    def request(self, route, method='GET', body=None):
        self.calls.append((method, route, copy.deepcopy(body)))
        path = urlsplit(route).path
        if method != 'GET':
            if self.deny_write:
                raise CanvasError('Native deletion denied', status=403)
            self.written = True
            self.deleted_id = int(path.rsplit(':', 1)[1])
            row = copy.deepcopy(self.pages[self.deleted_id])
            self.deleted_page = copy.deepcopy(row)
            if not self.ignore_delete:
                self.pages.pop(self.deleted_id)
            row.update(published=False, front_page=False, workflow_state='deleted', locked_for_user=True,
                       updated_at='2026-10-03T12:00:00Z', secure_params='synthetic-private-ack-token')
            if self.front_changed:
                self.pages[10]['front_page'] = False
            return self.ack_response if self.ack_response is not None else {**row, **self.ack_patch}, ''
        if path == '/api/v1/users/self/profile':
            self.profile_reads += 1
            changed = self.written and self.account_changed or self.profile_reads == self.account_changed_at
            return {'id': 8 if changed else self.user}, ''
        if path.endswith('/permissions'):
            return {'manage_wiki_delete': False} if self.written and self.permission_lost else self.permissions, ''
        if '/assignments/' in path:
            if self.written and not self.keep_assignment:
                raise CanvasError('Missing linked assignment', status=self.assignment_status or 404)
            return copy.deepcopy(self.assignment), ''
        if '/pages/' not in path:
            return {'id': int(path.rsplit('/', 1)[1]), **self.context,
                    **({'name': 'Changed context'} if self.written and self.context_changed else {})}, ''
        key = unquote(path.split('/pages/', 1)[1])
        if key.startswith('page_id:'):
            identifier = int(key.split(':')[1].split('/')[0])
            if identifier not in self.pages:
                if self.exact_readable_after:
                    return copy.deepcopy(self.deleted_page), ''
                raise CanvasError('Deleted page exact-ID access denied', status=self.exact_status)
            if '/revisions/' in key:
                if not key.endswith('/latest'):
                    raise CanvasError('History permission denied', status=403)
                return {**self.revision, 'edited_by': {'email': 'synthetic-private-editor@example.edu'}}, ''
            self.page_reads += 1
            if self.page_reads == 2 and self.preflight_mutation:
                self.preflight_mutation(self)
            return copy.deepcopy(self.pages[identifier]), ''
        if self.slug_status:
            raise CanvasError('Old URL read failed', status=self.slug_status)
        if self.slug_patch is not None:
            return copy.deepcopy(self.slug_patch), ''
        row = next((page for page in self.pages.values() if page['url'] == key), None)
        if row is None and key.isascii() and key.isdecimal():
            row = self.pages.get(int(key))
        if row is None:
            raise CanvasError('Old page URL missing', status=404)
        return copy.deepcopy(row), ''

    def list(self, route, max_pages):
        self.calls.append(('GET', route, None))
        if self.list_failure or self.written and self.after_list_failure or max_pages < 2:
            raise CanvasError('Incomplete page inventory')
        return copy.deepcopy(self.list_patch if self.list_patch is not None else list(self.pages.values()))


class PageDeletionTests(unittest.TestCase):
    def setUp(self):
        self.client = DeletionClient()

    def delete(self, **options):
        return delete(self.client, '123', '9', context_type='course', acknowledge=True, **options)

    def execute(self, **options):
        preview = self.delete(**options)
        return self.delete(yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [row for row in self.client.calls if row[0] != 'GET']

    def linked(self):
        self.client.pages[9]['assignment'] = copy.deepcopy(self.client.assignment)

    def test_preview_binds_exact_identity_revision_content_inventory_and_omits_private_payloads(self):
        preview = self.delete()
        self.assertEqual(preview['route'], '/api/v1/courses/123/pages/page_id:9?no_verifiers=true')
        self.assertEqual(preview['method'], 'DELETE')
        self.assertIsNone(preview['body'])
        self.assertEqual(preview['revision']['revision_id'], 3)
        self.assertEqual(preview['permissions'], {'manage_wiki_delete': True})
        self.assertTrue(preview['dry_run'])
        self.assertNotIn('synthetic-private', str(preview))
        self.assertEqual(self.writes(), [])
        self.assertFalse(any('/revisions?' in route for _, route, _ in self.client.calls))

    def test_native_delete_rights_are_separate_from_editing_ownership_and_history(self):
        for value in (False, None, 1, 'true'):
            with self.subTest(value=value):
                self.client = DeletionClient()
                self.client.permissions = {'manage_wiki_delete': value, 'manage_wiki_update': True}
                with self.assertRaises(CanvasError):
                    self.delete()
                self.assertEqual(self.writes(), [])
        self.client = DeletionClient()
        self.client.context.update(workflow_state='completed', concluded=True, non_collaborative=True)
        result = self.execute()
        self.assertEqual(result['deleted_page']['page_id'], 9)

    def test_single_exact_delete_verified_by_inventory_id_and_old_url(self):
        for context_type, item, exact_status in (('course', '123', 403), ('group', '18', 404)):
            self.client = DeletionClient()
            self.client.exact_status = exact_status
            preview = delete(self.client, item, '9', context_type=context_type, acknowledge=True)
            result = delete(self.client, item, '9', context_type=context_type, acknowledge=True,
                            yes=True, confirm=preview['confirm'])
            self.assertEqual(result['exact_id_read_status'], exact_status)
            self.assertEqual(result['original_url_resolution'], {'status': 'not_found'})
            self.assertTrue(result['removed_from_page_inventory'])
            self.assertEqual(self.writes(), [('DELETE', f'/api/v1/{context_type}s/{item}/pages/page_id:9?no_verifiers=true', None)])
            self.assertNotIn('synthetic-private', str(result))
            self.assertTrue(self.client.pages[10]['front_page'])

    def test_numeric_slug_rebound_is_reported_and_never_deleted(self):
        self.client.pages[9]['url'] = '10'
        result = self.execute()
        self.assertEqual(result['original_url_resolution'], {'status': 'resolves_to_another_page', 'page_id': 10})
        self.assertEqual(len(self.writes()), 1)
        self.assertIn('page 10; that page was not deleted', brief(result))
        self.assertEqual(set(self.client.pages), {10})

    def test_front_page_is_refused_without_an_automatic_unset_or_replacement(self):
        self.client.pages[9]['front_page'] = True
        with self.assertRaisesRegex(CanvasError, 'front page cannot'):
            self.delete()
        self.assertEqual(self.writes(), [])

    def test_linked_assignment_needs_distinct_ack_and_one_native_cascade_only(self):
        self.linked()
        with self.assertRaisesRegex(CanvasError, 'acknowledge-linked-assignment-deletion'):
            self.delete()
        preview = self.delete(acknowledge_assignment=True)
        self.assertEqual(preview['linked_assignment']['id'], 81)
        self.assertNotIn('synthetic-private', str(preview))
        result = self.delete(acknowledge_assignment=True, yes=True, confirm=preview['confirm'])
        self.assertEqual(result['linked_assignment_read_status'], 404)
        self.assertEqual(result['linked_assignment_id'], 81)
        self.assertEqual(len(self.writes()), 1)
        self.assertNotIn('/assignments/', self.writes()[0][1])

    def test_stale_binding_for_every_distinct_destination_or_side_effect_never_writes(self):
        def body(client):
            client.pages[9]['body'] = 'Changed body'
        mutations = {
            'body': body,
            'revision': lambda c: c.revision.update(revision_id=4),
            'inventory': lambda c: c.pages[10].update(title='Changed'),
            'context': lambda c: c.context.update(name='Changed'),
            'account': lambda c: setattr(c, 'user', 8),
            'linked': lambda c: c.pages[9].update(assignment=copy.deepcopy(c.assignment)),
            'roles': lambda c: c.pages[9].update(editing_roles='teachers,students'),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                self.client = DeletionClient()
                preview = self.delete(acknowledge_assignment=True)
                mutate(self.client)
                with self.assertRaisesRegex(CanvasError, 'Preview changed'):
                    self.delete(acknowledge_assignment=True, yes=True, confirm=preview['confirm'])
                self.assertEqual(self.writes(), [])

    def test_fresh_page_or_account_change_mid_preflight_refuses(self):
        for mutate in (lambda c: c.pages[9].update(body='Changed'), lambda c: setattr(c, 'user', 8)):
            self.client = DeletionClient()
            self.client.preflight_mutation = mutate
            with self.assertRaisesRegex(CanvasError, 'preflight'):
                self.delete()
            self.assertEqual(self.writes(), [])

    def test_readable_draft_null_html_and_opaque_native_blocks_are_bound_without_replaying_them(self):
        for patch in ({'body': None, 'published': False},
                      {'editor': 'block_editor', 'block_editor_attributes': {'id': 17, 'blocks': '{synthetic-private-blocks}', 'version': '0.2'}},
                      {'editor': 'block_content_editor', 'block_editor_attributes': {'id': 17, 'blocks': [{'type': 'synthetic-private-block'}]}},
                      {'editor': 'block_editor', 'block_editor_data': {'synthetic-private-key': 'private'}},
                      {'editor': 'block_editor', 'block_editor_data': ['private']},
                      {'editor': 'block_editor', 'block_editor_data': 'synthetic-private-external'}):
            self.client = DeletionClient()
            self.client.pages[9].update(patch)
            preview = self.delete()
            self.assertNotIn('synthetic-private', str(preview))
            result = self.delete(yes=True, confirm=preview['confirm'])
            self.assertEqual(result['deleted_page']['page_id'], 9)
            self.assertIsNone(self.writes()[0][2])

    def test_block_content_changes_invalidate_prior_digest(self):
        self.client.pages[9].update(editor='block_editor', block_editor_attributes={'id': 17, 'blocks': 'Original'})
        preview = self.delete()
        self.client.pages[9]['block_editor_attributes']['blocks'] = 'Changed'
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            self.delete(yes=True, confirm=preview['confirm'])
        self.assertEqual(self.writes(), [])

    def test_malformed_or_inaccessible_native_content_is_not_deleted(self):
        for patch in ({'editor': 'unknown'}, {'body': 42}, {'locked_for_user': True}, {'hidden_for_user': True},
                      {'editor': 'block_editor', 'block_editor_attributes': {'blocks': 'x'}},
                      {'editor': 'block_editor', 'block_editor_attributes': []},
                      {'editor': 'block_editor', 'block_editor_attributes': {'id': 17}},
                      {'editor': 'block_editor', 'block_editor_data': 42},
                      {'editor': 'block_editor', 'block_editor_attributes': {'id': 17, 'blocks': 'x'}, 'block_editor_data': {}}):
            self.client = DeletionClient()
            self.client.pages[9].update(patch)
            with self.assertRaises(CanvasError):
                self.delete()
            self.assertEqual(self.writes(), [])
        self.client = DeletionClient()
        self.client.pages[9].pop('body')
        with self.assertRaises(CanvasError):
            self.delete()

    def test_linked_assignment_projection_requires_exact_native_course_association(self):
        for patch in ({'id': True}, {'course_id': 124}, {'course_id': '123'}, {'name': ''}, {'published': 1},
                      {'submission_types': ['online_upload']}, {'submission_types': ['wiki_page', 'wiki_page']},
                      {'submission_types': [1]}, {'submission_types': []}, {'workflow_state': {}},
                      {'workflow_state': 'deleted'}, {'updated_at': None}):
            self.client = DeletionClient()
            self.linked()
            self.client.pages[9]['assignment'].update(patch)
            with self.assertRaises(CanvasError):
                self.delete(acknowledge_assignment=True)
            self.assertEqual(self.writes(), [])
        self.client = DeletionClient()
        self.linked()
        self.client.assignment['name'] = 'Changed independent record'
        with self.assertRaisesRegex(CanvasError, 'Linked assignment changed'):
            self.delete(acknowledge_assignment=True)

    def test_incomplete_ambiguous_or_stale_inventory_revision_is_rejected_before_delete(self):
        for mode in ('limit', 'duplicate', 'fronts', 'absent', 'revision', 'deleted_context'):
            self.client = DeletionClient()
            if mode == 'duplicate':
                self.client.list_patch = [self.client.pages[9], self.client.pages[9]]
            elif mode == 'fronts':
                self.client.pages[11] = {**self.client.pages[10], 'page_id': 11}
            elif mode == 'absent':
                self.client.list_patch = [self.client.pages[10]]
            elif mode == 'revision':
                self.client.revision['updated_at'] = '2026-10-02T12:00:00Z'
            elif mode == 'deleted_context':
                self.client.context['workflow_state'] = 'deleted'
            with self.assertRaises(CanvasError):
                self.delete(max_pages=1 if mode == 'limit' else 100)
            self.assertEqual(self.writes(), [])

    def test_invalid_local_arguments_never_start_network(self):
        for item, page, context, ack, assignment_ack, limit in (
                ('0', '9', 'course', True, False, 100), ('123', '09', 'course', True, False, 100),
                ('123', '9', 'user', True, False, 100), ('123', '9', 'course', False, False, 100),
                ('123', '9', 'course', 1, False, 100), ('123', '9', 'course', True, 1, 100),
                ('123', '9', 'course', True, False, True), ('123', '9', 'course', True, False, 0)):
            self.client = DeletionClient()
            with self.assertRaises(CanvasError):
                delete(self.client, item, page, context_type=context, acknowledge=ack,
                       acknowledge_assignment=assignment_ack, max_pages=limit)
            self.assertEqual(self.client.calls, [])
        with self.assertRaises(CanvasError):
            self.delete(yes=True)
        self.assertEqual(self.client.calls, [])

    def test_native_write_denial_is_one_attempt_not_an_automatic_retry(self):
        self.client.deny_write = True
        with self.assertRaisesRegex(CanvasError, 'Native deletion denied'):
            self.execute()
        self.assertEqual(len(self.writes()), 1)

    def test_bad_acknowledgements_report_uncertainty_without_private_response(self):
        for patch in ({'page_id': 10}, {'published': True}, {'front_page': True}, {'title': 'Other'},
                      {'url': 'other'}, {'editing_roles': 'public'}, {'publish_at': '2027-01-01T12:00:00Z'},
                      {'workflow_state': 'active'}, {'updated_at': 'invalid'}):
            self.client = DeletionClient()
            self.client.ack_patch = patch
            with self.assertRaisesRegex(CanvasError, 'may have succeeded') as caught:
                self.execute()
            self.assertNotIn('synthetic-private', str(caught.exception))
            self.assertEqual(len(self.writes()), 1)
        self.client = DeletionClient()
        self.client.ack_response = ['synthetic-private-invalid-ack']
        with self.assertRaisesRegex(CanvasError, 'may have succeeded') as caught:
            self.execute()
        self.assertNotIn('synthetic-private', str(caught.exception))

    def test_403_exact_read_alone_never_proves_delete_or_assignment_cascade(self):
        for mode in ('listed', 'old403', 'old_original', 'old_foreign', 'exact401', 'exact_readable', 'cascade403', 'cascade_active'):
            self.client = DeletionClient()
            self.linked()
            if mode == 'listed':
                self.client.ignore_delete = True
            elif mode == 'old403':
                self.client.slug_status = 403
            elif mode == 'old_original':
                self.client.slug_patch = self.client.pages[9]
            elif mode == 'old_foreign':
                self.client.slug_patch = {**self.client.pages[10], 'page_id': 11}
            elif mode == 'exact401':
                self.client.exact_status = 401
            elif mode == 'exact_readable':
                self.client.exact_readable_after = True
            elif mode == 'cascade403':
                self.client.assignment_status = 403
            else:
                self.client.keep_assignment = True
            with self.assertRaisesRegex(CanvasError, 'may have succeeded'):
                self.execute(acknowledge_assignment=True)
            self.assertEqual(len(self.writes()), 1)

    def test_post_delete_account_context_permission_front_or_inventory_loss_is_uncertain(self):
        for flag in ('account_changed', 'context_changed', 'permission_lost', 'front_changed', 'after_list_failure'):
            self.client = DeletionClient()
            setattr(self.client, flag, True)
            with self.assertRaisesRegex(CanvasError, 'may have succeeded'):
                self.execute()
            self.assertEqual(len(self.writes()), 1)
        self.client = DeletionClient()
        self.client.account_changed_at = 6  # Preview (2), execution preflight (2), scope readback, final readback.
        with self.assertRaisesRegex(CanvasError, 'may have succeeded'):
            self.execute()
        self.assertEqual(len(self.writes()), 1)

    def test_parser_and_brief_keep_acknowledgement_and_cascade_boundaries_visible(self):
        args = parser().parse_args(['page-delete', '123', '9', '--context', 'course', '--acknowledge-page-deletion'])
        self.assertEqual(args.page_id, '9')
        self.assertTrue(args.acknowledge_page_deletion)
        self.assertFalse(args.acknowledge_linked_assignment_deletion)
        self.linked()
        result = self.execute(acknowledge_assignment=True)
        rendered = brief(result)
        self.assertIn('Shared course page 9 deleted', rendered)
        self.assertIn('assignment 81', rendered)
        self.assertNotIn('synthetic-private', rendered)
