import io
import unittest
from urllib.error import HTTPError

from canvas_pocket.client import CanvasError, Client, origin


class Response(io.BytesIO):
    def __init__(self, body, link='', status=200):
        super().__init__(body)
        self.headers = {'Link': link}
        self.status = status


class Tests(unittest.TestCase):
    def test_empty_write_acknowledgement_requires_explicit_exact_204(self):
        client = Client('https://canvas.example.edu', 'synthetic', lambda *a, **kw: Response(b'', status=204))
        self.assertEqual(client.request('/api/v1/example', 'DELETE', expect_no_content=True), (None, ''))
        with self.assertRaisesRegex(CanvasError, 'unexpected response'):
            client.request('/api/v1/example', 'DELETE')
        for status, body in ((200, b'null'), (200, b''), (204, b'private-response')):
            client.transport = lambda *a, **kw: Response(body, status=status)
            with self.subTest(status=status, body=body), self.assertRaisesRegex(CanvasError, 'expected empty 204') as caught:
                client.request('/api/v1/example', 'DELETE', expect_no_content=True)
            self.assertNotIn('private-response', str(caught.exception))
        client.transport = lambda *a, **kw: self.fail('GET should fail before transport')
        with self.assertRaises(CanvasError):
            client.request('/api/v1/example', expect_no_content=True)

    def test_put_and_delete_use_same_origin_no_redirect_transport(self):
        calls = []
        def send(req, **kw):
            calls.append(req)
            return Response(b'{"id":41}')
        client = Client('https://canvas.example.edu', 'synthetic', send)
        client.request('/api/v1/planner_notes/41', 'PUT', {'title': 'Synthetic'})
        client.request('/api/v1/planner_notes/41', 'DELETE')
        self.assertEqual([req.get_method() for req in calls], ['PUT', 'DELETE'])
        self.assertEqual(calls[0].data, b'{"title": "Synthetic"}')
        self.assertIsNone(calls[1].data)
        with self.assertRaises(CanvasError):
            client.request('https://other.example.edu/api/v1/planner_notes/41', 'DELETE')
        self.assertEqual(len(calls), 2)

    def test_origins(self):
        for bad in ('http://example.com', 'https://user:secret@example.com', 'https://example.com/path'):
            with self.assertRaises(CanvasError): origin(bad)

    def test_pagination(self):
        replies = iter([Response(b'[]', '<https://canvas.example.edu/api/v1/courses?page=2>; rel="next"'), Response(b'[{"id":2}]')])
        c = Client('https://canvas.example.edu', 'fake', lambda *a, **kw: next(replies))
        self.assertEqual(c.list('/api/v1/courses'), [{'id': 2}])

    def test_no_cross_origin_leak(self):
        calls = []
        def send(req, **kw):
            calls.append(req)
            return Response(b'[]', '<https://evil.example/api/v1/courses>; rel="next"')
        with self.assertRaises(CanvasError):
            Client('https://canvas.example.edu', 'fake', send).list('/api/v1/courses')
        self.assertEqual(len(calls), 1)

    def test_page_limit(self):
        c = Client('https://canvas.example.edu', 'fake', lambda *a, **kw: Response(b'[]', '</api/v1/courses?page=2>; rel="next"'))
        with self.assertRaises(CanvasError): c.list('/api/v1/courses', 1)

    def test_auth_error_is_safe(self):
        def send(req, **kw):
            raise HTTPError(req.full_url, 401, 'private response', {}, None)
        with self.assertRaisesRegex(CanvasError, 'auth login') as caught:
            Client('https://canvas.example.edu', 'fake', send).request('/api/v1/courses')
        self.assertEqual(caught.exception.status, 401)

    def test_http_status_is_structured_without_exposing_response(self):
        def send(req, **kw):
            raise HTTPError(req.full_url, 404, 'private response', {}, None)
        with self.assertRaises(CanvasError) as caught:
            Client('https://canvas.example.edu', 'fake', send).request('/api/v1/courses/1/pages')
        self.assertEqual(caught.exception.status, 404)
        self.assertNotIn('private response', str(caught.exception))

    def test_conversation_get_cannot_mark_inbox_read(self):
        calls = []
        def send(req, **kw):
            calls.append(req)
            return Response(b'{"id":2}')
        client = Client('https://canvas.example.edu', 'fake', send)
        with self.assertRaisesRegex(CanvasError, 'auto_mark_as_read=false'):
            client.request('/api/v1/conversations/2')
        self.assertEqual(calls, [])
        data, _ = client.request('/api/v1/conversations/2?auto_mark_as_read=false')
        self.assertEqual(data['id'], 2)
        self.assertEqual(len(calls), 1)

    def test_submission_read_status_include_is_blocked_before_transport(self):
        calls = []
        def send(req, **kw):
            calls.append(req)
            return Response(b'{}')
        client = Client('https://canvas.example.edu', 'fake', send)
        for route in ('/api/v1/courses/1/assignments/2/submissions/self?include[]=read_status',
                      '/api/v1/courses/1/students/submissions?include%5B%5D=read_status'):
            with self.assertRaisesRegex(CanvasError, 'marks submissions read'):
                client.request(route)
        self.assertEqual(calls, [])

    def test_conversation_aliases_and_parameter_shapes_do_not_bypass_no_read_guard(self):
        calls = []
        def send(req, **kw):
            calls.append(req)
            return Response(b'{"id":2}')
        client = Client('https://canvas.example.edu', 'synthetic', send)
        paths = ('/api/v1/conversations/2/', '/api/v1/conversations/2.json',
                 '/api/v1/%63onversations/2', '/api/v1/conversations/%32',
                 '/api/v1//conversations/2', '/api/v1/conversations%2F2')
        for path in paths:
            with self.subTest(path=path), self.assertRaisesRegex(CanvasError, 'auto_mark_as_read=false'):
                client.request(path)
        for query in ('auto_mark_as_read=true', 'auto_mark_as_read[]=false',
                      'auto_mark_as_read=false&auto_mark_as_read=',
                      'auto_mark_as_read=false&auto_mark_as_read[0]=true'):
            with self.subTest(query=query), self.assertRaises(CanvasError):
                client.request('/api/v1/conversations/2?' + query)
        self.assertEqual(calls, [])
        for path in paths:
            client.request(path + '?auto_mark_as_read=false')
        self.assertEqual(len(calls), len(paths))

    def test_indexed_and_scalar_include_shapes_cannot_mark_submissions_read(self):
        calls = []
        def send(req, **kw):
            calls.append(req)
            return Response(b'{}')
        client = Client('https://canvas.example.edu', 'synthetic', send)
        for query in ('include=read_status', 'include[0]=read_status', 'include%5B1%5D=read_status',
                      'include=submission_comments,read_status', 'include[]=submission_comments&include[]=read_status',
                      'access_token[]=secret', 'as_user_id[0]=7'):
            with self.subTest(query=query), self.assertRaises(CanvasError):
                client.request('/api/v1/courses/1/assignments/2/submissions/self?' + query)
        self.assertEqual(calls, [])
        client.request('/api/v1/courses/1/assignments/2/submissions/self?include[0]=submission_comments')
        self.assertEqual(len(calls), 1)

    def test_new_quiz_namespace_stays_on_canvas_origin(self):
        calls = []
        def send(req, **kw):
            calls.append(req.full_url)
            return Response(b'[]')
        client = Client('https://canvas.example.edu', 'fake', send)
        self.assertEqual(client.list('/api/quiz/v1/courses/1/quizzes'), [])
        self.assertEqual(calls, ['https://canvas.example.edu/api/quiz/v1/courses/1/quizzes'])
        with self.assertRaises(CanvasError):
            client.request('https://other.example.edu/api/quiz/v1/courses/1/quizzes')
        with self.assertRaises(CanvasError):
            client.request('/api/quiz/v1/../users/1')
        self.assertEqual(len(calls), 1)


if __name__ == '__main__': unittest.main()
