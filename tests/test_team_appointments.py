"""Explicit shared-team Scheduler ownership, full inventories and uncertain writes."""

import copy
import json
import unittest
from unittest.mock import Mock

from canvas_cli.cli import brief
from canvas_cli.client import CanvasError
from canvas_cli.team_appointments import cancel, read, reserve


class TeamAppointmentTests(unittest.TestCase):
    def setUp(self):
        self.slot = {'id': 601, 'context_code': 'appointment_group_501', 'appointment_group_id': 501,
                     'participant_type': 'Group', 'parent_event_id': None, 'workflow_state': 'locked',
                     'start_at': '2099-10-05T19:00:00-07:00', 'end_at': '2099-10-05T19:30:00-07:00',
                     'reserved': False, 'available_slots': 2, 'participants_per_appointment': 3,
                     'child_events': [{'group': {'users': [{'email': 'synthetic-private-peer@example.edu'}]}}]}
        self.past_slot = {**self.slot, 'id': 602, 'start_at': '2020-10-05T19:00:00-07:00',
                          'end_at': '2020-10-05T19:30:00-07:00'}
        self.group = {'id': 501, 'title': 'Synthetic team hours', 'workflow_state': 'active',
                      'context_codes': ['course_101'], 'sub_context_codes': ['group_category_21'],
                      'participant_type': 'Group', 'max_appointments_per_participant': 2,
                      'reserved_times': [], 'appointments': [self.slot, self.past_slot]}
        self.team = {'id': 11, 'name': 'Synthetic course team', 'course_id': 101, 'group_category_id': 21,
                     'concluded': False, 'non_collaborative': False, 'users': [{'email': 'synthetic-private-roster@example.edu'}]}
        self.membership = {'id': 91, 'group_id': 11, 'user_id': 7, 'moderator': False, 'workflow_state': 'accepted'}
        self.reservation = {'id': 701, 'context_code': 'group_11', 'appointment_group_id': 501, 'parent_event_id': 601,
                            'participant_type': 'Group', 'workflow_state': 'locked', 'start_at': self.slot['start_at'],
                            'end_at': self.slot['end_at'], 'comments': 'Synthetic private teammate question',
                            'description': 'Synthetic private inherited instructions'}
        self.inventory = []
        self.profile, self.permission = {'id': 7}, True
        self.ack_patch, self.readback_patch = {}, {}
        self.inventory_after = None
        self.denied_readback = self.denied_membership = False
        self.writes = []
        self.client = Mock(host='https://canvas.example.edu')
        self.client.request.side_effect = self._request
        self.client.list.side_effect = self._list

    def _request(self, route, method='GET', body=None):
        if route == '/api/v1/users/self/profile':
            return copy.deepcopy(self.profile), ''
        if route == '/api/v1/appointment_groups/501?include%5B%5D=reserved_times&include_past_appointments=true':
            return copy.deepcopy(self.group), ''
        if route == '/api/v1/groups/11':
            return copy.deepcopy(self.team), ''
        if route == '/api/v1/groups/11/memberships/self':
            if self.writes and self.denied_membership:
                raise CanvasError('Synthetic private membership denial', status=403)
            return copy.deepcopy(self.membership), ''
        if route == '/api/v1/groups/11/permissions?permissions%5B%5D=manage_calendar':
            return {'manage_calendar': self.permission}, ''
        if route == '/api/v1/calendar_events/601?excludes%5B%5D=child_events':
            return copy.deepcopy(self.slot), ''
        if route == '/api/v1/calendar_events/701?excludes%5B%5D=child_events':
            if self.writes and self.denied_readback:
                raise CanvasError('Synthetic private reservation denial', status=403)
            return {**copy.deepcopy(self.reservation), **(self.readback_patch if self.writes else {})}, ''
        self.writes.append((method, route, copy.deepcopy(body)))
        if (method, route) == ('POST', '/api/v1/calendar_events/601/reservations'):
            self.assertEqual(body['participant_id'], 11)
            self.assertIs(body['cancel_existing'], False)
            self.reservation['comments'] = body.get('comments')
            self.inventory.append(copy.deepcopy(self.reservation))
        elif (method, route) == ('DELETE', '/api/v1/calendar_events/701'):
            self.assertEqual(body['which'], 'one')
            self.reservation['workflow_state'] = 'deleted'
            self.inventory = [row for row in self.inventory if row['id'] != 701]
        else:
            self.fail(f'Unexpected synthetic request {method} {route}')
        return {**copy.deepcopy(self.reservation), 'context_code': 'course_101', **self.ack_patch}, ''

    def _list(self, route, max_pages):
        if route.startswith('/api/v1/appointment_groups?'):
            return [copy.deepcopy(self.group)]
        self.assertIn('all_events=true', route)
        self.assertIn('context_codes%5B%5D=group_11', route)
        self.assertIn('excludes%5B%5D=child_events', route)
        self.assertIn('excludes%5B%5D=description', route)
        self.assertNotIn('start_date', route)
        self.assertNotIn('include%5B%5D=participants', route)
        return copy.deepcopy(self.inventory_after if self.writes and self.inventory_after is not None else self.inventory)

    def _ready_cancel(self):
        self.inventory = [copy.deepcopy(self.reservation)]

    def _reserve(self, **options):
        return reserve(self.client, '501', '11', '601', acknowledge_team_change=True, **options)

    def _cancel(self, **options):
        return cancel(self.client, '501', '11', '701', acknowledge_team_change=True, **options)

    def test_read_is_member_bound_and_never_uses_user_reserved_times_for_the_team(self):
        self._ready_cancel()
        self.group['reserved_times'] = [{'id': 999}]  # Native user-only association, not this team's bookings.
        self.inventory += [{'id': 887, 'context_code': 'group_11', 'title': 'Synthetic private regular event'},
                           {**self.reservation, 'id': 702, 'appointment_group_id': 502}]
        result = read(self.client, '501', '11', max_pages=3)
        self.assertEqual([row['id'] for row in result['team_reservations']], [701])
        self.assertIsNone(result['appointment_group']['reserved_times'])
        self.assertTrue(result['complete_for_endpoint'])
        self.assertNotIn('Synthetic private', json.dumps(result))
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertIn('team reservation 701', brief(result))
        self.assertIn('including bookings made by teammates', result['note'])
        routes = [call.args[0] for call in self.client.request.call_args_list]
        self.assertIn('/api/v1/groups/11/memberships/self', routes)
        self.assertNotIn('/api/v1/groups/11/memberships?per_page=100', routes)
        self.assertEqual(self.writes, [])

    def test_empty_inventory_is_only_a_selected_team_endpoint_claim(self):
        result = read(self.client, '501', '11')
        self.assertEqual(result['team_reservations'], [])
        self.assertIn('for this team and Scheduler group', brief(result))
        self.assertNotIn('no office hours', brief(result).lower())

    def test_preview_explicitly_targets_team_never_replaces_bookings_and_verified_readback(self):
        preview = self._reserve(comments='Synthetic selected question')
        self.assertEqual(preview['body'], {'participant_id': 11, 'cancel_existing': False, 'comments': 'Synthetic selected question'})
        self.assertEqual(self.writes, [])
        self.assertIn('Every member', preview['effect'])
        self.assertNotIn('reserved', preview['slot'])
        result = self._reserve(comments='Synthetic selected question', yes=True, confirm=preview['confirm'])
        self.assertEqual(result['appointment_reservation']['context_code'], 'group_11')
        self.assertEqual(result['team']['id'], 11)
        self.assertFalse(result['cancelled'])
        self.assertEqual(len(self.writes), 1)
        self.assertNotIn('Synthetic selected question', json.dumps(result))
        self.assertIn('Team 11 Scheduler reservation 701', brief(result))

    def test_cancel_can_remove_a_teammate_booking_but_only_exact_team_reservation(self):
        self._ready_cancel()
        preview = self._cancel(reason='Synthetic schedule change')
        self.assertEqual(preview['route'], '/api/v1/calendar_events/701')
        self.assertEqual(preview['body'], {'which': 'one', 'cancel_reason': 'Synthetic schedule change'})
        self.assertIn('including one booked by a teammate', preview['effect'])
        self.assertNotIn('Synthetic private', json.dumps(preview))
        result = self._cancel(reason='Synthetic schedule change', yes=True, confirm=preview['confirm'])
        self.assertTrue(result['cancelled'])
        self.assertEqual(result['appointment_reservation']['workflow_state'], 'deleted')
        self.assertEqual([row[:2] for row in self.writes], [('DELETE', '/api/v1/calendar_events/701')])

    def test_invalid_flags_ids_acknowledgement_and_inputs_fail_before_requests(self):
        cases = (lambda: reserve(self.client, '501', '11', '601'),
                 lambda: cancel(self.client, '501', '11', '701'), lambda: self._reserve(yes=True),
                 lambda: self._cancel(confirm='unpaired'), lambda: self._reserve(comments=3),
                 lambda: self._cancel(reason='x' * 10001), lambda: read(self.client, '0501', '11'),
                 lambda: read(self.client, '501', '../11'), lambda: read(self.client, '501', '11', max_pages=True))
        for operation in cases:
            with self.subTest(operation=operation), self.assertRaises(CanvasError):
                operation()
        self.client.request.assert_not_called()
        self.client.list.assert_not_called()

    def test_foreign_concluded_noncollaborative_or_ambiguous_group_set_cannot_change_team_bookings(self):
        cases = (({'id': 12}, {}), ({'concluded': True}, {}), ({'non_collaborative': True}, {}),
                 ({'non_collaborative': None}, {}), ({'course_id': True}, {}), ({'group_category_id': '21'}, {}),
                 ({'group_category_id': 22}, {}), ({'workflow_state': 'deleted'}, {}),
                 ({'name': {'private': 'Synthetic private metadata'}}, {}),
                 ({}, {'participant_type': 'User'}), ({}, {'sub_context_codes': []}),
                 ({}, {'sub_context_codes': ['group_category_21', 'group_category_22']}),
                 ({}, {'context_codes': ['course_102']}), ({}, {'context_codes': ['course_101', 'course_102']}))
        for team_patch, group_patch in cases:
            original_team, original_group = copy.deepcopy(self.team), copy.deepcopy(self.group)
            self.team.update(team_patch); self.group.update(group_patch)
            with self.subTest(team=team_patch, group=group_patch), self.assertRaises(CanvasError) as caught:
                self._reserve()
            self.assertNotIn('Synthetic private metadata', str(caught.exception))
            self.team, self.group = original_team, original_group
        self.assertEqual(self.writes, [])

    def test_accepted_exact_own_membership_and_explicit_native_permission_required(self):
        for patch in ({'workflow_state': 'invited'}, {'workflow_state': 'requested'}, {'workflow_state': 'deleted'},
                      {'user_id': 8}, {'user_id': True}, {'group_id': 12}, {'moderator': None}):
            original = copy.deepcopy(self.membership)
            self.membership.update(patch)
            with self.subTest(patch=patch), self.assertRaises(CanvasError):
                self._reserve()
            self.membership = original
        for value in (False, None, 'true', 1):
            self.permission = value
            with self.subTest(permission=value), self.assertRaises(CanvasError):
                read(self.client, '501', '11')
        self.assertEqual(self.writes, [])

    def test_calendar_duplicates_foreign_rows_bad_relations_and_truncation_fail_closed(self):
        cases = ([self.reservation, self.reservation], [{**self.reservation, 'context_code': 'group_12'}],
                 [{**self.reservation, 'context_code': 'course_101'}], [{**self.reservation, 'id': True}],
                 [{**self.reservation, 'appointment_group_id': '501'}], [{**self.reservation, 'participant_type': 'User'}],
                 [{**self.reservation, 'parent_event_id': 603}], [{**self.reservation, 'group': {'id': 12}}],
                 [{**self.reservation, 'user': {'id': 7}}], [{**self.reservation, 'series_uuid': 'Synthetic series'}],
                 [{**self.reservation, 'workflow_state': 'deleted'}])
        for rows in cases:
            self.inventory = rows
            with self.subTest(rows=rows), self.assertRaises(CanvasError):
                read(self.client, '501', '11')
        self.client.list.side_effect = CanvasError('Page limit reached', status=None)
        with self.assertRaisesRegex(CanvasError, 'Page limit'):
            self._reserve()
        self.assertEqual(self.writes, [])

    def test_past_bookings_count_toward_limit_but_cannot_be_cancelled(self):
        self.inventory = [{**self.reservation, 'id': 702, 'parent_event_id': 602,
                           'start_at': self.past_slot['start_at'], 'end_at': self.past_slot['end_at']}]
        self.group['max_appointments_per_participant'] = 1
        with self.assertRaisesRegex(CanvasError, 'limit'):
            self._reserve()
        self.group['max_appointments_per_participant'] = 2
        self.reservation.update(parent_event_id=602, start_at=self.past_slot['start_at'], end_at=self.past_slot['end_at'])
        self._ready_cancel()
        with self.assertRaisesRegex(CanvasError, 'current or future'):
            self._cancel()
        self.assertEqual(self.writes, [])

    def test_duplicate_team_booking_full_or_past_slot_and_unlisted_reservation_refused(self):
        self._ready_cancel()
        with self.assertRaisesRegex(CanvasError, 'already reserved'):
            self._reserve()
        self.inventory = []
        for patch in ({'available_slots': 0}, {'available_slots': True}, {'id': 602}, {'parent_event_id': 601},
                      {'participant_type': 'User'}, {'start_at': '2020-10-05T19:00:00Z', 'end_at': '2020-10-05T20:00:00Z'}):
            original = copy.deepcopy(self.slot)
            self.slot.update(patch)
            with self.subTest(patch=patch), self.assertRaises(CanvasError):
                self._reserve()
            self.slot.clear(); self.slot.update(original)
        with self.assertRaisesRegex(CanvasError, 'selected team appointment inventory'):
            self._cancel()
        self.assertEqual(self.writes, [])

    def test_state_account_membership_and_teammate_inventory_are_bound_to_confirmation(self):
        preview = self._reserve()
        self.membership['moderator'] = True
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            self._reserve(yes=True, confirm=preview['confirm'])
        self.membership['moderator'] = False
        self.inventory = [{**self.reservation, 'id': 702, 'parent_event_id': 602,
                           'start_at': self.past_slot['start_at'], 'end_at': self.past_slot['end_at']}]
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            self._reserve(yes=True, confirm=preview['confirm'])
        self.inventory = []
        self.client.host = 'https://other.example.edu'
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            self._reserve(yes=True, confirm=preview['confirm'])
        self.assertEqual(self.writes, [])

    def test_cancel_hidden_content_revision_is_bound_without_printing_comments(self):
        self._ready_cancel()
        preview = self._cancel()
        self.reservation['comments'] = 'Synthetic private changed question'
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            self._cancel(yes=True, confirm=preview['confirm'])
        self.assertNotIn('Synthetic private', json.dumps(preview))
        self.assertEqual(self.writes, [])

    def test_malformed_ack_foreign_readback_lost_membership_or_missing_inventory_are_uncertain_not_retried(self):
        cases = (('ack_patch', {'id': True}), ('ack_patch', {'participant_type': 'User'}),
                 ('readback_patch', {'context_code': 'group_12'}), ('readback_patch', {'parent_event_id': 602}),
                 ('readback_patch', {'comments': 'Synthetic private altered question'}),
                 ('denied_readback', True), ('denied_membership', True), ('inventory_after', []))
        for attribute, value in cases:
            self.setUp()
            preview = self._reserve(comments='Synthetic selected question')
            setattr(self, attribute, value)
            with self.subTest(attribute=attribute, value=value), self.assertRaisesRegex(CanvasError, 'uncertain|could not be verified') as caught:
                self._reserve(comments='Synthetic selected question', yes=True, confirm=preview['confirm'])
            self.assertEqual(len(self.writes), 1)
            self.assertNotIn('Synthetic private', str(caught.exception))

    def test_acknowledged_cancellation_must_be_deleted_and_absent_from_full_inventory(self):
        for attribute, value in (('ack_patch', {'id': 601}), ('readback_patch', {'workflow_state': 'locked'}),
                                 ('inventory_after', [self.reservation]), ('denied_membership', True)):
            self.setUp()
            self._ready_cancel()
            preview = self._cancel()
            setattr(self, attribute, value)
            with self.subTest(attribute=attribute), self.assertRaisesRegex(CanvasError, 'uncertain|could not be verified'):
                self._cancel(yes=True, confirm=preview['confirm'])
            self.assertEqual([row[:2] for row in self.writes], [('DELETE', '/api/v1/calendar_events/701')])

    def test_account_switch_during_intake_is_not_a_valid_preview(self):
        original_request, count = self.client.request.side_effect, 0
        def request(route, method='GET', body=None):
            nonlocal count
            if route == '/api/v1/users/self/profile':
                count += 1
                return {'id': 7 if count == 1 else 8}, ''
            return original_request(route, method, body)
        self.client.request.side_effect = request
        with self.assertRaisesRegex(CanvasError, 'account changed'):
            self._reserve()
        self.assertEqual(self.writes, [])
