import unittest
from unittest.mock import Mock

from canvas_cli.client import CanvasError
from canvas_cli.group_content import (
    base,
    file_metadata,
    listing,
    page,
    quota,
    resolve_folder_path,
    root,
)


class GroupContentTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.group = {'id': 11, 'name': 'Synthetic group'}
        self.folder = {'id': 95, 'context_type': 'Group', 'context_id': 11, 'name': 'Group files',
                       'parent_folder_id': None, 'files_count': 1, 'folders_count': 0}
        self.client.request.return_value = (self.group, '')

    def test_group_files_are_paginated_metadata_without_signed_urls_or_unknown_private_fields(self):
        self.client.list.return_value = [{'id': 91, 'folder_id': 95, 'display_name': 'Synthetic group file',
                                          'size': 20, 'hidden_for_user': False,
                                          'url': 'https://storage.example.edu/file?token=secret',
                                          'doc_preview_url': 'private viewer session', 'user': {'name': 'Private uploader'}}]
        result = listing(self.client, '11', 'files', 2)
        self.assertEqual(result['group_id'], 11)
        self.assertEqual(result['items'][0]['size'], 20)
        self.assertTrue(result['complete_for_endpoint'])
        for private in ('secret', 'private viewer session', 'Private uploader'):
            self.assertNotIn(private, str(result))
        self.client.list.assert_called_once_with('/api/v1/groups/11/files?per_page=100', 2)
        self.client.request.assert_called_once_with('/api/v1/groups/11')

    def test_group_folders_validate_exact_context_not_only_folder_id(self):
        self.client.list.return_value = [self.folder]
        self.assertEqual(listing(self.client, '11', 'folders')['items'][0]['context_type'], 'Group')
        for row in ({**self.folder, 'context_type': 'Course'}, {**self.folder, 'context_id': 12},
                    {**self.folder, 'context_id': '11'}, {**self.folder, 'context_id': True},
                    {**self.folder, 'id': True}):
            self.client.list.return_value = [row]
            with self.subTest(row=row), self.assertRaises(CanvasError):
                listing(self.client, '11', 'folders')

    def test_group_page_index_skips_unpublished_locked_pages_and_never_dumps_bodies(self):
        self.client.list.return_value = [{'url': 'welcome', 'page_id': 1, 'title': 'Welcome', 'published': True,
                                          'body': 'Private page body'},
                                         {'url': 'draft', 'published': False, 'title': 'Hidden draft'},
                                         {'url': 'locked', 'published': True, 'locked_for_user': True}]
        result = listing(self.client, '11', 'pages')
        self.assertEqual([row['url'] for row in result['items']], ['welcome'])
        self.assertNotIn('Private page body', str(result))
        self.assertNotIn('Hidden draft', str(result))

    def test_tabs_are_only_visible_paths_and_are_not_opened(self):
        self.client.list.return_value = [
            {'id': 'home', 'label': 'Home', 'html_url': '/groups/11', 'type': 'internal'},
            {'id': 'hidden', 'label': 'Not visible', 'hidden': True},
            {'id': 'none', 'label': 'Unavailable', 'visibility': 'none'},
            {'id': 'external', 'label': 'External tool', 'html_url': 'https://tool.example.edu/?access_token=secret'}]
        result = listing(self.client, '11', 'tabs')
        self.assertEqual([row['id'] for row in result['items']], ['home', 'external'])
        self.assertNotIn('secret', str(result))
        self.client.request.assert_called_once_with('/api/v1/groups/11')

    def test_duplicate_invalid_or_foreign_context_content_is_not_returned(self):
        samples = {'files': {'id': 91}, 'folders': self.folder, 'pages': {'url': 'welcome'}, 'tabs': {'id': 'home'}}
        for resource, row in samples.items():
            self.client.list.return_value = [row, row]
            with self.subTest(resource=resource), self.assertRaisesRegex(CanvasError, 'duplicate'):
                listing(self.client, '11', resource)
            self.client.list.return_value = [[]]
            with self.assertRaises(CanvasError):
                listing(self.client, '11', resource)
        self.client.request.return_value = ({'id': 12}, '')
        self.client.list.reset_mock()
        with self.assertRaisesRegex(CanvasError, 'different content context'):
            listing(self.client, '11', 'files')
        self.client.list.assert_not_called()

    def test_group_page_full_read_checks_slug_or_numeric_id_and_redacts_credentials(self):
        record = {'url': 'welcome', 'page_id': 31, 'published': True,
                  'body': '<p>Synthetic group page</p>', 'secure_params': 'private opaque verifier'}
        for key, route in (('welcome', '/pages/welcome'), ('31', '/pages/31'), (None, '/front_page')):
            self.client.request.side_effect = [(self.group, ''), (record, '')]
            result = page(self.client, '11', key)
            self.assertEqual(result['body'], record['body'])
            self.assertNotIn('private opaque verifier', str(result))
            self.client.request.assert_called_with('/api/v1/groups/11' + route)
        for changes in ({'url': 'different'}, {'page_id': 32}, {'published': False}, {'locked_for_user': True}):
            self.client.request.side_effect = [(self.group, ''), ({**record, **changes}, '')]
            with self.subTest(changes=changes), self.assertRaises(CanvasError):
                page(self.client, '11', '31' if 'page_id' in changes else 'welcome')

    def test_invalid_context_resource_and_page_paths_fail_before_network(self):
        for value in ('0', '01', '١', '../11', None, True):
            with self.subTest(value=value), self.assertRaises(CanvasError):
                listing(self.client, value, 'files')
        for resource in ('modules', 'assignments', 'users'):
            with self.assertRaises(CanvasError):
                listing(self.client, '11', resource)
        for key in ('', '..', '../other', 'http://example.edu', 'bad\\path', 'bad\nkey'):
            with self.assertRaises(CanvasError):
                page(self.client, '11', key)
        with self.assertRaises(CanvasError):
            base('11', 'account')
        self.client.request.assert_not_called()
        self.client.list.assert_not_called()

    def test_numeric_slug_precedes_numeric_id_and_explicit_page_id_disambiguates(self):
        colliding = {'url': '31', 'page_id': 32, 'published': True, 'body': '<p>Numeric slug</p>'}
        self.client.request.side_effect = [(self.group, ''), (colliding, '')]
        self.assertEqual(page(self.client, '11', '31')['page_id'], 32)
        self.client.request.side_effect = [(self.group, ''), (colliding, '')]
        with self.assertRaisesRegex(CanvasError, 'different group page'):
            page(self.client, '11', 'page_id:31')
        expected = {'url': 'welcome', 'page_id': 31, 'published': True}
        self.client.request.side_effect = [(self.group, ''), (expected, '')]
        self.assertEqual(page(self.client, '11', 'page_id:31')['page_id'], 31)
        self.client.request.assert_called_with('/api/v1/groups/11/pages/page_id%3A31')
        self.client.request.reset_mock()
        for key in ('page_id:', 'page_id:0', 'page_id:01', 'page_id:١'):
            with self.assertRaises(CanvasError):
                page(self.client, '11', key)
        self.client.request.assert_not_called()

    def test_root_folder_checks_native_context_and_root_identity(self):
        self.client.request.side_effect = [(self.group, ''), (self.folder, '')]
        result = root(self.client, '11', 'group')
        self.assertEqual(result['root_folder']['id'], 95)
        self.assertIn('materialize', result['note'])
        self.client.request.assert_called_with('/api/v1/groups/11/folders/root')
        for row in ({**self.folder, 'parent_folder_id': 94}, {**self.folder, 'context_type': 'Course'}):
            self.client.request.side_effect = [(self.group, ''), (row, '')]
            with self.assertRaises(CanvasError):
                root(self.client, '11', 'group')

    def test_folder_path_encodes_native_relative_names_and_returns_exact_chain(self):
        children = [{**self.folder, 'id': 96, 'name': 'Week 1', 'parent_folder_id': 95},
                    {**self.folder, 'id': 97, 'name': 'Résumé % notes', 'parent_folder_id': 96,
                     'private_field': 'synthetic-private-folder-data'}]
        self.client.request.side_effect = [(self.group, ''), ([self.folder, *children], '')]
        result = resolve_folder_path(self.client, '11', 'group', 'Week 1/Résumé % notes')
        self.client.request.assert_called_with('/api/v1/groups/11/folders/by_path/Week%201/R%C3%A9sum%C3%A9%20%25%20notes')
        self.assertEqual(result['folder_id'], 97)
        self.assertEqual([row['id'] for row in result['folders']], [95, 96, 97])
        self.assertTrue(result['complete_for_path'])
        self.assertIn('materialize', result['note'])
        self.assertNotIn('synthetic-private-folder-data', str(result))

    def test_empty_folder_path_resolves_only_native_root_in_each_namespace(self):
        for kind, item in (('course', '101'), ('group', '11'), ('user', '7')):
            record = {**self.folder, 'context_type': kind.title(), 'context_id': int(item)}
            self.client.request.side_effect = [({'id': int(item)}, ''), ([record], '')]
            result = resolve_folder_path(self.client, item, kind)
            self.assertEqual(result['folders'], [record])
            prefix = '/api/v1/users/self' if kind == 'user' else f'/api/v1/{kind}s/{item}'
            self.client.request.assert_called_with(prefix + '/folders/by_path')

    def test_invalid_relative_paths_fail_before_canvas_access(self):
        for path in (None, True, '/Week 1', 'Week 1/', 'Week 1//Readings', '.', '..', 'Week 1/../Readings',
                     'bad\\path', 'bad\npath', 'https://canvas.example.edu/folders/1'):
            self.client.request.reset_mock()
            with self.subTest(path=path), self.assertRaises(CanvasError):
                resolve_folder_path(self.client, '11', 'group', path)
            self.client.request.assert_not_called()

    def test_folder_path_rejects_missing_extra_foreign_or_inconsistent_hierarchy(self):
        child = {**self.folder, 'id': 96, 'name': 'Readings', 'parent_folder_id': 95}
        records = ([], [self.folder], [self.folder, child, child], {}, [self.folder, self.folder],
                   [{**self.folder, 'parent_folder_id': 94}, child],
                   [self.folder, {**child, 'parent_folder_id': True}],
                   [self.folder, {**child, 'parent_folder_id': 94}],
                   [self.folder, {**child, 'name': 'Other'}],
                   [self.folder, {**child, 'context_type': 'User'}],
                   [self.folder, {**child, 'hidden_for_user': True}],
                   [self.folder, {**child, 'locked_for_user': True}],
                   [self.folder, {**child, 'workflow_state': 'deleted'}],
                   [self.folder, {key: value for key, value in child.items() if key != 'parent_folder_id'}])
        for rows in records:
            self.client.request.side_effect = [(self.group, ''), (rows, '')]
            with self.subTest(rows=rows), self.assertRaises(CanvasError):
                resolve_folder_path(self.client, '11', 'group', 'Readings')
        self.client.request.side_effect = [(self.group, ''), ([self.folder, child], '</api/v1/other>; rel="next"')]
        with self.assertRaisesRegex(CanvasError, 'incomplete'):
            resolve_folder_path(self.client, '11', 'group', 'Readings')

    def test_folder_path_does_not_guess_other_user_storage_or_mask_access_failure(self):
        self.client.request.side_effect = [({'id': 7}, '')]
        with self.assertRaisesRegex(CanvasError, 'signed-in user'):
            resolve_folder_path(self.client, '8', 'user', 'Readings')
        self.client.request.reset_mock()
        self.client.request.side_effect = [(self.group, ''), CanvasError('Native path not found', status=404)]
        with self.assertRaisesRegex(CanvasError, 'not found') as caught:
            resolve_folder_path(self.client, '11', 'group', 'Readings')
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(len(self.client.request.call_args_list), 2)

    def test_quota_reads_native_bytes_for_course_group_or_verified_own_user(self):
        for context, item, native in (('course', '101', '/api/v1/courses/101'),
                                      ('group', '11', '/api/v1/groups/11'), ('user', '7', '/api/v1/users/self')):
            self.client.request.reset_mock()
            self.client.request.side_effect = [({'id': int(item), 'name': 'Synthetic context'}, ''),
                                               ({'quota': 100, 'quota_used': 30, 'secret_field': 'private'}, '')]
            result = quota(self.client, item, context)
            self.assertEqual(result['remaining_bytes'], 70)
            self.assertFalse(result['over_quota'])
            self.assertNotIn('secret_field', str(result))
            self.client.request.assert_called_with(native + '/files/quota')
        self.client.request.side_effect = [(self.group, ''), ({'quota': 100, 'quota_used': 101}, '')]
        result = quota(self.client, '11', 'group')
        self.assertTrue(result['over_quota'])
        self.assertEqual(result['remaining_bytes'], 0)

    def test_other_users_and_invalid_quota_values_are_refused(self):
        self.client.request.reset_mock()
        self.client.request.side_effect = [({'id': 7}, '')]
        with self.assertRaisesRegex(CanvasError, 'signed-in user'):
            quota(self.client, '8', 'user')
        self.client.request.assert_called_once_with('/api/v1/users/self/profile')
        for record in ([], {}, {'quota': True, 'quota_used': 0}, {'quota': 10, 'quota_used': -1},
                       {'quota': 10, 'quota_used': '0'}, {'quota': None, 'quota_used': 0}):
            self.client.request.side_effect = [(self.group, ''), (record, '')]
            with self.subTest(record=record), self.assertRaisesRegex(CanvasError, 'quota'):
                quota(self.client, '11', 'group')

    def test_download_metadata_uses_the_scoped_group_file_not_global_id_fallback(self):
        record = {'id': 91, 'url': 'https://storage.example.edu/private-download', 'size': 20}
        self.client.request.side_effect = [(self.group, ''), (record, '')]
        self.assertEqual(file_metadata(self.client, '11', '91'), record)
        self.client.request.assert_called_with('/api/v1/groups/11/files/91')
        for patch in ({'id': 92}, {'hidden_for_user': True}, {'locked_for_user': True},
                      {'workflow_state': 'deleted'}, {'url': None}, {'url': []}):
            self.client.request.side_effect = [(self.group, ''), ({**record, **patch}, '')]
            with self.subTest(patch=patch), self.assertRaises(CanvasError):
                file_metadata(self.client, '11', '91')

    def test_access_rate_limit_and_page_cap_errors_are_not_empty_success(self):
        self.client.list.side_effect = CanvasError('Page cap reached')
        with self.assertRaisesRegex(CanvasError, 'Page cap'):
            listing(self.client, '11', 'files')
        self.client.request.side_effect = CanvasError('Rate limit', status=429)
        with self.assertRaises(CanvasError) as error:
            listing(self.client, '11', 'pages')
        self.assertEqual(error.exception.status, 429)

    def test_known_foreign_group_associations_fail_before_body_or_download_output(self):
        record = {'id': 91, 'url': 'welcome', 'page_id': 31, 'published': True, 'body': 'private body'}
        for patch in ({'group_id': 12}, {'context_id': 12}, {'context_type': 'Course'}, {'group_id': True}):
            with self.subTest(patch=patch):
                bad = {**record, **patch}
                for resource in ('files', 'pages'):
                    self.client.request.side_effect = None
                    self.client.request.return_value = (self.group, '')
                    self.client.list.return_value = [bad]
                    with self.assertRaisesRegex(CanvasError, 'outside the requested group'):
                        listing(self.client, '11', resource)
                self.client.request.side_effect = [(self.group, ''), (bad, '')]
                with self.assertRaisesRegex(CanvasError, 'outside the requested group'):
                    page(self.client, '11', 'welcome')
                self.client.request.side_effect = [(self.group, ''), (bad, '')]
                with self.assertRaisesRegex(CanvasError, 'outside the requested group'):
                    file_metadata(self.client, '11', '91')


if __name__ == '__main__':
    unittest.main()
