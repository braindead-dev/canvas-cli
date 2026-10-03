import unittest
from unittest.mock import Mock

from canvas_cli.client import CanvasError
from canvas_cli.discovery import file_index, linked_files, referenced_ids


class DiscoveryTests(unittest.TestCase):
    def test_files_index_uses_api_when_available(self):
        client = Mock()
        client.list.return_value = [{'id': 1, 'display_name': 'Visible.pdf'},
                                    {'id': 2, 'hidden_for_user': True}]
        data = file_index(client, '123', 100)
        self.assertTrue(data['complete'])
        self.assertEqual(data['source'], 'files-api')
        self.assertEqual([item['id'] for item in data['files']], [1])
        client.list.assert_called_once_with('/api/v1/courses/123/files?per_page=100', 100)

    def test_files_index_fallback_is_explicitly_partial(self):
        client = Mock(host='https://canvas.example.edu')
        client.request.return_value = ({'syllabus_body':
                                        '<a href="/courses/123/files/9">Reading</a>'}, '')

        def listing(route, _max_pages):
            if route.endswith('/files?per_page=100'):
                raise CanvasError('not found', status=404)
            return []

        client.list.side_effect = listing
        data = file_index(client, '123', 100, resolve=False)
        self.assertFalse(data['complete'])
        self.assertEqual(data['source'], 'linked-content')
        self.assertEqual([item['id'] for item in data['files']], [9])
        self.assertEqual(data['unavailable'], [{'resource': 'files', 'status': 404}])

    def test_files_index_does_not_hide_rate_limit(self):
        client = Mock()
        client.list.side_effect = CanvasError('rate limit', status=429)
        with self.assertRaises(CanvasError):
            file_index(client, '123', 100)

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
            if '/discussion_topics?' in route:
                return []
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
                raise CanvasError('Canvas denied access', status=403)
            if '/assignments?' in route:
                return []
            if '/discussion_topics?' in route:
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

    def test_locked_or_unpublished_sources_are_not_followed(self):
        client = Mock(host='https://canvas.example.edu')
        client.request.return_value = ({'syllabus_body': ''}, '')

        def listing(route, _max_pages):
            if '/modules?' in route:
                return [{'id': 1, 'name': 'Draft', 'published': False,
                         'items': [{'type': 'File', 'content_id': 90}]},
                        {'id': 3, 'name': 'Locked module', 'state': 'locked',
                         'items': [{'type': 'File', 'content_id': 96}]},
                        {'id': 2, 'name': 'Visible', 'published': True,
                         'items': [{'type': 'File', 'content_id': 91, 'published': False},
                                   {'type': 'File', 'content_id': 92, 'locked_for_user': True},
                                   {'type': 'File', 'content_id': 97, 'hidden_for_user': True},
                                   {'type': 'File', 'content_id': 98, 'state': 'locked'},
                                   {'type': 'File', 'content_id': 93, 'published': True}]}]
            if '/assignments?' in route:
                return [{'id': 4, 'published': False,
                         'description': '<a href="/courses/123/files/94">Draft</a>'},
                        {'id': 5, 'locked_for_user': True,
                         'description': '<a href="/courses/123/files/95">Locked</a>'},
                        {'id': 6, 'hidden_for_user': True,
                         'description': '<a href="/courses/123/files/99">Hidden</a>'}]
            if '/discussion_topics?' in route:
                return []
            raise AssertionError(route)

        client.list.side_effect = listing
        result = linked_files(client, '123', 100, resolve=False)
        self.assertEqual([item['id'] for item in result['files']], [93])

    def test_all_pages_scans_published_unmoduled_pages_only(self):
        client = Mock(host='https://canvas.example.edu')
        def request(route):
            if route.endswith('syllabus_body'):
                return {'syllabus_body': ''}, ''
            if route.endswith('/pages/extra'):
                return {'body': '<a href="/courses/123/files/50">Extra</a>', 'published': True}, ''
            raise AssertionError(route)
        def listing(route, max_pages):
            if '/modules?' in route or '/assignments?' in route or '/discussion_topics?' in route:
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

    def test_instructor_topic_links_are_found_without_reading_student_entries(self):
        client = Mock(host='https://canvas.example.edu')
        client.request.return_value = ({'syllabus_body': ''}, '')

        def listing(route, _max_pages):
            if '/modules?' in route or '/assignments?' in route:
                return []
            if 'only_announcements=true' in route:
                return [{'id': 1, 'title': 'Reading', 'published': True,
                         'message': '<a href="/courses/123/files/31">Reading</a>'},
                        {'id': 2, 'published': False,
                         'message': '<a href="/courses/123/files/99">Draft</a>'},
                        {'id': 5, 'title': 'Closed replies', 'published': True,
                         'locked_for_user': True,
                         'message': '<a href="/courses/123/files/33">Readable announcement</a>'}]
            if '/discussion_topics?' in route:
                return [{'id': 3, 'title': 'Prompt', 'published': True,
                         'message': '<a href="/courses/123/files/32">Prompt attachment</a>'},
                        {'id': 4, 'locked_for_user': True,
                         'message': '<a href="/courses/123/files/98">Locked discussion</a>'}]
            raise AssertionError(route)

        client.list.side_effect = listing
        result = linked_files(client, '123', 100, resolve=False)
        self.assertEqual([item['id'] for item in result['files']], [31, 32, 33])
        self.assertIn('announcement: Reading', result['files'][0]['sources'])
        self.assertIn('discussion prompt: Prompt', result['files'][1]['sources'])
        self.assertIn('announcement: Closed replies', result['files'][2]['sources'])
        self.assertNotIn('/entries', str(client.list.call_args_list))

    def test_rate_limit_in_discovery_is_not_reported_as_skipped(self):
        client = Mock(host='https://canvas.example.edu')
        client.request.return_value = ({'syllabus_body': ''}, '')
        client.list.side_effect = CanvasError('rate limit', status=429)
        with self.assertRaisesRegex(CanvasError, 'rate limit'):
            linked_files(client, '123', 100)
