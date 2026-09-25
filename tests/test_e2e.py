"""Installed CLI subprocesses against a TLS mock server; synthetic data only."""
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@unittest.skipUnless(shutil.which('openssl'), 'openssl required for local TLS fixture')
class E2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.cert = root / 'cert.pem'
        key = root / 'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(key), '-out', str(cls.cert), '-days', '1',
                        '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost'],
                       check=True, capture_output=True)
        cls.calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                cls.calls.append((self.command, self.path))
                if self.headers.get('Authorization') != 'Bearer synthetic-token':
                    self.send_response(401); self.end_headers(); return
                if self.path == '/api/v1/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/api/v1/users/self/profile')
                    self.end_headers(); return
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                if self.path == '/api/v1/courses?per_page=100':
                    self.send_header('Link', '</api/v1/courses?page=2>; rel="next"')
                    data = [{'id': 101, 'name': 'Synthetic course'}]
                elif self.path == '/api/v1/courses?page=2': data = [{'id': 102}]
                else: data = {'id': 101, 'name': 'Synthetic resource'}
                self.end_headers(); self.wfile.write(json.dumps(data).encode())
            def do_POST(self):
                cls.calls.append((self.command, self.path))
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps({'id': 999, **body}).encode())
        cls.server = ThreadingHTTPServer(('localhost', 0), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cls.cert, key)
        cls.server.socket = ctx.wrap_socket(cls.server.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); cls.tmp.cleanup()

    def invoke(self, *args, token='synthetic-token'):
        env = {**os.environ, 'CANVAS_ORIGIN': f'https://localhost:{self.server.server_port}',
               'CANVAS_TOKEN': token, 'SSL_CERT_FILE': str(self.cert), 'NO_PROXY': 'localhost'}
        return subprocess.run([sys.executable, '-m', 'canvas_pocket.cli', *args], env=env,
                              text=True, capture_output=True, timeout=10)

    def test_courses_paginate_over_tls(self):
        r = self.invoke('courses')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([x['id'] for x in json.loads(r.stdout)], [101, 102])

    def test_expired_auth(self):
        r = self.invoke('auth', 'status', token='invalid-secret')
        self.assertEqual(r.returncode, 1)
        self.assertIn('auth login', r.stderr)
        self.assertNotIn('invalid-secret', r.stderr)

    def test_redirect_refused(self):
        before = len(self.calls)
        r = self.invoke('get', '/api/v1/redirect')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(len(self.calls), before + 1)

    def test_preview_then_post(self):
        message = Path(self.tmp.name) / 'message.txt'
        message.write_text('Synthetic message')
        before = len(self.calls)
        r = self.invoke('post', '101', '202', '--message-file', str(message))
        self.assertTrue(json.loads(r.stdout)['dry_run'])
        self.assertEqual(len(self.calls), before)
        r = self.invoke('post', '101', '202', '--message-file', str(message), '--yes')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['id'], 999)
        self.assertEqual(len(self.calls), before + 1)

    def test_capabilities_without_credentials(self):
        r = self.invoke('capabilities')
        self.assertIn('get', json.loads(r.stdout)['read'])
