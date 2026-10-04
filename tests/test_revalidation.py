import copy
import io
import json
import unittest
from email.message import Message
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

from canvas_cli.client import CanvasError, Client, valid_etag
from canvas_cli.page_revalidation import PageRevalidation
from canvas_cli.snapshot import capture

HOST = 'https://canvas.example.edu'
PAGE = {'page_id': 42, 'url': 'welcome', 'published': True, 'body': 'Synthetic private body'}


class Response(io.BytesIO):
    def __init__(self, data=PAGE, *, status=200, headers=None, raw=None):
        super().__init__(json.dumps(data).encode() if raw is None else raw)
        self.status = status
        self.headers = headers or {}


class TransportTests(unittest.TestCase):
    def client(self, response):
        self.send = Mock(return_value=response)
        return Client(HOST, 'synthetic-private-token', self.send)

    def test_full_json_get_and_exact_empty_304_share_guarded_transport(self):
        first = Response(headers={'ETag': 'W/"v1"'})
        client = self.client(first)
        result = client.conditional_get('/api/v1/courses/12/pages/page_id:42')
        self.assertEqual(result, {'data': PAGE, 'not_modified': False, 'etag': 'W/"v1"'})
        request = self.send.call_args.args[0]
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(request.get_header('Cache-control'), 'no-cache')
        self.assertIsNone(request.get_header('If-none-match'))
        second = Response(status=304, headers={'ETag': 'W/"v1"'}, raw=b'')
        self.send.return_value = second
        result = client.conditional_get('/api/v1/courses/12/pages/page_id:42', 'W/"v1"')
        self.assertEqual(result, {'data': None, 'not_modified': True, 'etag': 'W/"v1"'})
        self.assertEqual(self.send.call_args.args[0].get_header('If-none-match'), 'W/"v1"')
        self.assertTrue(first.closed and second.closed)
        self.assertEqual(self.send.call_count, 2)

    def test_urllib_http_error_304_is_closed_and_validated(self):
        body = io.BytesIO(b'')
        client = self.client(None)
        error = HTTPError(HOST + '/api/v1/example', 304, 'Synthetic private reason', {'ETag': '"v1"'}, body)
        self.send.side_effect = error
        self.assertTrue(client.conditional_get('/api/v1/example', '"v1"')['not_modified'])
        self.assertTrue(body.closed)

    def test_invalid_tags_fail_before_transport_and_do_not_leak(self):
        client = self.client(None)
        for tag in ('*', '"v1", "v2"', 'v1', 'w/"v1"', '"\nprivate"', '"\rprivate"',
                    '"\x00private"', '"\x7fprivate"', '"☃"', '"' + 'x' * 512 + '"', 4, True):
            with self.subTest(tag=repr(tag)), self.assertRaisesRegex(CanvasError, 'Invalid revalidation') as error:
                client.conditional_get('/api/v1/example', tag)
            self.assertNotIn('private', str(error.exception))
        self.send.assert_not_called()
        for tag in ('""', 'W/""', '"v1"', '"back\\slash"'):
            self.assertTrue(valid_etag(tag))
        self.assertFalse(valid_etag(None))

    def test_route_side_effect_and_origin_guards_apply_to_conditional_reads(self):
        client = self.client(None)
        for route in ('https://other.example.edu/api/v1/pages', '/api/v1/../pages',
                      '/api/v1/conversations/2', '/api/v1/example?include[]=read_status',
                      '/api/v1/example?access_token=secret', '/api/v1/example?as_user_id[]=8'):
            with self.subTest(route=route), self.assertRaises(CanvasError):
                client.conditional_get(route, '"v1"')
        self.send.assert_not_called()

    def test_cache_policy_and_unexpected_vary_or_invalid_etag_disable_retention(self):
        for headers in ({}, {'ETag': '*'}, {'ETag': '"v1"', 'Cache-Control': 'private, NO-STORE'},
                        {'ETag': '"v1"', 'Vary': '*'}, {'ETag': '"v1"', 'Vary': 'Cookie'},
                        {'ETag': '"v1"', 'Cache-Control': None}, {'ETag': '"v1"', 'Vary': None}):
            client = self.client(Response(headers=headers))
            with self.subTest(headers=headers):
                result = client.conditional_get('/api/v1/example')
            self.assertEqual(result['data'], PAGE)
            self.assertIsNone(result['etag'])
        client = self.client(Response(headers={'ETag': '"v1"', 'Vary': 'Accept, Authorization, Accept-Encoding',
                                             'Cache-Control': 'max-age=0, private, must-revalidate'}))
        self.assertEqual(client.conditional_get('/api/v1/example')['etag'], '"v1"')

    def test_repeated_http_headers_cannot_hide_no_store_or_ambiguous_etags(self):
        for field, values in (('ETag', ('"v1"', '"v2"')),
                              ('Cache-Control', ('private', 'no-store')),
                              ('Vary', ('Accept', '*'))):
            headers = Message()
            if field != 'ETag':
                headers['ETag'] = '"v1"'
            for value in values:
                headers[field] = value
            client = self.client(Response(headers=headers))
            self.assertIsNone(client.conditional_get('/api/v1/example')['etag'])
            self.send.return_value = Response(status=304, headers=headers, raw=b'')
            with self.assertRaises(CanvasError):
                client.conditional_get('/api/v1/example', '"v1"')

    def test_malformed_or_unsolicited_304_never_reuses_or_retries(self):
        cases = ((None, {'ETag': '"v1"'}, b''), ('"v1"', {}, b''),
                 ('"v1"', {'ETag': '"v2"'}, b''), ('"v1"', {'ETag': '"v1"'}, b'Synthetic private body'),
                 ('"v1"', {'ETag': '"v1"', 'Cache-Control': 'no-store'}, b''),
                 ('"v1"', {'ETag': '"v1"', 'Vary': 'Cookie'}, b''))
        for tag, headers, body in cases:
            response = Response(status=304, headers=headers, raw=body)
            client = self.client(response)
            with self.subTest(tag=tag, headers=headers), self.assertRaises(CanvasError) as error:
                client.conditional_get('/api/v1/example', tag)
            self.assertNotIn('Synthetic private', str(error.exception))
            self.assertTrue(response.closed)
            self.assertEqual(self.send.call_count, 1)
        client = self.client(Response(status=304))
        with self.assertRaises(CanvasError):
            client.request('/api/v1/example')

    def test_http_network_status_and_malformed_json_fail_safely_without_stale_fallback(self):
        for code in (401, 403, 404, 429, 500):
            client = self.client(None)
            self.send.side_effect = HTTPError(HOST, code, 'Synthetic private reason', {}, io.BytesIO(b'private'))
            with self.subTest(code=code), self.assertRaises(CanvasError) as error:
                client.conditional_get('/api/v1/example', '"v1"')
            self.assertEqual(error.exception.status, code)
            self.assertNotIn('private', str(error.exception))
            self.assertEqual(self.send.call_count, 1)
        for raw in (b'{"id":1,"id":2}', b'{"private":NaN}', b'Synthetic private invalid json'):
            client = self.client(Response(raw=raw))
            with self.assertRaises(CanvasError) as error:
                client.conditional_get('/api/v1/example')
            self.assertNotIn('private', str(error.exception))
        for exception in (URLError('synthetic-private'), TimeoutError('synthetic-private')):
            client = self.client(None)
            self.send.side_effect = exception
            with self.assertRaises(CanvasError) as error:
                client.conditional_get('/api/v1/example')
            self.assertNotIn('synthetic-private', str(error.exception))
        client = self.client(Response(status=201))
        with self.assertRaises(CanvasError):
            client.conditional_get('/api/v1/example')

    def test_http_error_304_read_failure_is_closed_and_safe(self):
        class FailingBody(io.BytesIO):
            def read(self, *args):
                raise OSError('synthetic-private-read-failure')
        body = FailingBody()
        client = self.client(None)
        self.send.side_effect = HTTPError(HOST, 304, 'Private', {'ETag': '"v1"'}, body)
        with self.assertRaisesRegex(CanvasError, 'Network failure') as error:
            client.conditional_get('/api/v1/example', '"v1"')
        self.assertTrue(body.closed)
        self.assertNotIn('synthetic-private', str(error.exception))


class PageTests(unittest.TestCase):
    def baseline(self, page=PAGE):
        client = Mock()
        client.conditional_get.return_value = {'data': page, 'etag': '"v1"', 'not_modified': False}
        cache = PageRevalidation(None)
        stored = cache.read(client, '12', PAGE)
        return {'pages': [stored], 'page_revalidation': copy.deepcopy(cache.metadata())}

    def test_exact_id_read_and_checked_304_do_not_mutate_the_baseline(self):
        previous = self.baseline()
        original = copy.deepcopy(previous)
        cache = PageRevalidation(previous)
        client = Mock()
        client.conditional_get.return_value = {'data': None, 'etag': '"v1"', 'not_modified': True}
        page = cache.read(client, '12', PAGE)
        client.conditional_get.assert_called_once_with('/api/v1/courses/12/pages/page_id:42', '"v1"')
        self.assertEqual(page, PAGE)
        self.assertEqual(cache.stats, {'pages_fetched': 0, 'pages_revalidated': 1, 'conditional_requests': 1})
        page['body'] = 'Synthetic edited projection'
        self.assertEqual(previous, original)

    def test_legacy_malformed_duplicate_and_checksum_edited_hints_force_full_read(self):
        good = self.baseline()
        cases = [None, {}, {'pages': good['pages']}, {**good, 'pages': None},
                 {**good, 'pages': [None]}, {**good, 'pages': [PAGE, PAGE]},
                 {**good, 'page_revalidation': {'schema_version': True, 'entries': []}},
                 {**good, 'page_revalidation': {'schema_version': 1, 'entries': None}},
                 {**good, 'page_revalidation': {'schema_version': 1, 'entries': [None]}},
                 {**good, 'pages': [{**PAGE, 'page_id': True}]},
                 {**good, 'pages': [{**PAGE, 'invalid_private_field': object()}]},
                 {**good, 'pages': [{**PAGE, 'invalid_private_field': float('nan')}]},
                 {**good, 'pages': [{**PAGE, 'invalid_private_field': '\ud800'}]},
                 {**good, 'pages': [{**PAGE, 'body': 'Synthetic edited cached body'}]}]
        for change in ({'page_id': True}, {'url': 'different'}, {'etag': '*'}, {'sha256': 'wrong'}):
            entry = {**good['page_revalidation']['entries'][0], **change}
            cases.append({**good, 'page_revalidation': {'schema_version': 1, 'entries': [entry]}})
        entry = good['page_revalidation']['entries'][0]
        cases.append({**good, 'page_revalidation': {'schema_version': 1, 'entries': [entry, entry]}})
        for previous in cases:
            with self.subTest(previous=previous):
                cache = PageRevalidation(previous)
                client = Mock()
                client.conditional_get.return_value = {'data': PAGE, 'etag': None, 'not_modified': False}
                cache.read(client, '12', PAGE)
                self.assertIsNone(client.conditional_get.call_args.args[1])
                self.assertEqual(cache.entries, [])

    def test_identity_slug_and_parent_associations_must_match_current_inventory(self):
        client = Mock()
        for page in (None, [], {**PAGE, 'page_id': 43}, {**PAGE, 'page_id': True},
                     {**PAGE, 'url': 'another'}, {**PAGE, 'course_id': 13}, {**PAGE, 'course_id': True}):
            client.conditional_get.return_value = {'data': page, 'etag': '"v1"', 'not_modified': False}
            with self.subTest(page=page), self.assertRaisesRegex(CanvasError, 'different page'):
                PageRevalidation(None).read(client, '12', PAGE)
        renamed = {**PAGE, 'url': 'renamed'}
        client.conditional_get.return_value = {'data': renamed, 'etag': '"v2"', 'not_modified': False}
        cache = PageRevalidation(self.baseline())
        self.assertEqual(cache.read(client, '12', renamed), renamed)
        self.assertIsNone(client.conditional_get.call_args.args[1])

    def test_fallback_slug_no_identity_no_body_and_hidden_bodies_are_not_cached(self):
        client = Mock()
        for page in ({'url': 'week/one', 'body': 'Synthetic'}, {**PAGE, 'body': None},
                     {**PAGE, 'published': False}, {**PAGE, 'locked_for_user': True},
                     {**PAGE, 'hidden_for_user': True}):
            client.conditional_get.return_value = {'data': page, 'etag': '"v1"', 'not_modified': False}
            cache = PageRevalidation(None)
            cache.read(client, '12', {'url': page['url']})
            self.assertEqual(cache.entries, [])
        client.conditional_get.assert_called_with('/api/v1/courses/12/pages/welcome', None)
        client.conditional_get.return_value = {'data': {'url': 'week/one'}, 'etag': None, 'not_modified': False}
        PageRevalidation(None).read(client, '12', {'url': 'week/one'})
        client.conditional_get.assert_called_with('/api/v1/courses/12/pages/week%2Fone', None)

    def test_saved_fields_are_redacted_before_checksum_and_no_candidate_304_is_refused(self):
        page = {**PAGE, 'access_token': 'synthetic-private-token',
                'body': '<a href="https://storage.example.edu/file?verifier=synthetic-private">Reading</a>'}
        previous = self.baseline(page)
        self.assertNotIn('synthetic-private', json.dumps(previous))
        self.assertEqual(len(PageRevalidation(previous).candidates), 1)
        client = Mock()
        client.conditional_get.return_value = {'data': None, 'etag': '"v1"', 'not_modified': True}
        with self.assertRaisesRegex(CanvasError, 'No matching saved page'):
            PageRevalidation(None).read(client, '12', PAGE)

    def test_capture_refreshes_all_inventories_and_never_fetches_hidden_or_deleted_cached_pages(self):
        client = Mock(host=HOST)
        client.request.return_value = ({'id': 12}, '')
        client.list.side_effect = [[], [], [PAGE, {**PAGE, 'url': 'hidden', 'published': False}], [], []]
        client.conditional_get.return_value = {'data': None, 'etag': '"v1"', 'not_modified': True}
        cache = PageRevalidation(self.baseline())
        result = capture(client, '12', 100, page_revalidation=cache)
        self.assertTrue(result['complete'])
        self.assertEqual(len(result['pages']), 1)
        self.assertEqual(client.list.call_count, 5)
        self.assertEqual(client.conditional_get.call_count, 1)
        self.assertEqual(result['excluded_unpublished_or_locked_pages'], 1)
        client.list.side_effect = [[], [], [], [], []]
        client.conditional_get.reset_mock()
        result = capture(client, '12', 100, page_revalidation=PageRevalidation(self.baseline()))
        self.assertEqual(result['pages'], [])
        self.assertEqual(result['page_revalidation']['entries'], [])
        client.conditional_get.assert_not_called()

    def test_denied_page_marks_partial_and_never_retains_old_body_or_validator(self):
        for code in (403, 404):
            client = Mock(host=HOST)
            client.request.return_value = ({'id': 12}, '')
            client.list.side_effect = [[], [], [PAGE], [], []]
            client.conditional_get.side_effect = CanvasError('Synthetic denied', status=code)
            result = capture(client, '12', 100, page_revalidation=PageRevalidation(self.baseline()))
            self.assertFalse(result['complete'])
            self.assertEqual(result['pages'], [])
            self.assertEqual(result['page_revalidation']['entries'], [])
            self.assertIn('page welcome', result['unavailable'])


if __name__ == '__main__':
    unittest.main()
