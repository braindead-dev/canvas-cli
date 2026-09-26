import unittest
from unittest.mock import patch

from canvas_pocket.client import CanvasError
from canvas_pocket.find import find


class FakeClient:
    def __init__(self):
        self.calls = []

    def list(self, route, max_pages):
        self.calls.append((route, max_pages))
        if '/assignments?' in route:
            return [{'id': 1, 'name': 'Synthetic paper', 'due_at': '2026-10-01',
                     'description': 'private details'},
                    {'id': 2, 'name': 'Hidden paper', 'published': False}]
        if '/discussion_topics?' in route:
            return [{'id': 3, 'title': 'Synthetic discussion'}]
        if '/pages?' in route:
            raise CanvasError('Canvas HTTP 404', status=404)
        if '/files?' in route:
            raise CanvasError('Canvas denied access', status=403)
        if '/modules/4/items?' in route:
            raise CanvasError('Canvas denied access', status=403)
        if '/modules?' in route:
            return [{'id': 4, 'name': 'Week 1', 'items': None}]
        raise AssertionError(route)


class FindTests(unittest.TestCase):
    def test_reports_partial_coverage_without_private_bodies(self):
        client = FakeClient()
        with patch('canvas_pocket.discovery.linked_files', return_value={
                'files': [], 'skipped_sources': []}):
            result = find(client, '101', 'Synthetic', 4)
        self.assertFalse(result['complete'])
        self.assertEqual(result['coverage']['pages'], 'module_pages_partially_searched')
        self.assertEqual(result['coverage']['modules'],
                         'searched_module_names_items_may_be_omitted')
        self.assertEqual(result['coverage']['files'], 'linked_files_only')
        self.assertEqual([row['id'] for row in result['results']], [1, 3])
        self.assertNotIn('private details', str(result))
        self.assertEqual(len(client.calls), 7)

    def test_file_search_falls_back_to_accessible_linked_names(self):
        client = FakeClient()
        with patch('canvas_pocket.discovery.linked_files', return_value={
                'files': [{'id': 10, 'display_name': 'Synthetic reading.pdf', 'downloadable': True},
                          {'id': 11, 'display_name': 'Other.pdf', 'downloadable': True},
                          {'id': 12, 'display_name': 'Synthetic hidden.pdf', 'downloadable': False}],
                'skipped_sources': ['unreadable page']}) as linked:
            result = find(client, '101', 'synthetic', selected='files')
        linked.assert_called_once_with(client, '101', 100)
        self.assertEqual(result['coverage']['files'], 'linked_files_partially_searched')
        self.assertEqual(result['results'], [
            {'area': 'file', 'id': 10, 'title': 'Synthetic reading.pdf', 'due_at': None}])
        self.assertFalse(result['complete'])
        self.assertIn('linked files', result['unavailable']['files'])

    def test_area_selection_and_query_validation(self):
        client = FakeClient()
        result = find(client, '101', 'paper', selected='assignments')
        self.assertEqual(list(result['coverage']), ['assignments'])
        self.assertEqual(len(client.calls), 1)
        for query in ('', 'x' * 201):
            with self.assertRaises(CanvasError):
                find(client, '101', query)

    def test_server_ignoring_search_term_does_not_return_unrelated_titles(self):
        class Unfiltered:
            def list(self, route, _max_pages):
                if '/assignments?' in route:
                    return [{'id': 1, 'name': 'Completely unrelated'},
                            {'id': 2, 'name': 'Synthetic paper'},
                            {'id': 3, 'name': 'Synthetic draft', 'published': False}]
                if '/modules?' in route:
                    return [{'id': 4, 'name': 'Week one', 'items': [
                        {'id': 5, 'title': 'Synthetic worksheet'},
                        {'id': 6, 'title': 'Unrelated item'},
                        {'id': 7, 'title': 'Synthetic draft', 'published': False}]},
                        {'id': 8, 'name': 'Synthetic locked module', 'state': 'locked'}]
                raise AssertionError(route)

        assignment = find(Unfiltered(), '101', 'synthetic', selected='assignments')
        self.assertEqual([row['id'] for row in assignment['results']], [2])
        module = find(Unfiltered(), '101', 'synthetic', selected='modules')
        self.assertEqual([row['id'] for row in module['results']], [5])

    def test_rate_limit_stops_later_probes(self):
        class Limited:
            def list(self, route, max_pages):
                raise CanvasError('Canvas rate limit reached', status=429)
        result = find(Limited(), '101', 'paper')
        self.assertEqual(result['coverage']['assignments'], 'unavailable')
        self.assertEqual(result['coverage']['discussions'], 'not_checked_after_rate_limit')

    def test_network_failure_does_not_masquerade_as_missing_area(self):
        class Offline:
            def list(self, _route, _max_pages):
                raise CanvasError('Network failure')
        with self.assertRaises(CanvasError):
            find(Offline(), '101', 'paper')

    def test_rate_limit_during_linked_file_fallback_stops_later_areas(self):
        class LimitedFiles:
            def list(self, route, _max_pages):
                if '/files?' in route:
                    raise CanvasError('Files list denied', status=403)
                return []

        with patch('canvas_pocket.discovery.linked_files',
                   side_effect=CanvasError('rate limit', status=429)):
            result = find(LimitedFiles(), '101', 'paper')
        self.assertEqual(result['coverage']['files'], 'unavailable')
        self.assertEqual(result['coverage']['modules'], 'not_checked_after_rate_limit')
        self.assertFalse(result['complete'])

    def test_page_search_falls_back_to_module_titles_with_partial_coverage(self):
        class ModulePages:
            def list(self, route, _max_pages):
                if '/pages?' in route:
                    raise CanvasError('Canvas HTTP 404', status=404)
                if '/modules?' in route:
                    return [{'id': 6, 'published': True}]
                if '/modules/6/items?' in route:
                    return [{'type': 'Page', 'page_url': 'project-guide'},
                            {'type': 'Page', 'page_url': 'other'}]
                raise AssertionError(route)

            def request(self, route):
                slug = route.rsplit('/', 1)[1]
                return {'url': slug, 'title': 'Project guide' if slug == 'project-guide'
                        else 'Other page', 'published': True, 'body': 'private'}, ''

        result = find(ModulePages(), '101', 'project', selected='pages')
        self.assertFalse(result['complete'])
        self.assertEqual(result['coverage']['pages'], 'module_pages_only')
        self.assertEqual(result['results'], [
            {'area': 'page', 'id': 'project-guide', 'title': 'Project guide', 'due_at': None}])
        self.assertNotIn('private', str(result))
