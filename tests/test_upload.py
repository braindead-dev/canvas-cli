"""Upload validation tests; no real Canvas or storage writes."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from canvas_pocket.client import CanvasError
from canvas_pocket.upload import _upload_to_storage, prepare, upload


class FakeClient:
    def __init__(self, assignment=None):
        self.host = 'https://canvas.example.edu'
        self.user_id = 7
        self.assignment = assignment
        self.calls = []

    def request(self, route, method='GET', body=None):
        self.calls.append((method, route, body))
        if route == '/api/v1/users/self/profile':
            return {'id': self.user_id}, ''
        return self.assignment, ''


class UploadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / 'paper.txt'
        self.source.write_text('original')
        self.assignment = {'id': 2, 'course_id': 1, 'name': 'Paper',
                           'published': True, 'locked_for_user': False,
                           'submission_types': ['online_upload'],
                           'allowed_extensions': ['txt']}

    def test_changed_file_refuses_before_canvas_write(self):
        client = FakeClient(self.assignment)
        _, digest = prepare(client, self.source, 100, '1', '2')
        self.source.write_text('modified')
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            upload(client, self.source, 100, '1', '2', True, digest)
        self.assertTrue(all(method == 'GET' for method, _, _ in client.calls))

    def test_rejects_ineligible_assignment_and_extension(self):
        for change in ({'published': False}, {'locked_for_user': True},
                       {'submission_types': ['online_text_entry']},
                       {'allowed_extensions': ['pdf']}, {'id': 3}):
            client = FakeClient({**self.assignment, **change})
            with self.assertRaises(CanvasError):
                prepare(client, self.source, 100, '1', '2')

    def test_refuses_symlink_and_oversized_file(self):
        link = Path(self.tmp.name) / 'link.txt'
        link.symlink_to(self.source)
        for source, limit in ((link, 100), (self.source, 2)):
            with self.assertRaises(CanvasError):
                prepare(FakeClient(), source, limit)

    def test_bad_storage_targets_fail_before_network(self):
        with self.source.open('rb') as stream:
            for url, params in (('http://example.org/upload', {}),
                                ('https://user:pass@example.org/upload', {}),
                                ('https://example.org/upload', {'file': 'bad'}),
                                ('https://example.org/upload', ['not', 'a', 'dict'])):
                with self.assertRaisesRegex(CanvasError, 'unsafe|unsupported'):
                    _upload_to_storage(url, params, stream, 'paper.txt', 'text/plain')

    def test_staged_bytes_are_exactly_previewed_bytes(self):
        _, digest = prepare(FakeClient(), self.source, 100)
        client = Mock(host='https://canvas.example.edu')
        client.request.side_effect = [
            ({'id': 7}, ''),
            ({'upload_url': 'https://storage.example.org/upload', 'upload_params': {}}, ''),
            ({'id': 99}, ''),
        ]
        def inspect_storage(url, params, staged, name, content_type):
            self.assertEqual(staged.read(), b'original')
            self.assertEqual(name, 'paper.txt')
            return '/api/v1/files/99/create_success'
        with patch('canvas_pocket.upload._upload_to_storage', side_effect=inspect_storage):
            result = upload(client, self.source, 100, yes=True, confirm=digest)
        self.assertEqual(result['uploaded_file_id'], 99)
        self.assertEqual(client.request.call_args_list[1].args[1], 'POST')
        self.assertEqual(client.request.call_args_list[1].args[2]['on_duplicate'], 'rename')

    def test_mutation_after_fresh_preview_is_caught_before_canvas_post(self):
        from canvas_pocket.upload import prepare as real_prepare
        _, digest = real_prepare(FakeClient(), self.source, 100)
        def mutate_after_prepare(*args):
            result = real_prepare(*args)
            self.source.write_text('changed!')
            return result
        client = Mock(host='https://canvas.example.edu')
        client.request.return_value = ({'id': 7}, '')
        with (patch('canvas_pocket.upload.prepare', side_effect=mutate_after_prepare),
              self.assertRaisesRegex(CanvasError, 'Upload file changed')):
            upload(client, self.source, 100, yes=True, confirm=digest)
        client.request.assert_called_once_with('/api/v1/users/self/profile')

    def test_upload_account_change_is_refused_before_storage_or_post(self):
        client = FakeClient()
        _, digest = prepare(client, self.source, 100)
        client.user_id = 99
        with (patch('canvas_pocket.upload._upload_to_storage') as storage,
              self.assertRaisesRegex(CanvasError, 'Preview changed')):
            upload(client, self.source, 100, yes=True, confirm=digest)
        storage.assert_not_called()
        self.assertTrue(all(method == 'GET' for method, _, _ in client.calls))

    def test_storage_failure_modes_do_not_log_signed_url(self):
        signed = 'https://storage.example.org/upload?signature=private'
        with self.source.open('rb') as stream:
            for status, location in ((500, None), (201, None)):
                response = Mock(status_code=status, headers={})
                if location:
                    response.headers['Location'] = location
                with patch('canvas_pocket.upload.httpx.Client') as client:
                    client.return_value.__enter__.return_value.post.return_value = response
                    with self.assertRaises(CanvasError) as caught:
                        _upload_to_storage(signed, {}, stream, 'paper.txt', 'text/plain')
                self.assertNotIn('signature=private', str(caught.exception))
            with patch('canvas_pocket.upload.httpx.Client') as client:
                client.return_value.__enter__.return_value.post.side_effect = httpx.ConnectError('secret')
                with self.assertRaisesRegex(CanvasError, 'outcome uncertain') as caught:
                    _upload_to_storage(signed, {}, stream, 'paper.txt', 'text/plain')
            self.assertNotIn('secret', str(caught.exception))
