"""Installed CLI shared-team booking lifecycle against native-shaped HTTPS routes."""

import copy
import json
from pathlib import Path

from . import team_appointments
from .fixture import CanvasFixture


class TeamAppointmentE2E(CanvasFixture):
    def setUp(self):
        team_appointments.initialize(type(self), enabled=True)

    def _reserve_command(self):
        return ('appointment-team-reserve', '503', '13', '703', '--acknowledge-team-change')

    def _book(self):
        command = self._reserve_command()
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_read_has_explicit_team_scope_self_membership_no_roster_and_no_false_user_inventory(self):
        before = len(self.calls)
        result = self.invoke('appointment-team-reservations', '503', '13', '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Team 13', result.stdout)
        self.assertIn('No active reservations', result.stdout)
        self.assertNotIn('Synthetic private', result.stdout)
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        routes = [route for _, route in self.calls[before:]]
        self.assertIn('/api/v1/groups/13/memberships/self', routes)
        self.assertTrue(any('all_events=true' in route and 'context_codes%5B%5D=group_13' in route for route in routes))
        self.assertFalse(any('users?' in route or 'memberships?' in route for route in routes))

    def test_installed_book_read_and_cancel_verifies_group_not_course_context_ack(self):
        before = len(self.calls)
        result = self._book()
        data = json.loads(result.stdout)
        self.assertEqual(data['appointment_reservation']['context_code'], 'group_13')
        self.assertEqual(data['team']['id'], 13)
        self.assertEqual(self.team_write, {'participant_id': 13, 'cancel_existing': False})
        listing = self.invoke('appointment-team-reservations', '503', '13', '--format', 'brief')
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertIn('team reservation 803', listing.stdout)
        self.assertNotIn('Synthetic private', listing.stdout)
        duplicate = self.invoke(*self._reserve_command())
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn('already reserved', duplicate.stderr)
        command = ('appointment-team-cancel', '503', '13', '803', '--acknowledge-team-change', '--reason', 'Schedule changed')
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        removed = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'], '--format', 'brief')
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertIn('Team 13 Scheduler reservation 803', removed.stdout)
        self.assertIn('cancelled', removed.stdout)
        self.assertEqual(self.team_write, {'which': 'one', 'cancel_reason': 'Schedule changed'})
        self.assertEqual([row for row in self.calls[before:] if row[0] != 'GET'],
                         [('POST', '/api/v1/calendar_events/703/reservations'), ('DELETE', '/api/v1/calendar_events/803')])

    def test_missing_acknowledgement_bad_flags_and_bounded_utf8_files_make_no_requests(self):
        path = Path(self.tmp.name) / 'team-comments.txt'
        cases = [('appointment-team-reserve', '503', '13', '703'),
                 ('appointment-team-cancel', '503', '13', '803'), (*self._reserve_command(), '--yes')]
        for command in cases:
            before = len(self.calls)
            result = self.invoke(*command)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.calls[before:], [])
        for content in (b'\xff', b'x' * 40001):
            path.write_bytes(content)
            before = len(self.calls)
            result = self.invoke(*self._reserve_command(), '--comments-file', str(path))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.calls[before:], [])

    def test_full_pagination_is_required_for_reads_and_reservable_write_inventory(self):
        type(self).team_calendar.append({'id': 902, 'context_code': 'group_13', 'title': 'Synthetic other regular meeting'})
        for command in (('appointment-team-reservations', '503', '13'), self._reserve_command()):
            before = len(self.calls)
            result = self.invoke(*command, '--max-pages', '1')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertIn('Page limit', result.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        type(self).team_calendar.pop()
        result = self.invoke(*self._reserve_command(), '--max-pages', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Page limit', result.stderr)

    def test_group_set_membership_permission_and_foreign_calendar_cannot_be_assumed(self):
        for field, value in (('group_category_id', 32), ('non_collaborative', True), ('concluded', True)):
            team_appointments.initialize(type(self), enabled=True)
            self.team_context[field] = value
            before = len(self.calls)
            result = self.invoke(*self._reserve_command())
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        for membership in ({'workflow_state': 'invited'}, {'user_id': 8}):
            team_appointments.initialize(type(self), enabled=True)
            self.team_membership.update(membership)
            result = self.invoke(*self._reserve_command())
            self.assertNotEqual(result.returncode, 0)
        team_appointments.initialize(type(self), enabled=True)
        type(self).team_permission = False
        result = self.invoke(*self._reserve_command())
        self.assertNotEqual(result.returncode, 0)
        team_appointments.initialize(type(self), enabled=True)
        self.team_calendar.append({'id': 902, 'context_code': 'group_14'})
        result = self.invoke('appointment-team-reservations', '503', '13')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('Synthetic private', result.stderr)

    def test_teammate_state_and_comment_file_changes_invalidate_confirmation(self):
        path = Path(self.tmp.name) / 'team-comments.txt'
        path.write_text('Synthetic selected question', encoding='utf-8')
        command = (*self._reserve_command(), '--comments-file', str(path))
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        confirmation = json.loads(preview.stdout)['confirm']
        path.write_text('Synthetic changed question', encoding='utf-8')
        result = self.invoke(*command, '--yes', '--confirm', confirmation)
        self.assertNotEqual(result.returncode, 0)
        path.write_text('Synthetic selected question', encoding='utf-8')
        self.team_membership['moderator'] = True
        result = self.invoke(*command, '--yes', '--confirm', confirmation)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Preview changed', result.stderr)
        self.team_membership['moderator'] = False
        type(self).team_calendar.append({'id': 805, 'context_code': 'group_13', 'appointment_group_id': 503,
                                        'parent_event_id': 705, 'participant_type': 'Group', 'workflow_state': 'locked',
                                        'start_at': self.team_past_slot['start_at'], 'end_at': self.team_past_slot['end_at']})
        result = self.invoke(*command, '--yes', '--confirm', confirmation)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Preview changed', result.stderr)
        self.assertIsNone(self.team_write)

    def test_native_rejection_ambiguous_ack_and_missing_readback_never_retry_or_claim_success(self):
        for mode in ('team_native_denial', 'team_ack_malformed', 'team_readback_denied',
                     'team_membership_denied_after_write', 'team_missing_after_write'):
            team_appointments.initialize(type(self), enabled=True)
            command = self._reserve_command()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            setattr(type(self), mode, True)
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertNotIn('Synthetic private', result.stderr)
            self.assertEqual([row for row in self.calls[before:] if row[0] != 'GET'],
                             [('POST', '/api/v1/calendar_events/703/reservations')])
            if mode != 'team_native_denial':
                self.assertRegex(result.stderr, 'uncertain|could not be verified')

    def test_individual_commands_cannot_mutate_shared_bookings_and_cancel_never_targets_parent(self):
        result = self.invoke('appointment-reserve', '503', '703')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('group booking', result.stderr)
        self._book()
        before = len(self.calls)
        result = self.invoke('appointment-team-cancel', '503', '13', '703', '--acknowledge-team-change')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        # An old hidden comment changes the cancellation digest, without being printed.
        command = ('appointment-team-cancel', '503', '13', '803', '--acknowledge-team-change')
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertNotIn('Synthetic private', preview.stdout)
        self.team_reservation['comments'] = 'Synthetic private changed teammate question'
        result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Preview changed', result.stderr)

    def test_cancellation_readback_failure_is_uncertain_after_one_delete(self):
        self._book()
        command = ('appointment-team-cancel', '503', '13', '803', '--acknowledge-team-change')
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        # Arm the denial for the next write, not the earlier booking's read state.
        type(self).team_write = None
        type(self).team_readback_denied = True
        before = len(self.calls)
        result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('could not be verified', result.stderr)
        self.assertEqual([row for row in self.calls[before:] if row[0] != 'GET'],
                         [('DELETE', '/api/v1/calendar_events/803')])

    def test_past_bookings_use_full_inventory_for_limit_instead_of_current_user_times(self):
        self.team_scheduler['max_appointments_per_participant'] = 1
        self.team_scheduler['reserved_times'] = []
        self.team_calendar.append({'id': 805, 'context_code': 'group_13', 'appointment_group_id': 503,
                                   'parent_event_id': 705, 'participant_type': 'Group', 'workflow_state': 'locked',
                                   'start_at': self.team_past_slot['start_at'], 'end_at': self.team_past_slot['end_at']})
        result = self.invoke(*self._reserve_command())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('limit', result.stderr)
        self.assertIsNone(self.team_write)
        read = self.invoke('appointment-team-reservations', '503', '13')
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertEqual([row['id'] for row in json.loads(read.stdout)['team_reservations']], [805])
        duplicate = copy.deepcopy(self.team_calendar[-1])
        self.team_calendar.append(duplicate)
        malformed = self.invoke('appointment-team-reservations', '503', '13')
        self.assertNotEqual(malformed.returncode, 0)
        self.assertEqual(malformed.stdout, '')
