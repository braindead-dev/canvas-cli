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
from urllib.parse import parse_qs, urlsplit


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
        cls.topic_state = {'subscribed': False, 'read_state': 'unread', 'allow_rating': True}
        cls.own_entry_ratings = {'301': 1}
        cls.rating_ack_status = 204
        cls.personal_file = {'id': 881, 'folder_id': 91, 'display_name': 'synthetic-personal.txt',
                             'size': 20, 'uuid': 'synthetic-file-verifier', 'updated_at': '2026-10-02T12:00:00Z'}
        cls.personal_root = {'id': 91, 'context_type': 'User', 'context_id': 7, 'name': 'Root',
                             'parent_folder_id': None, 'for_submissions': False}
        cls.personal_destination = {**cls.personal_root, 'id': 92, 'name': 'Notes', 'parent_folder_id': 91}
        cls.personal_children = []
        cls.favorite_ids = {'course': set(), 'group': set()}
        cls.favorite_defaults = {'course': [{'id': 101, 'name': 'Synthetic course'},
                                            {'id': 102, 'name': 'Synthetic second course'}],
                                 'group': [{'id': 11, 'name': 'Synthetic group'},
                                           {'id': 12, 'name': 'Synthetic second group'}]}
        cls.inbox_state = {'workflow_state': 'unread', 'starred': False, 'subscribed': True,
                           'private': False, 'message_count': 1}
        cls.inbox_messages = [{'id': 31, 'author_id': 7, 'body': 'Synthetic private message'}]
        cls.course_nicknames = {101: 'Synthetic nickname', 102: 'Another nickname'}
        cls.custom_colors = {'course_101': '#abc'}
        cls.user_settings = {'manual_mark_as_read': False, 'collapse_global_nav': True,
                             'collapse_course_nav': False, 'hide_dashcard_color_overlays': False}
        cls.dashboard_positions = {'course_101': 1, 'course_102': 2, 'group_12': '9'}
        cls.activity_hidden_ids = set()
        cls.activity_items = [
            {'id': 71, 'type': 'Conversation', 'conversation_id': 12, 'title': 'Synthetic activity message',
             'read_state': False, 'message': 'Synthetic private body',
             'latest_messages': [{'body': 'Synthetic message content'}]},
            {'id': 72, 'type': 'AssessmentRequest', 'assessment_request_id': 61,
             'course_id': 101, 'context_type': 'course', 'title': 'Synthetic peer-review notice', 'read_state': False},
            {'id': 73, 'type': 'DiscussionTopic', 'discussion_topic_id': 202, 'course_id': 101,
             'context_type': 'course', 'title': 'Synthetic activity topic', 'require_initial_post': True,
             'user_has_posted': False, 'read_state': True, 'message': 'Synthetic cached prompt',
             'root_discussion_entries': [{'message': 'Synthetic cached peer entry'}]},
        ]
        cls.missing_assignments = [
            {'id': 88, 'course_id': 101, 'name': 'Synthetic missing paper', 'published': True,
             'due_at': '2026-10-01T06:59:00Z', 'locked_for_user': True,
             'course': {'id': 101, 'name': 'Synthetic course'},
             'description': 'Synthetic private prompt', 'fixture_current_period': False,
             'planner_override': {'id': 51, 'user_id': 7, 'plannable_type': 'assignment',
                                  'plannable_id': 88, 'marked_complete': True, 'dismissed': False}},
            {'id': 89, 'course_id': 102, 'name': 'Synthetic late upload', 'published': True,
             'due_at': '2026-09-28T16:00:00Z', 'locked_for_user': False,
             'course': {'id': 102, 'name': 'Synthetic second course'}, 'fixture_current_period': True},
        ]
        cls.student_submissions = [{
            'id': 31, 'assignment_id': 88, 'user_id': 7, 'attempt': 2, 'workflow_state': 'submitted',
            'grade_matches_current_submission': False, 'body': 'Synthetic private submitted body',
            'assignment': {'id': 88, 'course_id': 101, 'name': 'Synthetic paper', 'published': True},
            'submission_history': [{'assignment_id': 88, 'user_id': 7, 'attempt': 1,
                                    'body': 'Synthetic first attempt'}, None],
            'submission_comments': [{'id': 41, 'author_id': 8, 'comment': 'Synthetic private feedback'}],
        }]
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
                if self.path == '/api/v1/folders/94' and not any(row['id'] == 94 for row in cls.personal_children):
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
                elif self.path.startswith('/api/v1/users/self/missing_submissions?'):
                    query = parse_qs(urlsplit(self.path).query)
                    data = cls.missing_assignments
                    if query.get('course_ids[]'):
                        data = [row for row in data if str(row['course_id']) in query['course_ids[]']]
                    if 'submittable' in query.get('filter[]', []):
                        data = [row for row in data if not row.get('locked_for_user')]
                    if 'current_grading_period' in query.get('filter[]', []):
                        data = [row for row in data if row.get('fixture_current_period')]
                    if 'planner_overrides' not in query.get('include[]', []):
                        data = [{key: value for key, value in row.items() if key != 'planner_override'} for row in data]
                    if not query.get('page'):
                        self.send_header('Link', f'<{self.path}&page=2>; rel="next"')
                        data = []
                elif self.path == '/api/v1/courses/101/assignments?per_page=100':
                    data = [{'id': 88, 'name': 'Synthetic paper',
                             'due_at': (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()}]
                elif self.path.startswith('/api/v1/courses/101/students/submissions?'):
                    query = parse_qs(urlsplit(self.path).query)
                    data = cls.student_submissions
                    if query.get('assignment_ids[]'):
                        data = [row for row in data if str(row['assignment_id']) in query['assignment_ids[]']]
                    if query.get('workflow_state'):
                        data = [row for row in data if row.get('workflow_state') == query['workflow_state'][0]]
                    if not query.get('page'):
                        self.send_header('Link', f'<{self.path}&page=2>; rel="next"')
                        data = []
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
                elif self.path.startswith('/api/v1/courses/101/assignments/88/peer_reviews?'):
                    reviews = [{'id': 61, 'asset_id': 41, 'asset_type': 'Submission', 'user_id': 7,
                                'assessor_id': 9, 'workflow_state': 'assigned'},
                               {'id': 62, 'asset_id': 42, 'asset_type': 'Submission', 'user_id': 9,
                                'assessor_id': 7, 'workflow_state': 'completed'},
                               {'id': 63, 'asset_id': 41, 'asset_type': 'Submission', 'user_id': 7,
                                'workflow_state': 'completed'}]
                    if 'page=2' in self.path:
                        data = reviews[1:]
                    else:
                        self.send_header('Link', f'<{self.path}&page=2>; rel="next"')
                        data = reviews[:1]
                    if 'include%5B%5D=submission_comments' in self.path:
                        data = [{**row, 'submission_comments': [{'comment': 'Synthetic review feedback'}]} for row in data]
                    if 'include%5B%5D=user' in self.path:
                        data = [{**row, 'user': {'id': row['user_id']},
                                 **({'assessor': {'id': row['assessor_id']}} if 'assessor_id' in row else {})} for row in data]
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
                            'published': True, 'locked_for_user': False,
                            'message': 'Synthetic current prompt', **cls.topic_state}
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
                elif self.path in ('/api/v1/courses/101/discussion_topics/202/view?include_new_entries=1',
                                   '/api/v1/groups/11/discussion_topics/203/view?include_new_entries=1'):
                    data = {'entry_ratings': cls.own_entry_ratings,
                            'participants': [{'id': 8, 'name': 'Synthetic private participant'}],
                            'view': [{'id': 302, 'message': 'Synthetic cached peer body', 'replies': [cls.entry]}],
                            'new_entries': [{'id': 303, 'message': 'Synthetic new entry body'}]}
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
                    data = [row for row in cls.personal_children if row['parent_folder_id'] == 92]
                elif self.path == '/api/v1/folders/91/folders?per_page=100':
                    data = [cls.personal_destination, *[row for row in cls.personal_children if row['parent_folder_id'] == 91]]
                elif self.path == '/api/v1/folders/94':
                    data = next(row for row in cls.personal_children if row['id'] == 94)
                elif self.path in ('/api/v1/folders/94/folders?per_page=100', '/api/v1/folders/94/files?per_page=100'):
                    data = []
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
                elif self.path == '/api/v1/users/self/course_nicknames?per_page=100':
                    self.send_header('Link', '</api/v1/users/self/course_nicknames?page=2>; rel="next"')
                    data = []
                elif self.path == '/api/v1/users/self/course_nicknames?page=2':
                    data = [{'course_id': row['id'], 'name': row['name'], 'nickname': cls.course_nicknames[row['id']]}
                            for row in cls.favorite_defaults['course'] if row['id'] in cls.course_nicknames]
                elif self.path.startswith('/api/v1/users/self/course_nicknames/'):
                    item = int(self.path.rsplit('/', 1)[1])
                    course = next(row for row in cls.favorite_defaults['course'] if row['id'] == item)
                    data = {'course_id': item, 'name': course['name'], 'nickname': cls.course_nicknames.get(item)}
                elif self.path == '/api/v1/users/self/colors':
                    data = {'custom_colors': cls.custom_colors}
                elif self.path == '/api/v1/users/self/settings':
                    data = cls.user_settings
                elif self.path == '/api/v1/users/self/dashboard_positions':
                    data = {'dashboard_positions': cls.dashboard_positions}
                elif self.path.startswith(('/api/v1/users/self/activity_stream', '/api/v1/courses/101/activity_stream')):
                    stream = [row for row in cls.activity_items if row['id'] not in cls.activity_hidden_ids]
                    if '/courses/' in self.path or 'only_active_courses=true' in self.path:
                        stream = [row for row in stream if row.get('course_id') == 101]
                    if '/summary' in self.path:
                        counts = {}
                        for row in stream:
                            counts.setdefault(row['type'], {'type': row['type'], 'count': 0, 'unread_count': 0})
                            counts[row['type']]['count'] += 1
                            counts[row['type']]['unread_count'] += row.get('read_state') is False
                        data = list(counts.values())
                    elif 'page=2' in self.path:
                        data = stream
                    else:
                        self.send_header('Link', f'<{self.path}&page=2>; rel="next"')
                        data = []
                elif self.path == '/api/v1/users/self/favorites/courses?per_page=100':
                    self.send_header('Link', '</api/v1/users/self/favorites/courses?page=2>; rel="next"')
                    data = []
                elif self.path in ('/api/v1/users/self/favorites/courses?page=2',
                                   '/api/v1/users/self/favorites/groups?per_page=100'):
                    context = 'group' if '/groups?' in self.path else 'course'
                    data = [row for row in cls.favorite_defaults[context]
                            if not cls.favorite_ids[context] or row['id'] in cls.favorite_ids[context]]
                elif self.path in ('/api/v1/courses/101', '/api/v1/courses/102',
                                   '/api/v1/groups/11', '/api/v1/groups/12'):
                    context = 'group' if '/groups/' in self.path else 'course'
                    data = next(row for row in cls.favorite_defaults[context] if row['id'] == int(self.path.rsplit('/', 1)[1]))
                elif self.path == '/api/v1/conversations?per_page=100&scope=unread':
                    data = [{'id': 12, 'subject': 'Synthetic inbox thread'}]
                elif self.path == '/api/v1/conversations/12?auto_mark_as_read=false':
                    data = {'id': 12, 'subject': 'Synthetic thread',
                            'participants': [{'id': 7, 'name': 'Synthetic recipient'}], 'audience': [7],
                            **cls.inbox_state, 'messages': cls.inbox_messages}
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
                if self.path.startswith('/api/v1/users/self/activity_stream'):
                    if self.path == '/api/v1/users/self/activity_stream':
                        cls.activity_hidden_ids.update(row['id'] for row in cls.activity_items)
                    else:
                        cls.activity_hidden_ids.add(int(self.path.rsplit('/', 1)[1]))
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps({'hidden': True}).encode()); return
                if self.path == '/api/v1/users/self/settings':
                    cls.preference_write = body
                    cls.user_settings.update(body)
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps(cls.user_settings).encode()); return
                if self.path == '/api/v1/users/self/dashboard_positions':
                    cls.preference_write = body
                    cls.dashboard_positions.update(body['dashboard_positions'])
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps({'dashboard_positions': cls.dashboard_positions}).encode()); return
                if self.path.startswith('/api/v1/users/self/course_nicknames'):
                    cls.preference_write = body
                    if self.path == '/api/v1/users/self/course_nicknames':
                        cls.course_nicknames.clear()
                        data = {'message': 'OK'}
                    else:
                        item = int(self.path.rsplit('/', 1)[1])
                        if self.command == 'DELETE':
                            cls.course_nicknames.pop(item, None)
                        else:
                            cls.course_nicknames[item] = body['nickname']
                        course = next(row for row in cls.favorite_defaults['course'] if row['id'] == item)
                        data = {'course_id': item, 'name': course['name'], 'nickname': cls.course_nicknames.get(item)}
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps(data).encode()); return
                if self.path.startswith('/api/v1/users/self/colors/'):
                    asset = self.path.rsplit('/', 1)[1]
                    cls.preference_write = body
                    cls.custom_colors[asset] = body['hexcode']
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps({'hexcode': cls.custom_colors[asset]}).encode()); return
                if self.path == '/api/v1/conversations/12':
                    cls.inbox_write = body
                    if self.command == 'DELETE':
                        cls.inbox_state['message_count'] = 0
                        cls.inbox_messages = []
                    else:
                        cls.inbox_state.update(body['conversation'])
                    data = {'id': 12, 'subject': 'Synthetic thread', **cls.inbox_state}
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps(data).encode()); return
                if self.path.startswith('/api/v1/users/self/favorites/'):
                    namespace = self.path.split('/')[6]
                    context = namespace[:-1]
                    parts = self.path.split('/')
                    if len(parts) == 7:
                        cls.favorite_ids[context].clear()
                        data = {'status': 'ok'}
                    else:
                        item = int(parts[7])
                        if self.command == 'POST':
                            cls.favorite_ids[context].add(item)
                            data = {'context_id': item, 'context_type': context.title()}
                        else:
                            # Native course removal can first save the defaults when no custom favorites exist.
                            if context == 'course' and not any(cls.favorite_ids.values()):
                                cls.favorite_ids[context].update(row['id'] for row in cls.favorite_defaults[context])
                            data = ({'context_id': item, 'context_type': context.title()}
                                    if item in cls.favorite_ids[context] else {})
                            cls.favorite_ids[context].discard(item)
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps(data).encode()); return
                if self.path == '/api/v1/folders/94':
                    current = next(row for row in cls.personal_children if row['id'] == 94)
                    cls.folder_write = body
                    if self.command == 'DELETE':
                        data = current.copy()
                        cls.personal_children.remove(current)
                    else:
                        current.update({key: int(value) if key == 'parent_folder_id' else value
                                        for key, value in body.items()})
                        data = current
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps(data).encode()); return
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
                if any(self.path == prefix + '/entries/301/rating' for prefix in state_paths):
                    cls.rating_write = body
                    cls.own_entry_ratings['301'] = body['rating']
                    self.send_response(cls.rating_ack_status); self.end_headers()
                    if cls.rating_ack_status != 204:
                        self.wfile.write(json.dumps({'private': 'Synthetic response not for output'}).encode())
                    return
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

    def test_nickname_lifecycle_is_account_bound_and_preserves_actual_course_name(self):
        original = self.course_nicknames.copy()
        try:
            listing = self.invoke('nicknames')
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertEqual([row['course_id'] for row in json.loads(listing.stdout)], [101, 102])
            commands = [('nickname-set', '101', '--name', 'Synthetic alias'),
                        ('nickname-clear', '101'), ('nicknames-reset',)]
            for command in commands:
                before = len(self.calls)
                preview = self.invoke(*command)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                data = json.loads(preview.stdout)
                refused = self.invoke(*command, '--yes', '--confirm', 'wrong')
                self.assertNotEqual(refused.returncode, 0)
                self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                sent = self.invoke(*command, '--yes', '--confirm', data['confirm'], '--format', 'brief')
                self.assertEqual(sent.returncode, 0, sent.stderr)
                self.assertIn('nicknames' if command[0] == 'nicknames-reset' else 'Nickname', sent.stdout)
                self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                                 [(data['method'], data['route'])])
                self.assertEqual(self.preference_write, data['body'] or {})
                current = self.invoke('nickname', '101')
                self.assertEqual(current.returncode, 0, current.stderr)
                current = json.loads(current.stdout)
                self.assertEqual(current['name'], 'Synthetic course')
                self.assertEqual(current['nickname'], 'Synthetic alias' if command[0] == 'nickname-set' else None)
            self.assertEqual(self.course_nicknames, {})
        finally:
            type(self).course_nicknames = original

    def test_nickname_reset_refuses_changed_or_truncated_inventory_over_tls(self):
        original = self.course_nicknames.copy()
        try:
            preview = self.invoke('nicknames-reset')
            self.assertEqual(preview.returncode, 0, preview.stderr)
            type(self).course_nicknames[102] = 'Changed after preview'
            before = len(self.calls)
            changed = self.invoke('nicknames-reset', '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn('Preview changed', changed.stderr)
            truncated = self.invoke('nicknames-reset', '--max-pages', '1')
            self.assertNotEqual(truncated.returncode, 0)
            self.assertIn('Page limit', truncated.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        finally:
            type(self).course_nicknames = original

    def test_course_group_and_personal_calendar_colors_over_tls(self):
        original = self.custom_colors.copy()
        try:
            for context, item in [('course', '101'), ('group', '11'), ('user', '7')]:
                command = ('color-set', item, '--context', context, '--hex', 'AABBCC')
                before = len(self.calls)
                preview = self.invoke(*command)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                data = json.loads(preview.stdout)
                self.assertEqual(data['body'], {'hexcode': '#aabbcc'})
                refused = self.invoke(*command, '--yes', '--confirm', 'wrong')
                self.assertNotEqual(refused.returncode, 0)
                self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
                self.assertEqual(sent.returncode, 0, sent.stderr)
                self.assertTrue(json.loads(sent.stdout)['acknowledged'])
                self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'], [('PUT', data['route'])])
                current = self.invoke('color', item, '--context', context)
                self.assertEqual(current.returncode, 0, current.stderr)
                self.assertEqual(json.loads(current.stdout)['hexcode'], '#aabbcc')
            current = self.invoke('color', '102')
            self.assertIsNone(json.loads(current.stdout)['hexcode'])
            before = len(self.calls)
            denied = self.invoke('color-set', '8', '--context', 'user', '--hex', 'abc')
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn('own personal calendar', denied.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        finally:
            type(self).custom_colors = original

    def test_own_settings_changes_preserve_unrequested_fields_and_reject_stale_state(self):
        original = self.user_settings.copy()
        try:
            listing = self.invoke('settings')
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertEqual(json.loads(listing.stdout)['settings'], original)
            command = ('settings-set', '--set', 'manual_mark_as_read=true', '--set', 'collapse_course_nav=true')
            before = len(self.calls)
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            data = json.loads(preview.stdout)
            refused = self.invoke(*command, '--yes', '--confirm', 'wrong')
            self.assertNotEqual(refused.returncode, 0)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
            sent = self.invoke(*command, '--yes', '--confirm', data['confirm'], '--format', 'brief')
            self.assertEqual(sent.returncode, 0, sent.stderr)
            self.assertIn('manual_mark_as_read: True', sent.stdout)
            self.assertEqual(self.preference_write, {'manual_mark_as_read': True, 'collapse_course_nav': True})
            self.assertEqual(self.user_settings['collapse_global_nav'], original['collapse_global_nav'])
            self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                             [('PUT', '/api/v1/users/self/settings')])
            before = len(self.calls)
            stale = self.invoke(*command, '--yes', '--confirm', data['confirm'])
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn('Preview changed', stale.stderr)
            missing = self.invoke('settings-set', '--set', 'widget_dashboard_dark_mode=true')
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn('not reported', missing.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        finally:
            type(self).user_settings = original

    def test_dashboard_order_and_single_position_are_confirmed_merges_over_tls(self):
        original = self.dashboard_positions.copy()
        try:
            commands = [('dashboard-order', 'course_102', 'course_101', 'group_11'),
                        ('dashboard-position-set', '7', '--context', 'user', '--position', '-1')]
            for command in commands:
                before = len(self.calls)
                preview = self.invoke(*command)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                data = json.loads(preview.stdout)
                refused = self.invoke(*command, '--yes', '--confirm', 'wrong')
                self.assertNotEqual(refused.returncode, 0)
                self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
                self.assertEqual(sent.returncode, 0, sent.stderr)
                self.assertTrue(json.loads(sent.stdout)['acknowledged'])
                self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                                 [('PUT', '/api/v1/users/self/dashboard_positions')])
                self.assertEqual(self.preference_write, data['body'])
            current = self.invoke('dashboard-positions')
            self.assertEqual(current.returncode, 0, current.stderr)
            self.assertEqual(json.loads(current.stdout)['dashboard_positions'],
                             {'course_101': 1, 'course_102': 0, 'group_11': 2, 'group_12': '9', 'user_7': -1})
            before = len(self.calls)
            for command in [('dashboard-order', 'course_101', 'course_101'), ('dashboard-order', 'course_01'),
                            ('dashboard-position-set', '8', '--context', 'user', '--position', '0')]:
                denied = self.invoke(*command)
                self.assertNotEqual(denied.returncode, 0)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        finally:
            type(self).dashboard_positions = original

    def test_bulk_own_submissions_paginate_filters_and_opt_in_private_history_without_writes(self):
        before = len(self.calls)
        result = self.invoke('submissions', '101', '--assignment', '88', '--assignment', '88',
                             '--state', 'submitted', '--include-history', '--include-comments')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['assignment_ids'], [88])
        row = data['submissions'][0]
        self.assertEqual(row['submission_history'][0]['attempt'], 1)
        self.assertIsNone(row['submission_history'][1])
        self.assertEqual(row['submission_comments'], [{'id': 41, 'author_id': 8}])
        self.assertNotIn('Synthetic private', result.stdout)
        self.assertNotIn('Synthetic first attempt', result.stdout)
        self.assertEqual(len(self.calls[before:]), 3)
        self.assertTrue(all(method == 'GET' and 'read_status' not in route for method, route in self.calls[before:]))
        self.assertIn('student_ids%5B%5D=7', self.calls[-1][1])
        self.assertEqual(self.calls[-1][1].count('assignment_ids%5B%5D=88'), 1)
        content = self.invoke('submissions', '101', '--include-history', '--include-comments', '--include-content')
        self.assertEqual(content.returncode, 0, content.stderr)
        self.assertIn('Synthetic private submitted body', content.stdout)
        self.assertIn('Synthetic first attempt', content.stdout)
        self.assertIn('Synthetic private feedback', content.stdout)
        brief = self.invoke('--format', 'brief', 'submissions', '101', '--include-content')
        self.assertEqual(brief.returncode, 0, brief.stderr)
        self.assertIn('Grade does not match', brief.stdout)
        self.assertNotIn('Synthetic private', brief.stdout)

    def test_bulk_own_submission_page_limit_and_foreign_owner_or_history_do_not_emit_partial_content(self):
        limited = self.invoke('--max-pages', '1', 'submissions', '101')
        self.assertNotEqual(limited.returncode, 0)
        self.assertEqual(limited.stdout, '')
        saved = type(self).student_submissions
        try:
            for row in ({**saved[0], 'user_id': 8},
                        {**saved[0], 'submission_history': [{'user_id': 8, 'body': 'Synthetic foreign work'}]}):
                type(self).student_submissions = [row]
                refused = self.invoke('submissions', '101', '--include-history', '--include-content')
                self.assertNotEqual(refused.returncode, 0)
                self.assertEqual(refused.stdout, '')
                self.assertNotIn('Synthetic foreign work', refused.stderr)
            type(self).student_submissions = [{**saved[0], 'assignment_visible': False}]
            withheld = self.invoke('submissions', '101', '--include-history', '--include-comments', '--include-content')
            self.assertEqual(withheld.returncode, 0, withheld.stderr)
            self.assertIn('content_withheld', withheld.stdout)
            self.assertNotIn('Synthetic private', withheld.stdout)
            self.assertNotIn('Synthetic first attempt', withheld.stdout)
        finally:
            type(self).student_submissions = saved

    def test_discussion_rating_reads_return_own_votes_without_cached_bodies_or_read_writes(self):
        before = len(self.calls)
        result = self.invoke('topic-ratings', '101', '202')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['own_entry_ratings'], type(self).own_entry_ratings)
        self.assertEqual(data['snapshot_entry_ids'], [301, 302, 303])
        self.assertNotIn('Synthetic cached peer body', result.stdout)
        self.assertNotIn('Synthetic private participant', result.stdout)
        self.assertEqual(self.calls[before:], [
            ('GET', '/api/v1/users/self/profile'), ('GET', '/api/v1/courses/101/discussion_topics/202'),
            ('GET', '/api/v1/courses/101/discussion_topics/202/view?include_new_entries=1')])
        group = self.invoke('--format', 'brief', 'topic-ratings', '11', '203', '--context', 'group')
        self.assertEqual(group.returncode, 0, group.stderr)
        self.assertIn('Own ratings:', group.stdout)

    def test_like_and_unlike_course_and_group_use_account_bound_preview_and_leave_content_untouched(self):
        saved = type(self).own_entry_ratings.copy()
        entry = type(self).entry.copy()
        topic_state = type(self).topic_state.copy()
        try:
            for context_id, topic_id, context, value in (('101', '202', 'course', '0'), ('11', '203', 'group', '1')):
                command = ('entry-rate', context_id, topic_id, '301', '--rating', value, '--context', context)
                preview = self.invoke(*command)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                data = json.loads(preview.stdout)
                self.assertEqual(data['method'], 'POST')
                self.assertEqual(data['body'], {'rating': int(value)})
                self.assertNotIn(entry['message'], preview.stdout)
                before = len(self.calls)
                sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
                self.assertEqual(sent.returncode, 0, sent.stderr)
                self.assertEqual(json.loads(sent.stdout)['discussion_rating']['rating'], int(value))
                self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                                 [('POST', f'/api/v1/{context}s/{context_id}/discussion_topics/{topic_id}/entries/301/rating')])
                self.assertEqual(type(self).rating_write, {'rating': int(value)})
                self.assertEqual(type(self).entry, entry)
                self.assertEqual(type(self).topic_state, topic_state)
        finally:
            type(self).own_entry_ratings = saved

    def test_rating_changed_body_or_own_vote_invalidates_preview_and_pagination_limit_blocks_write(self):
        saved = type(self).own_entry_ratings.copy()
        entry = type(self).entry.copy()
        try:
            command = ('entry-rate', '101', '202', '301', '--rating', '0')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            digest = json.loads(preview.stdout)['confirm']
            for alteration in ('vote', 'body'):
                if alteration == 'vote':
                    type(self).own_entry_ratings = {}
                else:
                    type(self).own_entry_ratings = saved.copy()
                    type(self).entry = {**entry, 'message': 'Synthetic changed body, same timestamp'}
                before = len(self.calls)
                refused = self.invoke(*command, '--yes', '--confirm', digest)
                self.assertNotEqual(refused.returncode, 0)
                self.assertIn('Preview changed', refused.stderr)
                self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
            limited = self.invoke('--max-pages', '1', *command)
            self.assertNotEqual(limited.returncode, 0)
            self.assertIn('Page limit reached', limited.stderr)
        finally:
            type(self).own_entry_ratings = saved
            type(self).entry = entry

    def test_rating_post_first_disabled_and_ambiguous_ack_fail_without_retries_or_body_echo(self):
        saved_topic = type(self).topic_state.copy()
        saved_ratings = type(self).own_entry_ratings.copy()
        command = ('entry-rate', '101', '202', '301', '--rating', '0')
        try:
            for flags in ({'allow_rating': False}, {'require_initial_post': True, 'user_can_see_posts': False}):
                type(self).topic_state = {**saved_topic, **flags}
                before = len(self.calls)
                refused = self.invoke(*command)
                self.assertNotEqual(refused.returncode, 0)
                self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                self.assertFalse(any('/view?' in route or '/entry_list?' in route for _, route in self.calls[before:]))
            type(self).topic_state = saved_topic.copy()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            type(self).rating_ack_status = 200
            before = len(self.calls)
            ambiguous = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(ambiguous.returncode, 0)
            self.assertIn('empty 204 acknowledgement', ambiguous.stderr)
            self.assertNotIn('Synthetic response not for output', ambiguous.stderr + ambiguous.stdout)
            self.assertEqual(sum(method == 'POST' for method, _ in self.calls[before:]), 1)
        finally:
            type(self).topic_state = saved_topic
            type(self).own_entry_ratings = saved_ratings
            type(self).rating_ack_status = 204

    def test_missing_work_paginates_native_filters_and_does_not_treat_planner_marker_as_submitted(self):
        before = len(self.calls)
        result = self.invoke('missing', '--timezone', 'America/Los_Angeles', '--include-planner')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual([row['id'] for row in data['missing_assignments']], [88, 89])
        first = data['missing_assignments'][0]
        self.assertEqual(first['due_local'], '2026-09-30T23:59:00-07:00')
        self.assertTrue(first['planner_override']['marked_complete'])
        self.assertEqual(first['status_source'], 'canvas_missing_submissions')
        self.assertNotIn('Synthetic private prompt', result.stdout)
        self.assertFalse(data['complete_coursework_inventory'])
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        self.assertEqual(len(self.calls[before:]), 3)
        filtered = self.invoke('missing', '--course', '101', '--course', '102', '--course', '101',
                               '--submittable', '--current-grading-period')
        self.assertEqual(filtered.returncode, 0, filtered.stderr)
        self.assertEqual([row['id'] for row in json.loads(filtered.stdout)['missing_assignments']], [89])
        self.assertEqual(self.calls[-1][1].count('course_ids%5B%5D=101'), 1)
        brief = self.invoke('--format', 'brief', 'missing', '--course', '101', '--include-planner')
        self.assertEqual(brief.returncode, 0, brief.stderr)
        self.assertIn('Locked for this user', brief.stdout)
        self.assertIn('missing submission remains', brief.stdout)

    def test_missing_work_page_limit_invalid_timezone_and_wrong_account_marker_fail_closed(self):
        before = len(self.calls)
        bad_zone = self.invoke('missing', '--timezone', 'No/Such_Zone')
        self.assertNotEqual(bad_zone.returncode, 0)
        self.assertEqual(len(self.calls), before)
        limited = self.invoke('--max-pages', '1', 'missing')
        self.assertNotEqual(limited.returncode, 0)
        self.assertNotIn('missing_assignments', limited.stdout)
        saved = type(self).missing_assignments
        try:
            type(self).missing_assignments = [{**saved[0], 'planner_override': {
                **saved[0]['planner_override'], 'user_id': 8}}]
            wrong = self.invoke('missing', '--include-planner')
            self.assertNotEqual(wrong.returncode, 0)
            self.assertIn('outside this own assignment', wrong.stderr)
            type(self).missing_assignments = []
            empty = self.invoke('missing')
            self.assertEqual(empty.returncode, 0, empty.stderr)
            self.assertEqual(json.loads(empty.stdout)['missing_assignments'], [])
            self.assertFalse(json.loads(empty.stdout)['complete_coursework_inventory'])
        finally:
            type(self).missing_assignments = saved

    def test_activity_reads_paginate_without_marking_read_and_gate_cached_discussion_entries(self):
        original = self.topic_state.copy()
        try:
            type(self).topic_state.update({'require_initial_post': True, 'user_can_see_posts': False})
            before = len(self.calls)
            listing = self.invoke('activity')
            self.assertEqual(listing.returncode, 0, listing.stderr)
            data = json.loads(listing.stdout)
            self.assertEqual([row['id'] for row in data['activity']], [71, 72, 73])
            self.assertNotIn('Synthetic private body', listing.stdout)
            self.assertFalse(data['complete_coursework_inventory'])
            notices = self.invoke('activity', '--type', 'AssessmentRequest', '--format', 'brief')
            self.assertEqual(notices.returncode, 0, notices.stderr)
            self.assertIn('72 | AssessmentRequest', notices.stdout)
            self.assertNotIn('71 |', notices.stdout)
            content = self.invoke('activity', '--active', '--include-content')
            self.assertEqual(content.returncode, 0, content.stderr)
            self.assertIn('Synthetic current prompt', content.stdout)
            self.assertNotIn('Synthetic cached peer entry', content.stdout)
            self.assertNotIn('Synthetic private body', content.stdout)
            self.assertIn('entries_withheld', content.stdout)
            course = self.invoke('activity', '--course', '101')
            self.assertEqual(course.returncode, 0, course.stderr)
            self.assertEqual([row['id'] for row in json.loads(course.stdout)['activity']], [72, 73])
            counts = self.invoke('activity-summary', '--course', '101')
            self.assertEqual(counts.returncode, 0, counts.stderr)
            self.assertEqual(sum(row['count'] for row in json.loads(counts.stdout)['activity_summary']), 2)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
            self.assertEqual([row['read_state'] for row in self.activity_items], [False, False, True])
        finally:
            type(self).topic_state = original

    def test_activity_hiding_is_revision_bound_and_does_not_touch_underlying_messages(self):
        original_hidden = self.activity_hidden_ids.copy()
        original_items = [row.copy() for row in self.activity_items]
        try:
            command = ('activity-dismiss', '71')
            before = len(self.calls)
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            data = json.loads(preview.stdout)
            self.assertNotIn('Synthetic private body', preview.stdout)
            type(self).activity_items[0]['message'] = 'Changed synthetic body'
            stale = self.invoke(*command, '--yes', '--confirm', data['confirm'])
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn('Preview changed', stale.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
            type(self).activity_items = [row.copy() for row in original_items]
            sent = self.invoke(*command, '--yes', '--confirm', data['confirm'], '--format', 'brief')
            self.assertEqual(sent.returncode, 0, sent.stderr)
            self.assertIn('hide acknowledged: 71', sent.stdout)
            self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                             [('DELETE', '/api/v1/users/self/activity_stream/71')])
            current = self.invoke('activity')
            self.assertEqual([row['id'] for row in json.loads(current.stdout)['activity']], [72, 73])
            self.assertEqual(self.inbox_state['message_count'], 1)
            self.assertEqual(self.inbox_messages[0]['body'], 'Synthetic private message')
            before = len(self.calls)
            required = self.invoke('activity-dismiss-all')
            self.assertNotEqual(required.returncode, 0)
            self.assertEqual(len(self.calls), before)
            truncated = self.invoke('activity-dismiss-all', '--all', '--max-pages', '1')
            self.assertNotEqual(truncated.returncode, 0)
            self.assertIn('Page limit', truncated.stderr)
            all_preview = self.invoke('activity-dismiss-all', '--all')
            self.assertEqual(all_preview.returncode, 0, all_preview.stderr)
            all_data = json.loads(all_preview.stdout)
            self.assertIn('outside the current visible feed', all_data['effect'])
            all_sent = self.invoke('activity-dismiss-all', '--all', '--yes', '--confirm', all_data['confirm'])
            self.assertEqual(all_sent.returncode, 0, all_sent.stderr)
            current = self.invoke('activity')
            self.assertEqual(json.loads(current.stdout)['activity'], [])
            self.assertEqual(self.inbox_state['message_count'], 1)
        finally:
            type(self).activity_hidden_ids = original_hidden
            type(self).activity_items = original_items

    def test_favorites_changes_are_preview_first_and_reset_restores_defaults(self):
        original = {context: ids.copy() for context, ids in self.favorite_ids.items()}
        try:
            for context, target in [('course', '102'), ('group', '11')]:
                type(self).favorite_ids = {'course': set(), 'group': set()}
                displayed = self.invoke('favorites', '--context', context)
                self.assertEqual(displayed.returncode, 0, displayed.stderr)
                self.assertEqual(len(json.loads(displayed.stdout)), 2)
                for command in [('favorite-add', target), ('favorite-remove', target),
                                ('favorite-remove', target), ('favorites-reset',)]:
                    with self.subTest(context=context, command=command):
                        args = (*command, '--context', context)
                        before = len(self.calls)
                        preview = self.invoke(*args)
                        self.assertEqual(preview.returncode, 0, preview.stderr)
                        data = json.loads(preview.stdout)
                        self.assertFalse(data['manual_selection_known'])
                        wrong = self.invoke(*args, '--yes', '--confirm', 'wrong')
                        self.assertNotEqual(wrong.returncode, 0)
                        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                        sent = self.invoke(*args, '--yes', '--confirm', data['confirm'], '--format', 'brief')
                        self.assertEqual(sent.returncode, 0, sent.stderr)
                        self.assertIn('acknowledged', sent.stdout)
                        method = 'POST' if command[0] == 'favorite-add' else 'DELETE'
                        route = f'/api/v1/users/self/favorites/{context}s' + (f'/{target}' if len(command) > 1 else '')
                        self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'], [(method, route)])
                        if command[0] == 'favorite-add':
                            current = self.invoke('favorites', '--context', context)
                            self.assertEqual([row['id'] for row in json.loads(current.stdout)], [int(target)])
                self.assertEqual(self.favorite_ids[context], set())
                reset = self.invoke('favorites', '--context', context)
                self.assertEqual(len(json.loads(reset.stdout)), 2)
        finally:
            type(self).favorite_ids = original

    def test_favorite_preview_rejects_truncated_inventory_and_changed_selection(self):
        original = {context: ids.copy() for context, ids in self.favorite_ids.items()}
        try:
            type(self).favorite_ids = {'course': set(), 'group': set()}
            command = ('favorite-add', '102')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            type(self).favorite_ids['course'].add(101)
            before = len(self.calls)
            changed = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn('Preview changed', changed.stderr)
            truncated = self.invoke(*command, '--max-pages', '1')
            self.assertNotEqual(truncated.returncode, 0)
            self.assertIn('Page limit', truncated.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        finally:
            type(self).favorite_ids = original

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

    def test_personal_folder_edit_move_and_empty_delete_are_stateful_over_tls(self):
        original = self.personal_children.copy()
        self.__class__.personal_children = [{**self.personal_destination, 'id': 94,
                                           'name': 'Synthetic child', 'parent_folder_id': 92}]
        try:
            commands = [('my-folder-edit', '94', '--name', 'Revised child', '--parent', '91'),
                        ('my-folder-delete', '94')]
            for command in commands:
                with self.subTest(command=command):
                    before = len(self.calls)
                    preview = self.invoke(*command)
                    self.assertEqual(preview.returncode, 0, preview.stderr)
                    data = json.loads(preview.stdout)
                    self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                    sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
                    self.assertEqual(sent.returncode, 0, sent.stderr)
                    self.assertEqual(self.folder_write, data['body'] or {})
                    self.assertNotIn('force', self.folder_write)
                    self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                                     [(data['method'], '/api/v1/folders/94')])
                    read = self.invoke('folder', '94')
                    if command[0] == 'my-folder-edit':
                        self.assertEqual(read.returncode, 0, read.stderr)
                        self.assertEqual(json.loads(read.stdout)['name'], 'Revised child')
                        self.assertEqual(json.loads(read.stdout)['parent_folder_id'], 91)
                    else:
                        self.assertNotEqual(read.returncode, 0)
                        self.assertIn('HTTP 404', read.stderr)
        finally:
            self.__class__.personal_children = original

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

    def test_peer_review_scopes_paginate_and_preserve_anonymity_without_writes(self):
        before = len(self.calls)
        result = self.invoke('peer-reviews', '101', '88')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual([row['id'] for row in data['peer_reviews']], [61, 63])
        self.assertFalse(data['owed_review_inventory_complete'])
        self.assertNotIn('assessor_id', data['peer_reviews'][1])
        result = self.invoke('peer-reviews', '101', '88', '--scope', 'visible', '--include-users', '--include-comments')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual([row['id'] for row in data['peer_reviews']], [61, 62, 63])
        self.assertTrue(data['peer_reviews'][1]['assigned_to_self'])
        self.assertEqual(data['peer_reviews'][0]['submission_comments'][0]['comment'], 'Synthetic review feedback')
        self.assertNotIn('assessor', data['peer_reviews'][2])
        brief = self.invoke('peer-reviews', '101', '88', '--format', 'brief')
        self.assertEqual(brief.returncode, 0, brief.stderr)
        self.assertIn('hidden/unknown', brief.stdout)
        truncated = self.invoke('peer-reviews', '101', '88', '--max-pages', '1')
        self.assertNotEqual(truncated.returncode, 0)
        self.assertIn('Page limit', truncated.stderr)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        self.assertFalse(any('/allocate' in route or 'read_status' in route for _, route in self.calls[before:]))

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

    def test_inbox_organization_changes_only_requested_own_view_fields(self):
        original, messages = self.inbox_state.copy(), list(self.inbox_messages)
        try:
            for options, expected in [(('--state', 'read'), {'workflow_state': 'read'}),
                                      (('--state', 'unread'), {'workflow_state': 'unread'}),
                                      (('--state', 'archived'), {'workflow_state': 'archived'}),
                                      (('--starred', '--no-subscribed'), {'starred': True, 'subscribed': False}),
                                      (('--no-starred', '--subscribed'), {'starred': False, 'subscribed': True})]:
                with self.subTest(options=options):
                    command = ('inbox-edit', '12', *options)
                    before = len(self.calls)
                    preview = self.invoke(*command)
                    self.assertEqual(preview.returncode, 0, preview.stderr)
                    data = json.loads(preview.stdout)
                    self.assertEqual(data['body'], {'conversation': expected})
                    self.assertNotIn('Synthetic private message', preview.stdout)
                    rejected = self.invoke(*command, '--yes', '--confirm', 'wrong')
                    self.assertNotEqual(rejected.returncode, 0)
                    self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                    sent = self.invoke(*command, '--yes', '--confirm', data['confirm'], '--format', 'brief')
                    self.assertEqual(sent.returncode, 0, sent.stderr)
                    self.assertIn('acknowledged', sent.stdout)
                    self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                                     [('PUT', '/api/v1/conversations/12')])
                    self.assertEqual(self.inbox_write, {'conversation': expected})
                    current = self.invoke('conversation', '12')
                    self.assertEqual(current.returncode, 0, current.stderr)
                    thread = json.loads(current.stdout)
                    for key, value in expected.items():
                        self.assertEqual(thread[key], value)
                    self.assertEqual(thread['messages'], messages)
        finally:
            type(self).inbox_state, type(self).inbox_messages = original, messages

    def test_inbox_delete_empties_own_view_only_and_requires_permanent_ack(self):
        original, messages = self.inbox_state.copy(), list(self.inbox_messages)
        try:
            before = len(self.calls)
            missing = self.invoke('inbox-delete', '12')
            self.assertNotEqual(missing.returncode, 0)
            self.assertEqual(self.calls[before:], [])
            command = ('inbox-delete', '12', '--permanent')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            sent = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertEqual(sent.returncode, 0, sent.stderr)
            self.assertTrue(json.loads(sent.stdout)['deleted_from_own_view'])
            self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                             [('DELETE', '/api/v1/conversations/12')])
            current = json.loads(self.invoke('conversation', '12').stdout)
            self.assertEqual(current['messages'], [])
            self.assertEqual(current['message_count'], 0)
            self.assertFalse(any('/delete_for_all' in route for _, route in self.calls[before:]))
        finally:
            type(self).inbox_state, type(self).inbox_messages = original, messages

    def test_inbox_new_message_or_private_thread_refuses_old_preview_or_subscription(self):
        original, messages = self.inbox_state.copy(), list(self.inbox_messages)
        try:
            command = ('inbox-edit', '12', '--no-starred')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            type(self).inbox_messages = messages + [{'id': 32, 'body': 'Synthetic later message'}]
            before = len(self.calls)
            changed = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn('Preview changed', changed.stderr)
            self.inbox_state['private'] = True
            refused = self.invoke('inbox-edit', '12', '--no-subscribed')
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn('group conversation', refused.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        finally:
            type(self).inbox_state, type(self).inbox_messages = original, messages

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
