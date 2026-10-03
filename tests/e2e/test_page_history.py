"""Installed CLI pagination, privacy, native permissions and revision restore."""

import json

from . import page_history
from .fixture import CanvasFixture


class PageHistoryE2E(CanvasFixture):
    def setUp(self):
        page_history.initialize(type(self), enabled=True)

    def command(self, name='page-revisions', revision='1', *, group=False, fields=()):
        return (name, '18' if group else '108', '2001',
                *((revision,) if name != 'page-revisions' else ()), '--context', 'group' if group else 'course',
                *(('--acknowledge-shared-page',) if name == 'page-restore' else ()), *fields)

    def approved(self, command):
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def test_installed_paged_history_defaults_to_metadata_and_rejects_incomplete_inventory(self):
        before = len(self.calls)
        result = self.invoke(*self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual([row['revision_id'] for row in data['page_revisions']], [3, 2, 1])
        self.assertTrue(data['complete_for_endpoint'])
        for marker in ('private', 'Earlier', 'edited_by'):
            self.assertNotIn(marker, result.stdout)
        self.assertTrue(any('page=3' in route for _, route in self.calls[before:]))
        result = self.invoke(*self.command(), '--max-pages', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Page limit', result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))

    def test_installed_latest_is_readable_without_history_or_write_rights_including_drafts(self):
        type(self).history_edit_allowed = False
        type(self).history_permissions = {'manage_wiki_create': False, 'manage_wiki_update': False, 'participate_as_student': False}
        self.history_pages[2001]['published'] = False
        before = len(self.calls)
        result = self.invoke(*self.command('page-revision', 'latest', fields=('--include-content',)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['page_revision']['revision_id'], 3)
        self.assertFalse(any('/permissions' in route for _, route in self.calls[before:]))
        for command in (self.command(), self.command('page-revision')):
            result = self.invoke(*command)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('denied access', result.stderr)
            self.assertNotIn('synthetic-private', result.stderr)

    def test_installed_numeric_detail_projects_editors_only_by_request_and_body_is_json_only(self):
        command = self.command('page-revision', fields=('--include-editors', '--include-content'))
        result = self.invoke(*command)
        self.assertEqual(result.returncode, 0, result.stderr)
        revision = json.loads(result.stdout)['page_revision']
        self.assertEqual(revision['body'], '<p>Synthetic historical private HTML</p>')
        self.assertEqual(set(revision['edited_by']), {'id', 'name', 'display_name'})
        self.assertNotIn('synthetic-private', result.stdout)
        result = self.invoke(*command, '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('historical private HTML', result.stdout)
        self.assertIn('Content included in JSON only', result.stdout)

    def test_installed_restore_uses_one_exact_id_post_despite_other_numeric_slug(self):
        for group in (False, True):
            page_history.initialize(type(self), enabled=True)
            before = len(self.calls)
            result = self.approved(self.command('page-restore', group=group))
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data['restored_page']['page_id'], 2001)
            self.assertEqual(data['current_revision_id'], 4)
            self.assertEqual(data['restored_page']['title'], 'Earlier')
            self.assertEqual(self.history_pages[2002]['title'], 'Numeric slug')
            self.assertTrue(data['html_matches_revision'])
            self.assertNotIn('body', data['restored_page'])
            self.assertNotIn('private', result.stdout)
            self.assertEqual([row for row in self.calls[before:] if row[0] != 'GET'],
                             [('POST', f"/api/v1/{'groups/18' if group else 'courses/108'}/pages/page_id:2001/revisions/1?no_verifiers=true")])

    def test_installed_front_page_restore_requires_ack_and_does_not_silently_repair(self):
        type(self).history_front_url = 'current'
        command = self.command('page-restore')
        before = len(self.calls)
        result = self.invoke(*command)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('acknowledge-front-page-change', result.stderr)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        result = self.approved((*command, '--acknowledge-front-page-change'))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['front_page_deselected'])
        self.assertFalse(data['restored_page']['front_page'])
        self.assertEqual(sum(method != 'GET' for method, _ in self.calls[before:]), 1)

    def test_installed_noop_keeps_revision_and_full_restore_preserves_scheduled_draft(self):
        result = self.approved(self.command('page-restore', '3'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['current_revision_id'], 3)
        self.history_pages[2001].update(published=False, publish_at='2027-10-01T12:00:00Z')
        result = self.approved(self.command('page-restore'))
        self.assertEqual(result.returncode, 0, result.stderr)
        page = json.loads(result.stdout)['restored_page']
        self.assertFalse(page['published'])
        self.assertEqual(page['publish_at'], '2027-10-01T12:00:00Z')

    def test_installed_stale_revision_selected_content_inventory_account_context_and_target_never_write(self):
        for mutation in ('revision', 'selected', 'inventory', 'account', 'context', 'target'):
            page_history.initialize(type(self), enabled=True)
            command = self.command('page-restore')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mutation == 'revision':
                self.history_records[4] = {**self.history_records[3], 'revision_id': 4}
            elif mutation == 'selected':
                self.history_records[1]['body'] = '<p>Different imported history</p>'
            elif mutation == 'inventory':
                self.history_pages[2002]['title'] = 'Changed title'
            elif mutation == 'account':
                type(self).history_viewer = 8
            elif mutation == 'context':
                self.history_context['name'] = 'Different context'
            else:
                command = self.command('page-restore', '2')
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Preview changed', result.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))

    def test_installed_normalized_html_and_urls_are_reported_without_exposing_private_content(self):
        type(self).history_sanitize = type(self).history_url_suffix = True
        self.history_records[1]['body'] += '<script>bad()</script>'
        result = self.approved(self.command('page-restore'))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data['html_matches_revision'])
        self.assertFalse(data['url_matches_revision'])
        self.assertEqual(data['restored_page']['url'], 'earlier-2')
        self.assertNotIn('private', result.stdout)

    def test_installed_unpredicted_front_url_change_requires_acknowledgement_not_silent_success(self):
        type(self).history_front_url = 'current'
        type(self).history_url_suffix = True
        before = len(self.calls)
        result = self.approved(self.command('page-restore', '3'))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('may have succeeded', result.stderr)
        self.assertEqual(sum(method != 'GET' for method, _ in self.calls[before:]), 1)
        page_history.initialize(type(self), enabled=True)
        type(self).history_front_url = 'current'
        type(self).history_url_suffix = True
        result = self.approved(self.command('page-restore', '3', fields=('--acknowledge-front-page-change',)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['front_page_deselected'])

    def test_installed_readback_ack_denial_permissions_identity_and_ignored_restore_never_retry(self):
        for failure in ('ack', 'readback', 'denial', 'permissions', 'identity', 'ignored', 'metadata', 'title'):
            page_history.initialize(type(self), enabled=True)
            command = self.command('page-restore')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if failure == 'ack':
                type(self).history_ack_patch = {'body': 'synthetic-private-invalid-ack'}
            elif failure == 'readback':
                type(self).history_readback_denied = True
            elif failure == 'denial':
                type(self).history_write_denied = True
            elif failure == 'permissions':
                type(self).history_permissions_lost = True
            elif failure == 'identity':
                type(self).history_account_changed = True
            elif failure == 'ignored':
                type(self).history_ignore_restore = True
            elif failure == 'metadata':
                type(self).history_readback_patch = {'editing_roles': 'students'}
            else:
                type(self).history_ack_patch = {'title': 'Earlier-2'}
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual(sum(method != 'GET' for method, _ in self.calls[before:]), 1)

    def test_installed_body_only_permission_cannot_restore_title_and_native_history_denial_stays_authoritative(self):
        type(self).history_permissions = {'manage_wiki_create': False, 'manage_wiki_update': False, 'participate_as_student': True}
        before = len(self.calls)
        result = self.invoke(*self.command('page-restore'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('full native page-update', result.stderr)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        type(self).history_student_wiki = True
        result = self.approved(self.command('page-restore'))
        self.assertEqual(result.returncode, 0, result.stderr)
        type(self).history_edit_allowed = False
        result = self.invoke(*self.command('page-restore'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('denied access', result.stderr)

    def test_installed_malformed_history_and_invalid_syntax_fail_without_partial_output_or_writes(self):
        for rows in ([], [{**self.history_records[3], 'latest': 'true'}],
                     [{**self.history_records[3], 'latest': True}, {**self.history_records[3], 'latest': True}]):
            type(self).history_list_patch = rows
            result = self.invoke(*self.command())
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
        for command in (('page-restore', '108', '2001', '1', '--context', 'course'),
                        self.command('page-restore', 'latest'), (*self.command('page-restore'), '--yes'),
                        self.command('page-revision', 'page_id:1'), (*self.command('page-revisions'), '--include-content')):
            before = len(self.calls)
            result = self.invoke(*command)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.calls[before:], [])


if __name__ == '__main__':
    import unittest
    unittest.main()
