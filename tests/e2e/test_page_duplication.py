"""Installed-CLI native duplication, pagination, lineage and private projections."""

import copy
import json

from . import page_duplication
from .fixture import CanvasFixture


class PageDuplicationE2E(CanvasFixture):
    def setUp(self):
        page_duplication.initialize(type(self), enabled=True)

    def command(self, *, assignment=False):
        return ('page-duplicate', '110', '4001', '--acknowledge-shared-page',
                *(('--acknowledge-linked-assignment-copy',) if assignment else ()))

    def approved(self, command):
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def writes(self, since):
        return [row for row in self.calls[since:] if row[0] != 'GET']

    def linked(self):
        self.copy_pages[4001]['assignment'] = copy.deepcopy(self.copy_assignments[83])

    def test_installed_private_free_preview_and_paginated_inventory_without_edit_history(self):
        before = len(self.calls)
        result = self.invoke(*self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['route'], '/api/v1/courses/110/pages/page_id:4001/duplicate?no_verifiers=true')
        self.assertEqual(data['body'], {})
        self.assertEqual(data['permissions'], {'manage_wiki_create': True, 'participate_as_student': False})
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertTrue(any('page=2' in route for _, route in self.calls[before:]))
        self.assertFalse(any('/revisions?' in route for _, route in self.calls[before:]))
        result = self.invoke(*self.command(), '--max-pages', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('Page limit', result.stderr)
        self.assertEqual(self.writes(before), [])

    def test_installed_native_post_selects_exact_source_despite_other_numeric_slug_and_leaves_source_front_alone(self):
        self.copy_pages[4001]['front_page'] = True
        self.copy_pages[4002]['front_page'] = False
        self.copy_context.update(workflow_state='completed', concluded=True)
        before = len(self.calls)
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['copied_page']['page_id'], 4003)
        self.assertEqual(data['copied_page']['title'], 'Copie de Target 🌿')
        self.assertFalse(data['copied_page']['published'])
        self.assertTrue(data['content_matches_source'])
        self.assertTrue(data['source_unchanged'])
        self.assertTrue(self.copy_pages[4001]['front_page'])
        self.assertEqual(self.copy_pages[4002]['title'], 'Numeric slug')
        self.assertEqual(self.writes(before), [('POST', '/api/v1/courses/110/pages/page_id:4001/duplicate?no_verifiers=true')])
        self.assertNotIn('synthetic-private', result.stdout)

    def test_installed_creation_and_student_opt_in_not_unrelated_update_rights(self):
        type(self).copy_permissions = {'manage_wiki_create': False, 'participate_as_student': True}
        before = len(self.calls)
        result = self.invoke(*self.command())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('wiki opt-in', result.stderr)
        self.assertEqual(self.writes(before), [])
        type(self).copy_student_wiki = True
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['copied_page']['page_id'], 4003)

    def test_installed_draft_schedule_todo_and_roles_follow_native_copy_not_implicit_publication(self):
        self.copy_pages[4001].update(published=False, publish_at='2027-01-01T12:00:00Z', editing_roles='teachers,students')
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout)['copied_page']
        self.assertFalse(row['published'])
        self.assertFalse(row['front_page'])
        self.assertIsNone(row['publish_at'])
        self.assertEqual(row['todo_date'], '2026-10-16T12:00:00Z')
        self.assertEqual(row['editing_roles'], 'teachers,students')
        self.assertEqual(self.copy_pages[4001]['publish_at'], '2027-01-01T12:00:00Z')

    def test_installed_linked_assignment_needs_ack_exact_lineage_and_separate_read_not_second_post(self):
        self.linked()
        before = len(self.calls)
        result = self.invoke(*self.command())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('acknowledge-linked-assignment-copy', result.stderr)
        self.assertEqual(self.writes(before), [])
        result = self.approved(self.command(assignment=True))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['copied_assignment']['id'], 84)
        self.assertTrue(data['assignment_lineage_verified'])
        self.assertEqual(data['assignment_configuration_changed_fields'], ['peer_review_count', 'post_to_sis'])
        self.assertIn('turnitin_settings', data['assignment_configuration_unknown_fields'])
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertEqual(len(self.writes(before)), 1)
        self.assertTrue(any('/assignments/84?' in route for _, route in self.calls[before:]))

    def test_installed_native_block_copy_allocates_independent_id_and_payload_is_not_sent(self):
        for editor in ('block_editor', 'block_content_editor'):
            page_duplication.initialize(type(self), enabled=True)
            self.copy_pages[4001].update(editor=editor, block_editor_attributes={'id': 99, 'blocks': 'synthetic-private-blocks'})
            before = len(self.calls)
            result = self.approved(self.command())
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertTrue(data['content_matches_source'])
            self.assertEqual(self.copy_pages[4003]['block_editor_attributes']['id'], 100)
            self.assertEqual(self.copy_pages[4001]['block_editor_attributes']['id'], 99)
            self.assertNotIn('synthetic-private', result.stdout)
            self.assertEqual(len(self.writes(before)), 1)

    def test_installed_native_normalization_and_configuration_differences_expose_fields_not_values(self):
        self.linked()
        type(self).copy_content_patch = {'body': '<p>Normalized copy</p>'}
        type(self).copy_assignment_patch = {'description': 'synthetic-private-rewritten-description'}
        result = self.approved(self.command(assignment=True))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data['content_matches_source'])
        self.assertIn('description', data['assignment_configuration_changed_fields'])
        self.assertNotIn('synthetic-private', result.stdout)

    def test_installed_stale_page_revision_todo_inventory_account_context_and_assignment_config_never_post(self):
        for mode in ('body', 'revision', 'todo', 'inventory', 'account', 'context', 'config'):
            page_duplication.initialize(type(self), enabled=True)
            self.linked()
            command = self.command(assignment=True)
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'body':
                self.copy_pages[4001]['body'] = 'Changed'
            elif mode == 'revision':
                self.copy_revision['revision_id'] = 4
            elif mode == 'todo':
                self.copy_pages[4001]['todo_date'] = '2026-10-17T12:00:00Z'
            elif mode == 'inventory':
                self.copy_pages[4002]['title'] = 'Changed'
            elif mode == 'account':
                type(self).copy_viewer = 8
            elif mode == 'context':
                self.copy_context['name'] = 'Changed'
            else:
                self.copy_assignments[83]['points_possible'] = 25
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Preview changed', result.stderr)
            self.assertEqual(self.writes(before), [])

    def test_installed_native_deny_or_local_invalid_ack_never_retries_or_falls_back_to_html_create(self):
        before = len(self.calls)
        result = self.invoke(*self.command()[:-1])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.writes(before), [])
        type(self).copy_deny = True
        result = self.approved(self.command())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('synthetic-private', result.stderr)
        self.assertEqual(len(self.writes(before)), 1)
        before = len(self.calls)
        result = self.invoke(*self.command(), '--context', 'group')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls[before:], [])

    def test_installed_copy_ack_readback_lineage_and_source_failures_are_uncertain_not_cleanup_actions(self):
        for mode in ('draft_read', 'account', 'permission', 'source', 'front', 'inventory', 'ack', 'ack_list', 'lineage', 'same_assignment', 'missing_assignment', 'readback'):
            page_duplication.initialize(type(self), enabled=True)
            self.linked()
            if mode == 'draft_read':
                type(self).copy_read_denied = True
            elif mode == 'account':
                type(self).copy_account_changed = True
            elif mode == 'permission':
                type(self).copy_permission_lost = True
            elif mode == 'source':
                type(self).copy_source_changed = True
            elif mode == 'front':
                type(self).copy_front_changed = True
            elif mode == 'inventory':
                type(self).copy_inventory_denied = True
            elif mode == 'ack':
                type(self).copy_ack_patch = {'page_id': 4001}
            elif mode == 'ack_list':
                type(self).copy_ack_response = ['synthetic-private-ack']
            elif mode == 'lineage':
                type(self).copy_assignment_patch = {'original_assignment_id': 80}
            elif mode == 'same_assignment':
                type(self).copy_reuse_assignment = True
            elif mode == 'missing_assignment':
                type(self).copy_page_patch = {'assignment': None}
            else:
                type(self).copy_ack_patch = {'body': 'synthetic-private-inconsistent-ack'}
            before = len(self.calls)
            result = self.approved(self.command(assignment=True))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('New content may already exist', result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)

    def test_installed_foreign_new_ids_never_fall_back_to_global_assignment_or_page_access(self):
        for assignment in (False, True):
            page_duplication.initialize(type(self), enabled=True)
            self.linked()
            if assignment:
                wrong = {**copy.deepcopy(self.copy_assignments[83]), 'id': 85, 'name': 'Copie de Target 🌿', 'published': False}
                type(self).copy_page_patch = {'assignment': wrong}
            else:
                type(self).copy_ack_patch = {'page_id': 4009}
            before = len(self.calls)
            result = self.approved(self.command(assignment=True))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('New content may already exist', result.stderr)
            self.assertNotIn('synthetic-private', result.stderr)
            expected = '/api/v1/courses/110/assignments/85?' if assignment else '/api/v1/courses/110/pages/page_id:4009?'
            self.assertTrue(any(route.startswith(expected) for _, route in self.calls[before:]))
            self.assertFalse(any(route.startswith('/api/v1/assignments/') for _, route in self.calls[before:]))
            self.assertEqual(len(self.writes(before)), 1)
