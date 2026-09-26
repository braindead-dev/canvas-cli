import unittest

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
        result = find(client, '101', 'Synthetic', 4)
        self.assertFalse(result['complete'])
        self.assertEqual(result['coverage']['pages'], 'module_pages_partially_searched')
        self.assertEqual(result['coverage']['modules'],
                         'searched_module_names_items_may_be_omitted')
        self.assertEqual([row['id'] for row in result['results']], [1, 3, 4])
        self.assertNotIn('private details', str(result))
        self.assertEqual(len(client.calls), 7)

    def test_area_selection_and_query_validation(self):
        client = FakeClient()
        result = find(client, '101', 'paper', selected='assignments')
        self.assertEqual(list(result['coverage']), ['assignments'])
        self.assertEqual(len(client.calls), 1)
        for query in ('', 'x' * 201):
            with self.assertRaises(CanvasError):
                find(client, '101', query)

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
