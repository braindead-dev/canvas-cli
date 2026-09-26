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
            raise CanvasError('Canvas HTTP 404')
        if '/files?' in route:
            raise CanvasError('Canvas denied access')
        if '/modules?' in route:
            return [{'id': 4, 'name': 'Week 1', 'items': None}]
        raise AssertionError(route)


class FindTests(unittest.TestCase):
    def test_reports_partial_coverage_without_private_bodies(self):
        client = FakeClient()
        result = find(client, '101', 'Synthetic', 4)
        self.assertFalse(result['complete'])
        self.assertEqual(result['coverage']['pages'], 'unavailable')
        self.assertEqual(result['coverage']['modules'],
                         'searched_module_names_items_may_be_omitted')
        self.assertEqual([row['id'] for row in result['results']], [1, 3, 4])
        self.assertNotIn('private details', str(result))
        self.assertEqual(len(client.calls), 5)

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
                raise CanvasError('Canvas rate limit reached')
        result = find(Limited(), '101', 'paper')
        self.assertEqual(result['coverage']['assignments'], 'unavailable')
        self.assertEqual(result['coverage']['discussions'], 'not_checked_after_rate_limit')
