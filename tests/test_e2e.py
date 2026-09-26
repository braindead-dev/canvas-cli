"""Installed CLI subprocesses against a TLS mock server; synthetic data only."""
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


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
                if self.path == '/storage/synthetic-file':
                    cls.storage_download_auth = self.headers.get('Authorization')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.end_headers()
                    self.wfile.write(b'Synthetic file bytes')
                    return
                if self.headers.get('Authorization') != 'Bearer synthetic-token':
                    self.send_response(401); self.end_headers(); return
                if self.path == '/api/v1/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/api/v1/users/self/profile')
                    self.end_headers(); return
                if self.path.startswith(('/api/v1/courses/101/files?per_page=',
                                         '/api/v1/courses/103/files?per_page=')):
                    self.send_response(403); self.end_headers(); return
                if self.path == '/api/v1/courses/101/pages?per_page=1':
                    self.send_response(404); self.end_headers(); return
                if self.path == '/api/v1/courses/102/pages?per_page=100':
                    self.send_response(404); self.end_headers(); return
                if self.path.startswith('/api/v1/courses/102/pages?per_page=100&search_term='):
                    self.send_response(404); self.end_headers(); return
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                if self.path == '/api/v1/courses?per_page=100':
                    self.send_header('Link', '</api/v1/courses?page=2>; rel="next"')
                    data = [{'id': 101, 'name': 'Synthetic course'}]
                elif self.path == '/api/v1/courses?page=2': data = [{'id': 102}]
                elif self.path == '/api/v1/courses?enrollment_state=active&per_page=100':
                    data = [{'id': 101, 'name': 'Synthetic course', 'course_code': 'TEST 101', 'workflow_state': 'available'}]
                elif self.path == '/api/v1/users/self/upcoming_events?per_page=100':
                    data = [{'id': 55, 'title': 'Synthetic upcoming event'}]
                elif self.path == '/api/v1/users/self/todo?per_page=100':
                    data = [{'id': 77}]
                elif self.path == '/api/v1/courses/101/assignments?per_page=100':
                    data = [{'id': 88, 'name': 'Synthetic paper',
                             'due_at': (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()}]
                elif self.path == '/api/v1/courses/103/assignments?per_page=100':
                    data = []
                elif self.path == '/api/v1/courses/101/assignments?per_page=100&search_term=Synthetic':
                    data = [{'id': 88, 'name': 'Synthetic paper',
                             'due_at': '2026-10-01T00:00:00Z'}]
                elif self.path == '/api/v1/courses/101/assignments?include%5B%5D=submission&per_page=100':
                    data = [{'id': 88, 'name': 'Synthetic paper',
                             'due_at': (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
                             'submission': {'workflow_state': 'submitted', 'submitted_at': '2026-09-01T12:00:00Z'}}]
                elif self.path == '/api/v1/courses/101?include[]=syllabus_body':
                    data = {'id': 101, 'syllabus_body': '<a href="/courses/101/files/7">Syllabus</a>'}
                elif self.path == '/api/v1/courses/103?include[]=syllabus_body':
                    data = {'id': 103, 'syllabus_body': '<a href="/courses/103/files/8">Reading</a>'}
                elif self.path in (
                    '/api/v1/courses/101/modules?include[]=items&per_page=100',
                    '/api/v1/courses/103/modules?include[]=items&per_page=100',
                ):
                    data = []
                elif self.path == '/api/v1/courses/101/files/7':
                    data = {'display_name': 'synthetic-syllabus.pdf', 'size': 123,
                            'hidden_for_user': True, 'url': 'https://files.example.edu/item'}
                elif self.path == '/api/v1/courses/103/files/8':
                    data = {'id': 8, 'display_name': 'synthetic-reading.pdf', 'size': 20,
                            'updated_at': '2026-09-25T00:00:00Z',
                            'url': f'https://localhost:{cls.server.server_port}/storage/synthetic-file'}
                elif self.path == '/api/v1/courses/103/files/9':
                    data = {'id': 9, 'display_name': 'synthetic-truncated.pdf', 'size': 25,
                            'url': f'https://localhost:{cls.server.server_port}/storage/synthetic-file'}
                elif self.path == '/api/v1/courses/101/assignments/88/submissions/self?include[]=submission_comments&include[]=rubric_assessment':
                    data = {'assignment_id': 88, 'workflow_state': 'submitted',
                            'submitted_at': '2026-09-01T12:00:00Z', 'grade': 'A',
                            'submission_comments': [{'comment': 'Synthetic feedback'}]}
                elif self.path == '/api/v1/courses/101/assignments/88':
                    data = {'id': 88, 'course_id': 101, 'name': 'Synthetic paper',
                            'published': True, 'locked_for_user': False,
                            'submission_types': ['online_url', 'online_text_entry'],
                            'due_at': '2026-10-01T00:00:00Z'}
                elif self.path == '/api/v1/courses/101/assignments/89':
                    data = {'id': 89, 'course_id': 101, 'name': 'Synthetic upload',
                            'published': True, 'locked_for_user': False,
                            'submission_types': ['online_upload'],
                            'allowed_extensions': ['txt']}
                elif self.path == '/api/v1/courses/101/discussion_topics/202':
                    data = {'id': 202, 'context_id': 101, 'title': 'Synthetic discussion',
                            'published': True, 'locked_for_user': False}
                elif self.path == '/api/v1/courses/101/discussion_topics/202/entries?per_page=100':
                    data = [{'id': 301, 'user_name': 'Synthetic student',
                             'message': '<p>Sample entry</p>', 'has_more_replies': True,
                             'recent_replies': [{'id': 401, 'message': 'Newest'}]}]
                elif self.path == '/api/v1/courses/101/discussion_topics/202/entries/301/replies?per_page=100':
                    data = [{'id': 401, 'message': 'Newest'},
                            {'id': 400, 'message': 'Older'}]
                elif self.path == '/api/v1/files/777/create_success':
                    data = {'id': 777, 'display_name': 'synthetic.txt'}
                elif self.path == '/api/v1/files/777':
                    data = {'id': 777, 'display_name': 'synthetic.txt', 'size': 22,
                            'uuid': 'synthetic-uuid', 'locked_for_user': False}
                elif self.path == '/api/v1/users/self/files?per_page=100' or self.path == '/api/v1/users/self/files?per_page=100&search_term=synthetic':
                    data = [{'id': 777, 'display_name': 'synthetic.txt', 'size': 22}]
                elif self.path == '/api/v1/users/self/profile':
                    data = {'id': 7, 'name': 'Synthetic Student'}
                elif self.path == '/api/v1/courses/101/enrollments?user_id=7&per_page=100':
                    data = [{'id': 30, 'user_id': 7, 'course_id': 101,
                             'grades': {'current_score': 95}}]
                elif self.path == '/api/v1/courses/101/folders?per_page=100':
                    data = [{'id': 3, 'name': 'Synthetic folder'}]
                elif self.path == '/api/v1/folders/3/files?per_page=100':
                    data = [{'id': 4, 'display_name': 'Synthetic file.pdf'}]
                elif self.path == '/api/v1/courses/101/sections?per_page=100':
                    data = [{'id': 5, 'name': 'Synthetic section'}]
                elif self.path == '/api/v1/courses/101/assignment_groups?per_page=100':
                    data = [{'id': 30, 'name': 'Projects', 'group_weight': 35}]
                elif self.path == '/api/v1/courses/101/rubrics?per_page=100':
                    data = [{'id': 31, 'title': 'Project rubric'}]
                elif self.path == '/api/v1/courses/101/quizzes?per_page=100':
                    data = [{'id': 32, 'title': 'Week 1 metadata', 'due_at': '2026-10-01T00:00:00Z'}]
                elif self.path == '/api/quiz/v1/courses/101/quizzes?per_page=100':
                    data = [{'id': 33, 'assignment_id': 34, 'title': 'Synthetic New Quiz'}]
                elif self.path == '/api/quiz/v1/courses/101/quizzes/34':
                    data = {'id': 33, 'assignment_id': 34, 'title': 'Synthetic New Quiz'}
                elif self.path == '/api/v1/courses/101/modules?per_page=100':
                    data = [{'id': 6, 'name': 'Week 1'}]
                elif self.path == '/api/v1/courses/102/modules?per_page=100':
                    data = [{'id': 7, 'name': 'Week 1', 'published': True}]
                elif self.path == '/api/v1/courses/101/modules/6/items?per_page=100':
                    data = [{'id': 9, 'title': 'Welcome', 'type': 'Page'}]
                elif self.path == '/api/v1/courses/102/modules/7/items?per_page=100':
                    data = [{'id': 10, 'title': 'Welcome', 'type': 'Page', 'page_url': 'welcome'},
                            {'id': 11, 'title': 'Hidden', 'type': 'Page', 'page_url': 'hidden',
                             'published': False}]
                elif self.path == '/api/v1/courses/101/pages?per_page=100':
                    data = [{'url': 'welcome', 'title': 'Welcome', 'published': True}]
                elif self.path == '/api/v1/courses/101/pages/welcome':
                    data = {'url': 'welcome', 'title': 'Welcome', 'published': True,
                            'body': '<p>Synthetic page</p>'}
                elif self.path == '/api/v1/courses/101/front_page':
                    data = {'url': 'welcome', 'title': 'Welcome', 'published': True,
                            'body': '<p>Synthetic front page</p>'}
                elif self.path == '/api/v1/courses/101/tabs?per_page=100':
                    data = [{'id': 'home', 'label': 'Home', 'html_url': '/courses/101',
                             'visibility': 'public', 'position': 1}]
                elif self.path == '/api/v1/courses/102/pages/welcome':
                    data = {'url': 'welcome', 'title': 'Welcome', 'published': True,
                            'body': '<p>Should not be printed in page index</p>'}
                elif self.path == '/api/v1/courses/101/discussion_topics?per_page=100&only_announcements=true':
                    data = [{'id': 22, 'title': 'Synthetic announcement',
                             'message': '<a href="/courses/101/files/7">Reading</a>'}]
                elif self.path == '/api/v1/courses/101/discussion_topics?per_page=100':
                    data = [{'id': 23, 'title': 'Synthetic discussion prompt',
                             'message': '<a href="/courses/101/files/7">Prompt file</a>'}]
                elif self.path == '/api/v1/courses/101/discussion_topics?per_page=100&only_announcements=false':
                    data = [{'id': 23, 'title': 'Synthetic discussion prompt',
                             'message': '<p>Discussion instructions</p>', 'published': True}]
                elif self.path in ('/api/v1/courses/103/discussion_topics?per_page=100',
                                   '/api/v1/courses/103/discussion_topics?per_page=100&only_announcements=true',
                                   '/api/v1/courses/103/discussion_topics?per_page=100&only_announcements=false'):
                    data = []
                elif self.path.startswith('/api/v1/calendar_events?'):
                    data = [{'id': 10, 'title': 'Synthetic event'}]
                elif self.path == '/api/v1/users/self/groups?per_page=100':
                    data = [{'id': 11, 'name': 'Synthetic group'}]
                elif self.path == '/api/v1/users/self/favorites/courses?per_page=100':
                    data = [{'id': 101, 'name': 'Synthetic course'}]
                elif self.path == '/api/v1/conversations?per_page=100&scope=unread':
                    data = [{'id': 12, 'subject': 'Synthetic inbox thread'}]
                elif self.path == '/api/v1/conversations/12?auto_mark_as_read=false':
                    data = {'id': 12, 'subject': 'Synthetic thread',
                            'participants': [{'id': 7, 'name': 'Synthetic recipient'}], 'audience': [7],
                            'messages': [{'body': 'Synthetic private message'}]}
                elif self.path == '/api/v1/search/recipients?type=user&per_page=100&user_id=7' or self.path.startswith('/api/v1/search/recipients?type=user&per_page=100&search='):
                    data = [{'id': 7, 'name': 'Synthetic recipient', 'type': 'user'}]
                elif self.path.startswith('/api/v1/announcements?'):
                    data = [{'id': 60, 'title': 'Synthetic announcement',
                             'posted_at': '2026-09-25T12:00:00Z', 'message': '<p>Synthetic update</p>'}]
                else: data = {'id': 101, 'name': 'Synthetic resource'}
                self.end_headers(); self.wfile.write(json.dumps(data).encode())
            def do_POST(self):
                cls.calls.append((self.command, self.path))
                raw = self.rfile.read(int(self.headers['Content-Length']))
                if self.path.startswith('/storage/upload'):
                    cls.storage_auth = self.headers.get('Authorization')
                    cls.storage_body = raw
                    cls.storage_type = self.headers.get('Content-Type')
                    self.send_response(201 if self.path.endswith('-created') else 303)
                    location = ('https://untrusted.example.org/api/v1/files/777/create_success'
                                if self.path.endswith('-foreign') else
                                f'https://localhost:{cls.server.server_port}/api/v1/files/777/create_success')
                    self.send_header('Location', location)
                    self.end_headers(); return
                if self.headers.get('Authorization') != 'Bearer synthetic-token':
                    self.send_response(401); self.end_headers(); return
                body = json.loads(raw)
                if self.path in ('/api/v1/users/self/files',
                                 '/api/v1/courses/101/assignments/89/submissions/self/files'):
                    cls.upload_initial = body
                    suffix = ('-created' if body['name'] == 'created.txt' else
                              '-foreign' if body['name'] == 'foreign.txt' else '')
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps({
                        'upload_url': f'https://localhost:{cls.server.server_port}/storage/upload{suffix}',
                        'upload_params': {'key': 'synthetic-key'},
                    }).encode()); return
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
                              text=True, capture_output=True, timeout=10, check=False)

    def test_courses_paginate_over_tls(self):
        r = self.invoke('courses')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([x['id'] for x in json.loads(r.stdout)], [101, 102])

    def test_expired_auth(self):
        r = self.invoke('auth', 'status', token='invalid-secret')
        self.assertEqual(r.returncode, 1)
        self.assertIn('auth login', r.stderr)
        self.assertNotIn('invalid-secret', r.stderr)

    def test_overview_against_tls_fixture(self):
        r = self.invoke('overview')
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data['courses'][0]['id'], 101)
        self.assertEqual(data['upcoming'][0]['id'], 55)
        self.assertEqual(data['todo'][0]['id'], 77)
        self.assertEqual(data['deadlines']['assignments'][0]['assignment_id'], 88)

    def test_brief_overview_is_readable(self):
        r = self.invoke('--format', 'brief', 'overview')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('Active courses\n101  TEST 101 — Synthetic course', r.stdout)
        self.assertIn('Upcoming\n55  Synthetic upcoming event', r.stdout)
        self.assertIn('Deadlines (next 14 days)\n88  Synthetic course: Synthetic paper', r.stdout)

    def test_deadlines_brief_and_linked_files_without_files_list(self):
        due = self.invoke('--format', 'brief', 'deadlines')
        self.assertEqual(due.returncode, 0, due.stderr)
        self.assertIn('88  Synthetic course: Synthetic paper', due.stdout)
        self.assertNotIn('unavailable', due.stdout)
        listing = self.invoke('files', '101')
        self.assertEqual(listing.returncode, 1)
        fallback = self.invoke('files', '101', '--best-effort', '--quick')
        self.assertEqual(fallback.returncode, 0, fallback.stderr)
        self.assertFalse(json.loads(fallback.stdout)['complete'])
        self.assertEqual(json.loads(fallback.stdout)['source'], 'linked-content')
        self.assertEqual(json.loads(fallback.stdout)['files'][0]['id'], 7)
        linked = self.invoke('linked-files', '101')
        self.assertEqual(linked.returncode, 0, linked.stderr)
        self.assertEqual(json.loads(linked.stdout)['files'][0]['display_name'], 'synthetic-syllabus.pdf')
        self.assertFalse(json.loads(linked.stdout)['files'][0]['downloadable'])
        self.assertIn('announcement: Synthetic announcement',
                      json.loads(linked.stdout)['files'][0]['sources'])
        self.assertIn('discussion prompt: Synthetic discussion prompt',
                      json.loads(linked.stdout)['files'][0]['sources'])
        brief = self.invoke('--format', 'brief', 'linked-files', '101')
        self.assertIn('not downloadable', brief.stdout)
        quick = self.invoke('linked-files', '101', '--quick')
        self.assertEqual(quick.returncode, 0, quick.stderr)
        self.assertTrue(json.loads(quick.stdout)['files'][0]['metadata_not_checked'])

    def test_own_submission_and_feedback_are_read_only(self):
        before = len(self.calls)
        result = self.invoke('submission', '101', '88')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['submission_comments'][0]['comment'], 'Synthetic feedback')
        self.assertEqual(self.calls[before:], [('GET', '/api/v1/courses/101/assignments/88/submissions/self?include[]=submission_comments&include[]=rubric_assessment')])
        brief = self.invoke('--format', 'brief', 'submission', '101', '88')
        self.assertIn('Status: submitted', brief.stdout)
        self.assertIn('Comments: 1', brief.stdout)

    def test_work_board_over_tls_is_read_only(self):
        before = len(self.calls)
        result = self.invoke('work', '--course', '101', '--days', '14')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['assignments'][0]['status'], 'submitted')
        self.assertEqual(self.calls[before:], [
            ('GET', '/api/v1/courses/101/assignments?include%5B%5D=submission&per_page=100')])
        brief = self.invoke('--format', 'brief', 'work', '--course', '101')
        self.assertIn('Synthetic paper [submitted]', brief.stdout)

    def test_cross_course_news_over_tls_is_read_only(self):
        before = len(self.calls)
        result = self.invoke('news', '--course', '101')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['announcements'][0]['message'], '<p>Synthetic update</p>')
        self.assertEqual(len(self.calls[before:]), 1)
        self.assertEqual(self.calls[before][0], 'GET')
        self.assertIn('context_codes%5B%5D=course_101', self.calls[before][1])
        brief = self.invoke('--format', 'brief', 'news', '--course', '101')
        self.assertIn('Synthetic announcement', brief.stdout)

    def test_grading_and_quiz_metadata_over_tls(self):
        before = len(self.calls)
        commands = [('assignment-groups', 'group_weight', 35),
                    ('rubrics', 'title', 'Project rubric'),
                    ('quizzes', 'title', 'Week 1 metadata')]
        for command, key, expected in commands:
            with self.subTest(command=command):
                result = self.invoke(command, '101')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)[0][key], expected)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        self.assertFalse(any('/submissions' in route for _, route in self.calls[before:]))
        new = self.invoke('new-quizzes', '101')
        self.assertEqual(new.returncode, 0, new.stderr)
        self.assertEqual(json.loads(new.stdout)[0]['assignment_id'], 34)
        single = self.invoke('new-quiz', '101', '34')
        self.assertEqual(single.returncode, 0, single.stderr)
        self.assertEqual(json.loads(single.stdout)['title'], 'Synthetic New Quiz')
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))

    def test_batch_download_needs_matching_preview_and_excludes_bearer_from_storage(self):
        directory = Path(self.tmp.name) / 'synthetic-downloads'
        directory.mkdir(exist_ok=True)
        command = ('download-linked', '103', '--directory', str(directory))
        before = len(self.calls)
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        plan = json.loads(preview.stdout)
        self.assertTrue(plan['dry_run'])
        self.assertEqual(len(plan['files']), 1)
        self.assertFalse(list(directory.iterdir()))
        chosen = self.invoke(*command, '--file', '8')
        self.assertEqual(chosen.returncode, 0, chosen.stderr)
        self.assertEqual(json.loads(chosen.stdout)['selected_file_ids'], ['8'])
        unknown = self.invoke(*command, '--file', '999')
        self.assertEqual(unknown.returncode, 1)
        self.assertIn('not discovered', unknown.stderr)
        missing = self.invoke(*command, '--yes')
        self.assertEqual(missing.returncode, 1)
        self.assertIn('--confirm', missing.stderr)
        wrong = self.invoke(*command, '--yes', '--confirm', 'wrong')
        self.assertEqual(wrong.returncode, 1)
        self.assertFalse(list(directory.iterdir()))
        saved = self.invoke(*command, '--yes', '--confirm', plan['confirm'])
        self.assertEqual(saved.returncode, 0, saved.stderr)
        self.assertEqual((directory / '8-synthetic-reading.pdf').read_bytes(),
                         b'Synthetic file bytes')
        self.assertIsNone(self.storage_download_auth)
        self.assertEqual([call for call in self.calls[before:]
                          if call[1] == '/storage/synthetic-file'],
                         [('GET', '/storage/synthetic-file')])

    def test_file_title_search_has_partial_linked_fallback(self):
        result = self.invoke('find', '103', '--query', 'reading', '--area', 'files')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data['complete'])
        self.assertEqual(data['coverage']['files'], 'linked_files_only')
        self.assertEqual(data['results'][0]['id'], 8)

    def test_single_download_refuses_short_success_response(self):
        destination = Path(self.tmp.name) / 'synthetic-truncated.pdf'
        result = self.invoke('download', '103', '9', '--output', str(destination))
        self.assertEqual(result.returncode, 1)
        self.assertIn('differs from Canvas metadata', result.stderr)
        self.assertFalse(destination.exists())

    def test_assignment_submission_preview_and_confirm_over_tls(self):
        source = Path(self.tmp.name) / 'project-url.txt'
        source.write_text('https://example.edu/synthetic-project')
        before = len(self.calls)
        command = ('submit-url', '101', '88', '--url-file', str(source))
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertTrue(data['dry_run'])
        self.assertEqual(self.calls[before:], [('GET', '/api/v1/courses/101/assignments/88')])
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(self.calls[-2:], [
            ('GET', '/api/v1/courses/101/assignments/88'),
            ('POST', '/api/v1/courses/101/assignments/88/submissions')])

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
        preview = json.loads(r.stdout)
        self.assertTrue(preview['dry_run'])
        self.assertEqual(self.calls[before:], [('GET', '/api/v1/courses/101/discussion_topics/202')])
        r = self.invoke('post', '101', '202', '--message-file', str(message), '--yes',
                        '--confirm', preview['confirm'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['id'], 999)
        self.assertEqual(self.calls[-2:], [
            ('GET', '/api/v1/courses/101/discussion_topics/202'),
            ('POST', '/api/v1/courses/101/discussion_topics/202/entries')])

    def test_capabilities_without_credentials(self):
        r = self.invoke('capabilities')
        self.assertIn('get', json.loads(r.stdout)['read'])

    def test_new_read_commands_over_tls(self):
        before = len(self.calls)
        commands = [
            (['grades', '101'], lambda d: d[0]['grades']['current_score'] == 95),
            (['folders', '101'], lambda d: d[0]['id'] == 3),
            (['folder-files', '3'], lambda d: d[0]['id'] == 4),
            (['sections', '101'], lambda d: d[0]['id'] == 5),
            (['outline', '101'], lambda d: d[0]['items'][0]['title'] == 'Welcome'),
            (['calendar', '--start', '2026-09-25', '--end', '2026-09-30', '--course', '101'],
             lambda d: d[0]['id'] == 10),
        ]
        for command, check in commands:
            with self.subTest(command=command):
                result = self.invoke(*command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(check(json.loads(result.stdout)))
        outline = self.invoke('--format', 'brief', 'outline', '101')
        self.assertIn('Week 1\n  9  Welcome', outline.stdout)
        grades = self.invoke('--format', 'brief', 'grades', '101')
        self.assertIn('Course 101: 95', grades.stdout)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))

    def test_snapshot_over_tls_is_private_and_read_only(self):
        destination = Path(self.tmp.name) / 'course-snapshot.json'
        before = len(self.calls)
        result = self.invoke('snapshot', '101', '--output', str(destination))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['complete'])
        snapshot = json.loads(destination.read_text())
        self.assertEqual(snapshot['pages'][0]['body'], '<p>Synthetic page</p>')
        self.assertEqual(snapshot['announcements'][0]['id'], 22)
        self.assertEqual(snapshot['discussions'][0]['title'], 'Synthetic discussion prompt')
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        repeated = self.invoke('snapshot', '101', '--output', str(destination))
        self.assertEqual(repeated.returncode, 1)

    def test_page_index_fallback_over_tls_is_explicitly_partial(self):
        before = len(self.calls)
        raw = self.invoke('pages', '102')
        self.assertEqual(raw.returncode, 1)
        fallback = self.invoke('pages', '102', '--best-effort')
        self.assertEqual(fallback.returncode, 0, fallback.stderr)
        result = json.loads(fallback.stdout)
        self.assertFalse(result['complete'])
        self.assertEqual(result['source'], 'module-pages')
        self.assertEqual([page['url'] for page in result['pages']], ['welcome'])
        self.assertNotIn('Should not be printed', fallback.stdout)
        self.assertNotIn('/pages/hidden', str(self.calls[before:]))
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))

    def test_page_title_search_falls_back_over_tls(self):
        before = len(self.calls)
        result = self.invoke('find', '102', '--query', 'welcome', '--area', 'pages')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data['complete'])
        self.assertEqual(data['coverage']['pages'], 'module_pages_only')
        self.assertEqual([row['id'] for row in data['results']], ['welcome'])
        self.assertNotIn('Should not be printed', result.stdout)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))

    def test_course_navigation_over_tls(self):
        before = len(self.calls)
        tabs = self.invoke('tabs', '101')
        self.assertEqual(tabs.returncode, 0, tabs.stderr)
        self.assertEqual(json.loads(tabs.stdout)[0]['id'], 'home')
        front = self.invoke('front-page', '101')
        self.assertEqual(front.returncode, 0, front.stderr)
        self.assertEqual(json.loads(front.stdout)['url'], 'welcome')
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))

    def test_discussion_thread_over_tls_follows_reply_pagination(self):
        before = len(self.calls)
        result = self.invoke('thread', '101', '202')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['complete'])
        self.assertEqual([reply['id'] for reply in data['entries'][0]['replies']], [401, 400])
        self.assertEqual(self.calls[before:], [
            ('GET', '/api/v1/courses/101/discussion_topics/202'),
            ('GET', '/api/v1/courses/101/discussion_topics/202/entries?per_page=100'),
            ('GET', '/api/v1/courses/101/discussion_topics/202/entries/301/replies?per_page=100')])

    def test_private_sync_over_tls_keeps_snapshots_out_of_stdout(self):
        directory = Path(self.tmp.name) / 'private-sync'
        before = len(self.calls)
        first = self.invoke('sync', '101', '--directory', str(directory))
        self.assertEqual(first.returncode, 0, first.stderr)
        baseline = json.loads(first.stdout)
        self.assertTrue(baseline['baseline'])
        second = self.invoke('sync', '101', '--directory', str(directory))
        self.assertEqual(second.returncode, 0, second.stderr)
        changed = json.loads(second.stdout)
        self.assertFalse(changed['baseline'])
        self.assertEqual(changed['previous'], baseline['saved'])
        self.assertNotIn('<p>Synthetic page</p>', second.stdout)
        self.assertEqual(len(list(directory.glob('*.json'))), 2)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))

    def test_inbox_read_does_not_change_read_state(self):
        before = len(self.calls)
        inbox = self.invoke('inbox', '--scope', 'unread')
        self.assertEqual(inbox.returncode, 0, inbox.stderr)
        self.assertEqual(json.loads(inbox.stdout)[0]['id'], 12)
        thread = self.invoke('conversation', '12')
        self.assertEqual(thread.returncode, 0, thread.stderr)
        self.assertEqual(json.loads(thread.stdout)['messages'][0]['body'],
                         'Synthetic private message')
        self.assertEqual(self.calls[before:], [
            ('GET', '/api/v1/conversations?per_page=100&scope=unread'),
            ('GET', '/api/v1/conversations/12?auto_mark_as_read=false')])

    def test_inbox_reply_preview_and_confirm_over_tls(self):
        message = Path(self.tmp.name) / 'inbox-reply.txt'
        message.write_text('Synthetic reply')
        before = len(self.calls)
        command = ('inbox-reply', '12', '--message-file', str(message))
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertTrue(data['dry_run'])
        self.assertEqual(self.calls[before:], [
            ('GET', '/api/v1/conversations/12?auto_mark_as_read=false')])
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(self.calls[-2:], [
            ('GET', '/api/v1/conversations/12?auto_mark_as_read=false'),
            ('POST', '/api/v1/conversations/12/add_message')])

    def test_recipient_lookup_and_compose_preview_over_tls(self):
        source = Path(self.tmp.name) / 'compose.txt'
        source.write_text('Synthetic hello')
        before = len(self.calls)
        found = self.invoke('recipients', '--search', 'Synthetic')
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertEqual(json.loads(found.stdout)[0]['id'], 7)
        command = ('inbox-compose', '--recipient', '7', '--subject', 'Synthetic subject',
                   '--message-file', str(source))
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertTrue(data['dry_run'])
        self.assertEqual([method for method, _ in self.calls[before:]], ['GET', 'GET'])
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(self.calls[-2:], [
            ('GET', '/api/v1/search/recipients?type=user&per_page=100&user_id=7'),
            ('POST', '/api/v1/conversations')])

    def test_personal_upload_three_step_tls_and_no_storage_token(self):
        source = Path(self.tmp.name) / 'synthetic.txt'
        source.write_text('Synthetic upload bytes')
        command = ('upload-personal', '--file', str(source))
        before = len(self.calls)
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertTrue(data['dry_run'])
        self.assertEqual(len(self.calls), before)
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(json.loads(sent.stdout)['uploaded_file_id'], 777)
        self.assertEqual(self.upload_initial['on_duplicate'], 'rename')
        self.assertIsNone(self.storage_auth)
        self.assertIn('multipart/form-data', self.storage_type)
        self.assertIn(b'synthetic-key', self.storage_body)
        self.assertIn(b'Synthetic upload bytes', self.storage_body)
        self.assertLess(self.storage_body.index(b'synthetic-key'),
                        self.storage_body.index(b'Synthetic upload bytes'))
        self.assertEqual(self.calls[-3:], [
            ('POST', '/api/v1/users/self/files'), ('POST', '/storage/upload'),
            ('GET', '/api/v1/files/777/create_success')])

    def test_assignment_upload_is_not_assignment_submission(self):
        source = Path(self.tmp.name) / 'synthetic.txt'
        source.write_text('Synthetic upload bytes')
        command = ('upload-assignment-file', '101', '89', '--file', str(source))
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertTrue(data['dry_run'])
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertIn('not submitted', json.loads(sent.stdout)['note'])
        self.assertNotIn('on_duplicate', self.upload_initial)
        self.assertNotIn(('POST', '/api/v1/courses/101/assignments/89/submissions'),
                         self.calls)

    def test_storage_201_location_is_confirmed(self):
        source = Path(self.tmp.name) / 'created.txt'
        source.write_text('Synthetic 201 upload')
        command = ('upload-personal', '--file', str(source))
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        sent = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(json.loads(sent.stdout)['uploaded_file_id'], 777)

    def test_foreign_confirmation_refused_without_token_leak(self):
        source = Path(self.tmp.name) / 'foreign.txt'
        source.write_text('Synthetic hostile redirect')
        command = ('upload-personal', '--file', str(source))
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        before = len(self.calls)
        sent = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertEqual(sent.returncode, 1)
        self.assertIn('confirmation failed', sent.stderr)
        self.assertEqual(self.calls[before:], [
            ('POST', '/api/v1/users/self/files'), ('POST', '/storage/upload-foreign')])
        self.assertIsNone(self.storage_auth)
        self.assertNotIn('untrusted.example.org', sent.stderr)

    def test_submit_uploaded_file_preview_and_confirm(self):
        command = ('submit-file', '101', '89', '777')
        before = len(self.calls)
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertTrue(data['dry_run'])
        self.assertEqual(data['file']['name'], 'synthetic.txt')
        self.assertEqual(self.calls[before:], [
            ('GET', '/api/v1/courses/101/assignments/89'), ('GET', '/api/v1/files/777')])
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(self.calls[-3:], [
            ('GET', '/api/v1/courses/101/assignments/89'), ('GET', '/api/v1/files/777'),
            ('POST', '/api/v1/courses/101/assignments/89/submissions')])

    def test_personal_file_discovery_and_metadata(self):
        found = self.invoke('my-files', '--search', 'synthetic')
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertEqual(json.loads(found.stdout)[0]['id'], 777)
        info = self.invoke('file-info', '777')
        self.assertEqual(info.returncode, 0, info.stderr)
        self.assertEqual(json.loads(info.stdout)['size'], 22)

    def test_course_doctor_reports_reachability_without_content(self):
        result = self.invoke('doctor', '101')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        statuses = {item['area']: item['status'] for item in data['probes']}
        self.assertEqual(statuses['files'], 'denied_403')
        self.assertEqual(statuses['pages'], 'not_found_404')
        self.assertEqual(statuses['assignments'], 'readable')
        self.assertNotIn('Synthetic course', result.stdout)

    def test_offline_snapshot_search_brief(self):
        source = Path(self.tmp.name) / 'synthetic-search.json'
        source.write_text(json.dumps({
            'schema_version': 1, 'course_id': 101, 'complete': False,
            'course': {'syllabus_body': '<p>Read about synthetic biology.</p>'},
            'assignments': [], 'announcements': [], 'modules': [], 'pages': [],
        }))
        result = self.invoke('--format', 'brief', 'snapshot-search', str(source),
                             '--query', 'synthetic biology')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('1 match(es)', result.stdout)
        self.assertIn('Snapshot incomplete', result.stdout)
        self.assertIn('Read about synthetic biology.', result.stdout)

    def test_live_title_find_single_area(self):
        result = self.invoke('--format', 'brief', 'find', '101', '--query', 'Synthetic',
                             '--area', 'assignments')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('1 result(s) in course 101', result.stdout)
        self.assertIn('assignment 88: Synthetic paper', result.stdout)
