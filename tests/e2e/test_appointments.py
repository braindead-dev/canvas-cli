"""Installed command tests for native Scheduler reads and own booking lifecycle."""

import json
from pathlib import Path

from . import appointments
from .fixture import CanvasFixture


class AppointmentE2E(CanvasFixture):
    def setUp(self):
        appointments.initialize(type(self))

    def test_discovery_paginates_native_scope_filters_and_omits_private_details(self):
        before = len(self.calls)
        result = self.invoke('appointment-groups')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual([row['id'] for row in data['appointment_groups']], [501, 502])
        self.assertEqual(len(self.calls[before:]), 2)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        self.assertNotIn('Synthetic private', result.stdout)
        scoped = self.invoke('appointment-groups', '--course', '101', '--course', '101', '--include-past')
        self.assertEqual(scoped.returncode, 0, scoped.stderr)
        self.assertEqual([row['id'] for row in json.loads(scoped.stdout)['appointment_groups']], [501])
        self.assertEqual(self.calls[-1][1].count('context_codes%5B%5D=course_101'), 1)
        self.assertIn('include_past_appointments=true', self.calls[-1][1])

    def test_group_slots_read_own_ids_and_explicit_organizer_details_only(self):
        before = len(self.calls)
        result = self.invoke('appointment-group', '501', '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('slot 601', result.stdout)
        self.assertIn('2 available', result.stdout)
        self.assertNotIn('Synthetic private', result.stdout)
        details = self.invoke('appointment-group', '501', '--include-details')
        self.assertEqual(details.returncode, 0, details.stderr)
        self.assertIn('Synthetic private office hours description', details.stdout)
        self.assertNotIn('synthetic-private-appointment-peer', details.stdout)
        self.assertNotIn('Synthetic private peer appointment comments', details.stdout)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))

    def test_page_limit_does_not_emit_partial_appointment_inventory(self):
        result = self.invoke('appointment-groups', '--max-pages', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('Page limit', result.stderr)

    def test_reservation_preview_staleness_own_write_and_cancel_lifecycle(self):
        command = ('appointment-reserve', '501', '601')
        before = len(self.calls)
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertEqual(data['body'], {'participant_id': 7, 'cancel_existing': False})
        stale = self.invoke(*command, '--yes', '--confirm', 'wrong')
        self.assertNotEqual(stale.returncode, 0)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'], '--format', 'brief')
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertIn('Own Scheduler reservation 701', sent.stdout)
        self.assertEqual(self.appointment_write, data['body'])
        self.assertNotIn('Synthetic private', sent.stdout)
        duplicate = self.invoke(*command)
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn('already reserved', duplicate.stderr)
        cancel = self.invoke('appointment-cancel', '501', '701', '--reason', 'Schedule changed')
        self.assertEqual(cancel.returncode, 0, cancel.stderr)
        cancel_data = json.loads(cancel.stdout)
        deleted = self.invoke('appointment-cancel', '501', '701', '--reason', 'Schedule changed',
                              '--yes', '--confirm', cancel_data['confirm'])
        self.assertEqual(deleted.returncode, 0, deleted.stderr)
        self.assertTrue(json.loads(deleted.stdout)['cancelled'])
        self.assertEqual(self.appointment_write, {'which': 'one', 'cancel_reason': 'Schedule changed'})
        self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                         [('POST', '/api/v1/calendar_events/601/reservations'), ('DELETE', '/api/v1/calendar_events/701')])

    def test_group_full_and_foreign_slot_are_refused_without_writes(self):
        for slot_patch, group_patch in (({}, {'participant_type': 'Group'}),
                                        ({'available_slots': 0}, {}), ({'appointment_group_id': 502}, {})):
            appointments.initialize(type(self))
            self.appointment_slot.update(slot_patch)
            self.appointment_group.update(group_patch)
            before = len(self.calls)
            result = self.invoke('appointment-reserve', '501', '601')
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
            self.assertEqual(result.stdout, '')

    def test_failed_ack_or_readback_never_reports_success_or_retries_a_booking(self):
        for mode in ('malformed', 'denied'):
            appointments.initialize(type(self))
            command = ('appointment-reserve', '501', '601')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'malformed':
                type(self).appointment_ack_mode = 'malformed'
            else:
                type(self).appointment_readback_denied = True
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertRegex(result.stderr, 'uncertain|could not be verified')
            self.assertNotIn('Synthetic private', result.stderr)
            self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                             [('POST', '/api/v1/calendar_events/601/reservations')])

    def test_comments_file_is_reread_bounded_and_shared_only_when_explicit(self):
        path = Path(self.tmp.name) / 'comments.txt'
        path.write_text('Synthetic selected question', encoding='utf-8')
        command = ('appointment-reserve', '501', '601', '--comments-file', str(path))
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertEqual(data['body']['comments'], 'Synthetic selected question')
        before = len(self.calls)
        path.write_text('Synthetic changed question', encoding='utf-8')
        stale = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertNotEqual(stale.returncode, 0)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        for content in (b'\xff', b'x' * 40001):
            path.write_bytes(content)
            before = len(self.calls)
            invalid = self.invoke(*command)
            self.assertNotEqual(invalid.returncode, 0)
            self.assertEqual(self.calls[before:], [])
        path.write_text('Synthetic selected question', encoding='utf-8')
        result = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.appointment_reservation['comments'], 'Synthetic selected question')
        self.assertNotIn('Synthetic selected question', result.stdout)
