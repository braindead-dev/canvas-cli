import unittest
from unittest.mock import Mock

from canvas_pocket.client import CanvasError
from canvas_pocket.discovery import linked_files, referenced_ids


class DiscoveryTests(unittest.TestCase):
    def test_links_keep_course_and_origin(self):
        html = ('<a href="/courses/123/files/10?wrap=1">a</a>'
                '<a data-api-endpoint="/courses/123/files/13/preview">d</a>'
                '<a data-api-endpoint="/api/v1/courses/123/files/14">api</a>'
                '<a href="/api/v1/files/15">global api</a>'
                '<a href="https://evil.example/courses/123/files/11">b</a>'
                '<a href="/courses/456/files/12">c</a>')
        self.assertEqual(referenced_ids(html, 'https://canvas.example.edu', '123'), {10, 13, 14, 15})

    def test_finds_references_without_files_list_permission(self):
        client = Mock(host='https://canvas.example.edu')
        def request(route):
            if route.endswith('syllabus_body'):
                return {'syllabus_body': '<a href="/courses/123/files/10">Syllabus</a>'}, ''
            if '/pages/' in route:
                return {'body': '<a href="/courses/123/files/13">Reading</a>'}, ''
            if '/files/' in route:
                return {'display_name': f"file-{route.rsplit('/', 1)[-1]}.pdf", 'size': 10,
                        'url': 'https://files.example.edu/item'}, ''
            raise AssertionError(route)
        def listing(route, max_pages):
            if '/modules?' in route:
                return [{'id': 1, 'name': 'Week 1', 'items_count': 2, 'items': [
                    {'type': 'File', 'content_id': 11}, {'type': 'Page', 'page_url': 'reading', 'title': 'Reading'}]}]
            if '/assignments?' in route:
                return [{'id': 2, 'name': 'Paper', 'description': '<a href="/courses/123/files/12">Doc</a>'}]
            raise AssertionError(route)
        client.request.side_effect = request
        client.list.side_effect = listing
        result = linked_files(client, '123', 100)
        self.assertEqual([f['id'] for f in result['files']], [10, 11, 12, 13])
        self.assertTrue(all(f['downloadable'] for f in result['files']))
        self.assertEqual(result['skipped_sources'], [])

    def test_partial_permissions_are_reported_without_hiding_other_files(self):
        client = Mock(host='https://canvas.example.edu')
        def request(route):
            if route.endswith('syllabus_body'):
                return {'syllabus_body': '<a href="/courses/123/files/10">Syllabus</a>'}, ''
            if '/files/' in route:
                return {'display_name': 'file.pdf', 'hidden_for_user': True,
                        'url': 'https://files.example.edu/item'}, ''
            raise AssertionError(route)
        def listing(route, max_pages):
            if '/modules?' in route:
                raise CanvasError('Canvas denied access')
            if '/assignments?' in route:
                return []
            raise AssertionError(route)
        client.request.side_effect = request
        client.list.side_effect = listing
        result = linked_files(client, '123', 100)
        self.assertEqual([f['id'] for f in result['files']], [10])
        self.assertFalse(result['files'][0]['downloadable'])
        self.assertEqual(result['skipped_sources'], ['modules'])

    def test_quick_mode_skips_file_metadata_requests(self):
        client = Mock(host='https://canvas.example.edu')
        client.request.return_value = ({'syllabus_body': '<a href="/courses/123/files/10">File</a>'}, '')
        client.list.return_value = []
        result = linked_files(client, '123', 100, resolve=False)
        self.assertEqual(result['files'], [{'id': 10, 'sources': ['syllabus'],
                                            'metadata_not_checked': True}])
        client.request.assert_called_once()

    def test_all_pages_scans_published_unmoduled_pages_only(self):
        client = Mock(host='https://canvas.example.edu')
        def request(route):
            if route.endswith('syllabus_body'):
                return {'syllabus_body': ''}, ''
            if route.endswith('/pages/extra'):
                return {'body': '<a href="/courses/123/files/50">Extra</a>', 'published': True}, ''
            raise AssertionError(route)
        def listing(route, max_pages):
            if '/modules?' in route or '/assignments?' in route:
                return []
            if '/pages?' in route:
                return [{'url': 'extra', 'title': 'Extra', 'published': True},
                        {'url': 'draft', 'title': 'Draft', 'published': False},
                        {'url': 'locked', 'title': 'Locked', 'locked_for_user': True}]
            raise AssertionError(route)
        client.request.side_effect = request
        client.list.side_effect = listing
        result = linked_files(client, '123', 100, resolve=False, all_pages=True)
        self.assertEqual(result['files'][0]['id'], 50)
        self.assertIn('all listed published pages', result['note'])
        self.assertNotIn('draft', str(client.request.call_args_list))
