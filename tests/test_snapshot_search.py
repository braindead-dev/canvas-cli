import unittest

from canvas_pocket.client import CanvasError
from canvas_pocket.snapshot_search import search


class SnapshotSearchTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            'schema_version': 1, 'course_id': 12, 'captured_at': 'synthetic-time',
            'complete': False, 'course': {'syllabus_body': '<p>Read about cells.</p>'},
            'assignments': [{'id': 1, 'name': 'Cell paper',
                             'description': '<script>injected hidden</script><p>Discuss mitochondria and cells.</p>'}],
            'announcements': [{'id': 2, 'title': 'Office hours',
                               'message': '<p>We discuss cells tomorrow.</p>'}],
            'discussions': [{'id': 5, 'title': 'Synthetic research prompt',
                             'message': '<p>Compare two methods.</p>'}],
            'pages': [{'url': 'cell-guide', 'title': 'Cell guide',
                       'body': '<p>Cells contain mitochondria.</p>'}],
            'modules': [{'id': 3, 'name': 'Cell module',
                         'items': [{'id': 4, 'title': 'Cell worksheet'}]}],
        }

    def test_ranks_title_matches_and_removes_html(self):
        result = search(self.snapshot, 'cell mitochondria')
        self.assertEqual(result['total_matches'], 2)
        self.assertEqual(result['shown'][0]['title'], 'Cell paper')
        self.assertFalse(result['snapshot_complete'])
        self.assertNotIn('<p>', str(result))
        self.assertNotIn('injected hidden', str(result))

    def test_limit_and_validation(self):
        result = search(self.snapshot, 'cells', 1)
        self.assertEqual(len(result['shown']), 1)
        self.assertGreater(result['total_matches'], 1)
        for query, limit in (('', 20), ('x' * 201, 20), ('x', 0), ('x', 101)):
            with self.assertRaises(CanvasError):
                search(self.snapshot, query, limit)
        with self.assertRaises(CanvasError):
            search({**self.snapshot, 'pages': None}, 'cells')

    def test_discussion_prompt_is_searchable_and_legacy_coverage_is_honest(self):
        result = search(self.snapshot, 'methods')
        self.assertEqual(result['shown'][0]['kind'], 'discussion')
        self.assertEqual(result['shown'][0]['id'], 5)
        older = dict(self.snapshot)
        del older['discussions']
        older['complete'] = True
        legacy = search(older, 'methods')
        self.assertFalse(legacy['snapshot_complete'])
        self.assertIn('predates discussion capture', legacy['note'])
        with self.assertRaises(CanvasError):
            search({**self.snapshot, 'discussions': None}, 'methods')
