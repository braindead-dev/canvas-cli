import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from canvas_pocket.client import CanvasError
from canvas_pocket.download import download
from test_client import Response


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

    def test_redirect_cannot_downgrade(self):
        def send(req, **kw):
            raise HTTPError(req.full_url, 302, '', {'Location': 'http://files.example/file'}, None)
        with self.assertRaises(CanvasError):
            download('https://files.example/file', 'unused', transport=send)
