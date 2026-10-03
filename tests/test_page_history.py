"""Native latest-vs-history permissions, private projections and exact restores."""

import copy
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from canvas_cli.cli import brief, parser
from canvas_cli.client import CanvasError
from canvas_cli.navigation import command_help
from canvas_cli.page_history import read, restore


class HistoryClient:
    host = 'https://canvas.example.edu'

    def __init__(self):
        self.calls = []
        self.user = 7
        self.permissions = {'manage_wiki_create': True, 'manage_wiki_update': True, 'participate_as_student': False}
        self.student_wiki = False
        self.context_patch = {}
        self.front_url = 'other'
        self.pages = {9: {'page_id': 9, 'title': 'Current', 'url': 'current', 'body': '<p>Synthetic current secret</p>',
                          'published': True, 'editing_roles': 'teachers', 'publish_at': None,
                          'updated_at': '2026-10-01T12:00:00Z'},
                      10: {'page_id': 10, 'title': 'Other', 'url': 'other', 'body': '<p>Other secret</p>',
                           'published': True, 'editing_roles': 'teachers', 'publish_at': None,
                           'updated_at': '2026-10-01T12:00:00Z'}}
        self.revisions = {1: {'revision_id': 1, 'title': 'Earlier', 'url': 'earlier', 'body': '<p>Synthetic historic secret</p>',
                              'updated_at': '2026-09-01T12:00:00Z'},
                          2: {'revision_id': 2, 'title': 'Current', 'url': 'current', 'body': '<p>Previous secret</p>',
                              'updated_at': '2026-09-15T12:00:00Z'},
                          3: {'revision_id': 3, **{key: self.pages[9][key] for key in ('title', 'url', 'body', 'updated_at')}}}
        self.history_allowed = self.read_allowed = True
        self.ack_patch = {}
        self.detail_patch = {}
        self.page_patch = {}
        self.list_patch = None
        self.written = self.ignore_restore = self.deny_write = self.deny_after = self.sanitize = False
        self.url_suffix = False
        self.changed_permission_after = self.changed_account_after = self.new_page_race = False
        self.list_failure = False

    def record(self, revision_id, summary=True):
        row = copy.deepcopy(self.revisions[revision_id])
        row['latest'] = revision_id == max(self.revisions)
        row['edited_by'] = {'id': 8, 'display_name': 'Synthetic editor', 'name': 'Synthetic longer name',
                            'email': 'synthetic-private-actor@example.edu', 'avatar_url': 'synthetic-private-avatar',
                            'login_id': 'synthetic-private-login', 'secure_params': 'synthetic-private-token'}
        if summary:
            for key in ('title', 'url', 'body'):
                row.pop(key)
        return row

    def page(self, page_id):
        row = {**copy.deepcopy(self.pages[page_id]), 'front_page': self.pages[page_id]['url'] == self.front_url,
               'last_edited_by': {'email': 'synthetic-private-editor@example.edu'}, 'secure_params': 'synthetic-private-token'}
        return {**row, **(self.page_patch if self.written else {})}

    def request(self, route, method='GET', body=None):
        self.calls.append((method, route, copy.deepcopy(body)))
        url = urlsplit(route)
        if method != 'GET':
            if self.deny_write:
                raise CanvasError('synthetic-private-native-denial', status=403)
            self.written = True
            if not self.ignore_restore:
                selected = self.revisions[int(url.path.rsplit('/', 1)[1])]
                page = self.pages[9]
                changes = {key: selected[key] for key in ('title', 'url', 'body')}
                if self.sanitize:
                    changes['body'] = changes['body'].replace('<script>bad()</script>', '')
                if self.url_suffix:
                    changes['url'] += '-2'
                if any(page[key] != value for key, value in changes.items()):
                    page.update(changes, updated_at='2026-10-03T12:00:00Z')
                    number = max(self.revisions) + 1
                    self.revisions[number] = {'revision_id': number, **{key: page[key] for key in ('title', 'url', 'body', 'updated_at')}}
            if self.new_page_race:
                self.pages[10]['url'] = 'concurrent-url'
            return {**self.record(max(self.revisions), False), **self.ack_patch}, ''
        if url.path == '/api/v1/users/self/profile':
            return {'id': 8 if self.written and self.changed_account_after else self.user}, ''
        if url.path.endswith('/permissions'):
            permissions = {**self.permissions}
            if self.written and self.changed_permission_after:
                permissions['manage_wiki_update'] = False
            return permissions, ''
        if '/pages/page_id:' not in url.path:
            context = {'id': int(url.path.rsplit('/', 1)[1]), 'name': 'Synthetic context', **self.context_patch}
            if 'include%5B%5D=allow_student_wiki_edits' in route:
                context['allow_student_wiki_edits'] = self.student_wiki
            return context, ''
        page_id = int(url.path.split('/page_id:')[1].split('/')[0])
        if not self.read_allowed or self.written and self.deny_after:
            raise CanvasError('synthetic-private-read-denial', status=403)
        if page_id not in self.pages:
            raise CanvasError('synthetic-private-missing-page', status=404)
        if '/revisions/' in url.path:
            identifier = url.path.rsplit('/', 1)[1]
            if identifier != 'latest' and not self.history_allowed:
                raise CanvasError('Native read-revisions denied', status=403)
            number = max(self.revisions) if identifier == 'latest' else int(identifier)
            if number not in self.revisions:
                raise CanvasError('synthetic-private-missing-revision', status=404)
            return {**self.record(number, 'summary=true' in route), **self.detail_patch}, ''
        return self.page(page_id), ''

    def list(self, route, max_pages):
        self.calls.append(('GET', route, None))
        if self.list_failure or max_pages < 2:
            raise CanvasError('Page limit reached')
        if '/revisions?' in route:
            if not self.history_allowed:
                raise CanvasError('Native read-revisions denied', status=403)
            return copy.deepcopy(self.list_patch) if self.list_patch is not None else [self.record(number) for number in self.revisions]
        return [self.page(number) for number in self.pages]


class PageHistoryTests(unittest.TestCase):
    def setUp(self):
        self.client = HistoryClient()

    def read(self, revision_id=None, **options):
        return read(self.client, '123', '9', revision_id, context_type='course', **options)

    def restore(self, revision_id='1', **options):
        return restore(self.client, '123', '9', revision_id, context_type='course', acknowledge_shared=True, **options)

    def execute(self, preview, revision_id='1', **options):
        return self.restore(revision_id, yes=True, confirm=preview['confirm'], **options)

    def writes(self):
        return [row for row in self.client.calls if row[0] != 'GET']

    def test_full_metadata_history_is_sorted_and_does_not_leak_content_or_actor_records(self):
        result = self.read()
        self.assertEqual([row['revision_id'] for row in result['page_revisions']], [3, 2, 1])
        self.assertTrue(result['complete_for_endpoint'])
        for marker in ('secret', 'synthetic-private', 'Earlier', 'edited_by'):
            self.assertNotIn(marker, str(result))
        self.assertEqual(self.writes(), [])
        self.assertIn('repair legacy', result['note'])

    def test_numeric_detail_and_latest_default_to_metadata_with_explicit_content_and_editor_projection(self):
        result = self.read('1')
        self.assertEqual(set(result['page_revision']), {'revision_id', 'updated_at', 'latest'})
        result = self.read('1', content=True, editors=True)
        self.assertEqual(result['page_revision']['title'], 'Earlier')
        self.assertEqual(result['page_revision']['body'], '<p>Synthetic historic secret</p>')
        self.assertEqual(result['page_revision']['edited_by'], {'id': 8, 'name': 'Synthetic longer name', 'display_name': 'Synthetic editor'})
        self.assertNotIn('synthetic-private', str(result))
        self.assertNotIn('secret', brief(result))
        self.assertEqual(self.read('latest')['page_revision']['revision_id'], 3)

    def test_readable_drafts_and_latest_do_not_invent_or_require_write_permissions(self):
        self.client.pages[9]['published'] = False
        self.client.permissions = {'manage_wiki_create': False, 'manage_wiki_update': False, 'participate_as_student': False}
        self.client.history_allowed = False
        self.assertFalse(self.read('latest')['page']['published'])
        self.assertFalse(any('/permissions' in row[1] for row in self.client.calls))
        for revision in (None, '1'):
            with self.assertRaisesRegex(CanvasError, 'read-revisions'):
                self.read(revision)
        self.client.read_allowed = False
        with self.assertRaises(CanvasError):
            self.read('latest')
        self.assertEqual(self.writes(), [])

    def test_restore_preview_omits_prior_bodies_and_editors_but_binds_full_inventory_and_revision(self):
        preview = self.restore()
        self.assertEqual(preview['route'], '/api/v1/courses/123/pages/page_id:9/revisions/1?no_verifiers=true')
        self.assertEqual(preview['body'], {})
        self.assertEqual(preview['restore_revision']['title'], 'Earlier')
        for marker in ('secret', 'synthetic-private', 'edited_by'):
            self.assertNotIn(marker, str(preview))
        self.assertEqual(preview['current_revision']['revision_id'], 3)
        self.assertEqual(self.writes(), [])
        self.assertTrue(preview['dry_run'])

    def test_restore_posts_once_exact_id_and_preserves_publication_roles_and_schedule(self):
        self.client.pages[9]['published'] = False
        self.client.pages[9]['publish_at'] = '2027-10-01T12:00:00Z'
        result = self.execute(self.restore())
        self.assertEqual(result['current_revision_id'], 4)
        self.assertEqual(result['restored_page']['page_id'], 9)
        self.assertEqual(result['restored_page']['title'], 'Earlier')
        self.assertFalse(result['restored_page']['published'])
        self.assertEqual(result['restored_page']['publish_at'], '2027-10-01T12:00:00Z')
        self.assertTrue(result['html_matches_revision'])
        self.assertNotIn('body', result['restored_page'])
        self.assertNotIn('secret', str(result))
        self.assertEqual(len(self.writes()), 1)
        self.assertTrue(result['acknowledgement_matches_readback'])
        self.assertEqual(self.client.pages[10]['title'], 'Other')

    def test_current_revision_restore_is_a_native_noop_without_claiming_a_new_revision(self):
        result = self.execute(self.restore('3'), '3')
        self.assertEqual(result['selected_revision_id'], 3)
        self.assertEqual(result['current_revision_id'], 3)
        self.assertTrue(result['html_matches_revision'])
        self.assertEqual(len(self.writes()), 1)

    def test_front_page_rename_requires_explicit_ack_and_observed_deselection_is_reported(self):
        self.client.front_url = 'current'
        with self.assertRaisesRegex(CanvasError, 'acknowledge-front-page-change'):
            self.restore()
        self.assertEqual(self.writes(), [])
        options = {'acknowledge_front': True}
        result = self.execute(self.restore(**options), **options)
        self.assertTrue(result['front_page_deselected'])
        self.assertFalse(result['restored_page']['front_page'])
        self.assertIn('no longer the front page', brief(result))
        self.assertEqual(len(self.writes()), 1)

    def test_front_page_body_restore_retains_selection_without_extra_ack(self):
        self.client.front_url = 'current'
        result = self.execute(self.restore('2'), '2')
        self.assertTrue(result['restored_page']['front_page'])
        self.assertFalse(result['front_page_deselected'])

    def test_full_update_permission_and_native_numeric_history_are_required_not_body_only(self):
        self.client.permissions = {'manage_wiki_create': False, 'manage_wiki_update': False, 'participate_as_student': True}
        with self.assertRaisesRegex(CanvasError, 'full native page-update'):
            self.restore()
        self.client.student_wiki = True
        self.assertTrue(self.execute(self.restore())['html_matches_revision'])
        self.client.written = False
        self.client.history_allowed = False
        with self.assertRaisesRegex(CanvasError, 'read-revisions'):
            self.restore()
        self.assertEqual(len(self.writes()), 1)

    def test_group_history_and_restore_are_native_group_not_course_namespaces(self):
        options = {'context_type': 'group', 'acknowledge_shared': True}
        data = restore(self.client, '456', '9', '1', **options)
        result = restore(self.client, '456', '9', '1', **options, yes=True, confirm=data['confirm'])
        self.assertEqual(result['group_id'], 456)
        self.assertEqual(self.writes()[0][1], '/api/v1/groups/456/pages/page_id:9/revisions/1?no_verifiers=true')

    def test_stale_account_page_body_revisions_inventory_permissions_and_requested_target_do_not_write(self):
        for mutation in ('account', 'body', 'revision', 'selected-body', 'inventory', 'permissions', 'target', 'context'):
            self.setUp()
            data = self.restore()
            if mutation == 'account':
                self.client.user = 8
            elif mutation == 'body':
                self.client.pages[9]['body'] = self.client.revisions[3]['body'] = '<p>Other edit</p>'
            elif mutation == 'revision':
                self.client.revisions[4] = {**self.client.revisions[3], 'revision_id': 4}
            elif mutation == 'selected-body':
                self.client.revisions[1]['body'] = '<p>Altered imported history</p>'
            elif mutation == 'inventory':
                self.client.pages[10]['title'] = 'Other title'
            elif mutation == 'permissions':
                self.client.permissions['manage_wiki_create'] = False
            elif mutation == 'context':
                self.client.context_patch['name'] = 'New context'
            with self.subTest(mutation=mutation), self.assertRaisesRegex(CanvasError, 'Preview changed'):
                self.execute(data, '2' if mutation == 'target' else '1')
            self.assertEqual(self.writes(), [])

    def test_sanitized_html_and_native_url_normalization_are_labeled_not_claimed_equivalent(self):
        self.client.revisions[1]['body'] += '<script>bad()</script>'
        self.client.sanitize = True
        result = self.execute(self.restore())
        self.assertFalse(result['html_matches_revision'])
        self.assertIn('differs', brief(result))

    def test_unpredicted_front_page_url_normalization_cannot_claim_acknowledged_success(self):
        self.client.front_url = 'current'
        self.client.url_suffix = True
        data = self.restore('3')
        self.assertFalse(data['front_page_may_be_deselected'])
        with self.assertRaisesRegex(CanvasError, 'may have succeeded'):
            self.execute(data, '3')
        self.assertEqual(len(self.writes()), 1)
        self.setUp()
        self.client.front_url = 'current'
        self.client.url_suffix = True
        options = {'acknowledge_front': True}
        result = self.execute(self.restore('3', **options), '3', **options)
        self.assertTrue(result['front_page_deselected'])
        self.assertFalse(result['url_matches_revision'])

    def test_malformed_history_duplicate_ids_incomplete_pagination_latest_mismatch_fail_without_partial_success(self):
        patches = [[], [self.client.record(3), self.client.record(3)],
                   [self.client.record(1)], [{**self.client.record(3), 'latest': 'true'}],
                   [{**self.client.record(3), 'revision_id': True}],
                   [{**self.client.record(3), 'updated_at': 'not-a-time'}]]
        for rows in patches:
            self.client.list_patch = rows
            with self.subTest(rows=rows), self.assertRaises(CanvasError):
                self.read()
        self.client.list_patch = None
        with self.assertRaisesRegex(CanvasError, 'Page limit'):
            self.read(max_pages=1)
        with self.assertRaisesRegex(CanvasError, 'Page limit'):
            self.restore(max_pages=1)
        self.assertEqual(self.writes(), [])

    def test_malformed_or_wrong_revision_details_and_missing_history_do_not_restore(self):
        for values in ({'revision_id': True}, {'revision_id': 0}, {'revision_id': 8}, {'latest': 1},
                      {'body': []}, {'title': None}, {'url': ''}, {'updated_at': 'bad'}):
            self.setUp()
            self.client.detail_patch = values
            with self.subTest(values=values), self.assertRaises(CanvasError):
                self.restore()
            self.assertEqual(self.writes(), [])
        self.setUp()
        with self.assertRaises(CanvasError):
            self.restore('99')
        self.assertEqual(self.writes(), [])

    def test_null_empty_native_html_is_readable_but_missing_or_block_editor_content_is_not(self):
        self.client.pages[9]['body'] = self.client.revisions[3]['body'] = None
        self.assertEqual(self.read('latest', content=True)['page_revision']['body'], '')
        self.assertTrue(self.execute(self.restore())['html_matches_revision'])
        for values in ({'editor': 'block_content_editor'}, {'block_editor_attributes': {}},
                      {'hidden_for_user': True}, {'locked_for_user': True}, {'page_id': 8}):
            self.setUp()
            self.client.pages[9].update(values)
            with self.subTest(values=values), self.assertRaises(CanvasError):
                self.read('latest')
            self.assertEqual(self.writes(), [])
        self.setUp()
        del self.client.pages[9]['body']
        with self.assertRaisesRegex(CanvasError, 'readable page HTML'):
            self.read('latest')

    def test_mixed_time_current_revision_and_page_are_rejected_before_restore(self):
        self.client.revisions[3]['body'] = '<p>Newer than the page response</p>'
        with self.assertRaisesRegex(CanvasError, 'changed during revision inspection'):
            self.restore()
        self.assertEqual(self.writes(), [])
        self.setUp()
        self.client.revisions[3]['updated_at'] = '2026-10-02T12:00:00Z'
        with self.assertRaisesRegex(CanvasError, 'changed during revision inspection'):
            self.read('latest')

    def test_latest_false_and_historical_latest_true_are_not_accepted_as_authoritative(self):
        self.client.detail_patch = {'latest': False}
        with self.assertRaisesRegex(CanvasError, 'current page revision'):
            self.read('latest')
        self.client.detail_patch = {'latest': True}
        with self.assertRaisesRegex(CanvasError, 'outside the observed current history'):
            self.restore()
        self.assertEqual(self.writes(), [])

    def test_read_account_switch_and_restore_mid_preflight_page_changes_fail_without_output_or_write(self):
        original_request = self.client.request

        def switch_after_detail(route, *args, **kwargs):
            result = original_request(route, *args, **kwargs)
            if '/revisions/latest?' in route:
                self.client.user = 8
            return result

        with patch.object(self.client, 'request', side_effect=switch_after_detail), self.assertRaisesRegex(CanvasError, 'account changed'):
            self.read('latest')
        self.assertEqual(self.writes(), [])
        self.setUp()
        original_list = self.client.list

        def edit_after_inventory(route, max_pages):
            rows = original_list(route, max_pages)
            self.client.pages[9]['body'] = self.client.revisions[3]['body'] = '<p>Concurrent preflight edit</p>'
            return rows

        with patch.object(self.client, 'list', side_effect=edit_after_inventory), self.assertRaisesRegex(CanvasError, 'changed during restoration preflight'):
            self.restore()
        self.assertEqual(self.writes(), [])

    def test_inventory_current_page_mismatch_and_body_only_ignored_restore_are_not_success(self):
        original_list = self.client.list

        def different_inventory(route, max_pages):
            rows = original_list(route, max_pages)
            rows[0]['title'] = 'Concurrent inventory title'
            return rows

        with patch.object(self.client, 'list', side_effect=different_inventory), self.assertRaisesRegex(CanvasError, 'changed during inventory'):
            self.restore()
        self.assertEqual(self.writes(), [])
        self.setUp()
        data = self.restore('2')
        self.client.ignore_restore = True
        with self.assertRaisesRegex(CanvasError, 'may have succeeded'):
            self.execute(data, '2')
        self.assertEqual(len(self.writes()), 1)

    def test_optional_editor_projection_does_not_promote_contacts_or_require_names(self):
        self.client.detail_patch = {'edited_by': {'id': 8, 'name': None, 'display_name': [],
                                                'email': 'synthetic-private-editor@example.edu'}}
        self.assertEqual(self.read('1', editors=True)['page_revision']['edited_by'], {'id': 8})
        self.assertNotIn('synthetic-private', str(self.read('1', editors=True)))
        self.client.detail_patch = {'edited_by': {'id': True, 'email': 'synthetic-private-editor@example.edu'}}
        self.assertNotIn('edited_by', self.read('1')['page_revision'])
        with self.assertRaises(CanvasError):
            self.read('1', editors=True)

    def test_unavailable_context_native_denial_and_preflight_inventory_ambiguity_do_not_write(self):
        for values in ({'workflow_state': 'completed'}, {'workflow_state': 'deleted'},
                      {'concluded': True}, {'non_collaborative': True}, {'access_restricted_by_date': True}):
            self.setUp()
            self.client.context_patch = values
            with self.subTest(values=values), self.assertRaises(CanvasError):
                self.restore()
            self.assertEqual(self.writes(), [])
        self.setUp()
        self.client.pages[10]['url'] = self.client.pages[9]['url'] = self.client.front_url
        self.client.revisions[3]['url'] = self.client.front_url
        with self.assertRaisesRegex(CanvasError, 'ambiguous'):
            self.restore()
        self.assertEqual(self.writes(), [])
        self.setUp()
        data = self.restore()
        self.client.deny_write = True
        with self.assertRaises(CanvasError) as error:
            self.execute(data)
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(len(self.writes()), 1)

    def test_unverified_restores_are_not_retried_or_repaired_and_never_log_private_responses(self):
        for failure in ('ack', 'ignored', 'readback', 'permissions', 'account', 'front-race', 'metadata', 'title-collision'):
            self.setUp()
            data = self.restore()
            if failure == 'ack':
                self.client.ack_patch = {'body': 'synthetic-private-unverified'}
            elif failure == 'ignored':
                self.client.ignore_restore = True
            elif failure == 'readback':
                self.client.deny_after = True
            elif failure == 'permissions':
                self.client.changed_permission_after = True
            elif failure == 'account':
                self.client.changed_account_after = True
            elif failure == 'front-race':
                self.client.new_page_race = True
            elif failure == 'metadata':
                self.client.page_patch = {'published': False}
            else:
                self.client.ack_patch = {'title': 'Earlier-2'}
            with self.subTest(failure=failure), self.assertRaisesRegex(CanvasError, 'may have succeeded') as error:
                self.execute(data)
            self.assertNotIn('synthetic-private', str(error.exception))
            self.assertEqual(len(self.writes()), 1)

    def test_invalid_ids_ack_context_limits_and_flags_make_no_requests(self):
        for options in ({'page_id': '0'}, {'revision_id': 'latest'}, {'revision_id': '01'}, {'revision_id': '-1'},
                        {'context_type': 'user'}, {'acknowledge_shared': False}, {'acknowledge_front': 1},
                        {'max_pages': True}, {'max_pages': 0}, {'yes': True}, {'confirm': 'bad'}):
            self.setUp()
            values = {'page_id': '9', 'revision_id': '1', 'context_type': 'course', 'acknowledge_shared': True, **options}
            with self.subTest(options=options), self.assertRaises(CanvasError):
                restore(self.client, '123', **values)
            self.assertEqual(self.client.calls, [])
        with self.assertRaises(CanvasError):
            self.read(content=True)
        self.assertEqual(self.client.calls, [])

    def test_revision_commands_have_distinct_native_get_or_preview_write_classifications(self):
        for name in ('page-revisions', 'page-revision'):
            self.assertEqual(command_help(parser(), name)['safety'], 'Canvas GET (server-side effects possible)')
        self.assertEqual(command_help(parser(), 'page-restore')['safety'], 'Canvas writes (preview-first)')


if __name__ == '__main__':
    unittest.main()
