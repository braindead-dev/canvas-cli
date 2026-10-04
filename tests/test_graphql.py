"""GraphQL shares the guarded HTTPS transport, without a generic CLI query surface."""

import json
import unittest
from urllib.error import HTTPError, URLError

from test_client import Response

from canvas_cli.client import CanvasError, Client
from canvas_cli.writes import digest, review


class GraphQLTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.body = b'{"data":{"legacyNode":{"_id":"9"}}}'
        self.status = 200
        self.client = Client('https://canvas.example.edu', 'synthetic-token', self.send)

    def send(self, request, **kwargs):
        self.calls.append(request)
        self.assertEqual(kwargs, {'timeout': 30})
        return Response(self.body, status=self.status)

    def query(self, **kwargs):
        return self.client.graphql(**({'document': 'query Synthetic { legacyNode { _id } }',
                                      'variables': {'topicId': '9'}, 'operation_name': 'Synthetic'} | kwargs))

    def test_fixed_post_origin_json_named_operation_and_bearer_use_existing_transport(self):
        self.assertEqual(self.query(), {'legacyNode': {'_id': '9'}})
        request = self.calls[0]
        self.assertEqual(request.full_url, 'https://canvas.example.edu/api/graphql')
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('Authorization'), 'Bearer synthetic-token')
        self.assertEqual(request.get_header('Content-type'), 'application/json')
        self.assertEqual(json.loads(request.data)['operationName'], 'Synthetic')
        self.assertEqual(json.loads(request.data)['variables'], {'topicId': '9'})

    def test_rest_expert_get_and_pagination_cannot_reach_graphql_or_foreign_endpoint(self):
        for route in ('/api/graphql', '/api/graphql?access_token=private',
                      'https://other.example.edu/api/graphql'):
            for method in ('GET', 'POST'):
                with self.subTest(route=route, method=method), self.assertRaises(CanvasError):
                    self.client.request(route, method, {})
        self.assertEqual(self.calls, [])

    def test_invalid_local_operation_or_json_is_refused_before_transport(self):
        for options in ({'document': None}, {'document': ' '}, {'variables': []},
                        {'operation_name': None}, {'operation_name': 'bad/operation'},
                        {'variables': {'x': float('nan')}}, {'variables': {'x': object()}}):
            with self.subTest(options=options), self.assertRaises(CanvasError):
                self.query(**options)
        self.assertEqual(self.calls, [])

    def test_errors_partial_data_wrong_shapes_and_duplicate_keys_never_leak_or_retry(self):
        for body in (b'[]', b'null', b'{"data":null}', b'{"data":[]}',
                     b'{"data":{},"errors":[{"message":"synthetic-private"}]}',
                     b'{"data":{},"errors":{}}', b'{"data":{},"data":{"private":"synthetic-private"}}',
                     b'{"data":{"x":NaN}}', b'synthetic-private'):
            self.body = body
            before = len(self.calls)
            with self.subTest(body=body), self.assertRaises(CanvasError) as caught:
                self.query()
            self.assertNotIn('synthetic-private', str(caught.exception))
            self.assertIn('repeating', str(caught.exception))
            self.assertEqual(len(self.calls) - before, 1)

    def test_null_or_empty_top_errors_are_valid_but_success_requires_http_200(self):
        for errors in (None, []):
            self.body = json.dumps({'data': {'x': 1}, 'errors': errors}).encode()
            self.assertEqual(self.query(), {'x': 1})
        for status in (201, 202, 204):
            self.status = status
            with self.subTest(status=status), self.assertRaisesRegex(CanvasError, 'HTTP acknowledgement'):
                self.query()

    def test_auth_permission_limit_redirect_network_failures_remain_private_and_non_retried(self):
        for status in (401, 403, 429, 302, 500):
            calls = []
            def fail(request, **kwargs):
                calls.append(request)
                raise HTTPError(request.full_url, status, 'synthetic-private', {}, None)
            self.client.transport = fail
            with self.subTest(status=status), self.assertRaises(CanvasError) as caught:
                self.query()
            self.assertEqual(caught.exception.status, status)
            self.assertNotIn('synthetic-private', str(caught.exception))
            self.assertEqual(len(calls), 1)
        for failure in (URLError('synthetic-private'), TimeoutError('synthetic-private')):
            calls = []
            def fail(request, **kwargs):
                calls.append(request)
                raise failure
            self.client.transport = fail
            with self.assertRaises(CanvasError) as caught:
                self.query()
            self.assertNotIn('synthetic-private', str(caught.exception))
            self.assertEqual(len(calls), 1)

    def test_pure_shared_preview_review_requires_fresh_exact_confirmation(self):
        preview = {'origin': self.client.host, 'user_id': 7, 'body': {'input': {'sortOrder': None}}}
        self.assertEqual(review(preview)['confirm'], digest(preview))
        self.assertIsNone(review(preview, True, digest(preview)))
        for yes, confirm in ((True, None), (False, 'bad'), (True, 'bad')):
            with self.assertRaises(CanvasError):
                review(preview, yes, confirm)
        self.assertEqual(self.calls, [])
