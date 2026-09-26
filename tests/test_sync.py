import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from canvas_pocket.cli import brief
from canvas_pocket.client import CanvasError
from canvas_pocket.sync import sync_course


def snapshot(description):
    return {
        'schema_version': 1, 'origin': 'https://canvas.example.edu',
        'course_id': 12, 'captured_at': '2026-09-25T12:00:00Z',
        'complete': False, 'unavailable': {'pages': 'Canvas HTTP 404'},
        'course': {'id': 12},
        'assignments': [{'id': 1, 'name': 'Paper', 'description': description}],
        'modules': [], 'announcements': [],
        'pages': [{'url': 'intro', 'title': 'Welcome', 'body': description}],
    }


class SyncTests(unittest.TestCase):
    def test_baseline_then_private_field_level_diff(self):
        client = Mock(host='https://canvas.example.edu')
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'snapshots'
            with patch('canvas_pocket.sync.capture', side_effect=[snapshot('old private body'),
                                                                 snapshot('new private body')]):
                first = sync_course(client, '12', 100, directory)
                second = sync_course(client, '12', 100, directory)
            self.assertTrue(first['baseline'])
            self.assertFalse(second['baseline'])
            self.assertEqual(second['previous'], first['saved'])
            self.assertEqual(len(list(directory.glob('*.json'))), 2)
            self.assertEqual(os.stat(first['saved']).st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(Path(second['saved']).read_text())['pages'][0]['body'],
                             'new private body')
            self.assertEqual(second['diff']['changes']['assignments']['changed'][0]['fields'],
                             ['description'])
            self.assertEqual(second['diff']['observed_changes']['pages'][0]['fields'], ['body'])
            self.assertIn('1 change(s) observed in partial resources', brief(second))
            self.assertNotIn('private body', str(second))

    def test_refuses_git_destination_before_capture(self):
        client = Mock(host='https://canvas.example.edu')
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / '.git').mkdir()
            with patch('canvas_pocket.sync.capture') as capture:
                with self.assertRaises(CanvasError):
                    sync_course(client, '12', 100, Path(folder) / 'snapshots')
                capture.assert_not_called()

    def test_opt_in_file_index_is_forwarded_to_capture(self):
        client = Mock(host='https://canvas.example.edu')
        with tempfile.TemporaryDirectory() as folder:
            with patch('canvas_pocket.sync.capture', return_value=snapshot('synthetic')) as capture:
                sync_course(client, '12', 100, Path(folder), include_linked_files=True)
            capture.assert_called_once_with(client, '12', 100, include_linked_files=True)

    def test_invalid_previous_snapshot_is_not_silently_ignored(self):
        client = Mock(host='https://canvas.example.edu')
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            with patch('canvas_pocket.sync.capture', return_value=snapshot('first')):
                first = sync_course(client, '12', 100, directory)
            Path(first['saved']).write_text('not JSON')
            with patch('canvas_pocket.sync.capture') as capture:
                with self.assertRaises(CanvasError):
                    sync_course(client, '12', 100, directory)
                capture.assert_not_called()

    def test_failed_refresh_preserves_last_private_baseline(self):
        client = Mock(host='https://canvas.example.edu')
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            with patch('canvas_pocket.sync.capture', return_value=snapshot('baseline')):
                first = sync_course(client, '12', 100, directory)
            with (patch('canvas_pocket.sync.capture', side_effect=CanvasError('rate limited', status=429)),
                  self.assertRaises(CanvasError)):
                sync_course(client, '12', 100, directory)
            self.assertEqual([str(path.resolve()) for path in directory.glob('*.json')],
                             [first['saved']])


if __name__ == '__main__':
    unittest.main()
