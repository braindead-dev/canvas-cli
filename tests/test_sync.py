import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from canvas_cli.cli import brief
from canvas_cli.client import CanvasError
from canvas_cli.sync import sync_course


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
    def setUp(self):
        # Capture is mocked below; own-profile checks remain explicit and independent.
        self.account_patch = patch('canvas_cli.sync.account', side_effect=lambda client: {
            'origin': client.host, 'user_id': 7})
        self.account = self.account_patch.start()
        self.addCleanup(self.account_patch.stop)

    def test_baseline_then_private_field_level_diff(self):
        client = Mock(host='https://canvas.example.edu')
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'snapshots'
            with patch('canvas_cli.sync.capture', side_effect=[snapshot('old private body'),
                                                                 snapshot('new private body')]):
                first = sync_course(client, '12', 100, directory)
                second = sync_course(client, '12', 100, directory)
            self.assertTrue(first['baseline'])
            self.assertFalse(second['baseline'])
            self.assertEqual(second['previous'], first['saved'])
            self.assertEqual(len(list(directory.glob('*.json'))), 2)
            self.assertEqual(os.stat(first['saved']).st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(Path(first['saved']).read_text())['viewer_user_id'], 7)
            self.assertIn('-user-7-course-12-', Path(first['saved']).name)
            self.assertTrue(second['diff']['viewer_identity_verified'])
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
            with patch('canvas_cli.sync.capture') as capture:
                with self.assertRaises(CanvasError):
                    sync_course(client, '12', 100, Path(folder) / 'snapshots')
                capture.assert_not_called()
                self.account.assert_not_called()

    def test_other_viewers_and_legacy_files_are_preserved_but_never_automatic_baselines(self):
        client = Mock(host='https://canvas.example.edu')
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            origin_key = hashlib.sha256(client.host.encode()).hexdigest()[:12]
            legacy = directory / f'{origin_key}-course-12-99999999.json'
            legacy.write_text(json.dumps(snapshot('legacy private body')))
            legacy_bytes = legacy.read_bytes()
            with patch('canvas_cli.sync.capture', return_value=snapshot('current')):
                first = sync_course(client, '12', 100, directory)
                self.account.side_effect = lambda client: {'origin': client.host, 'user_id': 8}
                other = sync_course(client, '12', 100, directory)
                self.account.side_effect = lambda client: {'origin': client.host, 'user_id': 7}
                back = sync_course(client, '12', 100, directory)
            self.assertTrue(first['baseline'])
            self.assertTrue(other['baseline'])
            self.assertEqual(back['previous'], first['saved'])
            self.assertEqual(legacy.read_bytes(), legacy_bytes)
            self.assertEqual(len(list(directory.glob('*.json'))), 4)
            self.assertNotIn('legacy private body', str(back))

    def test_identity_changes_or_profile_failure_do_not_save_captured_content(self):
        client = Mock(host='https://canvas.example.edu')
        identity = {'origin': client.host, 'user_id': 7}
        for final in ({**identity, 'user_id': 8}, {**identity, 'origin': 'https://other.example.edu'},
                      CanvasError('Expired authentication', status=401)):
            with self.subTest(final=final), tempfile.TemporaryDirectory() as folder:
                self.account.side_effect = [identity, final]
                with (patch('canvas_cli.sync.capture', return_value=snapshot('private')),
                      self.assertRaises(CanvasError)):
                    sync_course(client, '12', 100, folder)
                self.assertEqual(list(Path(folder).glob('*.json')), [])

    def test_capture_must_match_context_and_does_not_mutate_source(self):
        client = Mock(host='https://canvas.example.edu')
        source = snapshot('synthetic')
        for difference in ({'origin': 'https://other.example.edu'}, {'course_id': 13},
                           {'course_id': True}, {'viewer_user_id': 8}, {'viewer_user_id': True}):
            with self.subTest(difference=difference), tempfile.TemporaryDirectory() as folder:
                with (patch('canvas_cli.sync.capture', return_value={**source, **difference}),
                      self.assertRaisesRegex(CanvasError, 'Capture context')):
                    sync_course(client, '12', 100, folder)
                self.assertEqual(list(Path(folder).glob('*.json')), [])
        with (tempfile.TemporaryDirectory() as folder,
              patch('canvas_cli.sync.capture', return_value=source)):
            sync_course(client, '12', 100, folder)
        self.assertNotIn('viewer_user_id', source)

    def test_namespaced_previous_snapshot_still_requires_exact_viewer_metadata(self):
        client = Mock(host='https://canvas.example.edu')
        with tempfile.TemporaryDirectory() as folder:
            with patch('canvas_cli.sync.capture', return_value=snapshot('baseline')):
                first = sync_course(client, '12', 100, folder)
            original = json.loads(Path(first['saved']).read_text())
            for viewer in (None, True, '7', 8):
                with self.subTest(viewer=viewer):
                    Path(first['saved']).write_text(json.dumps({**original, 'viewer_user_id': viewer}))
                    with patch('canvas_cli.sync.capture') as capture:
                        with self.assertRaisesRegex(CanvasError, 'different origin, viewer or course'):
                            sync_course(client, '12', 100, folder)
                        capture.assert_not_called()

    def test_invalid_course_and_destination_fail_before_account_access(self):
        client = Mock(host='https://canvas.example.edu')
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / 'new'
            for course in ('0', '012', '../12', '１２', 12, True):
                with self.subTest(course=course), self.assertRaises(CanvasError):
                    sync_course(client, course, 100, destination)
            self.assertFalse(destination.exists())
            destination.write_text('Synthetic existing file')
            with self.assertRaises(CanvasError):
                sync_course(client, '12', 100, destination)
            self.account.assert_not_called()

    def test_initial_auth_failure_does_not_create_destination(self):
        client = Mock(host='https://canvas.example.edu')
        self.account.side_effect = CanvasError('Expired authentication', status=401)
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / 'new'
            with patch('canvas_cli.sync.capture') as capture, self.assertRaises(CanvasError):
                sync_course(client, '12', 100, destination)
            capture.assert_not_called()
            self.assertFalse(destination.exists())

    def test_opt_in_file_index_is_forwarded_to_capture(self):
        client = Mock(host='https://canvas.example.edu')
        with tempfile.TemporaryDirectory() as folder:
            with patch('canvas_cli.sync.capture', return_value=snapshot('synthetic')) as capture:
                sync_course(client, '12', 100, Path(folder), include_linked_files=True)
            capture.assert_called_once_with(client, '12', 100, include_linked_files=True)

    def test_incremental_opt_in_receives_only_the_account_bound_baseline(self):
        client = Mock(host='https://canvas.example.edu')
        with (tempfile.TemporaryDirectory() as folder,
              patch('canvas_cli.sync.capture', return_value=snapshot('synthetic')) as capture):
            first = sync_course(client, '12', 100, Path(folder), incremental=True)
            cache = capture.call_args.kwargs['page_revalidation']
            self.assertEqual(cache.candidates, {})
            self.assertEqual(first['revalidation']['scope'], 'page-bodies-only')
            second = sync_course(client, '12', 100, Path(folder), incremental=True)
            self.assertEqual(second['previous'], first['saved'])
            self.account.side_effect = lambda client: {'origin': client.host, 'user_id': 8}
            other = sync_course(client, '12', 100, Path(folder), incremental=True)
            self.assertTrue(other['baseline'])
            self.assertEqual(capture.call_args.kwargs['page_revalidation'].candidates, {})

    def test_invalid_previous_snapshot_is_not_silently_ignored(self):
        client = Mock(host='https://canvas.example.edu')
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            with patch('canvas_cli.sync.capture', return_value=snapshot('first')):
                first = sync_course(client, '12', 100, directory)
            Path(first['saved']).write_text('not JSON')
            with patch('canvas_cli.sync.capture') as capture:
                with self.assertRaises(CanvasError):
                    sync_course(client, '12', 100, directory)
                capture.assert_not_called()

    def test_failed_refresh_preserves_last_private_baseline(self):
        client = Mock(host='https://canvas.example.edu')
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            with patch('canvas_cli.sync.capture', return_value=snapshot('baseline')):
                first = sync_course(client, '12', 100, directory)
            with (patch('canvas_cli.sync.capture', side_effect=CanvasError('rate limited', status=429)),
                  self.assertRaises(CanvasError)):
                sync_course(client, '12', 100, directory)
            self.assertEqual([str(path.resolve()) for path in directory.glob('*.json')],
                             [first['saved']])


if __name__ == '__main__':
    unittest.main()
