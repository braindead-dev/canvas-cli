import unittest
from unittest.mock import Mock

from canvas_cli.client import CanvasError
from canvas_cli.events import change, create, read, timing


class EventTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.profile = {'id': 7}
        self.event = {'id': 61, 'context_code': 'user_7', 'title': 'Synthetic event',
                      'start_at': '2026-10-05T09:00:00-07:00', 'end_at': '2026-10-05T10:00:00-07:00',
                      'all_day': False, 'workflow_state': 'active', 'updated_at': '2026-10-01T12:00:00Z'}

    def test_times_require_offsets_and_valid_positive_intervals(self):
        data = timing('2026-10-05T09:00:00-07:00', '2026-10-05T10:00:00-07:00',
                      time_zone='America/Los_Angeles')
        self.assertFalse(data['all_day'])
        self.assertEqual(data['time_zone_edited'], 'America/Los_Angeles')
        self.assertEqual(timing('2026-10-05T16:00:00Z', '2026-10-05T17:00:00Z')['start_at'],
                         '2026-10-05T16:00:00+00:00')
        for start, end in [('2026-10-05T09:00:00', '2026-10-05T10:00:00Z'),
                           ('20261005T090000Z', '2026-10-05T10:00:00Z'),
                           ('2026-10-05T09:00:00-00:00', '2026-10-05T10:00:00Z'),
                           ('2026-10-05T09:00:00+01:99', '2026-10-05T10:00:00Z'),
                           ('2026-10-05T09:00:00Z', '2026-10-05T08:00:00Z'),
                           ('2026-10-05T09:00:00Z', '2026-10-05T09:00:00Z'),
                           ('2026-02-30T09:00:00Z', '2026-10-05T10:00:00Z'),
                           ('2026-10-05T09:00:00Z', None)]:
            with self.subTest(start=start, end=end), self.assertRaises(CanvasError):
                timing(start, end)

    def test_daylight_saving_offsets_and_all_day_dates_are_not_guessed(self):
        summer = timing(day='2026-10-05', time_zone='America/Los_Angeles')
        winter = timing(day='2026-12-05', time_zone='America/Los_Angeles')
        self.assertTrue(summer['all_day'])
        self.assertEqual(summer['start_at'], summer['end_at'])
        self.assertTrue(summer['start_at'].endswith('-07:00'))
        self.assertTrue(winter['start_at'].endswith('-08:00'))
        # Explicit offsets disambiguate the repeated hour, including crossing the DST boundary.
        self.assertFalse(timing('2026-11-01T01:30:00-07:00', '2026-11-01T01:45:00-08:00',
                                time_zone='America/Los_Angeles')['all_day'])
        for kwargs in ({'day': '2026-10-05'}, {'time_zone': 'UTC'},
                       {'day': '2026-10-05', 'time_zone': 'Not/A_Zone'},
                       {'day': '2011-12-30', 'time_zone': 'Pacific/Apia'},
                       {'day': '2026-10-05', 'time_zone': 'UTC', 'start': '2026-10-05T00:00:00Z'},
                       {'start': '2026-12-05T09:00:00-07:00', 'end': '2026-12-05T10:00:00-07:00',
                        'time_zone': 'America/Los_Angeles'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                timing(**kwargs)

    def test_create_preview_escapes_plain_text_and_binds_the_personal_calendar(self):
        self.client.request.return_value = (self.profile, '')
        preview = create(self.client, 'Study', day='2026-10-05', time_zone='UTC',
                         details='Read <notes>\nBring a pen', location='Home')
        event = preview['body']['calendar_event']
        self.assertEqual(event['context_code'], 'user_7')
        self.assertEqual(event['description'], '<p>Read &lt;notes&gt;<br>Bring a pen</p>')
        self.assertTrue(preview['dry_run'])
        self.client.request.assert_called_once_with('/api/v1/users/self/profile')
        self.client.request.side_effect = [(self.profile, ''), ({**self.event, 'title': 'Study'}, '')]
        result = create(self.client, 'Study', day='2026-10-05', time_zone='UTC',
                        details='Read <notes>\nBring a pen', location='Home', yes=True, confirm=preview['confirm'])
        self.assertEqual(result['calendar_event']['id'], 61)
        self.client.request.assert_called_with('/api/v1/calendar_events', 'POST', preview['body'])

    def test_invalid_create_and_incomplete_confirmation_fail_before_network(self):
        for kwargs in ({'title': ''}, {'title': 'Study'}, {'title': 'Study', 'yes': True},
                       {'title': None, 'day': '2026-10-05', 'time_zone': 'UTC'},
                       {'title': 'Study', 'day': '2026-10-05', 'time_zone': 'UTC', 'details': 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                create(self.client, **kwargs)
        self.client.request.assert_not_called()

    def test_edit_sends_only_specified_fields_and_one_occurrence(self):
        self.client.request.side_effect = [(self.profile, ''), (self.event, '')]
        preview = change(self.client, '61', title='Updated', details='', location='')
        self.assertEqual(preview['body'], {'which': 'one', 'calendar_event':
                                          {'title': 'Updated', 'description': '', 'location_name': ''}})
        self.client.request.side_effect = [(self.profile, ''), (self.event, ''), (self.event, '')]
        result = change(self.client, '61', title='Updated', details='', location='',
                        yes=True, confirm=preview['confirm'])
        self.assertEqual(result['calendar_event']['id'], 61)
        self.client.request.assert_called_with('/api/v1/calendar_events/61', 'PUT', preview['body'])

    def test_delete_is_single_occurrence_even_when_in_a_series(self):
        event = {**self.event, 'series_uuid': 'synthetic-series', 'rrule': 'FREQ=WEEKLY;COUNT=3'}
        self.client.request.side_effect = [(self.profile, ''), (event, '')]
        preview = change(self.client, '61', delete=True, cancel_reason='Schedule changed')
        self.assertEqual(preview['body'], {'which': 'one', 'cancel_reason': 'Schedule changed'})
        self.client.request.side_effect = [(self.profile, ''), (event, ''),
                                           ({**event, 'workflow_state': 'deleted'}, '')]
        change(self.client, '61', delete=True, cancel_reason='Schedule changed', yes=True, confirm=preview['confirm'])
        self.client.request.assert_called_with('/api/v1/calendar_events/61', 'DELETE', preview['body'])

    def test_other_users_course_events_appointments_and_locked_events_cannot_be_mutated(self):
        for fields in ({'context_code': 'user_8'}, {'context_code': 'course_9'},
                       {'appointment_group_id': 12}, {'parent_event_id': 12},
                       {'child_events_count': 1}, {'child_events': [{'id': 12}]},
                       {'own_reservation': True}, {'hidden': True}, {'locked_for_user': True},
                       {'workflow_state': 'deleted'}, {'workflow_state': 'locked'},
                       {'workflow_state': None}):
            self.client.request.reset_mock()
            self.client.request.side_effect = [(self.profile, ''), ({**self.event, **fields}, '')]
            with self.subTest(fields=fields), self.assertRaises(CanvasError):
                change(self.client, '61', title='Edited')
            self.assertEqual(self.client.request.call_count, 2)

    def test_changed_account_destination_or_event_invalidates_confirmation(self):
        self.client.request.side_effect = [(self.profile, ''), (self.event, '')]
        preview = change(self.client, '61', title='Edited')
        for profile, event in [({'id': 8}, {**self.event, 'context_code': 'user_8'}),
                               (self.profile, {**self.event, 'updated_at': '2026-10-02T12:00:00Z'}),
                               (self.profile, {**self.event, 'rrule': 'FREQ=DAILY;COUNT=3'})]:
            self.client.request.reset_mock()
            self.client.request.side_effect = [(profile, ''), (event, '')]
            with self.subTest(profile=profile, event=event), self.assertRaisesRegex(CanvasError, 'Preview changed'):
                change(self.client, '61', title='Edited', yes=True, confirm=preview['confirm'])
            self.assertEqual(self.client.request.call_count, 2)
        self.client.host = 'https://other.example.edu'
        self.client.request.side_effect = [(self.profile, ''), (self.event, '')]
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            change(self.client, '61', title='Edited', yes=True, confirm=preview['confirm'])

    def test_read_id_validation_and_ambiguous_write_response(self):
        for event_id in ('assignment_61', '0', '061', '../61'):
            with self.subTest(event_id=event_id), self.assertRaises(CanvasError):
                read(self.client, event_id)
        self.client.request.assert_not_called()
        for record in (None, {'id': True}, {'id': 62}):
            self.client.request.return_value = (record, '')
            with self.subTest(record=record), self.assertRaises(CanvasError):
                read(self.client, '61')
        self.client.request.side_effect = [(self.profile, ''), (self.event, '')]
        preview = change(self.client, '61', title='Edited')
        self.client.request.reset_mock()
        self.client.request.side_effect = [(self.profile, ''), (self.event, ''), ({'id': 99}, '')]
        with self.assertRaisesRegex(CanvasError, 'outcome uncertain'):
            change(self.client, '61', title='Edited', yes=True, confirm=preview['confirm'])
        self.assertEqual(self.client.request.call_count, 3)

    def test_edit_validation_does_not_make_reads(self):
        for kwargs in ({}, {'delete': True, 'title': 'Edited'},
                       {'title': 'Edited', 'cancel_reason': 'Wrong operation'},
                       {'location': 3}, {'start': '2026-10-01T12:00:00Z'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                change(self.client, '61', **kwargs)
        self.client.request.assert_not_called()


if __name__ == '__main__': unittest.main()
