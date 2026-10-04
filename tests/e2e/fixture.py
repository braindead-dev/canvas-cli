"""Shared synthetic Canvas/storage HTTPS fixture; never contacts a real account."""

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
from urllib.parse import parse_qs, unquote, urlsplit

from . import (
    announcement_authoring,
    appointments,
    channels,
    feedback_comments,
    module_items,
    module_paths,
    page_authoring,
    page_deletion,
    page_duplication,
    page_history,
    page_scheduling,
    snapshot_revalidation,
    submission_attention,
    submission_comments,
    submission_drafts,
    team_appointments,
    topic_management,
    topic_view,
    what_if,
    what_if_course,
)


@unittest.skipUnless(shutil.which('openssl'), 'openssl required for local TLS fixture')


class CanvasFixture(unittest.TestCase):
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
        announcement_authoring.initialize(cls)
        appointments.initialize(cls)
        module_items.initialize(cls)
        module_paths.initialize(cls)
        team_appointments.initialize(cls)
        page_authoring.initialize(cls)
        page_history.initialize(cls)
        page_deletion.initialize(cls)
        page_duplication.initialize(cls)
        page_scheduling.initialize(cls)
        snapshot_revalidation.initialize(cls)
        topic_management.initialize(cls)
        topic_view.initialize(cls)
        submission_drafts.initialize(cls)
        submission_comments.initialize(cls)
        submission_attention.initialize(cls)
        feedback_comments.initialize(cls)
        what_if.initialize(cls)
        what_if_course.initialize(cls)
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
        cls.own_profile = {'id': 7, 'name': 'Synthetic Student', 'short_name': 'Synthetic',
                           'sortable_name': 'Student, Synthetic', 'title': None, 'bio': 'Synthetic private old biography',
                           'pronunciation': None, 'pronouns': 'they/them', 'time_zone': 'America/Denver',
                           'locale': None, 'effective_locale': 'en', 'primary_email': 'synthetic-profile@example.edu',
                           'login_id': 'synthetic-private-profile-login', 'sis_user_id': 'synthetic-private-profile-sis',
                           'calendar': {'ics': 'https://example.edu/feeds/synthetic-private-profile-secret.ics'}}
        cls.profile_denied = False
        cls.profile_ack = 'normal'
        cls.profile_ignored_fields = set()
        cls.profile_fail_readback = False
        cls.profile_written = False
        cls.sync_switch_viewer = False
        cls.planning_assignments = None
        cls.dashboard_positions = {'course_101': 1, 'course_102': 2, 'group_12': '9'}
        channels.initialize(cls)
        cls.raw_json_response = b'{"id":1}'
        cls.notification_preferences = {
            'new_announcement': {'notification': 'new_announcement', 'category': 'announcement', 'frequency': 'daily'},
            'submission_comment': {'notification': 'submission_comment', 'category': 'submission_comment', 'frequency': 'never'}}
        cls.notification_ack_shape = 'normal'
        cls.group_folder = {'id': 95, 'context_type': 'Group', 'context_id': 11, 'name': 'Group files',
                            'parent_folder_id': None, 'files_count': 1, 'folders_count': 0}
        cls.group_file = {'id': 891, 'folder_id': 95, 'display_name': 'synthetic-group.txt', 'size': 20,
                          'locked_for_user': False, 'hidden_for_user': False}
        cls.group_page = {'page_id': 411, 'url': 'welcome', 'title': 'Group welcome', 'published': True,
                          'body': '<p>Synthetic group page body</p>', 'secure_params': 'synthetic-private-page-verifier'}
        cls.storage_quota = {'quota': 1000, 'quota_used': 20}
        cls.upload_scoped_record = None
        cls.upload_denied = False
        cls.upload_ack_patch = {}
        cls.upload_readback_patch = {}
        cls.membership_group_options = {'role': 'student_organized', 'group_category_id': 3,
                                        'non_collaborative': False, 'concluded': False,
                                        'join_level': 'parent_context_auto_join', 'members_count': 20, 'is_full': False}
        cls.group_memberships = [{'id': 72, 'group_id': 11, 'user_id': 8, 'workflow_state': 'accepted', 'moderator': False}]
        cls.membership_permissions = {'join': True, 'leave': True}
        cls.membership_ack = 'normal'
        cls.membership_denied = False
        cls.membership_write = None
        cls.group_category = {'id': 3, 'context_type': 'Course', 'course_id': 101, 'name': 'Synthetic project sets',
                              'self_signup': 'restricted', 'group_limit': 5, 'allows_multiple_memberships': False,
                              'sis_group_category_id': 'synthetic-private-category-sis',
                              'progress': {'message': 'synthetic-private-category-progress'}}
        cls.category_groups = [{'id': 11, 'context_type': 'Course', 'course_id': 101, 'group_category_id': 3,
                                'name': 'Synthetic project team', 'members_count': 3,
                                'leader': {'id': 8, 'name': 'synthetic-private-category-leader'}}]
        cls.category_denied = False
        cls.own_enrollments = [{'id': 77, 'course_id': 101, 'user_id': 7, 'course_section_id': 31,
                                'type': 'StudentEnrollment', 'enrollment_state': 'active',
                                'grades': {'current_score': 100}, 'sis_user_id': 'synthetic-private-own-enrollment-sis',
                                'user': {'email': 'synthetic-private-own-enrollment-contact@example.edu'}},
                               {'id': 78, 'course_id': 101, 'user_id': 7, 'course_section_id': 32,
                                'type': 'TaEnrollment', 'enrollment_state': 'active'}]
        cls.enrollment_invitation = {'id': 99, 'course_id': 102, 'user_id': 7, 'course_section_id': 33,
                                     'type': 'StudentEnrollment', 'enrollment_state': 'invited',
                                     'updated_at': '2026-10-02T12:00:00Z'}
        cls.invitation_denied = False
        cls.invitation_ack = 'normal'
        cls.roster_users = [
            {'id': 7, 'name': 'Synthetic teacher', 'email': 'synthetic-roster-contact@example.edu',
             'sis_user_id': 'synthetic-private-roster-sis', 'login_id': 'synthetic-private-roster-login',
             'avatar_url': 'https://storage.example.edu/?token=synthetic-private-roster-avatar',
             'enrollments': [{'id': 27, 'course_id': 101, 'user_id': 7, 'course_section_id': 31,
                              'type': 'TeacherEnrollment', 'enrollment_state': 'active',
                              'grades': {'current_score': 100}}]},
            {'id': 8, 'name': 'Synthetic TA', 'email': 'synthetic-roster-ta@example.edu',
             'enrollments': [{'id': 28, 'course_id': 101, 'user_id': 8, 'course_section_id': 32,
                              'type': 'TaEnrollment', 'enrollment_state': 'invited', 'grades': {'current_score': 99}}]}]
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
                if announcement_authoring.read(cls, self):
                    return
                if snapshot_revalidation.read(cls, self):
                    return
                if what_if_course.read(cls, self):
                    return
                if what_if.read(cls, self):
                    return
                if feedback_comments.read(cls, self):
                    return
                if submission_attention.read(cls, self):
                    return
                if submission_comments.read(cls, self):
                    return
                if submission_drafts.read(cls, self):
                    return
                if topic_view.read(cls, self):
                    return
                if module_paths.read(cls, self):
                    return
                if topic_management.read(cls, self):
                    return
                if module_items.read(cls, self):
                    return
                if page_scheduling.read(cls, self):
                    return
                if page_duplication.read(cls, self):
                    return
                if page_deletion.read(cls, self):
                    return
                if page_history.read(cls, self):
                    return
                if page_authoring.read(cls, self):
                    return
                if team_appointments.read(cls, self):
                    return
                if appointments.read(cls, self):
                    return
                if channels.read(cls, self):
                    return
                if self.path == '/api/v1/synthetic-json':
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(cls.raw_json_response)
                    return
                if self.path == '/api/v1/users/self/profile' and cls.profile_fail_readback and cls.profile_written:
                    self.send_response(403); self.end_headers(); return
                if self.path == '/api/v1/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/api/v1/users/self/profile')
                    self.end_headers(); return
                if self.path.startswith('/api/v1/courses/102/users?'):
                    self.send_response(403); self.end_headers(); return
                if cls.category_denied and self.path.startswith(('/api/v1/courses/101/group_categories?', '/api/v1/group_categories/3')):
                    self.send_response(403); self.end_headers(); return
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
                if self.path.endswith('/folders/by_path/Missing'):
                    self.send_response(404); self.end_headers(); return
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                if self.path.startswith('/api/v1/users/self/enrollments?'):
                    if 'page=2' not in self.path:
                        self.send_header('Link', f'<{self.path}&page=2>; rel="next"')
                        data = []
                    else:
                        query = parse_qs(urlsplit(self.path).query)
                        types = query.get('type[]', [])
                        states = query.get('state[]', ['active', 'invited'])
                        data = [row for row in [*cls.own_enrollments, cls.enrollment_invitation]
                                if (not types or row['type'] in types) and row['enrollment_state'] in states]
                elif self.path.startswith('/api/v1/courses/101/permissions?'):
                    data = {'read_roster': True, 'send_messages': False, 'private': 'synthetic-private-permission-metadata'}
                elif self.path.startswith('/api/v1/courses/101/group_categories?'):
                    if 'page=2' not in self.path:
                        self.send_header('Link', f'<{self.path}&page=2>; rel="next"')
                        data = []
                    else:
                        data = [cls.group_category]
                elif self.path == '/api/v1/group_categories/3':
                    data = cls.group_category
                elif self.path.startswith('/api/v1/group_categories/3/groups?'):
                    if 'page=2' not in self.path:
                        self.send_header('Link', f'<{self.path}&page=2>; rel="next"')
                        data = []
                    else:
                        data = cls.category_groups
                elif self.path.startswith(('/api/v1/courses/101/users?', '/api/v1/groups/11/users?')):
                    query = parse_qs(urlsplit(self.path).query)
                    if 'page=2' not in self.path:
                        self.send_header('Link', f'<{self.path}&page=2>; rel="next"')
                        data = []
                    else:
                        data = [{**row} for row in cls.roster_users]
                        if 'enrollments' not in query.get('include[]', []):
                            data = [{key: value for key, value in row.items() if key != 'enrollments'} for row in data]
                elif self.path.startswith('/api/v1/groups/11/memberships?'):
                    if 'page=2' not in self.path:
                        self.send_header('Link', f'<{self.path}&page=2>; rel="next"')
                        data = []
                    else:
                        data = cls.group_memberships
                elif self.path.startswith('/api/v1/groups/11/permissions?'):
                    data = cls.membership_permissions
                elif self.path == '/api/v1/courses?per_page=100':
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
                    data = (cls.planning_assignments if cls.planning_assignments is not None else
                            [{'id': 88, 'name': 'Synthetic paper',
                              'due_at': (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()}])
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
                    data = (cls.planning_assignments if cls.planning_assignments is not None else
                            [{'id': 88, 'name': 'Synthetic paper',
                              'due_at': (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
                              'submission': {'workflow_state': 'submitted', 'submitted_at': '2026-09-01T12:00:00Z'}},
                             {'id': 89, 'name': 'Unfinished project',
                              'due_at': (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
                              'submission': {'workflow_state': 'unsubmitted'}}])
                elif self.path == '/api/v1/courses/101?include[]=syllabus_body':
                    if cls.sync_switch_viewer:
                        cls.own_profile = {**cls.own_profile, 'id': 8}
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
                    data = ({**cls.upload_scoped_record, **cls.upload_ack_patch} if cls.upload_scoped_record else
                            {'id': 777, 'display_name': 'synthetic.txt'})
                elif self.path in ('/api/v1/courses/101/files/777', '/api/v1/groups/11/files/777', '/api/v1/users/self/files/777'):
                    data = {**(cls.upload_scoped_record or {}), **cls.upload_readback_patch}
                elif self.path == '/api/v1/files/777':
                    data = {'id': 777, 'display_name': 'synthetic.txt', 'size': 22,
                            'uuid': 'synthetic-uuid', 'locked_for_user': False}
                elif self.path == '/api/v1/files/778':
                    data = {'id': 778, 'display_name': 'second.txt', 'size': 14,
                            'uuid': 'second-synthetic-uuid', 'locked_for_user': False}
                elif self.path == '/api/v1/users/self/files?per_page=100' or self.path == '/api/v1/users/self/files?per_page=100&search_term=synthetic':
                    data = [{'id': 777, 'display_name': 'synthetic.txt', 'size': 22}]
                elif self.path == '/api/v1/users/self/profile':
                    data = cls.own_profile
                elif self.path == '/api/v1/files/881':
                    data = cls.personal_file
                elif self.path in ('/api/v1/folders/91', '/api/v1/users/self/folders/root'):
                    data = cls.personal_root
                elif self.path in ('/api/v1/folders/92', '/api/v1/users/self/folders/92'):
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
                elif self.path.startswith(('/api/v1/groups/11/files?', '/api/v1/groups/11/folders?', '/api/v1/groups/11/pages?')):
                    resource = urlsplit(self.path).path.rsplit('/', 1)[1]
                    if 'page=2' not in self.path:
                        self.send_header('Link', f'</api/v1/groups/11/{resource}?page=2>; rel="next"')
                        data = []
                    else:
                        data = {'files': [{**cls.group_file, 'url': 'https://storage.example.edu/?token=synthetic-private'}],
                                'folders': [cls.group_folder],
                                'pages': [cls.group_page, {'page_id': 412, 'url': 'draft', 'published': False,
                                                          'body': 'Synthetic hidden group page'}]}[resource]
                elif self.path == '/api/v1/groups/11/files/891':
                    data = {**cls.group_file, 'url': f'https://localhost:{cls.server.server_port}/storage/synthetic-file'}
                elif self.path in ('/api/v1/groups/11/folders/root', '/api/v1/groups/11/folders/95'):
                    data = cls.group_folder
                elif self.path in ('/api/v1/courses/101/folders/root', '/api/v1/courses/101/folders/96'):
                    data = {**cls.group_folder, 'id': 96, 'context_type': 'Course', 'context_id': 101}
                elif any(self.path.startswith(prefix + '/folders/by_path') for prefix in
                         ('/api/v1/courses/101', '/api/v1/groups/11', '/api/v1/users/self')):
                    prefix = next(prefix for prefix in ('/api/v1/courses/101', '/api/v1/groups/11', '/api/v1/users/self')
                                  if self.path.startswith(prefix + '/folders/by_path'))
                    root_record = (cls.personal_root if prefix.endswith('/self') else
                                   {**cls.group_folder, 'id': 96, 'context_type': 'Course', 'context_id': 101}
                                   if prefix.startswith('/api/v1/courses') else cls.group_folder)
                    path = unquote(self.path[len(prefix + '/folders/by_path'):]).lstrip('/')
                    data = [root_record]
                    for index, name in enumerate(path.split('/') if path else []):
                        data.append({**root_record, 'id': root_record['id'] + index + 10,
                                     'name': name, 'parent_folder_id': data[-1]['id'],
                                     'private_field': 'synthetic-private-folder-detail'})
                elif self.path in ('/api/v1/groups/11/pages/welcome', '/api/v1/groups/11/pages/411', '/api/v1/groups/11/front_page'):
                    data = cls.group_page
                elif self.path == '/api/v1/groups/11/tabs?per_page=100':
                    data = [{'id': 'home', 'label': 'Home', 'type': 'internal', 'html_url': '/groups/11'},
                            {'id': 'hidden', 'label': 'Synthetic hidden tab', 'hidden': True},
                            {'id': 'external', 'label': 'External tool', 'type': 'external', 'html_url': 'https://tool.example.edu/'}]
                elif self.path in ('/api/v1/courses/101/files/quota', '/api/v1/groups/11/files/quota', '/api/v1/users/self/files/quota'):
                    data = cls.storage_quota
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
                elif self.path == '/api/v1/users/self/communication_channels/19/notification_preferences':
                    data = {'notification_preferences': list(cls.notification_preferences.values())}
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
                    if self.path == '/api/v1/groups/11':
                        data = {**data, **cls.membership_group_options}
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
                if announcement_authoring.write(cls, self, body):
                    return
                if what_if_course.execute(cls, self, body):
                    return
                if what_if.execute(cls, self, body):
                    return
                if feedback_comments.execute(cls, self, body):
                    return
                if submission_attention.execute(cls, self, body):
                    return
                if submission_comments.execute(cls, self, body):
                    return
                if submission_drafts.execute(cls, self, body):
                    return
                if topic_view.execute(cls, self, body):
                    return
                if module_paths.write(cls, self, body):
                    return
                if topic_management.write(cls, self, body):
                    return
                if module_items.write(cls, self, body):
                    return
                if page_scheduling.write(cls, self, body):
                    return
                if page_duplication.write(cls, self, body):
                    return
                if page_deletion.write(cls, self, body):
                    return
                if page_history.write(cls, self, body):
                    return
                if page_authoring.write(cls, self, body):
                    return
                if team_appointments.write(cls, self, body):
                    return
                if appointments.write(cls, self, body):
                    return
                if channels.write(cls, self, body):
                    return
                if self.path == '/api/v1/users/self':
                    if cls.profile_denied:
                        self.send_response(403); self.end_headers(); return
                    if self.command != 'PUT' or body.get('override_sis_stickiness') is not False:
                        self.send_response(400); self.end_headers(); return
                    cls.profile_write = body
                    cls.profile_written = True
                    cls.own_profile.update({key: value for key, value in body['user'].items()
                                            if key not in cls.profile_ignored_fields})
                    data = cls.own_profile if cls.profile_ack == 'normal' else {'private': 'Synthetic never log profile error'}
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps(data).encode()); return
                if self.path in ('/api/v1/courses/102/enrollments/99/accept', '/api/v1/courses/102/enrollments/99/reject'):
                    if cls.invitation_denied:
                        self.send_response(403); self.end_headers(); return
                    if self.command != 'POST' or cls.enrollment_invitation['enrollment_state'] != 'invited':
                        self.send_response(400); self.end_headers(); return
                    cls.enrollment_invitation['enrollment_state'] = 'active' if self.path.endswith('/accept') else 'rejected'
                    data = {'success': True} if cls.invitation_ack == 'normal' else {'private': 'Synthetic never log invitation error'}
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps(data).encode()); return
                if self.path in ('/api/v1/groups/11/memberships', '/api/v1/groups/11/users/self'):
                    if cls.membership_denied:
                        self.send_response(403); self.end_headers(); return
                    cls.membership_write = body
                    if self.command == 'POST':
                        own = {'id': 71, 'group_id': 11, 'user_id': 7, 'moderator': False,
                               'workflow_state': 'requested' if cls.membership_group_options['role'] == 'communities' and
                               cls.membership_group_options['join_level'] == 'parent_context_request' else 'accepted'}
                        cls.group_memberships = [row for row in cls.group_memberships if row['user_id'] != 7] + [own]
                        data = own
                    elif self.command == 'DELETE':
                        cls.group_memberships = [row for row in cls.group_memberships if row['user_id'] != 7]
                        data = {'ok': True}
                    else:
                        self.send_response(400); self.end_headers(); return
                    if cls.membership_ack == 'ambiguous':
                        data = {'private': 'Synthetic never log membership error'}
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps(data).encode()); return
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
                if self.path == '/api/v1/users/self/communication_channels/19/notification_preferences':
                    cls.notification_write = body
                    updates = body['notification_preferences']
                    for name, options in updates.items():
                        cls.notification_preferences[name]['frequency'] = options['frequency']
                    data = {'notification_preferences': [cls.notification_preferences[name] for name in updates]}
                    if cls.notification_ack_shape == 'ambiguous':
                        data = {'private_body': 'Synthetic never log notification error', 'notification_preferences': []}
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps(data).encode()); return
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
                                 '/api/v1/courses/101/files', '/api/v1/groups/11/files',
                                 '/api/v1/courses/101/assignments/89/submissions/self/files'):
                    if cls.upload_denied:
                        self.send_response(403); self.end_headers(); return
                    cls.upload_initial = body
                    cls.upload_scoped_record = ({'id': 777, 'display_name': body['name'], 'size': body['size'],
                                                 'folder_id': body['parent_folder_id'],
                                                 'url': 'https://storage.example.edu/file?signature=synthetic-private-upload'}
                                                if 'parent_folder_id' in body else None)
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
        return subprocess.run([sys.executable, '-m', 'canvas_cli.cli', *args], env=env,
                              text=True, capture_output=True, timeout=10, check=False)
