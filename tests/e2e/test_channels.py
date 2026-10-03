"""Installed CLI own-contact lifecycle over real, synthetic HTTPS."""

import json
from pathlib import Path

from . import channels
from .fixture import CanvasFixture


class ChannelE2E(CanvasFixture):
    def setUp(self):
        channels.initialize(type(self))
        self.path = Path(self.tmp.name) / 'contact-address.txt'
        self.path.write_text('synthetic-new@example.edu\n', encoding='utf-8')
        self.command = ('channel-create', '--type', 'email', '--address-file', str(self.path),
                        '--acknowledge-contact-message')

    def test_add_and_remove_contact_with_native_confirmation_and_complete_owned_readback(self):
        before = len(self.calls)
        preview = self.invoke(*self.command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertEqual(data['body'], {'communication_channel': {'type': 'email', 'address': 'synthetic-new@example.edu'},
                                        'skip_confirmation': False})
        self.assertNotIn('synthetic-contact@example.edu', preview.stdout)
        self.assertNotIn('synthetic-private-push-token', preview.stdout)
        wrong = self.invoke(*self.command, '--yes', '--confirm', 'wrong')
        self.assertNotEqual(wrong.returncode, 0)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        added = self.invoke(*self.command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(added.returncode, 0, added.stderr)
        result = json.loads(added.stdout)
        self.assertTrue(result['verified'])
        self.assertTrue(result['confirmation_required'])
        self.assertEqual(result['channel_change']['id'], 21)
        self.assertEqual(self.contact_write, data['body'])
        self.assertNotIn('synthetic-new@example.edu', added.stdout)
        self.assertNotIn('Synthetic private', added.stdout)
        repeat = self.invoke(*self.command)
        self.assertNotEqual(repeat.returncode, 0)
        self.assertIn('already', repeat.stderr)
        command = ('channel-delete', '21', '--acknowledge-contact-removal')
        deletion = self.invoke(*command)
        self.assertEqual(deletion.returncode, 0, deletion.stderr)
        removed = self.invoke(*command, '--yes', '--confirm', json.loads(deletion.stdout)['confirm'], '--format', 'brief')
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertIn('Own channel 21 | email | retired | removed', removed.stdout)
        self.assertNotIn('synthetic-new@example.edu', removed.stdout)
        self.assertEqual([row['id'] for row in self.communication_channels], [19, 20])
        self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                         [('POST', '/api/v1/users/self/communication_channels'), ('DELETE', '/api/v1/users/self/communication_channels/21')])

    def test_changed_address_file_or_inventory_requires_fresh_confirmation(self):
        preview = self.invoke(*self.command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        confirm = json.loads(preview.stdout)['confirm']
        before = len(self.calls)
        self.path.write_text('synthetic-changed@example.edu', encoding='utf-8')
        changed = self.invoke(*self.command, '--yes', '--confirm', confirm)
        self.assertNotEqual(changed.returncode, 0)
        self.assertIn('Preview changed', changed.stderr)
        self.path.write_text('synthetic-new@example.edu', encoding='utf-8')
        self.communication_channels[0]['position'] = 9
        changed = self.invoke(*self.command, '--yes', '--confirm', confirm)
        self.assertNotEqual(changed.returncode, 0)
        self.assertIn('Preview changed', changed.stderr)
        deletion = ('channel-delete', '19', '--acknowledge-contact-removal')
        preview = self.invoke(*deletion)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.communication_channels[0]['address'] = 'synthetic-changed-contact@example.edu'
        changed = self.invoke(*deletion, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertNotEqual(changed.returncode, 0)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))

    def test_bounded_utf8_single_line_and_acknowledgements_fail_before_any_api_request(self):
        for content in (b'\xffSynthetic private contact', b'x' * 4097, b'one@example.edu\ntwo@example.edu',
                        b'one@example.edu\n\n', b'one@example.edu\n\r\n', b'', b'one@example.edu\x00'):
            self.path.write_bytes(content)
            before = len(self.calls)
            result = self.invoke(*self.command)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.calls[before:], [])
            self.assertNotIn('Synthetic private', result.stderr)
        self.path.write_text('synthetic-new@example.edu\r\n', encoding='utf-8')
        before = len(self.calls)
        missing = self.invoke(*self.command[:-1])
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn('acknowledge-contact-message', missing.stderr)
        missing = self.invoke('channel-delete', '19')
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn('acknowledge-contact-removal', missing.stderr)
        self.assertEqual(self.calls[before:], [])
        good = self.invoke(*self.command)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertEqual(json.loads(good.stdout)['body']['communication_channel']['address'], 'synthetic-new@example.edu')

    def test_truncated_and_foreign_contact_inventory_do_not_produce_a_write_preview(self):
        for options in (('--max-pages', '1'), ()):
            if not options:
                self.communication_channels[-1]['user_id'] = 8
            before = len(self.calls)
            result = self.invoke(*self.command, *options)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))

    def test_ambiguous_create_or_unavailable_readback_is_one_write_without_false_success(self):
        for mode in ('ambiguous', 'duplicate', 'denied'):
            channels.initialize(type(self))
            preview = self.invoke(*self.command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode in ('ambiguous', 'duplicate'):
                type(self).contact_ack_mode = mode
            else:
                type(self).contact_readback_denied = True
            before = len(self.calls)
            result = self.invoke(*self.command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertRegex(result.stderr, 'uncertain|could not verify|may have applied')
            self.assertNotIn('Synthetic private', result.stderr)
            self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                             [('POST', '/api/v1/users/self/communication_channels')])

    def test_ambiguous_still_present_or_native_restricted_removal_never_retries(self):
        command = ('channel-delete', '19', '--acknowledge-contact-removal')
        for mode in ('ambiguous', 'duplicate', 'still_present', 'restricted'):
            channels.initialize(type(self))
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode in ('ambiguous', 'duplicate'):
                type(self).contact_ack_mode = mode
            elif mode == 'still_present':
                type(self).contact_delete_keeps_row = True
            else:
                type(self).contact_restrict_delete = True
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertNotIn('Synthetic private', result.stderr)
            self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                             [('DELETE', '/api/v1/users/self/communication_channels/19')])

    def test_exact_push_channel_and_last_contact_retirement_are_not_provider_token_or_primary_email_claims(self):
        before = len(self.calls)
        for channel_id in ('20', '19'):
            command = ('channel-delete', channel_id, '--acknowledge-contact-removal')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertIn('last contact', preview.stdout)
            self.assertNotIn('synthetic-private-push-token', preview.stdout)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)['verified'])
            self.assertNotIn('synthetic-private-push-token', result.stdout)
            self.assertNotIn('synthetic-contact@example.edu', result.stdout)
        self.assertEqual(self.communication_channels, [])
        self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                         [('DELETE', '/api/v1/users/self/communication_channels/20'), ('DELETE', '/api/v1/users/self/communication_channels/19')])

    def test_sms_creation_uses_native_confirmation_not_push_tokens_or_login_creation(self):
        self.path.write_text('+15555550123', encoding='utf-8')
        command = ('channel-create', '--type', 'sms', '--address-file', str(self.path), '--acknowledge-contact-message')
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['confirmation_required'])
        self.assertEqual(self.contact_write, {'communication_channel': {'type': 'sms', 'address': '+15555550123'},
                                            'skip_confirmation': False})
        self.assertNotIn('+15555550123', result.stdout)

    def test_readback_page_limit_after_creation_is_uncertainty_with_only_one_post(self):
        type(self).communication_channels = self.communication_channels[:1]
        command = (*self.command, '--max-pages', '1')
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        before = len(self.calls)
        result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('could not verify', result.stderr)
        self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                         [('POST', '/api/v1/users/self/communication_channels')])
