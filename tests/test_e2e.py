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
        cls.event = {'id': 61, 'context_code': 'user_7', 'title': 'Synthetic event',
                     'start_at': '2026-10-05T09:00:00-07:00', 'end_at': '2026-10-05T10:00:00-07:00',
                     'all_day': False, 'workflow_state': 'active', 'updated_at': '2026-10-01T12:00:00Z'}
        cls.override = {'id': 55, 'user_id': 7, 'plannable_type': 'planner_note', 'plannable_id': 43,
                        'marked_complete': True, 'dismissed': False, 'workflow_state': 'active',
                        'updated_at': '2026-10-02T12:00:00Z', 'deleted_at': None}
        cls.entry = {'id': 301, 'user_id': 7, 'message': '<p>Synthetic original entry</p>',
                     'updated_at': '2026-10-02T12:00:00Z'}
        cls.topic_state = {'subscribed': False, 'read_state': 'unread'}
        cls.personal_file = {'id': 881, 'folder_id': 91, 'display_name': 'synthetic-personal.txt',
                             'size': 20, 'uuid': 'synthetic-file-verifier', 'updated_at': '2026-10-02T12:00:00Z'}
        cls.personal_root = {'id': 91, 'context_type': 'User', 'context_id': 7, 'name': 'Root',
                             'parent_folder_id': None, 'for_submissions': False}
        cls.personal_destination = {**cls.personal_root, 'id': 92, 'name': 'Notes', 'parent_folder_id': 91}
        cls.personal_children = []
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
                if self.path == '/api/v1/files/881' and cls.personal_file is None:
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
                             'submission': {'workflow_state': 'submitted', 'submitted_at': '2026-09-01T12:00:00Z'}},
                            {'id': 89, 'name': 'Unfinished project',
                             'due_at': (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
                             'submission': {'workflow_state': 'unsubmitted'}}]
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
                elif self.path == '/api/v1/courses/101/assignments/88/submissions/self':
                    data = {'id': 41, 'assignment_id': 88, 'user_id': 7, 'attempt': 1,
                            'workflow_state': 'submitted', 'assignment_visible': True}
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
                            'published': True, 'locked_for_user': False, **cls.topic_state}
                elif self.path == '/api/v1/groups/11/discussion_topics?per_page=100':
                    data = [{'id': 203, 'title': 'Synthetic group discussion', 'published': True}]
                elif self.path == '/api/v1/groups/11/discussion_topics?per_page=100&only_announcements=true':
                    data = [{'id': 204, 'title': 'Synthetic group announcement', 'is_announcement': True}]
                elif self.path in ('/api/v1/groups/11/discussion_topics/203', '/api/v1/groups/11/discussion_topics/204'):
                    data = {'id': int(self.path.rsplit('/', 1)[1]), 'context_id': 11, 'context_type': 'Group',
                            'title': 'Synthetic group topic', 'published': True, **cls.topic_state}
                elif self.path == '/api/v1/groups/11/discussion_topics/205':
                    data = {'id': 205, 'context_id': 11, 'context_type': 'Group', 'published': True,
                            'require_initial_post': True, 'user_can_see_posts': False}
                elif self.path in ('/api/v1/courses/101/discussion_topics/202/entry_list?ids%5B%5D=301&per_page=100',
                                   '/api/v1/groups/11/discussion_topics/203/entry_list?ids%5B%5D=301&per_page=100'):
                    self.send_header('Link', f'<{self.path}&page=2>; rel="next"')
                    data = []
                elif self.path in ('/api/v1/courses/101/discussion_topics/202/entry_list?ids%5B%5D=301&per_page=100&page=2',
                                   '/api/v1/groups/11/discussion_topics/203/entry_list?ids%5B%5D=301&per_page=100&page=2'):
                    data = [cls.entry]
                elif self.path == '/api/v1/groups/11/discussion_topics/203/entries?per_page=100':
                    data = [{'id': 301, 'message': 'Synthetic group entry', 'has_more_replies': True}]
                elif self.path == '/api/v1/groups/11/discussion_topics/203/entries/301/replies?per_page=100':
                    data = [{'id': 401, 'message': 'Synthetic group reply'}]
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
                elif self.path == '/api/v1/files/778':
                    data = {'id': 778, 'display_name': 'second.txt', 'size': 14,
                            'uuid': 'second-synthetic-uuid', 'locked_for_user': False}
                elif self.path == '/api/v1/users/self/files?per_page=100' or self.path == '/api/v1/users/self/files?per_page=100&search_term=synthetic':
                    data = [{'id': 777, 'display_name': 'synthetic.txt', 'size': 22}]
                elif self.path == '/api/v1/users/self/profile':
                    data = {'id': 7, 'name': 'Synthetic Student'}
                elif self.path == '/api/v1/files/881':
                    data = cls.personal_file
                elif self.path in ('/api/v1/folders/91', '/api/v1/users/self/folders/root'):
                    data = cls.personal_root
                elif self.path == '/api/v1/folders/92':
                    data = cls.personal_destination
                elif self.path == '/api/v1/users/self/folders?per_page=100':
                    self.send_header('Link', '</api/v1/users/self/folders?page=2>; rel="next"')
                    data = [cls.personal_root]
                elif self.path == '/api/v1/users/self/folders?page=2':
                    data = [cls.personal_destination, *cls.personal_children]
                elif self.path == '/api/v1/folders/92/folders?per_page=100':
                    data = cls.personal_children
                elif self.path == '/api/v1/courses/105/content_exports?per_page=100':
                    self.send_header('Link', '</api/v1/courses/105/content_exports?page=2>; rel="next"')
                    data = [{'id': 51, 'user_id': 7, 'export_type': 'zip', 'workflow_state': 'exporting'}]
                elif self.path == '/api/v1/courses/105/content_exports?page=2':
                    data = [{'id': 52, 'user_id': 7, 'export_type': 'zip', 'workflow_state': 'exported',
                             'attachment': {'url': f'https://localhost:{cls.server.server_port}/storage/synthetic-file?signature=hidden'}}]
                elif self.path == '/api/v1/courses/105/content_exports/51':
                    data = {'id': 51, 'user_id': 7, 'export_type': 'zip', 'workflow_state': 'exporting',
                            'progress_url': f'https://localhost:{cls.server.server_port}/api/v1/progress/61'}
                elif self.path == '/api/v1/courses/105/content_exports/52':
                    data = {'id': 52, 'user_id': 7, 'export_type': 'zip', 'workflow_state': 'exported',
                            'attachment': {'url': f'https://localhost:{cls.server.server_port}/storage/synthetic-file', 'size': 20}}
                elif self.path == '/api/v1/progress/61':
                    data = {'id': 61, 'workflow_state': 'running', 'completion': 45}
                elif self.path == '/api/v1/courses/105':
                    data = {'id': 105, 'name': 'Synthetic export course'}
                elif self.path == '/api/v1/planner/items?page=2':
                    data = [{'plannable_type': 'assignment', 'plannable_id': 88,
                             'plannable': {'title': 'Synthetic assignment'},
                             'planner_override': {'marked_complete': True},
                             'submissions': {'missing': True}}]
                elif self.path.startswith('/api/v1/planner/items?'):
                    self.send_header('Link', '</api/v1/planner/items?page=2>; rel="next"')
                    data = [{'plannable_type': 'planner_note', 'plannable_id': 41,
                             'plannable': {'title': 'Synthetic personal task',
                                           'todo_date': '2026-10-02T12:00:00Z'}}]
                elif self.path.startswith('/api/v1/planner_notes?'):
                    data = [{'id': 41, 'user_id': 7, 'title': 'Synthetic personal task'}]
                elif self.path == '/api/v1/planner_notes/41':
                    data = {'id': 41, 'user_id': 7, 'title': 'Synthetic personal task'}
                elif self.path == '/api/v1/planner/overrides?per_page=100':
                    data = [cls.override]
                elif self.path == '/api/v1/planner/overrides/55':
                    data = cls.override
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
                elif self.path == '/api/v1/courses/104/modules?per_page=100':
                    data = [{'id': 21, 'name': 'Synthetic progress', 'state': 'started',
                             'requirement_type': 'one'},
                            {'id': 22, 'name': 'Future module', 'state': 'locked'},
                            {'id': 23, 'name': 'Unpublished', 'published': False}]
                elif self.path == '/api/v1/courses/104/modules/21/items?per_page=100&include%5B%5D=content_details':
                    self.send_header('Link', '</api/v1/courses/104/modules/21/items?page=2>; rel="next"')
                    data = [{'id': 31, 'title': 'Viewed page', 'completion_requirement':
                             {'type': 'must_view', 'completed': True}}]
                elif self.path == '/api/v1/courses/104/modules/21/items?page=2':
                    data = [{'id': 32, 'title': 'Unknown submission',
                             'completion_requirement': {'type': 'must_submit'}}]
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
                elif self.path == '/api/v1/calendar_events/61':
                    data = cls.event
                elif self.path == '/api/v1/calendar_events/62':
                    data = {**cls.event, 'id': 62, 'context_code': 'course_101'}
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
                raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
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
                body = json.loads(raw) if raw else {}
                if self.path in ('/api/v1/files/881', '/api/v1/folders/92/copy_file', '/api/v1/folders/92/folders'):
                    cls.personal_write = body
                    if self.path.endswith('/folders'):
                        data = {**cls.personal_destination, 'id': 94, 'parent_folder_id': 92, 'name': body['name']}
                        cls.personal_children.append(data)
                    elif self.path.endswith('/copy_file'):
                        data = {**cls.personal_file, 'id': 882, 'folder_id': 92}
                    elif self.command == 'DELETE':
                        data = cls.personal_file.copy()
                        cls.personal_file = None
                    else:
                        cls.personal_file = {**cls.personal_file,
                                             'display_name': body.get('name', cls.personal_file['display_name']),
                                             'folder_id': int(body.get('parent_folder_id', cls.personal_file['folder_id'])),
                                             'updated_at': '2026-10-02T13:00:00Z'}
                        data = cls.personal_file
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps(data).encode()); return
                state_paths = ('/api/v1/courses/101/discussion_topics/202', '/api/v1/groups/11/discussion_topics/203')
                if any(self.path == prefix + suffix for prefix in state_paths
                       for suffix in ('/read', '/subscribed', '/entries/301/read')):
                    cls.state_write = body
                    if self.path.endswith('/subscribed'):
                        cls.topic_state['subscribed'] = self.command == 'PUT'
                    elif self.path.endswith('/entries/301/read'):
                        cls.entry['read_state'] = 'read' if self.command == 'PUT' else 'unread'
                        if 'forced_read_state' in body:
                            cls.entry['forced_read_state'] = body['forced_read_state']
                    else:
                        cls.topic_state['read_state'] = 'read' if self.command == 'PUT' else 'unread'
                    self.send_response(204); self.end_headers(); return
                if self.path in ('/api/v1/courses/101/discussion_topics/202/entries/301',
                                 '/api/v1/groups/11/discussion_topics/203/entries/301'):
                    cls.entry_write = body
                    if self.command == 'DELETE':
                        cls.entry = {'id': 301, 'deleted': True}
                        self.send_response(204); self.end_headers(); return
                    cls.entry = {**cls.entry, **body, 'attachment': None, 'updated_at': '2026-10-02T13:00:00Z'}
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps(cls.entry).encode()); return
                if self.path in ('/api/v1/planner/overrides', '/api/v1/planner/overrides/55'):
                    cls.override_write = body
                    data = {**cls.override, **body}
                    if self.command == 'POST':
                        data['id'] = 56
                    elif self.command == 'DELETE':
                        data['workflow_state'] = 'deleted'
                        data['deleted_at'] = '2026-10-02T14:00:00Z'
                    else:
                        data['marked_complete'] = body.get('marked_complete', False)
                        data['dismissed'] = body.get('dismissed', False)
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps(data).encode()); return
                if self.path in ('/api/v1/calendar_events', '/api/v1/calendar_events/61'):
                    cls.event_write = body
                    data = {**cls.event, **body.get('calendar_event', {})}
                    if self.command == 'DELETE':
                        data['workflow_state'] = 'deleted'
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps(data).encode()); return
                if self.path == '/api/v1/courses/105/content_exports':
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps({'id': 51, 'user_id': 7, 'workflow_state': 'exporting',
                                                'export_type': body['export_type']}).encode()); return
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
            def do_PUT(self):
                self.do_POST()
            def do_DELETE(self):
                self.do_POST()
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

    def test_personal_calendar_lifecycle_is_preview_first_over_tls(self):
        commands = [(('event-create', '--title', 'Synthetic study block', '--date', '2026-10-05',
                       '--timezone', 'America/Los_Angeles'), 'POST', '/api/v1/calendar_events'),
                    (('event-edit', '61', '--start', '2026-10-05T12:00:00-07:00',
                       '--end', '2026-10-05T13:00:00-07:00'), 'PUT', '/api/v1/calendar_events/61'),
                    (('event-delete', '61', '--reason', 'Synthetic reason'), 'DELETE', '/api/v1/calendar_events/61')]
        for command, method, route in commands:
            with self.subTest(command=command):
                before = len(self.calls)
                preview = self.invoke(*command)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                data = json.loads(preview.stdout)
                self.assertTrue(data['dry_run'])
                self.assertTrue(all(verb == 'GET' for verb, _ in self.calls[before:]))
                rejected = self.invoke(*command, '--yes', '--confirm', 'wrong')
                self.assertNotEqual(rejected.returncode, 0)
                self.assertTrue(all(verb == 'GET' for verb, _ in self.calls[before:]))
                sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
                self.assertEqual(sent.returncode, 0, sent.stderr)
                self.assertEqual(json.loads(sent.stdout)['calendar_event']['id'], 61)
                self.assertEqual(self.event_write, data['body'])
                self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'], [(method, route)])
                if method != 'POST':
                    self.assertEqual(self.event_write['which'], 'one')

    def test_personal_calendar_refuses_course_events_and_ambiguous_time_input(self):
        before = len(self.calls)
        result = self.invoke('event-edit', '62', '--title', 'Not a personal event')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('personal calendar', result.stderr)
        self.assertTrue(all(verb == 'GET' for verb, _ in self.calls[before:]))
        before = len(self.calls)
        result = self.invoke('event-create', '--title', 'Bad time', '--start', '2026-10-05T09:00:00',
                             '--end', '2026-10-05T10:00:00')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.calls), before)
        read = self.invoke('event', '61')
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertEqual(json.loads(read.stdout)['context_code'], 'user_7')

    def test_group_discussion_reads_and_threads_use_the_group_namespace(self):
        before = len(self.calls)
        for command in (('discussions', '11'), ('announcements', '11'), ('topic', '11', '203'),
                        ('entries', '11', '203'), ('replies', '11', '203', '301')):
            result = self.invoke(*command, '--context', 'group')
            self.assertEqual(result.returncode, 0, result.stderr)
        result = self.invoke('thread', '11', '203', '--context', 'group')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['group_id'], 11)
        self.assertEqual(data['entries'][0]['replies'][0]['id'], 401)
        self.assertTrue(data['complete'])
        self.assertTrue(all(verb == 'GET' and route.startswith('/api/v1/groups/11/')
                            for verb, route in self.calls[before:]))

    def test_group_post_context_and_account_are_bound_to_exact_confirmation(self):
        source = Path(self.tmp.name) / 'group-post.txt'
        source.write_text('Synthetic group message')
        command = ('post', '11', '203', '--context', 'group', '--message-file', str(source))
        before = len(self.calls)
        result = self.invoke(*command)
        self.assertEqual(result.returncode, 0, result.stderr)
        preview = json.loads(result.stdout)
        self.assertEqual(preview['group_id'], '11')
        self.assertNotIn('course_id', preview)
        self.assertTrue(all(verb == 'GET' for verb, _ in self.calls[before:]))
        sent = self.invoke(*command, '--yes', '--confirm', preview['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                         [('POST', '/api/v1/groups/11/discussion_topics/203/entries')])

    def test_group_post_first_restriction_blocks_entry_read_before_list_request(self):
        before = len(self.calls)
        result = self.invoke('entries', '11', '205', '--context', 'group')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('initial post', result.stderr)
        self.assertEqual(self.calls[before:], [('GET', '/api/v1/groups/11/discussion_topics/205')])

    def test_own_entry_lifecycle_is_stateful_and_paginated_for_courses_and_groups(self):
        original = self.entry.copy()
        source = Path(self.tmp.name) / 'entry-edit.txt'
        source.write_text('Synthetic <edited> entry')
        try:
            for context, context_id, topic_id in [('course', '101', '202'), ('group', '11', '203')]:
                with self.subTest(context=context):
                    self.__class__.entry = original.copy()
                    args = (context_id, topic_id, '301', '--context', context)
                    before = len(self.calls)
                    read = self.invoke('entry', *args)
                    self.assertEqual(read.returncode, 0, read.stderr)
                    self.assertEqual(json.loads(read.stdout)['message'], original['message'])
                    for command in [('entry-edit', *args, '--message-file', str(source)), ('entry-delete', *args)]:
                        before = len(self.calls)
                        preview = self.invoke(*command)
                        self.assertEqual(preview.returncode, 0, preview.stderr)
                        data = json.loads(preview.stdout)
                        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                        rejected = self.invoke(*command, '--yes', '--confirm', 'not-the-digest')
                        self.assertNotEqual(rejected.returncode, 0)
                        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
                        self.assertEqual(sent.returncode, 0, sent.stderr)
                        method = 'DELETE' if command[0] == 'entry-delete' else 'PUT'
                        self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                                         [(method, f'/api/v1/{context}s/{context_id}/discussion_topics/{topic_id}/entries/301')])
                        reread = self.invoke('entry', *args)
                        self.assertEqual(reread.returncode, 0, reread.stderr)
                        state = json.loads(reread.stdout)
                        if method == 'DELETE':
                            self.assertTrue(json.loads(sent.stdout)['deleted'])
                            self.assertTrue(state['deleted'])
                        else:
                            self.assertEqual(state['message'], '<p>Synthetic &lt;edited&gt; entry</p>')
        finally:
            self.__class__.entry = original

    def test_entry_changes_reject_other_users_and_unacknowledged_attachment_loss_over_tls(self):
        original = self.entry.copy()
        source = Path(self.tmp.name) / 'attached-entry-edit.txt'
        source.write_text('Synthetic replacement')
        command = ('entry-edit', '101', '202', '301', '--message-file', str(source))
        try:
            self.__class__.entry = {**original, 'user_id': 99}
            before = len(self.calls)
            denied = self.invoke(*command)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn('own active', denied.stderr)
            self.__class__.entry = {**original, 'attachment': {'id': 71, 'display_name': 'synthetic.txt'}}
            denied = self.invoke(*command)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn('--remove-attachment', denied.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
            preview = self.invoke(*command, '--remove-attachment')
            self.assertEqual(preview.returncode, 0, preview.stderr)
            data = json.loads(preview.stdout)
            sent = self.invoke(*command, '--remove-attachment', '--yes', '--confirm', data['confirm'])
            self.assertEqual(sent.returncode, 0, sent.stderr)
            self.assertEqual(self.entry_write['remove_attachment'], '1')
            self.assertIsNone(self.entry['attachment'])
        finally:
            self.__class__.entry = original

    def test_entry_list_page_limit_fails_without_silent_partial_result(self):
        result = self.invoke('entry', '101', '202', '301', '--max-pages', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Page limit reached', result.stderr)
        self.assertEqual(result.stdout, '')

    def test_discussion_subscriptions_and_read_markers_are_explicit_stateful_writes(self):
        original_entry, original_state = self.entry.copy(), self.topic_state.copy()
        commands = [('topic-subscribe', 'subscribed', None), ('topic-unsubscribe', 'subscribed', None),
                    ('topic-mark-read', 'read', None), ('topic-mark-unread', 'read', None),
                    ('entry-mark-read', 'entries/301/read', True), ('entry-mark-unread', 'entries/301/read', False)]
        try:
            for context, context_id, topic_id in [('course', '101', '202'), ('group', '11', '203')]:
                for name, suffix, forced in commands:
                    with self.subTest(context=context, name=name):
                        command = [name, context_id, topic_id, '--context', context]
                        if name.startswith('entry-'):
                            command += ['301', '--forced-read-state' if forced else '--no-forced-read-state']
                        before = len(self.calls)
                        preview = self.invoke(*command)
                        self.assertEqual(preview.returncode, 0, preview.stderr)
                        data = json.loads(preview.stdout)
                        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                        rejected = self.invoke(*command, '--yes', '--confirm', 'wrong')
                        self.assertNotEqual(rejected.returncode, 0)
                        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'], '--format', 'brief')
                        self.assertEqual(sent.returncode, 0, sent.stderr)
                        self.assertIn('HTTP 204', sent.stdout)
                        method = 'DELETE' if name.endswith(('unsubscribe', 'unread')) else 'PUT'
                        self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                                         [(method, f'/api/v1/{context}s/{context_id}/discussion_topics/{topic_id}/{suffix}')])
                        if name.startswith('entry-'):
                            self.assertEqual(self.entry['forced_read_state'], forced)
                            self.assertEqual(self.entry['read_state'], 'unread' if method == 'DELETE' else 'read')
                            self.assertEqual(self.entry['message'], original_entry['message'])
                        elif suffix == 'subscribed':
                            self.assertEqual(self.topic_state['subscribed'], method == 'PUT')
                        else:
                            self.assertEqual(self.topic_state['read_state'], 'unread' if method == 'DELETE' else 'read')
        finally:
            self.__class__.entry, self.__class__.topic_state = original_entry, original_state

    def test_personal_file_organization_and_subfolder_creation_over_tls(self):
        original_file, original_children = self.personal_file.copy(), self.personal_children.copy()
        try:
            root = self.invoke('my-root')
            self.assertEqual(root.returncode, 0, root.stderr)
            self.assertEqual(json.loads(root.stdout)['id'], 91)
            listing = self.invoke('my-folders')
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertEqual([row['id'] for row in json.loads(listing.stdout)], [91, 92])
            commands = [('my-folder-create', '92', '--name', 'Synthetic child'),
                        ('my-file-copy', '881', '--folder', '92'),
                        ('my-file-edit', '881', '--name', 'revised.txt', '--folder', '92'),
                        ('my-file-delete', '881', '--permanent')]
            for command in commands:
                with self.subTest(command=command):
                    before = len(self.calls)
                    preview = self.invoke(*command)
                    self.assertEqual(preview.returncode, 0, preview.stderr)
                    data = json.loads(preview.stdout)
                    self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                    denied = self.invoke(*command, '--yes', '--confirm', 'wrong')
                    self.assertNotEqual(denied.returncode, 0)
                    self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                    sent = self.invoke(*command, '--yes', '--confirm', data['confirm'], '--format', 'brief')
                    self.assertEqual(sent.returncode, 0, sent.stderr)
                    self.assertEqual(self.personal_write, data['body'] or {})
                    self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                                     [(data['method'], data['route'])])
                    if command[0] == 'my-file-copy': self.assertEqual(self.personal_file, original_file)
                    if command[0] == 'my-file-edit':
                        reread = self.invoke('file-info', '881')
                        self.assertEqual(json.loads(reread.stdout)['display_name'], 'revised.txt')
                        self.assertEqual(json.loads(reread.stdout)['folder_id'], 92)
            deleted = self.invoke('file-info', '881')
            self.assertNotEqual(deleted.returncode, 0)
            self.assertIn('HTTP 404', deleted.stderr)
            self.assertEqual(self.personal_children[0]['parent_folder_id'], 92)
        finally:
            self.__class__.personal_file, self.__class__.personal_children = original_file, original_children

    def test_personal_file_delete_requires_ack_and_foreign_destinations_are_refused(self):
        original = self.personal_destination.copy()
        try:
            before = len(self.calls)
            result = self.invoke('my-file-delete', '881')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('--permanent', result.stderr)
            self.assertEqual(len(self.calls), before)
            self.__class__.personal_destination = {**original, 'context_type': 'Course'}
            result = self.invoke('my-file-copy', '881', '--folder', '92')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('own accessible personal', result.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        finally:
            self.__class__.personal_destination = original

    def test_planner_pagination_and_read_only_personal_notes(self):
        before = len(self.calls)
        result = self.invoke('planner', '--start', '2026-10-02', '--end', '2026-10-03',
                             '--course', '101', '--group', '11', '--filter', 'incomplete_items')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual([x['plannable_id'] for x in data['items']], [41, 88])
        self.assertIn('not proof', data['note'])
        for command in [('planner-notes', '--personal'), ('planner-note', '41'),
                        ('planner-overrides',)]:
            result = self.invoke(*command)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))

    def test_personal_task_preview_and_confirmed_creation(self):
        command = ('task-create', '--title', 'Synthetic personal task', '--date', '2026-10-02')
        before = len(self.calls)
        result = self.invoke(*command)
        self.assertEqual(result.returncode, 0, result.stderr)
        preview = json.loads(result.stdout)
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['user_id'], 7)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        rejected = self.invoke(*command, '--yes', '--confirm', 'wrong')
        self.assertNotEqual(rejected.returncode, 0)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        sent = self.invoke(*command, '--yes', '--confirm', preview['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(json.loads(sent.stdout)['title'], 'Synthetic personal task')
        self.assertEqual([c for c in self.calls[before:] if c[0] == 'POST'],
                         [('POST', '/api/v1/planner_notes')])

    def test_planner_override_creation_is_confirmed_and_feed_backed(self):
        command = ('planner-override-create', 'planner_note', '41', '--complete',
                   '--start', '2026-10-01', '--end', '2026-10-14')
        before = len(self.calls)
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertTrue(data['dry_run'])
        self.assertEqual(data['target']['id'], 41)
        self.assertTrue(all(verb == 'GET' for verb, _ in self.calls[before:]))
        rejected = self.invoke(*command, '--yes', '--confirm', 'wrong')
        self.assertNotEqual(rejected.returncode, 0)
        self.assertTrue(all(verb == 'GET' for verb, _ in self.calls[before:]))
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(json.loads(sent.stdout)['planner_override']['id'], 56)
        self.assertEqual(self.override_write, data['body'])
        self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                         [('POST', '/api/v1/planner/overrides')])

    def test_planner_override_edit_preserves_complete_and_supports_explicit_uncheck(self):
        for options in (('--dismiss',), ('--no-complete',)):
            before = len(self.calls)
            command = ('planner-override-edit', '55', *options)
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            data = json.loads(preview.stdout)
            self.assertEqual(data['body']['marked_complete'], options == ('--dismiss',))
            self.assertEqual(data['body']['dismissed'], options == ('--dismiss',))
            self.assertTrue(all(verb == 'GET' for verb, _ in self.calls[before:]))
            sent = self.invoke(*command, '--yes', '--confirm', data['confirm'], '--format', 'brief')
            self.assertEqual(sent.returncode, 0, sent.stderr)
            self.assertIn('not an assignment submission', sent.stdout)
            self.assertEqual(self.override_write, data['body'])
            self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                             [('PUT', '/api/v1/planner/overrides/55')])

    def test_planner_override_read_delete_and_course_acknowledgement(self):
        before = len(self.calls)
        read = self.invoke('planner-override', '55')
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertEqual(json.loads(read.stdout)['user_id'], 7)
        refused = self.invoke('planner-override-create', 'assignment', '88', '--complete')
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('allow-module-progress', refused.stderr)
        preview = self.invoke('planner-override-delete', '55')
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertTrue(all(verb == 'GET' for verb, _ in self.calls[before:]))
        sent = self.invoke('planner-override-delete', '55', '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(json.loads(sent.stdout)['planner_override']['workflow_state'], 'deleted')
        self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                         [('DELETE', '/api/v1/planner/overrides/55')])

    def test_task_edit_and_delete_require_separate_exact_previews(self):
        for command, method in [(('task-edit', '41', '--title', 'Edited synthetic task'), 'PUT'),
                                (('task-delete', '41'), 'DELETE')]:
            before = len(self.calls)
            result = self.invoke(*command)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertTrue(data['dry_run'])
            self.assertEqual(data['method'], method)
            self.assertTrue(all(verb == 'GET' for verb, _ in self.calls[before:]))
            rejected = self.invoke(*command, '--yes', '--confirm', 'wrong')
            self.assertNotEqual(rejected.returncode, 0)
            self.assertTrue(all(verb == 'GET' for verb, _ in self.calls[before:]))
            result = self.invoke(*command, '--yes', '--confirm', data['confirm'])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual([c for c in self.calls[before:] if c[0] != 'GET'],
                             [(method, '/api/v1/planner_notes/41')])

    def test_submission_comment_only_sends_comment_fields_to_current_user(self):
        source = Path(self.tmp.name) / 'feedback.txt'
        source.write_text('Synthetic comment')
        command = ('submission-comment', '101', '88', '--message-file', str(source), '--attempt', '1')
        before = len(self.calls)
        result = self.invoke(*command)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['dry_run'])
        self.assertEqual(set(data['body']), {'comment'})
        self.assertEqual(data['route'], '/api/v1/courses/101/assignments/88/submissions/7')
        self.assertTrue(all(verb == 'GET' for verb, _ in self.calls[before:]))
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(json.loads(sent.stdout)['comment']['text_comment'], 'Synthetic comment')
        self.assertEqual([c for c in self.calls[before:] if c[0] != 'GET'],
                         [('PUT', data['route'])])

    def test_module_progress_paginates_without_marking_content_viewed(self):
        before = len(self.calls)
        result = self.invoke('module-progress', '104')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data['complete'])
        self.assertEqual(data['module_progress'][0]['requirements'],
                         {'required': 2, 'completed': 1, 'incomplete': 0, 'unknown': 1})
        self.assertIsNone(data['module_progress'][1]['requirements'])
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        self.assertFalse(any('/modules/22/' in path or '/modules/23/' in path
                             for _, path in self.calls[before:]))
        result = self.invoke('module-progress', '104', '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('unknown', result.stdout)
        self.assertIn('coverage is partial', result.stdout)

    def test_async_export_read_preview_create_and_private_download(self):
        before = len(self.calls)
        index = self.invoke('exports', '105')
        self.assertEqual(index.returncode, 0, index.stderr)
        self.assertEqual([job['id'] for job in json.loads(index.stdout)], [51, 52])
        self.assertNotIn('signature', index.stdout)
        status = self.invoke('export-status', '105', '51', '--progress', '--format', 'brief')
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn('45%', status.stdout)
        self.assertIn('exporting', status.stdout)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        command = ('export-create', '105', '--type', 'zip', '--select', 'files', '777')
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertTrue(data['dry_run'])
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(json.loads(sent.stdout)['export']['workflow_state'], 'exporting')
        self.assertEqual([c for c in self.calls[before:] if c[0] == 'POST'],
                         [('POST', '/api/v1/courses/105/content_exports')])
        output = Path(self.tmp.name) / 'synthetic-export.zip'
        result = self.invoke('export-download', '105', '52', '--output', str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output.read_bytes(), b'Synthetic file bytes')
        self.assertIsNone(self.storage_download_auth)
        self.assertNotIn('/storage/', result.stdout)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        pending_output = Path(self.tmp.name) / 'pending-export.zip'
        result = self.invoke('export-download', '105', '51', '--output', str(pending_output))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(pending_output.exists())

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

    def test_agenda_over_tls_is_read_only_and_omits_submitted(self):
        before = len(self.calls)
        result = self.invoke('agenda', '--course', '101', '--days', '7', '--timezone', 'UTC')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual([item['assignment_id'] for item in data['items']], [89])
        self.assertEqual(data['items'][0]['course_name'], 'Synthetic course')
        self.assertEqual(self.calls[before:], [
            ('GET', '/api/v1/courses?enrollment_state=active&per_page=100'),
            ('GET', '/api/v1/courses/101/assignments?include%5B%5D=submission&per_page=100')])
        brief = self.invoke('--format', 'brief', 'agenda', '--course', '101', '--timezone', 'UTC')
        self.assertIn('Unfinished project', brief.stdout)
        self.assertNotIn('Synthetic paper', brief.stdout)

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
        self.assertEqual(self.calls[before:], [('GET', '/api/v1/users/self/profile'),
                                              ('GET', '/api/v1/courses/101/assignments/88')])
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
        self.assertEqual(self.calls[before:], [('GET', '/api/v1/users/self/profile'),
                                              ('GET', '/api/v1/courses/101/discussion_topics/202')])
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
        brief = self.invoke('capabilities', '--format', 'brief')
        self.assertEqual(brief.returncode, 0, brief.stderr)
        self.assertIn('Read-only (', brief.stdout)
        self.assertIn('Canvas writes (', brief.stdout)
        self.assertNotIn('"read":', brief.stdout)

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

    def test_snapshot_can_index_linked_file_metadata_without_binaries(self):
        destination = Path(self.tmp.name) / 'course-snapshot-files.json'
        before = len(self.calls)
        result = self.invoke('snapshot', '101', '--output', str(destination),
                             '--include-linked-files')
        self.assertEqual(result.returncode, 0, result.stderr)
        snapshot = json.loads(destination.read_text())
        self.assertEqual(snapshot['linked_file_scope'], 'readable-references-only')
        self.assertEqual(snapshot['linked_files'][0]['id'], 7)
        self.assertNotIn('url', snapshot['linked_files'][0])
        self.assertFalse(any(path == '/storage/synthetic-file'
                             for _, path in self.calls[before:]))

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
            ('GET', '/api/v1/users/self/profile'),
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
        self.assertEqual([method for method, _ in self.calls[before:]], ['GET', 'GET', 'GET'])
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(self.calls[-3:], [
            ('GET', '/api/v1/search/recipients?type=user&per_page=100&user_id=7'),
            ('GET', '/api/v1/users/self/profile'),
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
        self.assertEqual(self.calls[before:], [('GET', '/api/v1/users/self/profile')])
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
            ('GET', '/api/v1/users/self/profile'),
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
            ('GET', '/api/v1/users/self/profile'),
            ('GET', '/api/v1/courses/101/assignments/89'), ('GET', '/api/v1/files/777')])
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(self.calls[-3:], [
            ('GET', '/api/v1/courses/101/assignments/89'), ('GET', '/api/v1/files/777'),
            ('POST', '/api/v1/courses/101/assignments/89/submissions')])

    def test_multiple_uploaded_files_are_submitted_in_one_confirmed_request(self):
        command = ('submit-file', '101', '89', '777', '778')
        before = len(self.calls)
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertEqual(data['body']['submission']['file_ids'], [777, 778])
        self.assertEqual(len(data['files']), 2)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(json.loads(sent.stdout)['submission']['file_ids'], [777, 778])
        self.assertEqual([c for c in self.calls[before:] if c[0] == 'POST'],
                         [('POST', '/api/v1/courses/101/assignments/89/submissions')])
        before = len(self.calls)
        duplicate = self.invoke('submit-file', '101', '89', '777', '0777')
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertEqual(len(self.calls), before)

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
