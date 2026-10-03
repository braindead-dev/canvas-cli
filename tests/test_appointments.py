"""Own Scheduler flows, native context differences, and output privacy."""

import copy
import json
import unittest
from unittest.mock import Mock

from canvas_cli.appointments import cancel, listing, read, reserve
from canvas_cli.cli import brief
from canvas_cli.client import CanvasError


class AppointmentTests(unittest.TestCase):
    def setUp(self):
        self.slot = {'id': 601, 'appointment_group_id': 501, 'context_code': 'appointment_group_501',
                     'participant_type': 'User', 'parent_event_id': None, 'workflow_state': 'active',
                     'start_at': '2099-10-05T19:00:00-07:00', 'end_at': '2099-10-05T19:30:00-07:00',
                     'reserved': False, 'available_slots': 2, 'participants_per_appointment': 2,
                     'updated_at': '2026-10-02T12:00:00Z',
                     'child_events': [{'user': {'email': 'synthetic-private-peer@example.edu'}}],
                     'reserve_comments': 'Synthetic hidden peer comments', 'reserve_url': 'https://untrusted.example/reserve'}
        self.group = {'id': 501, 'title': 'Synthetic office hours', 'workflow_state': 'active',
                      'context_codes': ['course_101'], 'participant_type': 'User',
                      'max_appointments_per_participant': 2, 'reserved_times': [], 'appointments': [self.slot],
                      'description': 'Synthetic private organizer instructions', 'updated_at': '2026-10-02T12:00:00Z',
                      'users': [{'email': 'synthetic-private-roster@example.edu'}]}
        self.reservation = {'id': 701, 'appointment_group_id': 501, 'parent_event_id': 601,
                            'context_code': 'user_7', 'participant_type': 'User', 'workflow_state': 'locked',
                            'start_at': self.slot['start_at'], 'end_at': self.slot['end_at'],
                            'comments': 'Synthetic private old comment', 'description': 'Synthetic private inherited description',
                            'updated_at': '2026-10-02T12:00:00Z'}
        self.profile = {'id': 7}
        self.denied_readback = False
        self.ack_patch = {}
        self.readback_patch = {}
        self.writes = []
        self.client = Mock(host='https://canvas.example.edu')
        self.client.list.side_effect = self._list
        self.client.request.side_effect = self._request

    def _list(self, route, max_pages):
        self.assertIn('scope=reservable', route)
        self.assertIn('include%5B%5D=reserved_times', route)
        self.assertNotIn('child_events', route)
        self.assertNotIn('participants', route)
        return [copy.deepcopy(self.group)]

    def _request(self, route, method='GET', body=None):
        if route == '/api/v1/users/self/profile':
            return copy.deepcopy(self.profile), ''
        if route == '/api/v1/appointment_groups/501?include%5B%5D=reserved_times':
            return copy.deepcopy(self.group), ''
        if route == '/api/v1/calendar_events/601?excludes%5B%5D=child_events':
            return copy.deepcopy(self.slot), ''
        if route == '/api/v1/calendar_events/701?excludes%5B%5D=child_events':
            if self.denied_readback and self.writes:
                raise CanvasError('Synthetic denial', status=403)
            return {**copy.deepcopy(self.reservation), **(self.readback_patch if self.writes else {})}, ''
        self.writes.append((method, route, body))
        if method == 'POST' and route == '/api/v1/calendar_events/601/reservations':
            self.reservation['comments'] = body.get('comments')
        elif method == 'DELETE' and route == '/api/v1/calendar_events/701':
            self.reservation['workflow_state'] = 'deleted'
        else:
            self.fail(f'Unexpected synthetic request {method} {route}')
        # Native response can display a course, while the excluded-child GET reports user ownership.
        return {**copy.deepcopy(self.reservation), 'context_code': 'course_101', **self.ack_patch}, ''

    def _ready_cancel(self):
        self.group['reserved_times'] = [{key: self.reservation[key] for key in ('id', 'start_at', 'end_at')}]

    def test_listing_is_paginated_reservable_scoped_and_metadata_first(self):
        data = listing(self.client, 5, courses=['101', '101'], include_past=True)
        self.assertEqual(data['appointment_groups'][0]['id'], 501)
        self.assertEqual(data['scope'], 'reservable')
        self.assertTrue(data['include_past'])
        route, pages = self.client.list.call_args.args
        self.assertEqual(pages, 5)
        self.assertEqual(route.count('context_codes%5B%5D=course_101'), 1)
        self.assertIn('include_past_appointments=true', route)
        self.assertNotIn('Synthetic private', json.dumps(data))
        self.assertNotIn('synthetic-private', json.dumps(data))
        self.assertIn('not external advising', data['note'])

    def test_single_group_projects_slots_and_description_only_on_opt_in(self):
        data = read(self.client, '501')
        self.assertEqual(data['appointment_group']['appointments'][0]['id'], 601)
        for value in ('synthetic-private-peer', 'Synthetic hidden peer', 'untrusted.example', 'Synthetic private organizer'):
            self.assertNotIn(value, json.dumps(data))
        self.assertIn('Synthetic private organizer', json.dumps(read(self.client, '501', include_details=True)))
        summary = brief(data)
        self.assertIn('slot 601', summary)
        self.assertIn('2 available', summary)
        self.assertIn('not reserved by you', summary)
        self.assertNotIn('Synthetic hidden', summary)

    def test_group_bookings_are_readable_but_never_claimed_as_own_individual_bookings(self):
        self.group['participant_type'] = self.slot['participant_type'] = 'Group'
        self.group['reserved_times'] = [{'id': 702}]
        self.assertIsNone(listing(self.client)['appointment_groups'][0]['reserved_times'])
        self.slot['reserved'] = True
        self.assertNotIn('reserved by you', brief(read(self.client, '501')))
        for operation, target in ((reserve, '601'), (cancel, '701')):
            with self.subTest(operation=operation), self.assertRaisesRegex(CanvasError, 'group booking'):
                operation(self.client, '501', target)
        self.assertEqual(self.writes, [])

    def test_bad_identifiers_inputs_and_unpaired_execution_flags_make_no_requests(self):
        operations = (lambda: read(self.client, '0501'), lambda: listing(self.client, courses=['../101']),
                      lambda: reserve(self.client, '501', '0'), lambda: reserve(self.client, '501', '601', comments=3),
                      lambda: reserve(self.client, '501', '601', comments='x' * 10001),
                      lambda: reserve(self.client, '501', '601', yes=True),
                      lambda: cancel(self.client, '501', 'assignment_701'),
                      lambda: cancel(self.client, '501', '701', reason=3),
                      lambda: cancel(self.client, '501', '701', confirm='unpaired'))
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(CanvasError):
                operation()
        self.client.request.assert_not_called()
        self.client.list.assert_not_called()

    def test_malformed_unpublished_duplicate_and_foreign_groups_fail_without_record_dumps(self):
        changes = ({'id': True}, {'id': '501'}, {'workflow_state': 'pending'}, {'workflow_state': 'deleted'},
                   {'context_codes': []}, {'context_codes': ['user_7']}, {'participant_type': None},
                   {'reserved_times': None}, {'reserved_times': [{'id': True}]},
                   {'reserved_times': [{'id': 1}, {'id': 1}]}, {'title': {'private': 'Synthetic hidden data'}},
                   {'max_appointments_per_participant': False})
        for change in changes:
            self.client.list.side_effect = None
            self.client.list.return_value = [{**self.group, **change}]
            with self.subTest(change=change), self.assertRaises(CanvasError) as caught:
                listing(self.client)
            self.assertNotIn('Synthetic hidden data', str(caught.exception))
        self.client.list.return_value = [self.group, self.group]
        with self.assertRaisesRegex(CanvasError, 'duplicate appointment groups'):
            listing(self.client)
        self.client.list.return_value = [self.group]
        with self.assertRaisesRegex(CanvasError, 'outside the selected courses'):
            listing(self.client, courses=['102'])

    def test_single_group_requires_exact_id_and_valid_slot_inventory(self):
        for change in ({'id': 502}, {'appointments': None}, {'appointments': [self.slot, self.slot]},
                       {'appointments': [{**self.slot, 'appointment_group_id': 502}]},
                       {'appointments': [{**self.slot, 'context_code': 'course_101'}]}):
            self.client.request.side_effect = None
            self.client.request.return_value = ({**self.group, **change}, '')
            with self.subTest(change=change), self.assertRaises(CanvasError):
                read(self.client, '501')

    def test_reserve_preview_has_explicit_own_participant_never_replaces_existing_and_no_private_echo(self):
        data = reserve(self.client, '501', '601', comments='Synthetic selected question')
        self.assertTrue(data['dry_run'])
        self.assertEqual(data['body'], {'participant_id': 7, 'cancel_existing': False, 'comments': 'Synthetic selected question'})
        self.assertIn('shared with the organizer', data['effect'])
        self.assertNotIn('synthetic-private', json.dumps(data))
        self.assertNotIn('Synthetic hidden peer', json.dumps(data))
        self.assertEqual(self.writes, [])

    def test_verified_reservation_does_not_require_own_flag_on_native_course_context_acknowledgement(self):
        data = reserve(self.client, '501', '601', comments='Synthetic selected question')
        result = reserve(self.client, '501', '601', comments='Synthetic selected question', yes=True, confirm=data['confirm'])
        self.assertEqual(result['appointment_reservation']['context_code'], 'user_7')
        self.assertEqual(result['appointment_reservation']['id'], 701)
        self.assertFalse(result['cancelled'])
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.client.request.call_args.args, ('/api/v1/calendar_events/701?excludes%5B%5D=child_events',))
        self.assertNotIn('comments', result['appointment_reservation'])
        self.assertIn('reserved', brief(result))

    def test_changed_account_origin_state_or_comment_refuses_stale_reservation_preview(self):
        data = reserve(self.client, '501', '601', comments='Question')
        for change in ({'available_slots': 1}, {'updated_at': '2026-10-02T13:00:00Z'},
                       {'start_at': '2099-10-05T19:05:00-07:00'}):
            original = copy.deepcopy(self.slot)
            self.slot.update(change)
            with self.subTest(change=change), self.assertRaisesRegex(CanvasError, 'Preview changed'):
                reserve(self.client, '501', '601', comments='Question', yes=True, confirm=data['confirm'])
            self.slot = original
        for profile, origin, comments in (({'id': 8}, self.client.host, 'Question'),
                                         ({'id': 7}, 'https://other.example.edu', 'Question'),
                                         ({'id': 7}, 'https://canvas.example.edu', 'Changed')):
            self.profile, self.client.host = profile, origin
            with self.subTest(profile=profile, origin=origin), self.assertRaisesRegex(CanvasError, 'Preview changed'):
                reserve(self.client, '501', '601', comments=comments, yes=True, confirm=data['confirm'])
        self.assertEqual(self.writes, [])

    def test_full_reserved_past_unknown_or_foreign_slots_and_limits_cannot_reserve(self):
        for change in ({'available_slots': 0}, {'available_slots': True}, {'available_slots': '2'},
                       {'reserved': True}, {'reserved': None}, {'reserved': 0},
                       {'context_code': 'appointment_group_502'}, {'appointment_group_id': True},
                       {'participant_type': 'Group'}, {'parent_event_id': 602}, {'id': 602},
                       {'hidden': True}, {'workflow_state': 'deleted'},
                       {'start_at': '2020-10-05T19:00:00-07:00', 'end_at': '2020-10-05T19:30:00-07:00'},
                       {'end_at': None}, {'end_at': self.slot['start_at']}):
            original = copy.deepcopy(self.slot)
            self.slot.update(change)
            with self.subTest(change=change), self.assertRaises(CanvasError):
                reserve(self.client, '501', '601')
            self.slot = original
        self.group['max_appointments_per_participant'] = 0
        with self.assertRaisesRegex(CanvasError, 'limit'):
            reserve(self.client, '501', '601')
        self.client.list.side_effect = None
        self.client.list.return_value = []
        with self.assertRaisesRegex(CanvasError, 'own reservable inventory'):
            reserve(self.client, '501', '601')
        self.assertEqual(self.writes, [])

    def test_native_unlimited_capacity_and_locked_slot_can_reserve_without_inventing_a_count(self):
        self.slot.pop('available_slots')
        self.slot['participants_per_appointment'] = None
        self.slot['workflow_state'] = 'locked'  # Other reservations lock times, not further signups.
        self.assertTrue(reserve(self.client, '501', '601')['dry_run'])
        self.group['appointments'] = [self.slot]
        self.assertIn('capacity count not reported', brief(read(self.client, '501')))

    def test_reservation_acknowledgement_or_readback_failures_are_uncertain_and_never_retry(self):
        preview = reserve(self.client, '501', '601', comments='Question')
        for phase, patch in (('ack', {'id': True}), ('ack', {'parent_event_id': 602}),
                             ('readback', {'context_code': 'user_8'}), ('readback', {'participant_type': 'Group'}),
                             ('readback', {'start_at': '2099-10-05T19:05:00-07:00'}),
                             ('readback', {'comments': 'Synthetic hidden mismatched comment'})):
            self.ack_patch = patch if phase == 'ack' else {}
            self.readback_patch = patch if phase == 'readback' else {}
            self.writes.clear()
            with self.subTest(phase=phase, patch=patch), self.assertRaisesRegex(CanvasError, 'uncertain|could not be verified') as caught:
                reserve(self.client, '501', '601', comments='Question', yes=True, confirm=preview['confirm'])
            self.assertEqual(len(self.writes), 1)
            self.assertNotIn('Synthetic hidden', str(caught.exception))
        self.ack_patch = self.readback_patch = {}
        self.denied_readback = True
        self.writes.clear()
        with self.assertRaisesRegex(CanvasError, 'could not be verified'):
            reserve(self.client, '501', '601', comments='Question', yes=True, confirm=preview['confirm'])
        self.assertEqual(len(self.writes), 1)

    def test_cancel_uses_own_reservation_id_only_and_verifies_deleted_state(self):
        self._ready_cancel()
        preview = cancel(self.client, '501', '701', reason='Schedule changed')
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['body'], {'which': 'one', 'cancel_reason': 'Schedule changed'})
        self.assertEqual(preview['route'], '/api/v1/calendar_events/701')
        self.assertNotIn('Synthetic private', json.dumps(preview))
        result = cancel(self.client, '501', '701', reason='Schedule changed', yes=True, confirm=preview['confirm'])
        self.assertTrue(result['cancelled'])
        self.assertEqual(result['appointment_reservation']['workflow_state'], 'deleted')
        self.assertEqual([item[1] for item in self.writes], ['/api/v1/calendar_events/701'])
        self.assertIn('cancelled', brief(result))

    def test_foreign_unlisted_nonappointment_deleted_and_series_reservations_cannot_cancel(self):
        self._ready_cancel()
        for change in ({'context_code': 'user_8'}, {'context_code': 'course_101'}, {'participant_type': 'Group'},
                       {'appointment_group_id': 502}, {'parent_event_id': None}, {'parent_event_id': 602},
                       {'parent_event_id': True}, {'group': {'id': 11}}, {'workflow_state': 'deleted'},
                       {'user': {'id': 8}}, {'user': {'id': '7'}}, {'user': True},
                       {'series_uuid': 'synthetic-series'}, {'rrule': 'FREQ=WEEKLY;COUNT=2'}):
            original = copy.deepcopy(self.reservation)
            self.reservation.update(change)
            with self.subTest(change=change), self.assertRaises(CanvasError):
                cancel(self.client, '501', '701')
            self.reservation = original
        self.group['reserved_times'] = []
        with self.assertRaisesRegex(CanvasError, 'own reservation inventory'):
            cancel(self.client, '501', '701')
        self.assertEqual(self.writes, [])

    def test_cancel_acknowledgement_and_readback_failures_do_not_repeat_deletion(self):
        for phase, patch in (('ack', {'id': 601}), ('ack', {'workflow_state': 'locked'}),
                             ('readback', {'workflow_state': 'locked'}), ('readback', {'context_code': 'user_8'}),
                             ('denied', {})):
            self.setUp()
            self._ready_cancel()
            preview = cancel(self.client, '501', '701')
            self.ack_patch = patch if phase == 'ack' else {}
            self.readback_patch = patch if phase == 'readback' else {}
            self.denied_readback = phase == 'denied'
            with self.subTest(phase=phase, patch=patch), self.assertRaisesRegex(CanvasError, 'uncertain|could not be verified'):
                cancel(self.client, '501', '701', yes=True, confirm=preview['confirm'])
            self.assertEqual(len(self.writes), 1)
            self.assertEqual(self.writes[0][:2], ('DELETE', '/api/v1/calendar_events/701'))

    def test_changed_own_inventory_and_group_limits_require_fresh_reservation_review(self):
        preview = reserve(self.client, '501', '601')
        self.group['reserved_times'] = [{'id': 702, 'start_at': self.slot['start_at'], 'end_at': self.slot['end_at']}]
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            reserve(self.client, '501', '601', yes=True, confirm=preview['confirm'])
        self.group['max_appointments_per_participant'] = 1
        with self.assertRaisesRegex(CanvasError, 'limit'):
            reserve(self.client, '501', '601')
        self.assertEqual(self.writes, [])

    def test_hidden_comment_revision_changes_cancel_confirmation_without_echoing_old_comment(self):
        self._ready_cancel()
        preview = cancel(self.client, '501', '701')
        self.reservation['comments'] = 'Synthetic private changed comment'
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            cancel(self.client, '501', '701', yes=True, confirm=preview['confirm'])
        self.assertEqual(self.writes, [])

    def test_missing_own_reservations_or_capacity_are_unknown_not_complete(self):
        self.client.list.side_effect = None
        self.client.list.return_value = []
        data = listing(self.client)
        self.assertIn('selected native scope', brief(data))
        self.assertIn('do not prove', data['note'])
        self.client.list.side_effect = CanvasError('Pagination limit')
        with self.assertRaisesRegex(CanvasError, 'Pagination limit'):
            listing(self.client)
