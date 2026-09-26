import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from canvas_pocket.cli import parser, run
from canvas_pocket.client import CanvasError
from canvas_pocket.snapshot import capture, redact, save_private, validate_destination
from canvas_pocket.snapshot_diff import compare, read


class SnapshotTests(unittest.TestCase):
    def test_secret_fields_and_signed_queries_are_removed(self):
        source = {'secure_params': 'jwt-secret', 'nested': [
            {'access_token': 'private',
             'url': 'https://files.example.edu/item?wrap=1&verifier=secret&X-Amz-Signature=private'}]}
        result = redact(source)
        self.assertNotIn('secure_params', result)
        self.assertNotIn('access_token', result['nested'][0])
        self.assertEqual(result['nested'][0]['url'], 'https://files.example.edu/item?wrap=1')
        html = '<a href="https://files.example.edu/item?wrap=1&amp;X-Amz-Signature=private">Open</a>'
        self.assertNotIn('private', redact(html))
        self.assertNotIn('X-Amz-Signature', redact(html))
        self.assertIn('href="https://files.example.edu/item"', redact(html))
        self.assertEqual(redact('https://example.edu/page?visible=1'),
                         'https://example.edu/page?visible=1')

    def test_capture_records_partial_access_and_skips_unpublished_pages(self):
        client = Mock(host='https://canvas.example.edu')
        def request(route):
            if route == '/api/v1/courses/12?include[]=syllabus_body':
                return {'id': 12, 'syllabus_body': '<p>Public to enrolled students</p>'}, ''
            if route == '/api/v1/courses/12/pages/welcome':
                return {'url': 'welcome', 'published': True, 'body': '<p>Hello</p>'}, ''
            raise AssertionError(route)
        def listing(route, max_pages):
            if route.endswith('/assignments?per_page=100'):
                return [{'id': 3}, {'id': 30, 'published': False}]
            if route.endswith('/modules?per_page=100'):
                return [{'id': 4, 'name': 'Week 1'},
                        {'id': 40, 'name': 'Unpublished', 'published': False},
                        {'id': 41, 'name': 'Locked', 'state': 'locked'}]
            if route.endswith('/modules/4/items?per_page=100'):
                return [{'id': 5, 'title': 'Welcome'},
                        {'id': 50, 'title': 'Draft', 'published': False},
                        {'id': 51, 'title': 'Locked', 'locked_for_user': True}]
            if route.endswith('/pages?per_page=100'):
                return [{'url': 'welcome', 'published': True},
                        {'url': 'draft', 'published': False},
                        {'url': 'locked', 'locked_for_user': True}]
            if route.endswith('only_announcements=true'):
                raise CanvasError('Canvas denied access', status=403)
            if route.endswith('only_announcements=false'):
                return [{'id': 8, 'title': 'Visible prompt', 'message': 'Discuss this', 'published': True},
                        {'id': 9, 'title': 'Hidden prompt', 'published': False},
                        {'id': 10, 'title': 'Locked prompt', 'locked_for_user': True}]
            raise AssertionError(route)
        client.request.side_effect = request
        client.list.side_effect = listing
        result = capture(client, '12', 100)
        self.assertFalse(result['complete'])
        self.assertIn('announcements', result['unavailable'])
        self.assertEqual(result['excluded_unpublished_or_locked_pages'], 2)
        self.assertEqual(result['modules'][0]['items'][0]['title'], 'Welcome')
        self.assertEqual([item['id'] for item in result['assignments']], [3])
        self.assertEqual([item['id'] for item in result['modules']], [4])
        self.assertEqual([item['id'] for item in result['modules'][0]['items']], [5])
        self.assertEqual([topic['id'] for topic in result['discussions']], [8])
        self.assertNotIn('draft', str(client.request.call_args_list))
        self.assertFalse(any('/modules/40/items' in call.args[0] or '/modules/41/items' in call.args[0]
                             for call in client.list.call_args_list))

    def test_private_save_refuses_git_and_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            destination = root / 'course.json'
            data = {'complete': True, 'assignments': [], 'modules': [], 'pages': [],
                    'announcements': [], 'unavailable': {}}
            result = save_private(destination, data)
            self.assertTrue(result['complete'])
            self.assertEqual(json.loads(destination.read_text())['complete'], True)
            self.assertEqual(os.stat(destination).st_mode & 0o777, 0o600)
            with self.assertRaises(CanvasError):
                save_private(destination, data)
            (root / '.git').mkdir()
            with self.assertRaises(CanvasError):
                validate_destination(root / 'another.json')

    def test_module_page_fallback_marks_snapshot_incomplete(self):
        client = Mock(host='https://canvas.example.edu')
        def request(route):
            if route.endswith('?include[]=syllabus_body'):
                return {'id': 12}, ''
            if route.endswith('/pages/week-one'):
                return {'url': 'week-one', 'published': True, 'body': 'Hello'}, ''
            raise AssertionError(route)
        def listing(route, max_pages):
            if route.endswith('/modules?per_page=100'):
                return [{'id': 4}]
            if route.endswith('/modules/4/items?per_page=100'):
                return [{'type': 'Page', 'page_url': 'week-one'},
                        {'type': 'Page', 'page_url': 'week-one'},
                        {'type': 'Page', 'page_url': 'unpublished', 'published': False},
                        {'type': 'Page', 'page_url': 'locked', 'locked_for_user': True}]
            if route.endswith('/pages?per_page=100'):
                raise CanvasError('Canvas HTTP 404', status=404)
            return []
        client.request.side_effect = request
        client.list.side_effect = listing
        result = capture(client, '12', 100)
        self.assertFalse(result['complete'])
        self.assertEqual([page['url'] for page in result['pages']], ['week-one'])
        self.assertNotIn('locked', str(client.request.call_args_list))
        self.assertNotIn('unpublished', str(client.request.call_args_list))

    def test_rate_limit_aborts_capture_instead_of_saving_partial_state(self):
        client = Mock(host='https://canvas.example.edu')
        client.request.return_value = ({'id': 12}, '')
        client.list.side_effect = CanvasError('rate limited', status=429)
        with self.assertRaises(CanvasError):
            capture(client, '12', 100)
        client.list.assert_called_once()

    def test_opt_in_linked_file_metadata_is_scoped_and_private(self):
        client = Mock(host='https://canvas.example.edu')
        client.request.return_value = ({'id': 12, 'syllabus_body': ''}, '')
        client.list.return_value = []
        with patch('canvas_pocket.discovery.linked_files', return_value={
                'files': [{'id': 7, 'display_name': 'Synthetic reading.pdf', 'size': 20,
                           'downloadable': True, 'sources': ['syllabus']}],
                'skipped_sources': []}) as linked:
            result = capture(client, '12', 100, include_linked_files=True)
        linked.assert_called_once_with(client, '12', 100)
        self.assertEqual(result['linked_file_scope'], 'readable-references-only')
        self.assertEqual(result['linked_files'][0]['id'], 7)
        self.assertTrue(result['complete'])
        self.assertNotIn('url', result['linked_files'][0])

    def test_partial_linked_file_scan_is_labeled_incomplete(self):
        client = Mock(host='https://canvas.example.edu')
        client.request.return_value = ({'id': 12}, '')
        client.list.return_value = []
        with patch('canvas_pocket.discovery.linked_files', return_value={
                'files': [{'id': 7, 'metadata_unavailable': True}],
                'skipped_sources': ['unreadable page']}):
            result = capture(client, '12', 100, include_linked_files=True)
        self.assertFalse(result['complete'])
        self.assertIn('linked_files', result['unavailable'])

    def test_rate_limit_during_opt_in_file_scan_aborts_snapshot(self):
        client = Mock(host='https://canvas.example.edu')
        client.request.return_value = ({'id': 12}, '')
        client.list.return_value = []
        with (patch('canvas_pocket.discovery.linked_files',
                    side_effect=CanvasError('rate limit', status=429)),
              self.assertRaisesRegex(CanvasError, 'rate limit')):
            capture(client, '12', 100, include_linked_files=True)

    def test_diff_reports_only_changed_fields_and_skips_incomplete_categories(self):
        old = {'schema_version': 1, 'origin': 'https://canvas.example.edu', 'course_id': 12,
               'captured_at': 'yesterday', 'unavailable': {'pages': 'list denied'},
               'course': {'syllabus_body': 'Old'},
               'assignments': [{'id': 1, 'name': 'Paper', 'due_at': 'Monday'}],
               'modules': [], 'pages': [{'url': 'partial-old'}], 'announcements': []}
        new = {'schema_version': 1, 'origin': 'https://canvas.example.edu', 'course_id': 12,
               'captured_at': 'today', 'unavailable': {'pages': 'list denied'},
               'course': {'syllabus_body': 'New'},
               'assignments': [{'id': 1, 'name': 'Paper', 'due_at': 'Tuesday'}],
               'modules': [], 'pages': [{'url': 'partial-new'}], 'announcements': []}
        result = compare(old, new)
        self.assertEqual(result['changes']['assignments']['changed'][0]['fields'], ['due_at'])
        self.assertEqual(result['course_changed_fields'], ['syllabus_body'])
        self.assertIn('pages', result['skipped'])
        self.assertNotIn('pages', result['changes'])
        self.assertEqual(result['observed_changes']['pages'], [])
        self.assertIn('discussions', result['skipped'])
        self.assertNotIn('discussions', result['changes'])
        old['discussions'] = [{'id': 8, 'title': 'Prompt', 'message': 'Before'}]
        new['discussions'] = [{'id': 8, 'title': 'Prompt', 'message': 'After'}]
        self.assertEqual(compare(old, new)['changes']['discussions']['changed'][0]['fields'],
                         ['message'])
        old['linked_files'] = [{'id': 7, 'display_name': 'Synthetic.pdf', 'size': 10}]
        new['linked_files'] = [{'id': 7, 'display_name': 'Synthetic.pdf', 'size': 11}]
        self.assertEqual(compare(old, new)['changes']['linked_files']['changed'][0]['fields'],
                         ['size'])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'old.json'
            path.write_text(json.dumps(old))
            self.assertEqual(read(path)['captured_at'], 'yesterday')
            newer = Path(folder) / 'new.json'
            newer.write_text(json.dumps(new))
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(run(parser().parse_args(['snapshot-diff', str(path), str(newer)]))
                                 ['course_changed_fields'], ['syllabus_body'])
            new['course_id'] = 13
            with self.assertRaises(CanvasError):
                compare(old, new)


if __name__ == '__main__':
    unittest.main()
