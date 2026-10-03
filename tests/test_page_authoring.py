"""Shared wiki permissions, native defaults, exact IDs and uncertain write outcomes."""

import copy
import unittest

from canvas_cli.client import CanvasError
from canvas_cli.page_authoring import change


class PageClient:
    host = 'https://canvas.example.edu'

    def __init__(self):
        self.calls = []
        self.identity = 7
        self.permissions = {'manage_wiki_create': True, 'manage_wiki_update': True, 'participate_as_student': False}
        self.student_wiki = False
        self.context_patch = {}
        self.pages = {9: {'page_id': 9, 'url': 'welcome', 'title': 'Welcome', 'editing_roles': 'teachers,students',
                          'body': '<p>Synthetic private old body</p>', 'published': True, 'front_page': False,
                          'updated_at': '2026-10-01T12:00:00Z', 'publish_at': None,
                          'last_edited_by': {'email': 'synthetic-private-editor@example.edu'}, 'secure_params': 'synthetic-private-token'},
                      10: {'page_id': 10, 'url': '9', 'title': 'Numeric slug', 'editing_roles': 'teachers',
                           'body': '<p>Synthetic other private body</p>', 'published': True, 'front_page': True,
                           'updated_at': '2026-10-01T12:00:00Z', 'publish_at': None}}
        self.revision = {'revision_id': 3, 'updated_at': self.pages[9]['updated_at'], 'latest': True,
                         'edited_by': {'email': 'synthetic-private-revision-editor@example.edu'}}
        self.history_allowed = True
        self.ack_patch = {}
        self.after_patch = {}
        self.written = False
        self.denied_after = False
        self.ignored_fields = set()
        self.native_denial = False
        self.inventory_failure = False
        self.sanitize_body = False
        self.delete_race = False

    def request(self, route, method='GET', body=None):
        self.calls.append((method, route, copy.deepcopy(body)))
        if method != 'GET':
            if self.native_denial:
                raise CanvasError('Native page restriction', status=403)
            values = copy.deepcopy(body['wiki_page'])
            creating = method == 'POST' or self.delete_race
            page_id = 11 if creating else int(route.rsplit(':', 1)[1])
            current = ({'page_id': page_id, 'url': values.get('title', 'Unwanted').lower().replace(' ', '-'),
                        'title': values.get('title', 'Unwanted'), 'body': '', 'editing_roles': 'teachers',
                        'published': False, 'front_page': False, 'publish_at': None} if creating else self.pages[page_id])
            for key, value in values.items():
                if key != 'notify_of_update' and key not in self.ignored_fields:
                    current[key] = value
            if 'title' in values:
                current['url'] = values['title'].lower().replace(' ', '-')
            if current.get('front_page'):
                for other in self.pages.values():
                    other['front_page'] = False
                current['front_page'] = True
            if self.sanitize_body:
                current['body'] = current['body'].replace('<script>bad()</script>', '')
            current['updated_at'] = '2026-10-02T12:00:00Z'
            self.revision.update(revision_id=self.revision['revision_id'] + 1, updated_at=current['updated_at'])
            self.pages[page_id] = current
            self.written = True
            return {**copy.deepcopy(current), **self.ack_patch}, ''
        if route == '/api/v1/users/self/profile':
            return {'id': self.identity}, ''
        if '/permissions?' in route:
            return copy.deepcopy(self.permissions), ''
        if '?include%5B%5D=allow_student_wiki_edits' in route:
            return {'id': int(route.split('/')[4].split('?')[0]), 'allow_student_wiki_edits': self.student_wiki}, ''
        if '/pages/page_id:' in route:
            page_id = int(route.split('/page_id:')[1].split('/')[0])
            if page_id not in self.pages:
                raise CanvasError('missing page', status=404)
            if self.written and self.denied_after:
                raise CanvasError('synthetic-private-denial', status=403)
            if '/revisions?' in route:
                if not self.history_allowed:
                    raise CanvasError('No native edit-history permission', status=403)
                return [copy.deepcopy(self.revision)], ''
            if '/revisions/latest?' in route:
                return copy.deepcopy(self.revision), ''
            return {**copy.deepcopy(self.pages[page_id]), **(self.after_patch if self.written else {})}, ''
        return {'id': int(route.split('/')[4]), 'name': 'Synthetic context', **self.context_patch}, ''

    def list(self, route, max_pages):
        self.calls.append(('GET', route, None))
        if self.inventory_failure or max_pages == 1:
            raise CanvasError('Page limit reached')
        return [copy.deepcopy(row) for row in self.pages.values()]


class PageAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.client = PageClient()

    def preview(self, page_id='9', **options):
        return change(self.client, '123', page_id, context_type='course', acknowledge_shared=True,
                      **({'body': '<p>New 🌿 content</p>'} | options))

    def execute(self, preview, page_id='9', **options):
        return self.preview(page_id, yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [row for row in self.client.calls if row[0] != 'GET']

    def test_preview_binds_native_revision_exact_id_and_omits_private_prior_content(self):
        data = self.preview()
        self.assertEqual(data['route'], '/api/v1/courses/123/pages/page_id:9')
        self.assertEqual(data['revision']['revision_id'], 3)
        self.assertEqual(data['body'], {'wiki_page': {'body': '<p>New 🌿 content</p>', 'notify_of_update': False}})
        for marker in ('Synthetic private', 'synthetic-private', 'Synthetic other private'):
            self.assertNotIn(marker, str(data))
        self.assertTrue(data['dry_run'])
        self.assertIn('not an atomic lock', data['warning'])
        self.assertEqual(self.writes(), [])

    def test_title_change_uses_id_despite_colliding_numeric_slug_and_readback_new_url(self):
        data = self.preview(title=' Renamed 🌿 ')
        result = self.execute(data, title=' Renamed 🌿 ')
        self.assertEqual(result['shared_page']['page_id'], 9)
        self.assertEqual(result['shared_page']['url'], 'renamed-🌿')
        self.assertEqual(self.client.pages[10]['title'], 'Numeric slug')
        self.assertTrue(result['acknowledgement_matches_readback'])
        self.assertTrue(result['html_matches_request'])
        self.assertEqual(len(self.writes()), 1)
        self.assertTrue(all('/pages/9' not in row[1] for row in self.client.calls))

    def test_creation_posts_new_page_and_keeps_course_manager_draft_default(self):
        data = self.preview(None, title='Welcome')
        self.assertEqual(data['method'], 'POST')
        self.assertFalse(data['body']['wiki_page']['published'])
        self.assertEqual(data['duplicate_titles'], 1)
        result = self.execute(data, None, title='Welcome')
        self.assertTrue(result['created'])
        self.assertEqual(result['shared_page']['page_id'], 11)
        self.assertFalse(result['shared_page']['published'])
        self.assertEqual(len(self.writes()), 1)

    def test_student_course_creation_default_is_published_not_a_fake_private_draft(self):
        self.client.permissions = {'manage_wiki_create': False, 'manage_wiki_update': False, 'participate_as_student': True}
        self.client.student_wiki = True
        data = self.preview(None, title='Student notes')
        self.assertTrue(data['body']['wiki_page']['published'])
        result = self.execute(data, None, title='Student notes')
        self.assertTrue(result['shared_page']['published'])
        self.assertFalse(self.client.permissions['manage_wiki_update'])

    def test_read_or_update_permission_alone_cannot_create_and_title_only_edits_omit_old_body(self):
        self.client.permissions['manage_wiki_create'] = False
        with self.assertRaisesRegex(CanvasError, 'does not permit page creation'):
            self.preview(None, title='New')
        data = self.preview(title='New', body=None)
        result = self.execute(data, title='New', body=None)
        self.assertNotIn('body', result['shared_page'])
        self.assertNotIn('synthetic-private', str(result))
        self.assertNotIn('Synthetic private', str(result))

    def test_group_creation_defaults_to_published_and_context_appropriate_roles(self):
        options = {'context_type': 'group', 'acknowledge_shared': True, 'title': 'Group notes', 'roles': 'public,members'}
        data = change(self.client, '456', **options)
        self.assertTrue(data['body']['wiki_page']['published'])
        self.assertEqual(data['body']['wiki_page']['body'], '')
        self.assertEqual(data['body']['wiki_page']['editing_roles'], 'members,public')
        result = change(self.client, '456', **options, yes=True, confirm=data['confirm'])
        self.assertEqual(result['group_id'], 456)

    def test_page_level_student_edit_permission_is_history_not_latest_or_enrollment(self):
        self.client.permissions = {'manage_wiki_create': False, 'manage_wiki_update': False, 'participate_as_student': True}
        self.client.student_wiki = False
        data = self.preview()
        self.assertTrue(self.execute(data)['html_matches_request'])
        self.client.written = False
        self.client.history_allowed = False
        with self.assertRaisesRegex(CanvasError, 'edit-history'):
            self.preview()
        self.assertEqual(len(self.writes()), 1)

    def test_body_only_edit_does_not_grant_title_notify_publication_or_roles(self):
        self.client.permissions = {'manage_wiki_create': False, 'manage_wiki_update': False, 'participate_as_student': True}
        for options in ({'title': 'New'}, {'notify': True}, {'published': True}, {'front_page': False}, {'roles': 'students'}):
            with self.subTest(options=options), self.assertRaises(CanvasError):
                self.preview(**options)
        self.assertEqual(self.writes(), [])

    def test_front_page_inventory_is_bound_and_cannot_be_unpublished_without_unsetting(self):
        self.client.pages[9]['front_page'] = True
        self.client.pages[10]['front_page'] = False
        with self.assertRaisesRegex(CanvasError, 'front page must remain published'):
            self.preview(published=False)
        data = self.preview(published=False, front_page=False)
        self.assertEqual(data['current_front_page']['page_id'], 9)
        result = self.execute(data, published=False, front_page=False)
        self.assertFalse(result['shared_page']['front_page'])
        self.assertFalse(result['shared_page']['published'])

    def test_setting_front_page_changes_selected_page_and_verifies_inventory(self):
        data = self.preview(front_page=True, notify=True)
        self.assertEqual(data['current_front_page']['page_id'], 10)
        result = self.execute(data, front_page=True, notify=True)
        self.assertTrue(result['shared_page']['front_page'])
        self.assertFalse(self.client.pages[10]['front_page'])
        self.assertEqual(self.writes()[0][2]['wiki_page']['notify_of_update'], True)

    def test_stale_identity_revision_body_inventory_permissions_and_requested_fields_never_write(self):
        for mutation in ('identity', 'revision', 'body', 'permissions', 'context', 'inventory', 'requested'):
            self.setUp()
            data = self.preview(front_page=True)
            if mutation == 'identity':
                self.client.identity = 8
            elif mutation == 'revision':
                self.client.revision['revision_id'] = 4
            elif mutation == 'body':
                self.client.pages[9]['body'] = '<p>Another edit</p>'
            elif mutation == 'permissions':
                self.client.permissions['manage_wiki_create'] = False
            elif mutation == 'context':
                self.client.context_patch['name'] = 'Renamed context'
            elif mutation == 'inventory':
                self.client.pages[10]['title'] = 'Another front-page title'
            options = {'body': '<p>Different requested body</p>'} if mutation == 'requested' else {}
            with self.subTest(mutation=mutation), self.assertRaisesRegex(CanvasError, 'Preview changed'):
                self.execute(data, front_page=True, **options)
            self.assertEqual(self.writes(), [])

    def test_partial_or_ambiguous_inventory_and_missing_preflight_page_do_not_upsert(self):
        for options in ({'max_pages': 1}, {'front_page': True, 'max_pages': 1}):
            with self.assertRaisesRegex(CanvasError, 'Page limit'):
                self.preview(None if 'front_page' not in options else '9', title='New', **options)
        with self.assertRaises(CanvasError):
            self.preview('99')
        self.client.pages[10]['page_id'] = 9
        with self.assertRaisesRegex(CanvasError, 'ambiguous'):
            self.preview(None, title='New')
        self.assertEqual(self.writes(), [])

    def test_malformed_locked_foreign_deleted_or_block_editor_pages_are_not_written(self):
        for patch in ({'page_id': True}, {'page_id': 8}, {'published': 'true'}, {'title': None},
                      {'body': []}, {'locked_for_user': True}, {'hidden_for_user': True}, {'workflow_state': 'deleted'},
                      {'editor': 'block_editor'}, {'editor': 'block_content_editor'}, {'block_editor_attributes': {}},
                      {'block_editor_data': {}}, {'updated_at': 'bad timestamp'}):
            self.setUp()
            self.client.pages[9].update(patch)
            with self.subTest(patch=patch), self.assertRaises(CanvasError):
                self.preview()
            self.assertEqual(self.writes(), [])

    def test_native_null_empty_html_is_editable_but_absent_body_is_not_readable(self):
        self.client.pages[9]['body'] = None
        data = self.preview()
        self.assertTrue(self.execute(data)['html_matches_request'])
        self.client.written = False
        del self.client.pages[9]['body']
        with self.assertRaisesRegex(CanvasError, 'readable page HTML'):
            self.preview()

    def test_native_denials_and_malformed_permission_values_are_not_inferred_or_bypassed(self):
        for patch in ({'manage_wiki_update': 'true'}, {'manage_wiki_create': 1}, {'participate_as_student': None}):
            self.setUp()
            self.client.permissions.update(patch)
            with self.assertRaisesRegex(CanvasError, 'exact native page permissions'):
                self.preview()
        for patch in ({'concluded': True}, {'workflow_state': 'completed'}, {'non_collaborative': True}, {'access_restricted_by_date': True}):
            self.setUp()
            self.client.context_patch = patch
            with self.assertRaises(CanvasError):
                self.preview()
        self.setUp()
        self.client.history_allowed = False
        with self.assertRaises(CanvasError):
            self.preview()
        self.assertEqual(self.writes(), [])

    def test_drafts_require_authorized_native_wiki_management_not_student_read_leak(self):
        self.client.pages[9]['published'] = False
        self.assertTrue(self.preview()['dry_run'])
        self.client.permissions = {'manage_wiki_create': False, 'manage_wiki_update': False, 'participate_as_student': True}
        with self.assertRaisesRegex(CanvasError, 'authorized readable RCE'):
            self.preview()

    def test_scheduled_body_edit_preserves_schedule_but_implicit_unscheduling_is_refused(self):
        self.client.pages[9].update(published=False, publish_at='2099-10-05T12:00:00Z')
        data = self.preview()
        self.assertEqual(self.execute(data)['shared_page']['publish_at'], '2099-10-05T12:00:00Z')
        for options in ({'published': True}, {'front_page': True}):
            with self.assertRaisesRegex(CanvasError, 'scheduling controls'):
                self.preview(**options)

    def test_sanitized_html_is_reported_as_different_not_silently_claimed_identical(self):
        text = '<p>Safe</p><script>bad()</script>'
        self.client.sanitize_body = True
        data = self.preview(body=text)
        result = self.execute(data, body=text)
        self.assertFalse(result['html_matches_request'])
        self.assertEqual(result['shared_page']['body'], '<p>Safe</p>')

    def test_ignored_body_or_metadata_never_claims_success_and_is_not_retried(self):
        for ignored in ('body', 'title', 'published'):
            self.setUp()
            options = {'title': 'New', 'published': False}
            data = self.preview(**options)
            self.client.ignored_fields = {ignored}
            with self.subTest(ignored=ignored), self.assertRaisesRegex(CanvasError, 'may have succeeded'):
                self.execute(data, **options)
            self.assertEqual(len(self.writes()), 1)

    def test_foreign_ack_denied_readback_or_different_stored_body_is_uncertain_without_private_output(self):
        for variant in ('ack', 'readback', 'denied', 'upsert'):
            self.setUp()
            data = self.preview()
            if variant == 'ack':
                self.client.ack_patch = {'page_id': 8, 'body': 'synthetic-private-never-log'}
            elif variant == 'readback':
                self.client.after_patch = {'body': 'synthetic-private-never-log'}
            elif variant == 'denied':
                self.client.denied_after = True
            else:
                self.client.delete_race = True
            with self.subTest(variant=variant), self.assertRaisesRegex(CanvasError, 'unwanted page') as error:
                self.execute(data)
            self.assertNotIn('synthetic-private', str(error.exception))
            self.assertEqual(len(self.writes()), 1)

    def test_invalid_values_flags_ack_and_ids_fail_before_any_network(self):
        for patch in ({'title': ''}, {'title': 'x' * 256}, {'title': 'bad\nname'}, {'title': '\ud800'}, {'body': '\ud800'},
                      {'body': '\x00'}, {'body': 'x' * 40001}, {'body': []}, {'roles': 'members'},
                      {'roles': 'students,students'}, {'roles': ''}, {'published': 1}, {'front_page': 'false'},
                      {'notify': 1}, {'max_pages': 0}, {'acknowledge_shared': False}, {'yes': True}, {'confirm': 'abc'}):
            with self.subTest(patch=patch), self.assertRaises(CanvasError):
                change(self.client, '123', '9', context_type='course',
                       **({'body': '<p>New</p>', 'acknowledge_shared': True} | patch))
        for key in ('0', '01', 'welcome', 'page_id:9', '../9'):
            with self.assertRaises(CanvasError):
                self.preview(key)
        self.assertEqual(self.client.calls, [])


if __name__ == '__main__':
    unittest.main()
