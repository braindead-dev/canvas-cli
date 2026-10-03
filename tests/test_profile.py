import unittest
from unittest.mock import Mock

from canvas_pocket.client import CanvasError
from canvas_pocket.profile import change, read


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.record = {'id': 7, 'name': 'Synthetic Student', 'short_name': 'Synthetic',
                       'sortable_name': 'Student, Synthetic', 'title': None, 'bio': 'Private old biography',
                       'pronunciation': None, 'pronouns': 'they/them', 'time_zone': 'America/Denver',
                       'locale': None, 'effective_locale': 'en', 'primary_email': 'synthetic@example.edu',
                       'login_id': 'synthetic-private-login', 'sis_user_id': 'synthetic-private-sis',
                       'lti_user_id': 'synthetic-private-lti', 'avatar_url': 'https://example.edu/private-avatar',
                       'calendar': {'ics': 'https://example.edu/feeds/synthetic-secret.ics'},
                       'links': [{'url': 'https://example.edu/private-service'}], 'future_private_field': 'secret'}
        self.client.request.return_value = (self.record, '')

    def preview(self, changes=None, **kwargs):
        self.client.request.reset_mock()
        self.client.request.side_effect = [(self.record, '')]
        return change(self.client, changes or {'short_name': 'New display'}, acknowledge_shared=True, **kwargs)

    def test_own_profile_whitelists_optional_bio_and_email_and_never_secret_fields(self):
        result = read(self.client)
        self.assertEqual(result['own_profile']['id'], 7)
        self.assertEqual(result['own_profile']['effective_locale'], 'en')
        self.assertFalse(result['bio_included'])
        self.assertNotIn('bio', result['own_profile'])
        self.assertNotIn('primary_email', result['own_profile'])
        for options in ({'include_bio': True}, {'include_email': True}, {'include_bio': True, 'include_email': True}):
            result = read(self.client, **options)
            self.assertEqual('bio' in result['own_profile'], options.get('include_bio', False))
            self.assertEqual('primary_email' in result['own_profile'], options.get('include_email', False))
            for marker in ('synthetic-private', 'private-avatar', 'synthetic-secret', 'private-service', 'future_private_field'):
                self.assertNotIn(marker, str(result))
        self.client.request.assert_called_with('/api/v1/users/self/profile')
        self.client.list.assert_not_called()

    def test_invalid_profile_ids_types_and_unexpected_pagination_fail_without_dumping(self):
        for record in (None, [], {}, {**self.record, 'id': True}, {**self.record, 'id': 0},
                       {**self.record, 'short_name': ['never print']}, {**self.record, 'time_zone': 1}):
            self.client.request.return_value = (record, '')
            with self.subTest(record=record), self.assertRaises(CanvasError) as error:
                read(self.client)
            self.assertNotIn('never print', str(error.exception))
        self.client.request.return_value = (self.record, '</api/v1/users/self/profile?page=2>; rel="next"')
        with self.assertRaisesRegex(CanvasError, 'pagination'):
            read(self.client)
        self.client.request.return_value = ({**self.record, 'primary_email': False, 'bio': False}, '')
        self.assertNotIn('bio', read(self.client)['own_profile'])
        for options in ({'include_bio': True}, {'include_email': True}):
            with self.assertRaises(CanvasError):
                read(self.client, **options)

    def test_shared_profile_preview_binds_state_omits_unselected_bio_and_never_overrides_sis(self):
        preview = self.preview({'name': '  Synthetic New 🌿  ', 'short_name': 'New display', 'title': ''})
        self.assertTrue(preview['dry_run'])
        self.assertTrue(preview['shared_profile_change'])
        self.assertEqual(preview['body'], {'user': {'name': 'Synthetic New 🌿', 'short_name': 'New display', 'title': ''},
                                           'override_sis_stickiness': False})
        self.assertEqual(preview['route'], '/api/v1/users/self')
        self.assertEqual(preview['method'], 'PUT')
        self.assertNotIn('Private old biography', str(preview))
        self.assertNotIn('synthetic-secret', str(preview))
        self.assertEqual(self.client.request.call_count, 1)
        self.client.request.assert_called_once_with('/api/v1/users/self/profile')

    def test_timezone_only_needs_no_shared_ack_and_readback_uses_iana_not_rails_ack(self):
        self.client.request.side_effect = [(self.record, '')]
        preview = change(self.client, {'time_zone': 'America/Los_Angeles'})
        self.assertFalse(preview['shared_profile_change'])
        self.client.request.side_effect = [(self.record, ''),
                                          ({'id': 7, 'time_zone': 'Pacific Time (US & Canada)'}, ''),
                                          ({**self.record, 'time_zone': 'America/Los_Angeles'}, '')]
        result = change(self.client, {'time_zone': 'America/Los_Angeles'}, yes=True, confirm=preview['confirm'])
        self.assertTrue(result['read_back_verified'])
        self.assertEqual(result['profile_changes'], {'time_zone': 'America/Los_Angeles'})
        self.assertEqual(self.client.request.call_args_list[-2].args,
                         ('/api/v1/users/self', 'PUT', preview['body']))

    def test_bio_multiline_preview_and_names_optional_clear_are_verified_by_separate_get(self):
        changes = {'bio': 'New biography\nSecond line\twith tab\r\n', 'title': '', 'pronunciation': '', 'pronouns': ''}
        preview = self.preview(changes)
        self.assertEqual(preview['current_profile']['bio'], 'Private old biography')
        after = {**self.record, **changes, 'title': None, 'pronunciation': None}
        del after['pronouns']  # Native serializer omits nil pronouns.
        self.client.request.reset_mock()
        self.client.request.side_effect = [(self.record, ''), ({'id': 7}, ''), (after, '')]
        result = change(self.client, changes, acknowledge_shared=True, yes=True, confirm=preview['confirm'])
        self.assertTrue(result['read_back_verified'])
        self.assertEqual(result['profile_changes']['bio'], changes['bio'])
        self.assertIsNone(result['profile_changes']['pronouns'])
        self.assertEqual(self.client.request.call_count, 3)
        self.assertEqual(self.client.request.call_args_list[1].args, ('/api/v1/users/self', 'PUT', preview['body']))

    def test_foreign_identity_changed_site_name_bio_or_requested_text_invalidates_preview(self):
        preview = self.preview()
        for record, host, changes in (({**self.record, 'id': 8}, self.client.host, {'short_name': 'New display'}),
                                     ({**self.record, 'bio': 'Changed'}, self.client.host, {'short_name': 'New display'}),
                                     ({**self.record, 'name': 'Changed'}, self.client.host, {'short_name': 'New display'}),
                                     (self.record, 'https://other.example.edu', {'short_name': 'New display'}),
                                     (self.record, self.client.host, {'short_name': 'Different requested text'})):
            self.client.host = host
            self.client.request.reset_mock()
            self.client.request.side_effect = [(record, '')]
            with self.assertRaisesRegex(CanvasError, 'Preview changed'):
                change(self.client, changes, acknowledge_shared=True, yes=True, confirm=preview['confirm'])
            self.assertEqual(self.client.request.call_count, 1)

    def test_invalid_values_and_shared_ack_fail_before_any_request(self):
        for changes in ({}, [], {'email': 'synthetic@example.edu'}, {'locale': 'en'}, {'avatar': 'opaque'},
                        {'event': 'suspend'}, {'name': None}, {'name': '  '}, {'short_name': ''},
                        {'name': 'x' * 256}, {'bio': 'x' * 10001}, {'title': 'has\nnewline'},
                        {'pronouns': 'has\ttab'}, {'pronunciation': '\x00'}, {'bio': '\x0b'},
                        {'time_zone': ''}, {'time_zone': '../private'}, {'time_zone': '/etc/passwd'},
                        {'time_zone': 'invalid/synthetic'}, {'time_zone': 'Europe\\Berlin'}):
            with self.subTest(changes=changes), self.assertRaises(CanvasError):
                change(self.client, changes, acknowledge_shared=True)
        for kwargs in ({}, {'acknowledge_shared': 1}, {'acknowledge_shared': False}, {'yes': True}, {'confirm': 'digest'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                change(self.client, {'name': 'New'}, **kwargs)
        self.client.request.assert_not_called()
        self.client.list.assert_not_called()

    def test_ambiguous_ack_or_partial_readback_is_not_success_or_retried_or_logged(self):
        preview = self.preview({'name': 'New', 'short_name': 'New display'})
        for ack, after, count in ((None, None, 2), ({'id': 8, 'private': 'never print'}, None, 2),
                                  ({'id': True}, None, 2),
                                  ({'id': 7}, {**self.record, 'name': 'New'}, 3),
                                  ({'id': 7}, {**self.record, 'id': 8}, 3),
                                  ({'id': 7}, {'id': 7, 'name': False}, 3)):
            self.client.request.reset_mock()
            responses = [(self.record, ''), (ack, '')]
            if count == 3:
                responses.append((after, ''))
            self.client.request.side_effect = responses
            with self.subTest(ack=ack, after=after), self.assertRaisesRegex(CanvasError, 'Some edits may have applied') as error:
                change(self.client, {'name': 'New', 'short_name': 'New display'}, acknowledge_shared=True,
                       yes=True, confirm=preview['confirm'])
            self.assertEqual(self.client.request.call_count, count)
            self.assertNotIn('never print', str(error.exception))

    def test_readback_access_failure_is_explicitly_post_write_not_replayed(self):
        preview = self.preview()
        self.client.request.reset_mock()
        self.client.request.side_effect = [(self.record, ''), ({'id': 7}, ''), CanvasError('Synthetic GET denied', 403)]
        with self.assertRaisesRegex(CanvasError, 'Some edits may have applied'):
            change(self.client, {'short_name': 'New display'}, acknowledge_shared=True,
                   yes=True, confirm=preview['confirm'])
        self.assertEqual(self.client.request.call_count, 3)

    def test_write_permission_denial_is_not_approved_by_preview(self):
        preview = self.preview()
        self.client.request.reset_mock()
        self.client.request.side_effect = [(self.record, ''), CanvasError('Synthetic native permission denied', 403)]
        with self.assertRaisesRegex(CanvasError, 'permission denied'):
            change(self.client, {'short_name': 'New display'}, acknowledge_shared=True,
                   yes=True, confirm=preview['confirm'])
        self.assertEqual(self.client.request.call_count, 2)

