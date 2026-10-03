"""Installed-CLI HTTPS regression tests for core workflows."""

import json
from pathlib import Path

from .fixture import CanvasFixture


class CoreE2E(CanvasFixture):
    def test_ambiguous_or_nonfinite_json_response_is_not_printed_as_trusted_state(self):
        original = self.raw_json_response
        try:
            for response in (b'{"id":7,"id":8,"private":"Synthetic private raw JSON"}',
                             b'{"nested":{"id":7,"id":8}}', b'{"score":NaN}', b'{"score":1e999}'):
                type(self).raw_json_response = response
                before = len(self.calls)
                result = self.invoke('get', '/api/v1/synthetic-json')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertIn('unexpected response', result.stderr)
                self.assertNotIn('Synthetic private', result.stderr)
                self.assertEqual(self.calls[before:], [('GET', '/api/v1/synthetic-json')])
        finally:
            type(self).raw_json_response = original

    def test_offline_snapshot_commands_reject_ambiguous_identity_without_auth_or_overwriting_files(self):
        snapshot = Path(self.tmp.name) / 'synthetic-ambiguous-snapshot.json'
        output = Path(self.tmp.name) / 'synthetic-ambiguous-notes.md'
        snapshot.write_text('{"schema_version":1,"viewer_user_id":7,"viewer_user_id":8, '
                            '"private":"Synthetic private snapshot content"}', encoding='utf-8')
        before = len(self.calls)
        commands = (('snapshot-diff', str(snapshot), str(snapshot)),
                    ('snapshot-search', str(snapshot), '--query', 'Synthetic'),
                    ('snapshot-markdown', str(snapshot), '--output', str(output)))
        for command in commands:
            result = self.invoke(*command, token='invalid')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertIn('valid JSON snapshot', result.stderr)
            self.assertNotIn('Synthetic private', result.stderr)
            self.assertFalse(output.exists())
        self.assertEqual(self.calls[before:], [])

    def test_courses_paginate_over_tls(self):
        r = self.invoke('courses')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([x['id'] for x in json.loads(r.stdout)], [101, 102])


    def test_machine_schemas_work_without_auth_or_network_and_keep_write_safety_visible(self):
        before = len(self.calls)
        result = self.invoke('schema', 'enrollment-accept', token='invalid')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['schema_version'], 1)
        command = data['commands'][0]
        self.assertEqual(command['command'], 'enrollment-accept')
        self.assertEqual(command['safety'], 'Canvas writes (preview-first)')
        arguments = {row['destination']: row for row in command['arguments']}
        self.assertTrue(arguments['acknowledge_canvas_enrollment']['required'])
        self.assertIn('--confirm', arguments['confirm']['flags'])
        self.assertTrue(arguments['max_pages']['default_suppressed'])
        result = self.invoke('schema', 'auth', token='invalid')
        self.assertEqual(result.returncode, 0, result.stderr)
        nested = json.loads(result.stdout)['commands'][0]['subcommand_selectors'][0]
        self.assertEqual(set(nested['commands']), {'login', 'status', 'logout'})
        result = self.invoke('schema', '--search', 'group', '--format', 'brief', token='invalid')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('group-join | Canvas writes (preview-first)', result.stdout)
        self.assertIn('group-users | Read-only', result.stdout)
        self.assertEqual(self.calls[before:], [])


    def test_machine_schema_empty_search_conflict_and_unknown_commands_fail_offline(self):
        before = len(self.calls)
        for arguments, code in ((('schema', '--search', ' '), 1),
                                 (('schema', 'group-users', '--search', 'group'), 1),
                                 (('schema', 'not-a-command'), 2)):
            result = self.invoke(*arguments, token='invalid')
            self.assertEqual(result.returncode, code)
            self.assertEqual(result.stdout, '')
        result = self.invoke('schema', '--search', 'nonexistent-synthetic-command', token='invalid')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['commands'], [])
        self.assertEqual(self.calls[before:], [])


    def test_own_enrollment_foreign_truncated_and_stale_states_never_authorize_invitation_writes(self):
        original_invite, original_rows = self.enrollment_invitation.copy(), list(self.own_enrollments)
        try:
            command = ('enrollment-accept', '102', '99', '--acknowledge-canvas-enrollment')
            before = len(self.calls)
            preview = self.invoke(*command)
            digest = json.loads(preview.stdout)['confirm']
            self.enrollment_invitation['updated_at'] = '2026-10-02T13:00:00Z'
            result = self.invoke(*command, '--yes', '--confirm', digest)
            self.assertEqual(result.returncode, 1)
            self.assertIn('Preview changed', result.stderr)
            type(self).enrollment_invitation = original_invite.copy()
            self.enrollment_invitation['user_id'] = 8
            result = self.invoke(*command)
            self.assertEqual(result.returncode, 1)
            self.assertIn('outside the requested course/user', result.stderr)
            self.assertEqual(result.stdout, '')
            type(self).enrollment_invitation = original_invite.copy()
            for commands in (('enrollments', '--max-pages', '1'), (*command, '--max-pages', '1')):
                result = self.invoke(*commands)
                self.assertEqual(result.returncode, 1)
                self.assertIn('Page limit', result.stderr)
                self.assertEqual(result.stdout, '')
            self.own_enrollments.append(original_rows[0])
            result = self.invoke('enrollments')
            self.assertEqual(result.returncode, 1)
            self.assertIn('duplicate', result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        finally:
            type(self).enrollment_invitation = original_invite
            type(self).own_enrollments = original_rows


    def test_expired_auth(self):
        r = self.invoke('auth', 'status', token='invalid-secret')
        self.assertEqual(r.returncode, 1)
        self.assertIn('auth login', r.stderr)
        self.assertNotIn('invalid-secret', r.stderr)


    def test_auth_status_refuses_malformed_profile_without_logging_it(self):
        original = self.own_profile.copy()
        try:
            for user_id in (True, '7', 0):
                type(self).own_profile = {**original, 'id': user_id}
                before = len(self.calls)
                result = self.invoke('auth', 'status')
                self.assertEqual(result.returncode, 1)
                self.assertIn('did not identify the signed-in user', result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertNotIn('synthetic-private-profile', result.stderr)
                self.assertEqual(self.calls[before:], [('GET', '/api/v1/users/self/profile')])
        finally:
            type(self).own_profile = original


    def test_redirect_refused(self):
        before = len(self.calls)
        r = self.invoke('get', '/api/v1/redirect')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(len(self.calls), before + 1)


    def test_capabilities_without_credentials(self):
        r = self.invoke('capabilities')
        data = json.loads(r.stdout)
        self.assertNotIn('get', data['read'])
        self.assertIn('get (expert GET only; native server-side effects may apply)', data['read_with_native_side_effects'])
        self.assertIn('notification-preferences (GET may materialize default policy records)', data['read_with_native_side_effects'])
        brief = self.invoke('capabilities', '--format', 'brief')
        self.assertEqual(brief.returncode, 0, brief.stderr)
        self.assertIn('Read-only (', brief.stdout)
        self.assertIn('Canvas writes (', brief.stdout)
        self.assertNotIn('"read":', brief.stdout)
