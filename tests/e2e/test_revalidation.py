"""Real subprocess/TLS revalidation; no live account or academic records."""

import copy
import json
import os
import tempfile
from pathlib import Path

from .fixture import CanvasFixture

PAGE = {'page_id': 42, 'url': 'welcome', 'title': 'Synthetic page', 'published': True,
        'body': '<p>Synthetic private body</p>', 'course_id': 101}


class RevalidationE2E(CanvasFixture):
    def setUp(self):
        cls = type(self)
        original = copy.deepcopy(cls.own_profile)
        cls.snapshot_revalidation = {'listed': [copy.deepcopy(PAGE)], 'page': copy.deepcopy(PAGE),
                                     'etag': 'W/"v1"', 'requests': []}
        self.state = cls.snapshot_revalidation
        self.addCleanup(setattr, cls, 'snapshot_revalidation', None)
        self.addCleanup(setattr, cls, 'own_profile', original)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def sync(self, *, incremental=True, brief=False, expect_success=True):
        args = ['sync', '101', '--directory', self.folder.name]
        if incremental:
            args.append('--incremental')
        if brief:
            args.extend(['--format', 'brief'])
        result = self.invoke(*args)
        if expect_success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
        self.assertNotIn('Synthetic private body', result.stdout + result.stderr)
        self.assertNotIn('W/"v1"', result.stdout + result.stderr)
        self.assertNotIn('synthetic-token', result.stdout + result.stderr)
        return result if brief or not expect_success else json.loads(result.stdout)

    def test_baseline_revalidation_then_changed_body_refreshes_and_preserves_files(self):
        first = self.sync()
        original = Path(first['saved']).read_bytes()
        second = self.sync()
        self.assertTrue(first['baseline'])
        self.assertEqual(first['revalidation']['pages_fetched'], 1)
        self.assertEqual(second['revalidation']['pages_revalidated'], 1)
        self.assertEqual(second['revalidation']['conditional_requests'], 1)
        self.assertEqual(self.state['requests'], [('/api/v1/courses/101/pages/page_id:42', None),
                                                  ('/api/v1/courses/101/pages/page_id:42', 'W/"v1"')])
        self.state['page']['body'] = '<p>Synthetic changed body</p>'
        self.state['etag'] = 'W/"v2"'
        third = self.sync()
        self.assertEqual(third['revalidation']['pages_fetched'], 1)
        self.assertEqual(third['revalidation']['pages_revalidated'], 0)
        self.assertEqual(third['diff']['changes']['pages']['changed'][0]['fields'], ['body'])
        self.assertEqual(Path(first['saved']).read_bytes(), original)
        self.assertEqual(len(list(Path(self.folder.name).glob('*.json'))), 3)
        self.assertEqual(os.stat(third['saved']).st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(Path(second['saved']).read_text())['pages'][0]['body'], PAGE['body'])
        self.assertTrue(all(method == 'GET' for method, _ in self.calls))

    def test_no_validator_or_no_store_uses_full_bodies_without_conditional_headers(self):
        for headers, tag in (({}, None), ({'Cache-Control': 'private, no-store'}, 'W/"v1"'),
                             ({'Vary': 'Cookie'}, 'W/"v1"')):
            with self.subTest(headers=headers, tag=tag):
                self.state['headers'], self.state['etag'] = headers, tag
                self.sync()
                second = self.sync()
                self.assertEqual(second['revalidation']['pages_fetched'], 1)
                self.assertEqual(second['revalidation']['validator_pages'], 0)
                self.assertIsNone(self.state['requests'][-1][1])

    def test_listing_is_repaginated_and_hidden_or_removed_pages_never_reused(self):
        self.state['paginate'] = True
        first = self.sync()
        start = len(self.calls)
        self.state['listed'] = [{**PAGE, 'published': False}]
        second = self.sync()
        self.assertEqual(second['counts']['pages'], 0)
        self.assertEqual(len(self.state['requests']), 1)
        self.assertTrue(any(path.endswith('/pages?page=2') for _, path in self.calls[start:]))
        self.assertEqual(json.loads(Path(second['saved']).read_text())['page_revalidation']['entries'], [])
        self.state['listed'] = []
        third = self.sync()
        self.assertEqual(third['counts']['pages'], 0)
        self.assertEqual(len(self.state['requests']), 1)
        self.assertEqual(json.loads(Path(first['saved']).read_text())['pages'][0]['body'], PAGE['body'])

    def test_denied_page_saves_explicit_partial_coverage_without_cached_body(self):
        for status in (403, 404):
            self.state['page_status'] = 200
            self.sync()
            self.state['page_status'] = status
            denied = self.sync()
            self.assertFalse(denied['complete'])
            self.assertEqual(denied['counts']['pages'], 0)
            saved = json.loads(Path(denied['saved']).read_text())
            self.assertEqual(saved['page_revalidation']['entries'], [])
            self.assertIn('page welcome', denied['unavailable'])

    def test_bad_ack_rate_limit_and_account_change_do_not_save_or_modify_baseline(self):
        first = self.sync()
        path = Path(first['saved'])
        original = path.read_bytes()
        self.state['bad_ack'] = True
        self.assertIn('invalid revalidation', self.sync(expect_success=False).stderr)
        self.state['bad_ack'] = False
        self.state['page_status'] = 429
        self.assertIn('rate limit', self.sync(expect_success=False).stderr)
        self.state['page_status'] = 200
        self.state['change_account'] = True
        self.assertIn('account changed', self.sync(expect_success=False).stderr)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual([item.resolve() for item in Path(self.folder.name).glob('*.json')], [path])

    def test_locally_edited_body_forces_full_fetch_without_using_saved_tag(self):
        first = self.sync()
        path = Path(first['saved'])
        data = json.loads(path.read_text())
        data['pages'][0]['body'] = '<p>Synthetic locally edited cache</p>'
        path.write_text(json.dumps(data))
        second = self.sync()
        self.assertEqual(second['revalidation']['pages_fetched'], 1)
        self.assertEqual(second['revalidation']['conditional_requests'], 0)
        self.assertIsNone(self.state['requests'][-1][1])
        self.assertEqual(json.loads(Path(second['saved']).read_text())['pages'][0]['body'], PAGE['body'])

    def test_full_sync_default_does_not_use_or_retain_revalidation_hints(self):
        self.sync()
        second = self.sync(incremental=False)
        self.assertNotIn('revalidation', second)
        self.assertNotIn('page_revalidation', json.loads(Path(second['saved']).read_text()))
        self.assertEqual(self.state['requests'][-1], ('/api/v1/courses/101/pages/welcome', None))

    def test_other_viewer_never_uses_the_prior_viewers_validator(self):
        first = self.sync()
        type(self).own_profile = {**type(self).own_profile, 'id': 8}
        other = self.sync()
        self.assertTrue(other['baseline'])
        self.assertIsNone(self.state['requests'][-1][1])
        type(self).own_profile = {**type(self).own_profile, 'id': 7}
        back = self.sync()
        self.assertEqual(back['previous'], first['saved'])
        self.assertEqual(back['revalidation']['pages_revalidated'], 1)
        self.assertEqual(self.state['requests'][-1][1], 'W/"v1"')

    def test_brief_summary_reports_page_only_scope_without_headers_or_bodies(self):
        self.sync()
        result = self.sync(brief=True)
        self.assertIn('1 page body revalidated; 0 fetched', result.stdout)
        self.assertIn('inventories were fetched fresh', result.stdout)
