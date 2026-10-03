"""Installed CLI wiki authoring against synthetic native-shaped HTTPS endpoints."""

import json
from pathlib import Path

from . import page_authoring
from .fixture import CanvasFixture


class PageAuthoringE2E(CanvasFixture):
    def setUp(self):
        page_authoring.initialize(type(self), enabled=True)
        self.body_file = Path(self.tmp.name) / 'synthetic-page.html'
        self.body_file.write_text('<p>Shared notes 🌿</p>', encoding='utf-8')

    def command(self, *, creating=False, group=False, fields=()):
        return (('page-create' if creating else 'page-edit'), ('17' if group else '107'),
                *(() if creating else ('1001',)), '--context', ('group' if group else 'course'),
                '--acknowledge-shared-page', '--body-file', str(self.body_file), *fields)

    def approved(self, command):
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def test_installed_exact_id_edit_renames_without_numeric_slug_collision_and_verifies_html(self):
        before = len(self.calls)
        result = self.approved(self.command(fields=('--title', 'Renamed 🌿')))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['shared_page']['page_id'], 1001)
        self.assertEqual(data['shared_page']['url'], 'renamed-🌿')
        self.assertTrue(data['html_matches_request'])
        self.assertEqual(self.page_records[1002]['title'], 'Numeric slug')
        self.assertEqual([row for row in self.calls[before:] if row[0] != 'GET'],
                         [('PUT', '/api/v1/courses/107/pages/page_id:1001')])
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertTrue(any('revisions?per_page=1' in route for _, route in self.calls[before:]))

    def test_create_uses_post_with_role_appropriate_draft_or_published_defaults(self):
        for group in (False, True):
            page_authoring.initialize(type(self), enabled=True)
            result = self.approved(self.command(creating=True, group=group, fields=('--title', 'New wiki page')))
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertTrue(data['created'])
            self.assertEqual(data['shared_page']['published'], group)
            self.assertEqual(self.page_write['wiki_page']['notify_of_update'], False)

    def test_paged_create_inventory_and_front_page_inventory_are_required(self):
        for command in (self.command(creating=True, fields=('--title', 'New')), self.command(fields=('--front-page',))):
            before = len(self.calls)
            result = self.invoke(*command, '--max-pages', '1')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Page limit', result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))

    def test_native_implicit_front_page_selection_requires_intent_not_false_success(self):
        self.page_records[1002]['front_page'] = False
        command = self.command(creating=True, fields=('--title', 'Front Page', '--published'))
        before = len(self.calls)
        result = self.approved(command)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('may have succeeded', result.stderr)
        self.assertEqual(sum(method != 'GET' for method, _ in self.calls[before:]), 1)
        page_authoring.initialize(type(self), enabled=True)
        self.page_records[1002]['front_page'] = False
        result = self.approved((*command, '--front-page'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['shared_page']['front_page'])

    def test_front_page_and_publication_controls_roundtrip_without_false_delivery_claim(self):
        result = self.approved(self.command(fields=('--front-page', '--notify', '--editing-roles', 'students,teachers')))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.page_records[1001]['front_page'])
        self.assertFalse(self.page_records[1002]['front_page'])
        self.assertTrue(self.page_write['wiki_page']['notify_of_update'])
        result = self.approved(self.command(fields=('--no-front-page', '--no-published')))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.page_records[1001]['published'])
        self.assertIn('not delivery-verified', json.loads(result.stdout)['note'])

    def test_student_page_body_permission_does_not_allow_title_or_roles_but_course_optin_does(self):
        type(self).page_permissions = {'manage_wiki_create': False, 'manage_wiki_update': False, 'participate_as_student': True}
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        before = len(self.calls)
        result = self.invoke(*self.command(fields=('--title', 'New')))
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        type(self).page_student_wiki = True
        result = self.approved(self.command(fields=('--title', 'Student title')))
        self.assertEqual(result.returncode, 0, result.stderr)
        type(self).page_history_allowed = False
        result = self.invoke(*self.command())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')

    def test_stale_revision_body_file_account_and_context_do_not_send(self):
        for mutation in ('revision', 'body-file', 'identity', 'context'):
            page_authoring.initialize(type(self), enabled=True)
            self.body_file.write_text('<p>Shared notes 🌿</p>', encoding='utf-8')
            command = self.command()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mutation == 'revision':
                type(self).page_revision_id += 1
            elif mutation == 'body-file':
                self.body_file.write_text('<p>Different file</p>', encoding='utf-8')
            elif mutation == 'identity':
                type(self).page_viewer = 8
            else:
                self.page_context['name'] = 'Different context'
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Preview changed', result.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))

    def test_invalid_flags_ack_and_bounded_utf8_files_make_no_requests(self):
        for command in (('page-edit', '107', '1001', '--context', 'course', '--title', 'New'),
                        (*self.command(), '--yes'), (*self.command(), '--published', '--context', 'user')):
            before = len(self.calls)
            result = self.invoke(*command)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.calls[before:], [])
        for content in (b'\xff', b'x' * 40001, b'\x00'):
            self.body_file.write_bytes(content)
            before = len(self.calls)
            result = self.invoke(*self.command())
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.calls[before:], [])

    def test_sanitized_stored_html_difference_is_visible_in_brief_and_json(self):
        type(self).page_sanitize = True
        self.body_file.write_text('<p>Safe 🌿</p><script>bad()</script>', encoding='utf-8')
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data['html_matches_request'])
        self.assertEqual(data['shared_page']['body'], '<p>Safe 🌿</p>')
        # Test rendering separately without issuing another real/synthetic mutation.
        from canvas_cli.formatting import brief
        self.assertIn('differs from input', brief(data))

    def test_unverified_ack_readback_permissions_or_concurrent_upsert_is_not_success_or_retried(self):
        for variant in ('ack', 'readback', 'permissions', 'upsert', 'ignored-body', 'denial'):
            page_authoring.initialize(type(self), enabled=True)
            command = self.command()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if variant == 'ack':
                type(self).page_ack_patch = {'page_id': 1002, 'body': 'synthetic-private-never-log'}
            elif variant == 'readback':
                type(self).page_readback_denied = True
            elif variant == 'permissions':
                type(self).page_permissions_lost = True
            elif variant == 'upsert':
                type(self).page_delete_race = True
            elif variant == 'ignored-body':
                type(self).page_ignored_fields = {'body'}
            else:
                type(self).page_write_denied = True
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual(sum(method != 'GET' for method, _ in self.calls[before:]), 1)


if __name__ == '__main__':
    import unittest
    unittest.main()
