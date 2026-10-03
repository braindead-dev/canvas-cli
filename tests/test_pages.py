import unittest
from unittest.mock import Mock

from canvas_pocket.cli import brief, parser, run
from canvas_pocket.client import CanvasError
from canvas_pocket.pages import page_index


class PageIndexTests(unittest.TestCase):
    def test_complete_listing_filters_inaccessible_pages(self):
        client = Mock()
        client.list.return_value = [
            {'url': 'one', 'title': 'One', 'published': True},
            {'url': 'draft', 'published': False},
            {'url': 'locked', 'locked_for_user': True},
            {'url': 'state-locked', 'state': 'locked'},
            {'url': 'workflow-draft', 'workflow_state': 'unpublished'},
            None,
        ]
        result = page_index(client, '12', 100)
        self.assertTrue(result['complete'])
        self.assertEqual([item['url'] for item in result['pages']], ['one'])
        client.list.assert_called_once_with('/api/v1/courses/12/pages?per_page=100', 100)

    def test_denied_listing_falls_back_to_readable_module_pages(self):
        client = Mock()

        def listing(route, _limit):
            if route.endswith('/pages?per_page=100'):
                raise CanvasError('not found', status=404)
            if route.endswith('/modules?per_page=100'):
                return [{'id': 1, 'published': True}, {'id': 2, 'published': False},
                        {'id': 3, 'published': True}]
            if route.endswith('/modules/1/items?per_page=100'):
                return [{'type': 'Page', 'page_url': 'intro', 'published': True},
                        {'type': 'Page', 'page_url': 'intro', 'published': True},
                        {'type': 'Page', 'page_url': 'hidden', 'locked_for_user': True},
                        {'type': 'Page', 'page_url': 'draft', 'published': False}]
            if route.endswith('/modules/3/items?per_page=100'):
                return [{'type': 'Page', 'page_url': 'intro'},
                        {'type': 'Page', 'page_url': 'restricted'}]
            raise AssertionError(route)

        def request(route):
            if route.endswith('/pages/intro'):
                return {'url': 'intro', 'title': 'Introduction', 'published': True,
                        'updated_at': '2026-09-25', 'body': 'Private content'}, ''
            if route.endswith('/pages/restricted'):
                raise CanvasError('denied', status=403)
            raise AssertionError(route)

        client.list.side_effect = listing
        client.request.side_effect = request
        result = page_index(client, '12', 100)
        self.assertFalse(result['complete'])
        self.assertEqual(result['source'], 'module-pages')
        self.assertEqual(result['pages'], [{'url': 'intro', 'module_ids': [1, 3],
                                           'title': 'Introduction', 'updated_at': '2026-09-25'}])
        self.assertEqual(result['unavailable'], [
            {'resource': 'pages', 'status': 404}, {'resource': 'page restricted', 'status': 403}])
        self.assertNotIn('Private content', str(result))
        self.assertNotIn('/modules/2/', str(client.list.call_args_list))
        self.assertNotIn('/pages/draft', str(client.request.call_args_list))
        self.assertIn('Partial coverage', brief(result))

    def test_rate_limit_and_network_failures_are_not_hidden(self):
        for status in (401, 429, None):
            with self.subTest(status=status):
                client = Mock()
                client.list.side_effect = CanvasError('failed', status=status)
                with self.assertRaises(CanvasError):
                    page_index(client, '12', 100)
                client.list.assert_called_once()

    def test_cli_flag_preserves_default_raw_list(self):
        client = Mock()
        client.list.return_value = [{'url': 'intro', 'published': True}]
        import canvas_pocket.auth as auth
        original = auth.Client
        original_load = auth.load
        original_keyring = auth.secure_keyring
        try:
            auth.Client = lambda _host, _token: client
            auth.load = lambda: 'https://canvas.example.edu'
            auth.secure_keyring = lambda: Mock(get_password=lambda *_: 'test-token')
            self.assertEqual(run(parser().parse_args(['pages', '12'])),
                             [{'url': 'intro', 'published': True}])
            self.assertEqual(run(parser().parse_args(['pages', '12', '--best-effort']))['complete'], True)
        finally:
            auth.Client = original
            auth.load = original_load
            auth.secure_keyring = original_keyring


if __name__ == '__main__':
    unittest.main()
