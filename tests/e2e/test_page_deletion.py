"""Installed CLI exact-ID deletion, paginated evidence and safe uncertainty."""

import copy
import json

from . import page_deletion
from .fixture import CanvasFixture


class PageDeletionE2E(CanvasFixture):
    def setUp(self):
        page_deletion.initialize(type(self), enabled=True)

    def command(self, *, group=False, cascade=False):
        return ('page-delete', '19' if group else '109', '3001', '--context', 'group' if group else 'course',
                '--acknowledge-page-deletion', *(('--acknowledge-linked-assignment-deletion',) if cascade else ()))

    def approved(self, command):
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def writes(self, since):
        return [row for row in self.calls[since:] if row[0] != 'GET']

    def test_installed_preview_is_private_free_and_full_inventory_is_required(self):
        before = len(self.calls)
        result = self.invoke(*self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        preview = json.loads(result.stdout)
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['route'], '/api/v1/courses/109/pages/page_id:3001?no_verifiers=true')
        self.assertEqual(preview['permissions'], {'manage_wiki_delete': True})
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertTrue(any('/pages?' in route and 'page=2' in route for _, route in self.calls[before:]))
        self.assertFalse(any('/revisions?' in route for _, route in self.calls[before:]))
        result = self.invoke(*self.command(), '--max-pages', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Page limit', result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(self.writes(before), [])

    def test_installed_course_and_group_delete_exact_id_not_colliding_slug(self):
        for group, status in ((False, 403), (True, 404)):
            page_deletion.initialize(type(self), enabled=True)
            type(self).deletion_exact_status = status
            self.deletion_context.update(workflow_state='completed', concluded=True)
            before = len(self.calls)
            result = self.approved(self.command(group=group))
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data['deleted_page']['page_id'], 3001)
            self.assertEqual(data['exact_id_read_status'], status)
            self.assertEqual(data['original_url_resolution'], {'status': 'not_found'})
            self.assertTrue(self.deletion_pages[3002]['front_page'])
            self.assertEqual(self.writes(before), [('DELETE', f"/api/v1/{'groups/19' if group else 'courses/109'}/pages/page_id:3001?no_verifiers=true")])
            self.assertNotIn('synthetic-private', result.stdout)

    def test_installed_numeric_old_slug_rebound_is_not_a_second_delete(self):
        self.deletion_pages[3001]['url'] = '3002'
        before = len(self.calls)
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['original_url_resolution'], {'status': 'resolves_to_another_page', 'page_id': 3002})
        self.assertEqual(len(self.writes(before)), 1)
        self.assertEqual(set(self.deletion_pages), {3002})

    def test_installed_block_and_external_content_are_fingerprinted_not_sent_or_leaked(self):
        for patch in ({'editor': 'block_content_editor', 'block_editor_attributes': {'id': 99, 'blocks': 'synthetic-private-blocks'}},
                      {'editor': 'block_editor', 'block_editor_data': {'native': 'synthetic-private-external'}}):
            page_deletion.initialize(type(self), enabled=True)
            self.deletion_pages[3001].update(patch)
            before = len(self.calls)
            result = self.approved(self.command())
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('synthetic-private', result.stdout)
            self.assertEqual(len(self.writes(before)), 1)

    def test_installed_missing_delete_permission_front_page_or_ack_never_writes(self):
        for mode in ('permission', 'front', 'ack'):
            page_deletion.initialize(type(self), enabled=True)
            if mode == 'permission':
                type(self).deletion_permission = False
            elif mode == 'front':
                self.deletion_pages[3001]['front_page'] = True
            before = len(self.calls)
            result = self.invoke(*(self.command()[:-1] if mode == 'ack' else self.command()))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.writes(before), [])

    def test_installed_cascade_requires_distinct_ack_and_separate_assignment_404(self):
        self.deletion_pages[3001]['assignment'] = copy.deepcopy(self.deletion_assignment)
        before = len(self.calls)
        result = self.invoke(*self.command())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('acknowledge-linked-assignment-deletion', result.stderr)
        self.assertEqual(self.writes(before), [])
        result = self.approved(self.command(cascade=True))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['linked_assignment_id'], 82)
        self.assertEqual(data['linked_assignment_read_status'], 404)
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertEqual(len(self.writes(before)), 1)
        self.assertTrue(any(route.endswith('/assignments/82') for _, route in self.calls[before:]))

    def test_installed_stale_body_revision_inventory_account_context_or_cascade_does_not_delete(self):
        for mode in ('body', 'revision', 'inventory', 'account', 'context', 'cascade'):
            page_deletion.initialize(type(self), enabled=True)
            command = self.command(cascade=True)
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'body':
                self.deletion_pages[3001]['body'] = 'Changed'
            elif mode == 'revision':
                self.deletion_revision['revision_id'] = 4
            elif mode == 'inventory':
                self.deletion_pages[3002]['title'] = 'Changed'
            elif mode == 'account':
                type(self).deletion_viewer = 8
            elif mode == 'context':
                self.deletion_context['name'] = 'Changed'
            else:
                self.deletion_pages[3001]['assignment'] = copy.deepcopy(self.deletion_assignment)
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Preview changed', result.stderr)
            self.assertEqual(self.writes(before), [])

    def test_installed_native_restriction_is_safe_and_never_retried(self):
        type(self).deletion_deny = True
        before = len(self.calls)
        result = self.approved(self.command())
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('synthetic-private', result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(len(self.writes(before)), 1)

    def test_installed_failed_delete_or_cascade_evidence_reports_uncertainty_without_retries(self):
        for mode in ('index', 'slug403', 'exact401', 'exact_readable', 'assignment403', 'assignment_active', 'account', 'permission', 'front', 'index403', 'ack', 'ack_list'):
            page_deletion.initialize(type(self), enabled=True)
            self.deletion_pages[3001]['assignment'] = copy.deepcopy(self.deletion_assignment)
            if mode == 'index':
                type(self).deletion_ignore = True
            elif mode == 'slug403':
                type(self).deletion_slug_status = 403
            elif mode == 'exact401':
                type(self).deletion_exact_status = 401
            elif mode == 'exact_readable':
                type(self).deletion_exact_readable = True
            elif mode == 'assignment403':
                type(self).deletion_cascade_status = 403
            elif mode == 'assignment_active':
                type(self).deletion_keep_assignment = True
            elif mode == 'account':
                type(self).deletion_changed_account = True
            elif mode == 'permission':
                type(self).deletion_permission_lost = True
            elif mode == 'front':
                type(self).deletion_front_changed = True
            elif mode == 'index403':
                type(self).deletion_inventory_denied = True
            elif mode == 'ack':
                type(self).deletion_ack_patch = {'page_id': 3002}
            else:
                type(self).deletion_ack_response = ['synthetic-private-invalid-ack']
            before = len(self.calls)
            result = self.approved(self.command(cascade=True))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('may have succeeded', result.stderr)
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertEqual(len(self.writes(before)), 1)
