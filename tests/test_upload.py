"""Upload validation tests; no real Canvas or storage writes."""

from pathlib import Path
import tempfile
import unittest

from canvas_pocket.client import CanvasError
from canvas_pocket.upload import prepare, upload, _upload_to_storage


class FakeClient:
    def __init__(self, assignment=None):
        self.assignment = assignment
        self.calls = []

    def request(self, route, method='GET', body=None):
        self.calls.append((method, route, body))
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
