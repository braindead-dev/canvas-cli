"""Installed-CLI HTTPS regression tests for coursework workflows."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .fixture import CanvasFixture


class CourseworkE2E(CanvasFixture):
    def test_feedback_summary_follows_pages_with_own_grade_comments_and_rubric_but_never_answers(self):
        original = list(self.student_submissions)
        try:
            type(self).student_submissions = [{**original[0], 'grade': 'B+', 'score': 8.5,
                'graded_at': '2026-10-01T18:00:00Z', 'posted_at': '2026-10-01T19:00:00Z',
                'assignment': {**original[0]['assignment'], 'points_possible': 10},
                'submission_comments': [{'id': 41, 'author_id': 8, 'created_at': '2026-10-02T19:00:00Z',
                                         'comment': 'Synthetic feedback-only comment',
                                         'attachments': [{'url': 'https://example.edu/synthetic-private-feedback-attachment'}]}],
                'rubric_assessment': {'_criterion': {'points': 8.5, 'rating_id': 'rating1',
                                                      'comments': 'Synthetic rubric-only comment',
                                                      'private': 'synthetic-private-rubric-extra'}}}]
            before = len(self.calls)
            result = self.invoke('feedback', '101', '--timezone', 'America/Los_Angeles', '--format', 'brief')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Grade does not match the current attempt', result.stdout)
            self.assertIn('score 8.5 / 10', result.stdout)
            self.assertIn('12:00 PM PDT', result.stdout)
            self.assertNotIn('feedback-only comment', result.stdout)
            self.assertNotIn('rubric-only comment', result.stdout)
            self.assertNotIn('Synthetic private submitted body', result.stdout)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
            routes = [route for _, route in self.calls[before:]]
            self.assertEqual(len(routes), 3)
            query = parse_qs(urlsplit(routes[1]).query)
            self.assertEqual(query['student_ids[]'], ['7'])
            self.assertEqual(query['include[]'], ['assignment', 'submission_comments', 'rubric_assessment'])
            self.assertNotIn('read_status', routes[1])
            result = self.invoke('feedback', '101', '--include-text', '--assignment', '88')
            self.assertEqual(result.returncode, 0, result.stderr)
            item = json.loads(result.stdout)['feedback'][0]
            self.assertEqual(item['comments'][0]['comment'], 'Synthetic feedback-only comment')
            self.assertEqual(item['rubric_assessment']['_criterion']['comments'], 'Synthetic rubric-only comment')
            self.assertNotIn('Synthetic private submitted body', result.stdout)
            self.assertNotIn('Synthetic first attempt', result.stdout)
            self.assertNotIn('synthetic-private', result.stdout)
            self.assertNotIn('attachment', str(item['comments']))
        finally:
            type(self).student_submissions = original


    def test_feedback_since_priority_uncertain_dates_and_empty_native_inventory_over_tls(self):
        original = list(self.student_submissions)
        try:
            base = {'user_id': 7, 'score': 0, 'grade': '0', 'workflow_state': 'graded',
                    'grade_matches_current_submission': True, 'submission_comments': [], 'rubric_assessment': {}}
            type(self).student_submissions = [
                {**base, 'assignment_id': 88, 'assignment': {'id': 88}, 'graded_at': '2026-10-01T00:00:00Z'},
                {**base, 'assignment_id': 89, 'assignment': {'id': 89}, 'graded_at': '2026-10-03T00:00:00Z', 'redo_request': True},
                {**base, 'assignment_id': 90, 'assignment': {'id': 90}, 'graded_at': None, 'grade_matches_current_submission': False},
                {'user_id': 7, 'assignment_id': 91, 'assignment': {'id': 91}, 'submission_comments': []},
            ]
            result = self.invoke('feedback', '101', '--since', '2026-10-02T00:00:00Z')
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual([row['assignment_id'] for row in data['feedback']], [89, 90])
            self.assertEqual(data['excluded_before_since'], 1)
            self.assertEqual(data['excluded_no_reported_feedback'], 1)
            self.assertEqual(data['included_uncertain_dates'], 1)
            self.assertFalse(data['complete_coursework_inventory'])
            result = self.invoke('feedback', '101', '--assignment', '92', '--format', 'brief')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('not proof of completed coursework', result.stdout)
        finally:
            type(self).student_submissions = original


    def test_feedback_truncation_foreign_owner_malformed_rubric_and_hidden_assignment_fail_safely(self):
        original = list(self.student_submissions)
        try:
            result = self.invoke('feedback', '101', '--max-pages', '1')
            self.assertEqual(result.returncode, 1)
            self.assertIn('page limit', result.stderr.lower())
            self.assertEqual(result.stdout, '')
            for patch in ({'user_id': 8}, {'score': True}, {'rubric_assessment': {'a': {'points': True}}},
                          {'graded_at': 'not a timestamp'}):
                type(self).student_submissions = [{**original[0], **patch}]
                result = self.invoke('feedback', '101', '--include-text')
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertEqual(result.stdout, '')
                self.assertNotIn('Synthetic private', result.stderr)
            type(self).student_submissions = [{**original[0], 'assignment_visible': False,
                                               'rubric_assessment': {'a': {'comments': 'Synthetic hidden rubric', 'points': 10}}}]
            result = self.invoke('feedback', '101', '--include-text')
            self.assertEqual(result.returncode, 0, result.stderr)
            item = json.loads(result.stdout)['feedback'][0]
            self.assertIn('feedback_text_withheld', item)
            self.assertIsNone(item['rubric_assessment'])
            self.assertNotIn('Synthetic hidden rubric', result.stdout)
            self.assertNotIn('Synthetic private feedback', result.stdout)
            before = len(self.calls)
            for arguments in (('--since', '2026-10-02'), ('--since', '2026-10-02T00:00:00'),
                              ('--timezone', 'invalid/synthetic')):
                result = self.invoke('feedback', '101', *arguments)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(self.calls[before:], [])
        finally:
            type(self).student_submissions = original


    def test_bulk_rubric_association_is_opt_in_and_metadata_first_over_tls(self):
        original = list(self.student_submissions)
        try:
            type(self).student_submissions = [{**original[0], 'rubric_assessment': {
                '_criterion': {'rating_id': 'rating1', 'points': 0, 'comments': 'Synthetic private rubric comment'}}}]
            result = self.invoke('submissions', '101')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('rubric_assessment', result.stdout)
            before = len(self.calls)
            result = self.invoke('submissions', '101', '--include-rubric')
            self.assertEqual(result.returncode, 0, result.stderr)
            item = json.loads(result.stdout)['submissions'][0]
            self.assertEqual(item['rubric_assessment'], {'_criterion': {'rating_id': 'rating1', 'points': 0}})
            self.assertNotIn('Synthetic private', result.stdout)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
            query = parse_qs(urlsplit(self.calls[before + 1][1]).query)
            self.assertEqual(query['include[]'], ['assignment', 'rubric_assessment'])
            result = self.invoke('submissions', '101', '--include-rubric', '--include-content')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Synthetic private rubric comment', result.stdout)
        finally:
            type(self).student_submissions = original


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
