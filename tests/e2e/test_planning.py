"""Installed-CLI HTTPS regression tests for planning workflows."""

import json

from .fixture import CanvasFixture


class PlanningE2E(CanvasFixture):
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
