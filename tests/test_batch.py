import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from canvas_pocket.batch import batch_download, directory, safe_filename
from canvas_pocket.client import CanvasError


class BatchTests(unittest.TestCase):
    def test_safe_name_ignores_server_path(self):
        self.assertEqual(safe_filename(42, '../../private\\syllabus (1).pdf'),
                         '42-syllabus-1.pdf')

    @patch('canvas_pocket.batch.download')
    @patch('canvas_pocket.batch.linked_files')
    def test_preview_then_bounded_download(self, linked, download):
        linked.return_value = {'files': [{'id': 7, 'display_name': 'Read me.pdf',
                                          'size': 30, 'downloadable': True},
                                         {'id': 8, 'downloadable': False}],
                               'skipped_sources': ['files tab']}
        client = Mock()
        client.request.return_value = ({'url': 'https://files.example.edu/signed', 'size': 30}, '')
        download.return_value = {'bytes': 30}
        with tempfile.TemporaryDirectory() as folder:
            preview = batch_download(client, '12', folder, 100, 2, 100)
            self.assertTrue(preview['dry_run'])
            self.assertEqual(preview['skipped_unavailable'], 1)
            self.assertEqual(preview['files'][0]['name'], '7-Read-me.pdf')
            client.request.assert_not_called()
            download.assert_not_called()
            result = batch_download(client, '12', folder, 100, 2, 100, yes=True)
            self.assertEqual(result['bytes'], 30)
            download.assert_called_once_with('https://files.example.edu/signed',
                                             Path(folder).resolve() / '7-Read-me.pdf', 100)

    @patch('canvas_pocket.batch.linked_files')
    def test_limits_and_git_guard_fail_before_download(self, linked):
        linked.return_value = {'files': [{'id': 1, 'name': 'one', 'size': 101,
                                          'downloadable': True}], 'skipped_sources': []}
        with tempfile.TemporaryDirectory() as folder:
            client = Mock()
            with self.assertRaises(CanvasError):
                batch_download(client, '12', folder, 100, 1, 100, yes=True)
            client.request.assert_not_called()
            (Path(folder) / '.git').mkdir()
            with self.assertRaises(CanvasError):
                directory(folder)


if __name__ == '__main__':
    unittest.main()
