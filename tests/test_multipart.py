"""Attachment framing shares JSON's guarded bearer transport and response contract."""

import unittest
from email import policy
from email.parser import BytesParser
from unittest.mock import patch
from urllib.error import HTTPError

from test_client import Response

from canvas_cli.client import CanvasError, Client
from canvas_cli.multipart import MAX_BYTES, encode


def parts(payload, content_type):
    message = BytesParser(policy=policy.default).parsebytes(b'Content-Type: ' + content_type.encode('ascii') + b'\r\n\r\n' + payload)
    return list(message.iter_parts())


class MultipartTests(unittest.TestCase):
    def test_binary_utf8_basename_and_native_boolean_fields_are_exact(self):
        content = b'\x00\xff\r\nsynthetic-private-binary\x00'
        payload, media_type = encode({'is_announcement': True, 'lock_comment': False}, 'notes \u2603.txt', 'text/plain', content)
        decoded = parts(payload, media_type)
        self.assertEqual([row.get_param('name', header='content-disposition') for row in decoded],
                         ['is_announcement', 'lock_comment', 'attachment'])
        self.assertEqual([row.get_payload(decode=True) for row in decoded], [b'true', b'false', content])
        self.assertEqual(decoded[-1].get_filename(), 'notes \u2603.txt')
        self.assertEqual(decoded[-1].get_content_type(), 'text/plain')
        self.assertNotEqual(encode({}, 'notes.txt', 'text/plain', content)[1], media_type)

    def test_controls_header_injection_traversal_wrong_types_and_oversize_refuse_without_echo(self):
        for name in ('', '.', '..', '../notes.txt', 'a/b', 'a\\b', 'a"b', 'a\r\nsecret', 'a\x00b', '\ud800', 'x' * 256, True):
            with self.subTest(name=name), self.assertRaises(CanvasError) as result:
                encode({}, name, 'text/plain', b'x')
            self.assertNotIn('secret', str(result.exception))
        for mime in ('', 'text/plain\r\nX-Private: secret', 'text/plain; charset=utf-8', 'text/\u2603', None):
            with self.subTest(mime=mime), self.assertRaises(CanvasError):
                encode({}, 'notes.txt', mime, b'x')
        for fields in (None, [], {'attachment': 'other'}, {'x\r\nX-Private': 'secret'}, {'nested': {}},
                       {'bad': None}, {'bad': 1}, {'bad': '\x00'}, {'bad': '\ud800'}, {'bad': 'x' * 40001},
                       {str(index): 'x' for index in range(17)}):
            with self.subTest(fields=fields), self.assertRaises(CanvasError):
                encode(fields, 'notes.txt', 'text/plain', b'x')
        for content in (b'', 'x', bytearray(b'x'), b'x' * (MAX_BYTES + 1)):
            with self.subTest(length=len(content)), self.assertRaises(CanvasError):
                encode({}, 'notes.txt', 'text/plain', content)

    def test_random_boundary_collision_refuses_locally_without_retry(self):
        with patch('canvas_cli.multipart.secrets.token_hex', return_value='collision'):
            for fields, content in (({}, b'canvas-collision'), ({'message': 'canvas-collision'}, b'x')):
                with self.assertRaisesRegex(CanvasError, 'collision'):
                    encode(fields, 'notes.txt', 'text/plain', content)

    def test_same_origin_guard_and_one_api_transport_are_used_for_the_file_request(self):
        calls = []
        def send(req, **options):
            calls.append(req)
            self.assertEqual(options, {'timeout': 30})
            return Response(b'{"id":9}')
        client = Client('https://canvas.example.edu', 'synthetic-private-token', send)
        result = client.multipart('/api/v1/courses/123/discussion_topics/9?no_verifiers=true', 'PUT', {}, 'notes.txt', 'text/plain', b'x')
        self.assertEqual(result, ({'id': 9}, ''))
        self.assertEqual(calls[0].get_header('Authorization'), 'Bearer synthetic-private-token')
        self.assertEqual(calls[0].get_method(), 'PUT')
        self.assertEqual(parts(calls[0].data, calls[0].get_header('Content-type'))[-1].get_payload(decode=True), b'x')
        for route, method in (('https://foreign.example/api/v1/topics/9', 'PUT'), ('/outside', 'PUT'),
                              ('/api/v1/../outside', 'PUT'), ('/api/v1/topics/9?access_token=secret', 'PUT'),
                              ('/api/v1/topics/9', 'GET'), ('/api/v1/topics/9', 'DELETE')):
            with self.subTest(route=route, method=method), self.assertRaises(CanvasError):
                client.multipart(route, method, {}, 'notes.txt', 'text/plain', b'x')
        self.assertEqual(len(calls), 1)

    def test_uncertain_json_response_and_redirect_are_not_followed_or_retried_or_logged(self):
        for mode in ('json', 'redirect', 'denial'):
            calls = []
            def send(req, **options):
                calls.append(req)
                if mode != 'json':
                    raise HTTPError(req.full_url, 302 if mode == 'redirect' else 403, 'synthetic-private-error', {}, None)
                return Response(b'{"id":9,"id":10,"private":"synthetic-private-response"}')
            client = Client('https://canvas.example.edu', 'synthetic-private-token', send)
            with self.subTest(mode=mode), self.assertRaises(CanvasError) as result:
                client.multipart('/api/v1/courses/123/discussion_topics/9', 'PUT', {}, 'notes.txt', 'text/plain', b'x')
            self.assertEqual(len(calls), 1)
            self.assertNotIn('synthetic-private', str(result.exception))
