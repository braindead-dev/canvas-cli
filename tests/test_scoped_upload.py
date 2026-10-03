"""Exact-context file uploads; all records and storage targets are synthetic."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from canvas_pocket.client import CanvasError
from canvas_pocket.upload import prepare, upload


class ScopedClient:
    host = 'https://canvas.example.edu'

    def __init__(self, kind='group'):
        self.user_id = 7
        self.kind = kind
        self.context = {'id': 9, 'name': 'Synthetic shared files', 'workflow_state': 'available'}
        self.folder = {'id': 40, 'context_type': kind.title(), 'context_id': 7 if kind == 'user' else 9,
                       'name': 'Synthetic folder', 'parent_folder_id': None, 'for_submissions': False,
                       'private_field': 'synthetic-private-folder-data'}
        self.record = {'id': 777, 'folder_id': 40, 'size': 8, 'display_name': 'paper (1).txt',
                       'url': 'https://storage.example.edu/download?signature=synthetic-private-url'}
        self.scoped = None
        self.deny_upload = False
        self.calls = []

    def request(self, route, method='GET', body=None):
        self.calls.append((method, route, body))
        if route == '/api/v1/users/self/profile':
            return {'id': self.user_id}, ''
        if method == 'POST':
            if self.deny_upload:
                raise CanvasError('Canvas HTTP 403')
            return {'upload_url': 'https://storage.example.edu/upload', 'upload_params': {}}, ''
        if route == '/api/v1/files/777/create_success':
            return self.record, ''
        if '/folders/' in route:
            return self.folder, ''
        if route.endswith('/files/777'):
            return self.record if self.scoped is None else self.scoped, ''
        return self.context, ''


class ScopedUploadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / 'paper.txt'
        self.source.write_text('original')

    def options(self, kind='group', folder=None):
        return {'folder_id': folder} if kind == 'user' else {'context_type': kind, 'context_id': '9', 'folder_id': folder}

    def test_root_and_explicit_folder_previews_bind_exact_namespace(self):
        for kind in ('course', 'group', 'user'):
            for folder_id in ('40', None):
                if kind == 'user' and folder_id is None:
                    continue  # unchanged default personal upload is covered separately
                with self.subTest(kind=kind, folder=folder_id):
                    client = ScopedClient(kind)
                    preview = upload(client, self.source, 100, **self.options(kind, folder_id))
                    route = f'/api/v1/{kind}s/' + ('self' if kind == 'user' else '9')
                    self.assertEqual(preview['init_route'], route + '/files')
                    self.assertEqual(client.calls[-1][1], route + '/folders/' + (folder_id or 'root'))
                    self.assertEqual(preview['destination']['folder']['id'], 40)
                    self.assertEqual(preview['destination']['context_type'], kind)
                    self.assertNotIn('synthetic-private-folder-data', str(preview))
                    self.assertIn('visible to others', preview['destination']['warning'])
                    self.assertTrue(all(method == 'GET' for method, _, _ in client.calls))

    def test_all_contexts_use_exact_existing_folder_and_no_overwrite(self):
        for kind in ('course', 'group', 'user'):
            with self.subTest(kind=kind):
                client = ScopedClient(kind)
                options = self.options(kind, '40')
                preview = upload(client, self.source, 100, **options)
                with patch('canvas_pocket.upload._upload_to_storage', return_value='/api/v1/files/777/create_success') as storage:
                    result = upload(client, self.source, 100, yes=True, confirm=preview['confirm'], **options)
                posts = [call for call in client.calls if call[0] == 'POST']
                self.assertEqual(len(posts), 1)
                self.assertEqual(posts[0][1], preview['init_route'])
                self.assertEqual(posts[0][2], {'name': 'paper.txt', 'size': 8, 'content_type': 'text/plain',
                                              'on_duplicate': 'rename', 'parent_folder_id': 40})
                self.assertEqual(client.calls[-1][1], preview['init_route'] + '/777')
                storage.assert_called_once()
                self.assertEqual(result['uploaded_file_id'], 777)
                self.assertNotIn('synthetic-private-url', str(result))
                self.assertIn('no assignment submitted', result['note'])

    def test_invalid_context_combinations_and_ids_refused_before_reads(self):
        for options in ({'context_type': 'user', 'context_id': '9'}, {'context_type': 'group', 'context_id': True},
                        {'context_type': 'group', 'context_id': '09'}, {'context_id': '9'},
                        {'context_type': 'group', 'context_id': '9', 'assignment_id': '2'},
                        {'folder_id': '../40'}, {'folder_id': '40', 'assignment_id': '2'}):
            client = ScopedClient()
            with self.subTest(options=options), self.assertRaises(CanvasError):
                prepare(client, self.source, 100, **options)
            self.assertEqual(client.calls, [])

    def test_folder_context_identity_and_access_are_required(self):
        for changes in ({'id': True}, {'context_id': True}, {'context_id': 10}, {'context_type': 'Course'},
                        {'locked_for_user': True}, {'hidden_for_user': True}, {'for_submissions': True},
                        {'workflow_state': 'deleted'}, {'parent_folder_id': 39}):
            client = ScopedClient()
            client.folder.update(changes)
            with self.subTest(changes=changes), self.assertRaises(CanvasError):
                upload(client, self.source, 100, **self.options())
            self.assertTrue(all(method == 'GET' for method, _, _ in client.calls))
        client = ScopedClient()
        client.folder['id'] = 41
        with self.assertRaisesRegex(CanvasError, 'different upload folder'):
            upload(client, self.source, 100, **self.options(folder='40'))

    def test_context_identity_must_be_exact_and_available(self):
        for changes in ({'id': True}, {'id': 10}, {'workflow_state': 'deleted'}, {'workflow_state': 'unpublished'}):
            client = ScopedClient()
            client.context.update(changes)
            with self.subTest(changes=changes), self.assertRaises(CanvasError):
                upload(client, self.source, 100, **self.options())
            self.assertEqual(len(client.calls), 2)

    def test_account_context_and_folder_changes_invalidate_prior_preview(self):
        for change in ('account', 'context_name', 'context_state', 'folder_name', 'folder_lock', 'folder_parent'):
            client = ScopedClient()
            options = self.options(folder='40')
            preview = upload(client, self.source, 100, **options)
            if change == 'account':
                client.user_id = 8
            elif change == 'context_name':
                client.context['name'] = 'Synthetic renamed context'
            elif change == 'context_state':
                client.context['workflow_state'] = 'completed'
            else:
                client.folder[{'folder_name': 'name', 'folder_lock': 'lock_at', 'folder_parent': 'parent_folder_id'}[change]] = (
                    39 if change == 'folder_parent' else 'Synthetic changed value')
            with self.subTest(change=change), patch('canvas_pocket.upload._upload_to_storage') as storage:
                with self.assertRaisesRegex(CanvasError, 'Preview changed'):
                    upload(client, self.source, 100, yes=True, confirm=preview['confirm'], **options)
                storage.assert_not_called()
            self.assertTrue(all(method == 'GET' for method, _, _ in client.calls))

    def test_permission_denial_never_contacts_storage_or_falls_back(self):
        client = ScopedClient()
        options = self.options()
        preview = upload(client, self.source, 100, **options)
        client.deny_upload = True
        with patch('canvas_pocket.upload._upload_to_storage') as storage:
            with self.assertRaisesRegex(CanvasError, '403'):
                upload(client, self.source, 100, yes=True, confirm=preview['confirm'], **options)
            storage.assert_not_called()
        self.assertEqual([row[1] for row in client.calls if row[0] == 'POST'], ['/api/v1/groups/9/files'])

    def test_confirmation_and_scoped_metadata_mismatch_are_ambiguous_not_retried(self):
        changes = ({'folder_id': 41}, {'size': 9}, {'size': True}, {'display_name': None},
                   {'context_type': 'User'}, {'context_id': 10}, {'group_id': 10}, {'hidden_for_user': True})
        for phase in ('confirmation', 'scoped'):
            for change in changes:
                client = ScopedClient()
                options = self.options()
                preview = upload(client, self.source, 100, **options)
                if phase == 'confirmation':
                    client.record.update(change)
                else:
                    client.scoped = {**client.record, **change}
                with self.subTest(phase=phase, change=change), patch('canvas_pocket.upload._upload_to_storage',
                        return_value='/api/v1/files/777/create_success') as storage:
                    with self.assertRaisesRegex(CanvasError, 'may have succeeded') as caught:
                        upload(client, self.source, 100, yes=True, confirm=preview['confirm'], **options)
                    self.assertNotIn('synthetic-private-url', str(caught.exception))
                    storage.assert_called_once()
                self.assertEqual(len([call for call in client.calls if call[0] == 'POST']), 1)

    def test_scoped_read_identity_mismatch_and_boolean_confirmation_id_are_refused(self):
        for change in ('scoped', 'boolean'):
            client = ScopedClient()
            options = self.options()
            preview = upload(client, self.source, 100, **options)
            if change == 'scoped':
                client.scoped = {**client.record, 'id': 778}
            else:
                client.record['id'] = True
            with patch('canvas_pocket.upload._upload_to_storage', return_value='/api/v1/files/777/create_success'), self.assertRaises(CanvasError):
                upload(client, self.source, 100, yes=True, confirm=preview['confirm'], **options)
            self.assertEqual(len([call for call in client.calls if call[0] == 'POST']), 1)

    def test_confirmation_flags_and_invalid_limits_do_not_mutate(self):
        for flags in ({'yes': True}, {'confirm': 'wrong'}, {'max_bytes': True}, {'max_bytes': 0}):
            client = ScopedClient()
            with self.subTest(flags=flags), self.assertRaises(CanvasError):
                upload(client, self.source, **flags, **self.options())
            self.assertEqual(client.calls, [])
