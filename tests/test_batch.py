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
        client.request.return_value = ({'url': 'https://files.example.edu/signed', 'size': 30,
                                        'display_name': 'Read me.pdf'}, '')
        download.return_value = {'bytes': 30}
        with tempfile.TemporaryDirectory() as folder:
            preview = batch_download(client, '12', folder, 100, 2, 100)
            self.assertTrue(preview['dry_run'])
            self.assertEqual(preview['skipped_unavailable'], 1)
            self.assertEqual(preview['files'][0]['name'], '7-Read-me.pdf')
            self.assertTrue(preview['within_limits'])
            client.request.assert_not_called()
            download.assert_not_called()
            result = batch_download(client, '12', folder, 100, 2, 100,
                                    yes=True, confirm=preview['confirm'])
            self.assertEqual(result['bytes'], 30)
            download.assert_called_once_with('https://files.example.edu/signed',
                                             Path(folder).resolve() / '7-Read-me.pdf', 100)

    @patch('canvas_pocket.batch.linked_files')
    def test_limits_and_git_guard_fail_before_download(self, linked):
        linked.return_value = {'files': [{'id': 1, 'name': 'one', 'size': 101,
                                          'downloadable': True}], 'skipped_sources': []}
        with tempfile.TemporaryDirectory() as folder:
            client = Mock()
            preview = batch_download(client, '12', folder, 100, 1, 100)
            self.assertFalse(preview['within_limits'])
            self.assertEqual(len(preview['files']), 1)
            self.assertIn('--max-bytes', preview['limit_issues'][0])
            with self.assertRaises(CanvasError):
                batch_download(client, '12', folder, 100, 1, 100,
                               yes=True, confirm=preview['confirm'])
            client.request.assert_not_called()
            (Path(folder) / '.git').mkdir()
            with self.assertRaises(CanvasError):
                directory(folder)

    @patch('canvas_pocket.batch.linked_files')
    def test_preview_can_show_more_files_than_execution_limit(self, linked):
        linked.return_value = {'files': [
            {'id': 1, 'display_name': 'one.pdf', 'size': 10, 'downloadable': True},
            {'id': 2, 'display_name': 'two.pdf', 'size': 10, 'downloadable': True}],
            'skipped_sources': []}
        with tempfile.TemporaryDirectory() as folder:
            client = Mock()
            preview = batch_download(client, '12', folder, 100, 1, 100)
            self.assertFalse(preview['within_limits'])
            self.assertEqual(len(preview['files']), 2)
            self.assertIn('--max-files', preview['limit_issues'][0])
            with self.assertRaises(CanvasError):
                batch_download(client, '12', folder, 100, 1, 100,
                               yes=True, confirm=preview['confirm'])
            client.request.assert_not_called()

    @patch('canvas_pocket.batch.download')
    @patch('canvas_pocket.batch.linked_files')
    def test_download_requires_matching_unchanged_preview(self, linked, download):
        linked.return_value = {'files': [{'id': 1, 'display_name': 'one.pdf',
                                          'size': 10, 'downloadable': True}],
                               'skipped_sources': []}
        client = Mock()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(CanvasError, 'both --yes and --confirm'):
                batch_download(client, '12', folder, 100, 1, 100, yes=True)
            linked.assert_not_called()
            preview = batch_download(client, '12', folder, 100, 1, 100)
            linked.return_value['files'][0]['size'] = 11
            with self.assertRaisesRegex(CanvasError, 'preview changed'):
                batch_download(client, '12', folder, 100, 1, 100,
                               yes=True, confirm=preview['confirm'])
            download.assert_not_called()

    @patch('canvas_pocket.batch.download')
    @patch('canvas_pocket.batch.linked_files')
    def test_file_change_between_confirmation_and_transfer_is_refused(self, linked, download):
        linked.return_value = {'files': [{'id': 1, 'display_name': 'one.pdf',
                                          'size': 10, 'updated_at': 'before',
                                          'downloadable': True}], 'skipped_sources': []}
        client = Mock()
        client.request.return_value = ({'url': 'https://files.example.edu/signed',
                                        'display_name': 'one.pdf', 'size': 10,
                                        'updated_at': 'after'}, '')
        with tempfile.TemporaryDirectory() as folder:
            preview = batch_download(client, '12', folder, 100, 1, 100)
            with self.assertRaisesRegex(CanvasError, 'metadata changed'):
                batch_download(client, '12', folder, 100, 1, 100,
                               yes=True, confirm=preview['confirm'])
            download.assert_not_called()

    @patch('canvas_pocket.batch.download')
    @patch('canvas_pocket.batch.linked_files')
    def test_select_specific_discovered_files_without_expanding_batch_limits(self, linked, download):
        linked.return_value = {'files': [
            {'id': 1, 'display_name': 'one.pdf', 'size': 10, 'downloadable': True},
            {'id': 2, 'display_name': 'two.pdf', 'size': 10, 'downloadable': True},
            {'id': 3, 'display_name': 'locked.pdf', 'downloadable': False}],
            'skipped_sources': []}
        client = Mock()
        client.request.return_value = ({'url': 'https://files.example.edu/signed',
                                        'display_name': 'two.pdf', 'size': 10}, '')
        download.return_value = {'bytes': 10}
        with tempfile.TemporaryDirectory() as folder:
            all_files = batch_download(client, '12', folder, 100, 1, 100)
            self.assertFalse(all_files['within_limits'])
            selected = batch_download(client, '12', folder, 100, 1, 100, file_ids=['2'])
            self.assertTrue(selected['within_limits'])
            self.assertEqual([item['id'] for item in selected['files']], [2])
            self.assertEqual(selected['skipped_unavailable'], 1)
            self.assertEqual(selected['not_selected'], 1)
            self.assertNotEqual(all_files['confirm'], selected['confirm'])
            with self.assertRaisesRegex(CanvasError, 'not discovered'):
                batch_download(client, '12', folder, 100, 1, 100, file_ids=['999'])
            with self.assertRaisesRegex(CanvasError, 'not downloadable'):
                batch_download(client, '12', folder, 100, 1, 100, file_ids=['3'])
            with self.assertRaisesRegex(CanvasError, 'preview changed'):
                batch_download(client, '12', folder, 100, 1, 100, file_ids=['1'],
                               yes=True, confirm=selected['confirm'])
            result = batch_download(client, '12', folder, 100, 1, 100, file_ids=['2'],
                                    yes=True, confirm=selected['confirm'])
            self.assertEqual(result['saved'][0]['id'], 2)
            download.assert_called_once()


if __name__ == '__main__':
    unittest.main()
