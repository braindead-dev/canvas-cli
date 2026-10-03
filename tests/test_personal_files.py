import unittest
from unittest.mock import Mock

from canvas_pocket.client import CanvasError
from canvas_pocket.personal_files import change_file, create_folder, folders


class PersonalFilesTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.profile = {'id': 7}
        self.file = {'id': 81, 'folder_id': 10, 'display_name': 'synthetic.txt', 'size': 20,
                     'updated_at': '2026-10-02T12:00:00Z', 'uuid': 'synthetic-private-verifier',
                     'url': 'https://storage.example/private?signature=synthetic'}
        self.source = {'id': 10, 'context_type': 'User', 'context_id': 7, 'name': 'Root',
                       'parent_folder_id': None, 'for_submissions': False, 'files_count': 1, 'folders_count': 1}
        self.target = {**self.source, 'id': 11, 'name': 'Notes', 'parent_folder_id': 10}
        self.siblings = []
        self.result = {**self.file, 'folder_id': 11}
        def request(route, method='GET', body=None):
            if method != 'GET': return self.result, ''
            return ({'/api/v1/users/self/profile': self.profile, '/api/v1/files/81': self.file,
                     '/api/v1/folders/10': self.source, '/api/v1/folders/11': self.target,
                     '/api/v1/users/self/folders/root': self.source}[route], '')
        self.client.request.side_effect = request
        self.client.list.side_effect = lambda *args: self.siblings

    def test_personal_root_and_folder_inventory_are_read_only_and_paginated(self):
        self.assertEqual(folders(self.client, root=True)['id'], 10)
        self.siblings = [self.source, self.target]
        self.assertEqual(folders(self.client, 4), self.siblings)
        self.client.list.assert_called_once_with('/api/v1/users/self/folders?per_page=100', 4)
        self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))

    def test_rename_and_move_preview_use_no_overwrite_and_omit_private_urls(self):
        preview = change_file(self.client, '81', name='revised.txt', destination='11')
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['body'], {'name': 'revised.txt', 'parent_folder_id': '11', 'on_duplicate': 'rename'})
        self.assertNotIn('url', preview['file'])
        self.assertNotIn('uuid', preview['file'])
        self.assertNotIn('synthetic-private-verifier', str(preview))
        result = change_file(self.client, '81', name='revised.txt', destination='11',
                             yes=True, confirm=preview['confirm'])
        self.assertEqual(result['personal_file']['id'], 81)
        self.client.request.assert_called_with('/api/v1/files/81', 'PUT', preview['body'])

    def test_copy_does_not_mutate_source_and_can_copy_a_readable_course_file(self):
        self.file['folder_id'] = 900  # Not an own folder: copy reads source metadata, never changes it.
        preview = change_file(self.client, '81', destination='11', copy=True)
        self.assertIsNone(preview['source_folder'])
        self.assertEqual(preview['body'], {'source_file_id': '81', 'on_duplicate': 'rename'})
        self.result = {**self.file, 'id': 82, 'folder_id': 11}
        result = change_file(self.client, '81', destination='11', copy=True, yes=True, confirm=preview['confirm'])
        self.assertTrue(result['copied'])
        self.client.request.assert_called_with('/api/v1/folders/11/copy_file', 'POST', preview['body'])

    def test_deletion_requires_permanent_acknowledgement_and_does_not_enable_replace(self):
        with self.assertRaisesRegex(CanvasError, '--permanent'):
            change_file(self.client, '81', delete=True)
        self.client.request.assert_not_called()
        preview = change_file(self.client, '81', delete=True, permanent=True)
        self.assertIn('irreversible', preview['effect'])
        self.assertIsNone(preview['body'])
        self.result = self.file
        result = change_file(self.client, '81', delete=True, permanent=True, yes=True, confirm=preview['confirm'])
        self.assertTrue(result['deleted'])
        self.client.request.assert_called_with('/api/v1/files/81', 'DELETE', None)

    def test_other_contexts_users_and_submission_folders_are_not_write_destinations(self):
        for fields in ({'context_type': 'Course'}, {'context_id': 99}, {'context_id': True},
                       {'for_submissions': True}, {'locked_for_user': True}, {'hidden_for_user': True}):
            self.setUp(); self.target.update(fields)
            with self.subTest(fields=fields), self.assertRaisesRegex(CanvasError, 'own accessible personal'):
                change_file(self.client, '81', destination='11')
            self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))
        self.setUp(); self.source['context_type'] = 'Course'
        with self.assertRaises(CanvasError): change_file(self.client, '81', name='New')
        with self.assertRaises(CanvasError): change_file(self.client, '81', delete=True, permanent=True)

    def test_file_destination_identity_content_and_name_changes_require_new_confirmation(self):
        for change in ('account', 'origin', 'file_size', 'file_uuid', 'folder_name', 'requested_name'):
            self.setUp()
            preview = change_file(self.client, '81', name='New', destination='11')
            if change == 'account':
                self.profile['id'] = self.source['context_id'] = self.target['context_id'] = 99
            if change == 'origin': self.client.host = 'https://other.example.edu'
            if change == 'file_size': self.file['size'] = 21
            if change == 'file_uuid': self.file['uuid'] = 'changed-private-verifier'
            if change == 'folder_name': self.target['name'] = 'Changed'
            self.client.request.reset_mock()
            with self.subTest(change=change), self.assertRaisesRegex(CanvasError, 'Preview changed'):
                change_file(self.client, '81', name='Other' if change == 'requested_name' else 'New',
                            destination='11', yes=True, confirm=preview['confirm'])
            self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))

    def test_malformed_file_identity_size_and_access_are_refused(self):
        for fields in ({'id': True}, {'id': 82}, {'size': True}, {'size': -1},
                       {'locked_for_user': True}, {'hidden_for_user': True}, {'folder_id': None}):
            self.setUp(); self.file.update(fields)
            with self.subTest(fields=fields), self.assertRaises(CanvasError):
                change_file(self.client, '81', name='New')

    def test_input_errors_and_unpaired_confirmation_make_no_requests(self):
        for kwargs in ({}, {'name': '..'}, {'name': 'a/b'}, {'name': 'a\\b'}, {'name': 'a\n'},
                       {'name': 'x' * 256}, {'name': 'New', 'yes': True}, {'copy': True},
                       {'copy': True, 'destination': '11', 'name': 'New'},
                       {'delete': True, 'permanent': True, 'name': 'New'}, {'name': 'New', 'permanent': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                change_file(self.client, '81', **kwargs)
        for file_id in ('0', '081', '../81'):
            with self.assertRaises(CanvasError): change_file(self.client, file_id, name='New')
        self.client.request.assert_not_called()

    def test_ambiguous_file_write_acknowledgement_is_not_retried(self):
        preview = change_file(self.client, '81', destination='11')
        for result in (None, {'id': True}, {**self.file, 'id': 99}, {**self.file, 'folder_id': 99}):
            self.result = result; self.client.request.reset_mock()
            with self.subTest(result=result), self.assertRaisesRegex(CanvasError, 'verify in Canvas'):
                change_file(self.client, '81', destination='11', yes=True, confirm=preview['confirm'])
            self.assertEqual(sum(len(call.args) > 1 for call in self.client.request.call_args_list), 1)

    def test_folder_creation_binds_parent_and_siblings_and_creates_one_child(self):
        preview = create_folder(self.client, '11', 'Private Notes', max_pages=3)
        self.assertEqual(preview['body'], {'name': 'Private Notes'})
        self.client.list.assert_called_with('/api/v1/folders/11/folders?per_page=100', 3)
        self.result = {**self.target, 'id': 12, 'name': 'Private Notes', 'parent_folder_id': 11}
        result = create_folder(self.client, '11', 'Private Notes', max_pages=3, yes=True, confirm=preview['confirm'])
        self.assertEqual(result['personal_folder']['id'], 12)
        self.client.request.assert_called_with('/api/v1/folders/11/folders', 'POST', {'name': 'Private Notes'})
        self.siblings = [{'id': 15, 'name': 'Changed sibling'}]
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            create_folder(self.client, '11', 'Private Notes', max_pages=3, yes=True, confirm=preview['confirm'])

    def test_folder_creation_refuses_duplicate_and_wrong_result(self):
        self.siblings = [{'id': 12, 'name': 'Notes'}]
        with self.assertRaisesRegex(CanvasError, 'already exists'):
            create_folder(self.client, '11', 'Notes')
        self.siblings = []
        preview = create_folder(self.client, '11', 'Notes')
        for result in (None, self.target, {**self.target, 'id': 12, 'parent_folder_id': 99}):
            self.result = result
            with self.subTest(result=result), self.assertRaisesRegex(CanvasError, 'verify in Canvas'):
                create_folder(self.client, '11', 'Notes', yes=True, confirm=preview['confirm'])


if __name__ == '__main__': unittest.main()
