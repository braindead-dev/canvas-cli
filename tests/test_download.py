import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

from test_client import Response

from canvas_pocket.client import CanvasError
from canvas_pocket.download import download


class DownloadTests(unittest.TestCase):
    def test_no_bearer_and_no_overwrite(self):
        def send(req, **kw):
            self.assertIsNone(req.get_header('Authorization'))
            return Response(b'synthetic file')
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'out'
            result = download('https://files.example/file', path, transport=send)
            self.assertEqual(result['bytes'], 14)
            with self.assertRaises(FileExistsError):
                download('https://files.example/file', path, transport=send)
            self.assertEqual(path.read_bytes(), b'synthetic file')

    def test_size_limit_cleans_up(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'out'
            with self.assertRaises(CanvasError):
                download('https://files.example/file', path, 2, lambda *a, **kw: Response(b'large'))
            self.assertFalse(path.exists())

    def test_short_success_response_is_removed(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'out'
            with self.assertRaisesRegex(CanvasError, 'differs from Canvas metadata'):
                download('https://files.example/file', path, 100,
                         lambda *a, **kw: Response(b'short'), expected_bytes=10)
            self.assertFalse(path.exists())

    def test_invalid_or_too_large_advertised_size_stops_before_transport(self):
        def unexpected(*args, **kwargs):
            self.fail('Transport should not be used')
        for size in (-1, '10', True, 101):
            with self.subTest(size=size), self.assertRaises(CanvasError):
                download('https://files.example/file', 'unused', 100, unexpected,
                         expected_bytes=size)

    def test_redirect_cannot_downgrade(self):
        def send(req, **kw):
            raise HTTPError(req.full_url, 302, '', {'Location': 'http://files.example/file'}, None)
        with (tempfile.TemporaryDirectory() as folder,
              self.assertRaisesRegex(CanvasError, 'non-HTTPS')):
            download('https://files.example/file', Path(folder) / 'unused', transport=send)

    def test_refuses_download_inside_git_checkout_before_transport(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.git').mkdir()
            target = root / 'course.pdf'

            def unexpected(*args, **kwargs):
                self.fail('Transport should not be used')

            with self.assertRaisesRegex(CanvasError, 'Git checkout'):
                download('https://files.example/file', target, transport=unexpected)
            self.assertFalse(target.exists())
