import io
import unittest
from urllib.error import HTTPError

from canvas_pocket.client import CanvasError, Client, origin


class Response(io.BytesIO):
    def __init__(self, body, link=''):
        super().__init__(body)
        self.headers = {'Link': link}


class Tests(unittest.TestCase):
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
        with self.assertRaisesRegex(CanvasError, 'auth login'):
            Client('https://canvas.example.edu', 'fake', send).request('/api/v1/courses')

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
