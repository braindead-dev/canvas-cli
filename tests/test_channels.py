"""Own contact lifecycle, including confirmation, privacy and uncertain writes."""

import copy
import unittest
from unittest.mock import Mock

from canvas_cli.channels import create, delete, listing
from canvas_cli.client import CanvasError


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{'id': 19, 'user_id': 7, 'type': 'email', 'address': 'synthetic-old@example.edu',
                      'workflow_state': 'active', 'position': 1, 'created_at': '2026-10-02T12:00:00Z',
                      'last_bounce_summary': 'Synthetic private bounce', 'token': 'Synthetic private channel token'}]
        self.profile = {'id': 7, 'primary_email': 'Synthetic private profile email'}
        self.accepted = {'id': 21, 'user_id': 7, 'type': 'email', 'address': 'synthetic-new@example.edu',
                         'workflow_state': 'unconfirmed', 'position': 2, 'token': 'Synthetic private response token'}
        self.ack_patch = {}
        self.readback_patch = {}
        self.readback_error = None
        self.profile_after = None
        self.duplicate_id = False
        self.write_error = None
        self.writes = []
        self.client = Mock(host='https://canvas.example.edu')
        self.client.request.side_effect = self.request
        self.client.list.side_effect = self.inventory

    def request(self, route, method='GET', body=None):
        if route == '/api/v1/users/self/profile':
            return copy.deepcopy(self.profile_after if self.writes and self.profile_after is not None else self.profile), ''
        self.writes.append((route, method, copy.deepcopy(body)))
        if self.write_error:
            raise self.write_error
        if method == 'POST':
            row = {**self.accepted, **body['communication_channel']}
            if self.duplicate_id:
                row['id'] = 19
            self.rows.append(copy.deepcopy(row))
        elif method == 'DELETE':
            channel_id = int(route.rsplit('/', 1)[1])
            row = next(row for row in self.rows if row['id'] == channel_id)
            self.rows = [item for item in self.rows if item['id'] != channel_id]
            row = {**row, 'workflow_state': 'retired'}
        else:
            raise AssertionError('Unexpected synthetic request')
        return {**row, **self.ack_patch}, ''

    def inventory(self, route, max_pages):
        self.assertEqual(route, '/api/v1/users/self/communication_channels?per_page=100')
        if self.writes and self.readback_error:
            raise self.readback_error
        return [copy.deepcopy({**row, **(self.readback_patch if self.writes else {})}) for row in self.rows]

    def add(self, **options):
        return create(self.client, 'email', 'synthetic-new@example.edu', acknowledge_message=True, **options)

    def remove(self, channel='19', **options):
        return delete(self.client, channel, acknowledge_removal=True, **options)

    def test_create_preview_is_exact_own_confirmed_native_message_without_unselected_contact_data(self):
        preview = self.add(max_pages=3)
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['body'], {'communication_channel': {'type': 'email', 'address': 'synthetic-new@example.edu'},
                                           'skip_confirmation': False})
        self.assertEqual(preview['route'], '/api/v1/users/self/communication_channels')
        self.assertEqual(preview['method'], 'POST')
        self.assertTrue(preview['acknowledge_contact_message'])
        self.assertIn('retired', preview['effect'].lower())
        self.assertEqual(self.writes, [])
        self.client.list.assert_called_once_with('/api/v1/users/self/communication_channels?per_page=100', 3)
        for private in ('synthetic-old@example.edu', 'Synthetic private', 'build_pseudonym', 'confirmation_code'):
            self.assertNotIn(private, str(preview))

    def test_create_verifies_paginated_owned_state_and_omits_selected_address_from_result(self):
        preview = self.add()
        result = self.add(yes=True, confirm=preview['confirm'])
        self.assertTrue(result['verified'])
        self.assertTrue(result['confirmation_required'])
        self.assertFalse(result['deleted'])
        self.assertEqual(result['channel_change']['id'], 21)
        self.assertEqual(result['channel_change']['workflow_state'], 'unconfirmed')
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.writes[0], (preview['route'], 'POST', preview['body']))
        self.assertEqual(self.client.list.call_count, 3)
        self.assertEqual(self.client.request.call_args.args, ('/api/v1/users/self/profile',))
        for private in ('synthetic-new@example.edu', 'synthetic-old@example.edu', 'Synthetic private', 'token'):
            self.assertNotIn(private, str(result))

    def test_sms_and_reported_active_confirmation_race_are_not_false_delivery_claims(self):
        self.accepted['workflow_state'] = 'active'
        preview = create(self.client, 'sms', '+15555550123', acknowledge_message=True)
        result = create(self.client, 'sms', '+15555550123', acknowledge_message=True, yes=True, confirm=preview['confirm'])
        self.assertFalse(result['confirmation_required'])
        self.assertEqual(result['channel_change']['type'], 'sms')
        self.assertIn('delivery', result['note'])
        self.assertNotIn('+15555550123', str(result))

    def test_invalid_flags_addresses_and_missing_acknowledgements_fail_without_requests(self):
        for address in ('', None, [], ' leading@example.edu', 'trailing@example.edu ', 'a\nb@example.edu',
                        'a\rb@example.edu', 'a\x00b', 'a\x7fb', 'a\x85b', 'x' * 1025):
            with self.subTest(address=address), self.assertRaises(CanvasError):
                create(self.client, 'email', address, acknowledge_message=True)
        for options in ({'yes': True}, {'confirm': 'one-sided'}):
            with self.assertRaises(CanvasError):
                self.add(**options)
            with self.assertRaises(CanvasError):
                self.remove(**options)
        with self.assertRaisesRegex(CanvasError, 'acknowledge-contact-message'):
            create(self.client, 'email', 'synthetic@example.edu')
        with self.assertRaisesRegex(CanvasError, 'acknowledge-contact-removal'):
            delete(self.client, '19')
        with self.assertRaisesRegex(CanvasError, 'push registration'):
            create(self.client, 'push', 'Synthetic private provider', acknowledge_message=True)
        for channel in ('019', '0', '-1', '1/2', '1?token=private', True, None, '١٩'):
            with self.assertRaises(CanvasError):
                self.remove(channel)
        self.client.request.assert_not_called()
        self.client.list.assert_not_called()

    def test_existing_active_and_pending_case_variants_never_resend_confirmation(self):
        for state in ('active', 'unconfirmed'):
            self.rows[0].update(address='SYNTHETIC-NEW@example.edu', workflow_state=state)
            with self.assertRaisesRegex(CanvasError, 'not a confirmation-resend'):
                self.add()
        self.assertEqual(self.writes, [])

    def test_new_inventory_id_order_state_address_or_identity_invalidates_create_preview(self):
        mutations = [('id', 18), ('position', 2), ('workflow_state', 'unconfirmed'),
                     ('address', 'synthetic-changed@example.edu'), ('created_at', '2026-10-03T12:00:00Z')]
        for key, value in mutations:
            original = copy.deepcopy(self.rows[0])
            preview = self.add()
            self.rows[0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(CanvasError, 'Preview changed'):
                self.add(yes=True, confirm=preview['confirm'])
            self.rows[0] = original
        preview = self.add()
        self.rows.append({**self.rows[0], 'id': 22, 'address': 'synthetic-third@example.edu'})
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            self.add(yes=True, confirm=preview['confirm'])
        self.rows.pop()
        self.client.host = 'https://other.example.edu'
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            self.add(yes=True, confirm=preview['confirm'])
        self.client.host = 'https://canvas.example.edu'
        self.profile['id'] = 8
        with self.assertRaisesRegex(CanvasError, 'non-own'):
            self.add(yes=True, confirm=preview['confirm'])
        self.assertEqual(self.writes, [])

    def test_order_only_and_unselected_unknown_fields_do_not_invalidate_the_inventory_digest(self):
        self.rows.append({**self.rows[0], 'id': 20, 'type': 'push', 'address': 'Synthetic private provider'})
        preview = self.add()
        self.rows.reverse()
        self.rows[0]['unknown_private_field'] = {'nested': 'Synthetic private noise'}
        self.rows[0]['bounce_count'] = 2
        result = self.add(yes=True, confirm=preview['confirm'])
        self.assertTrue(result['verified'])
        self.assertEqual(len(self.writes), 1)

    def test_malformed_duplicate_retired_foreign_or_nested_metadata_never_leaks_records(self):
        original = copy.deepcopy(self.rows)
        for patch in ({'id': True}, {'user_id': 8}, {'user_id': True}, {'type': None},
                      {'workflow_state': 'retired'}, {'position': {'private': 'Synthetic private nested'}},
                      {'created_at': ['Synthetic private nested']}, {'bounce_count': True}):
            self.rows = [{**original[0], **patch}]
            with self.subTest(patch=patch), self.assertRaises(CanvasError) as error:
                listing(self.client)
            self.assertNotIn('Synthetic private', str(error.exception))
        self.rows = original * 2
        with self.assertRaisesRegex(CanvasError, 'duplicate'):
            self.add()
        self.rows = [{**original[0], 'address': ['Synthetic private invalid']}]
        with self.assertRaises(CanvasError):
            self.add()
        self.assertEqual(self.writes, [])

    def test_create_ack_foreign_id_type_state_or_address_is_uncertain_with_one_post(self):
        for patch in ({'id': True}, {'user_id': 8}, {'type': 'sms'}, {'workflow_state': 'retired'},
                      {'workflow_state': 'unknown'}, {'address': 'Synthetic private wrong destination'},
                      {'position': {'private': 'Synthetic private nested'}}):
            self.setUp()
            preview = self.add()
            self.ack_patch = patch
            with self.subTest(patch=patch), self.assertRaisesRegex(CanvasError, 'outcome uncertain') as error:
                self.add(yes=True, confirm=preview['confirm'])
            self.assertNotIn('Synthetic private', str(error.exception))
            self.assertEqual(len(self.writes), 1)
        self.setUp()
        preview = self.add()
        self.duplicate_id = True
        with self.assertRaisesRegex(CanvasError, 'already-visible'):
            self.add(yes=True, confirm=preview['confirm'])
        self.assertEqual(len(self.writes), 1)

    def test_readback_mismatch_denial_truncation_or_changed_account_is_uncertainty_not_retry(self):
        for patch in ({'address': 'Synthetic private changed'}, {'user_id': 8}, {'workflow_state': 'retired'},
                      {'workflow_state': 'unknown'}, {'type': 'push'}):
            self.setUp()
            preview = self.add()
            self.readback_patch = patch
            with self.assertRaisesRegex(CanvasError, 'could not verify'):
                self.add(yes=True, confirm=preview['confirm'])
            self.assertEqual(len(self.writes), 1)
        for failure in (CanvasError('Page limit reached'), CanvasError('Synthetic private denial', status=403)):
            self.setUp()
            preview = self.add()
            self.readback_error = failure
            with self.assertRaisesRegex(CanvasError, 'could not verify') as error:
                self.add(yes=True, confirm=preview['confirm'])
            self.assertNotIn('Synthetic private', str(error.exception))
            self.assertEqual(len(self.writes), 1)
        self.setUp()
        preview = self.add()
        self.profile_after = {'id': 8}
        with self.assertRaisesRegex(CanvasError, 'could not verify'):
            self.add(yes=True, confirm=preview['confirm'])
        self.assertEqual(len(self.writes), 1)

    def test_delete_exact_id_primary_last_or_push_retirement_with_separate_absence_verification(self):
        for channel_type in ('email', 'sms', 'push', 'slack'):
            self.setUp()
            self.rows[0]['type'] = channel_type
            preview = self.remove()
            self.assertEqual(preview['route'], '/api/v1/users/self/communication_channels/19')
            self.assertNotIn('body', preview)
            self.assertIn('last contact', preview['effect'])
            for private in ('synthetic-old@example.edu', 'Synthetic private'):
                self.assertNotIn(private, str(preview))
            result = self.remove(yes=True, confirm=preview['confirm'])
            self.assertTrue(result['deleted'])
            self.assertTrue(result['verified'])
            self.assertEqual(result['channel_change']['workflow_state'], 'retired')
            self.assertEqual(self.rows, [])
            self.assertEqual(self.writes, [(preview['route'], 'DELETE', None)])
            self.assertNotIn('Synthetic private', str(result))

    def test_delete_inventory_change_missing_or_unidentified_channel_is_not_written(self):
        preview = self.remove()
        self.rows[0]['address'] = 'synthetic-changed@example.edu'
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            self.remove(yes=True, confirm=preview['confirm'])
        self.rows[0]['address'] = None
        with self.assertRaisesRegex(CanvasError, 'destination'):
            self.remove()
        self.rows = []
        with self.assertRaisesRegex(CanvasError, 'not found'):
            self.remove()
        self.assertEqual(self.writes, [])

    def test_bad_retirement_ack_or_remaining_id_never_reports_success_or_repeats_delete(self):
        for patch in ({'id': 20}, {'workflow_state': 'active'}, {'user_id': 8},
                      {'type': 'sms'}, {'address': 'Synthetic private wrong address'}):
            self.setUp()
            preview = self.remove()
            self.ack_patch = patch
            with self.assertRaisesRegex(CanvasError, 'outcome uncertain'):
                self.remove(yes=True, confirm=preview['confirm'])
            self.assertEqual(len(self.writes), 1)
        self.setUp()
        preview = self.remove()
        old_rows = copy.deepcopy(self.rows)
        self.client.list.side_effect = lambda route, max_pages: old_rows
        with self.assertRaisesRegex(CanvasError, 'could not verify'):
            self.remove(yes=True, confirm=preview['confirm'])
        self.assertEqual(len(self.writes), 1)

    def test_native_restrictions_and_preflight_pagination_failure_do_not_trigger_retries(self):
        self.client.list.side_effect = CanvasError('Page limit reached')
        with self.assertRaisesRegex(CanvasError, 'Page limit'):
            self.add()
        self.assertEqual(self.writes, [])
        self.setUp()
        preview = self.remove()
        self.write_error = CanvasError('Canvas HTTP 400', status=400)
        with self.assertRaises(CanvasError) as error:
            self.remove(yes=True, confirm=preview['confirm'])
        self.assertEqual(error.exception.status, 400)
        self.assertEqual(len(self.writes), 1)

    def test_readback_can_be_confirmed_after_an_unconfirmed_ack_without_claiming_delivery(self):
        preview = self.add()
        self.readback_patch = {'workflow_state': 'active'}
        result = self.add(yes=True, confirm=preview['confirm'])
        self.assertFalse(result['confirmation_required'])
        self.assertIn('not verified', result['note'])
