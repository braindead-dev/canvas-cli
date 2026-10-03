"""Independent native schedule callbacks, feature gates and uncertain write readback."""

import copy
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import urlsplit

from canvas_cli.client import CanvasError
from canvas_cli.formatting import brief
from canvas_cli.page_scheduling import schedule

DATE = '2030-10-01T10:00:00-07:00'


class ScheduleClient:
    host = 'https://canvas.example.edu'

    def __init__(self):
        self.calls = []
        self.identity = 7
        self.context = {'id': 123, 'name': 'Synthetic scheduling course', 'root_account_id': 2}
        self.permissions = {'manage_wiki_create': False, 'manage_wiki_update': True, 'participate_as_student': False}
        self.flag = {'feature': 'scheduled_page_publication', 'state': 'on', 'locked': False,
                     'context_type': 'Account', 'context_id': 2, 'private': 'synthetic-private-flag'}
        self.pages = {9: {'page_id': 9, 'url': 'welcome', 'title': 'Welcome', 'body': '<p>synthetic-private-source</p>',
                          'published': True, 'front_page': False, 'editing_roles': 'teachers,students',
                          'publish_at': None, 'updated_at': '2026-10-01T12:00:00Z', 'last_edited_by': {'email': 'synthetic-private-peer@example.edu'}},
                      10: {'page_id': 10, 'url': '9', 'title': 'Numeric slug', 'body': '<p>synthetic-private-other</p>',
                           'published': True, 'front_page': True, 'editing_roles': 'teachers',
                           'publish_at': None, 'updated_at': '2026-10-01T12:00:00Z'}}
        self.revision_id = 3
        self.revision_patch = {}
        self.ack_patch = {}
        self.after_patch = {}
        self.after_hook = None
        self.written = False
        self.denied = self.readback_denied = self.feature_denied = self.history_denied = False
        self.ignored = self.delete_race = self.inventory_failure = False
        self.omit_ack_date = False
        self.normalize_date = False
        self.before_hook = None
        self.context_reads = self.profile_reads = self.written_profile_reads = 0
        self.feature_course_mismatch = self.preflight_account_switch = self.final_account_switch = False
        self.inventory_patch = {}

    def request(self, route, method='GET', body=None):
        self.calls.append((method, route, copy.deepcopy(body)))
        path = urlsplit(route).path
        if method != 'GET':
            if self.denied:
                raise CanvasError('Synthetic native blueprint denial', status=403)
            self.written = True
            page = self.pages[9]
            if self.delete_race:
                page = {**copy.deepcopy(page), 'page_id': 11, 'url': 'unwanted', 'title': 'Unwanted'}
                self.pages[11] = page
            if not self.ignored:
                page['publish_at'] = body['wiki_page']['publish_at']
                if page['publish_at'] is not None and self.normalize_date:
                    page['publish_at'] = page['publish_at'].replace('+00:00', 'Z')
                page['published'] = False
                page['updated_at'] = '2026-10-02T12:00:00Z'
                self.revision_id += 1
            result = {**copy.deepcopy(page), **self.ack_patch}
            if self.omit_ack_date:
                result.pop('publish_at', None)
            if self.after_hook:
                self.after_hook(self)
            return result, ''
        if path == '/api/v1/users/self/profile':
            self.profile_reads += 1
            self.written_profile_reads += int(self.written)
            if (self.preflight_account_switch and self.profile_reads == 2 or
                    self.final_account_switch and self.written_profile_reads == 2):
                return {'id': 8}, ''
            return {'id': self.identity}, ''
        if path == '/api/v1/courses/123':
            self.context_reads += 1
            if self.feature_course_mismatch and self.context_reads == 2:
                return {**copy.deepcopy(self.context), 'id': 999}, ''
            return copy.deepcopy(self.context), ''
        if path == '/api/v1/courses/123/permissions':
            return copy.deepcopy(self.permissions), ''
        if path.startswith('/api/v1/accounts/'):
            if self.feature_denied:
                raise CanvasError('synthetic-private-feature-denial', status=403)
            return copy.deepcopy(self.flag), ''
        if path.startswith('/api/v1/courses/123/pages/page_id:'):
            number = int(path.split(':')[1].split('/')[0])
            if number not in self.pages:
                raise CanvasError('Missing exact page', status=404)
            if self.written and self.readback_denied:
                raise CanvasError('synthetic-private-readback-denial', status=403)
            if path.endswith('/revisions'):
                if self.history_denied:
                    raise CanvasError('No native edit history', status=403)
                return [{'revision_id': self.revision_id}], ''
            if path.endswith('/revisions/latest'):
                return {'revision_id': self.revision_id, 'latest': True,
                        'updated_at': self.pages[number]['updated_at'], **self.revision_patch}, ''
            if self.before_hook and not self.written:
                self.before_hook(self)
            return {**copy.deepcopy(self.pages[number]), **(self.after_patch if self.written else {})}, ''
        raise CanvasError('Unexpected route', status=404)

    def list(self, route, max_pages):
        self.calls.append(('GET', route, None))
        if self.inventory_failure or max_pages < 2:
            raise CanvasError('Page limit reached')
        return [{**copy.deepcopy(row), **(self.inventory_patch if row['page_id'] == 9 else {})}
                for row in self.pages.values()]


class PageSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.client = ScheduleClient()

    def call(self, **options):
        return schedule(self.client, '123', '9', **({'publish_at': DATE, 'acknowledge_shared': True} | options))

    def run_write(self, **options):
        preview = self.call(**options)
        return self.call(**options, yes=True, confirm=preview['confirm'])

    def writes(self):
        return [row for row in self.client.calls if row[0] != 'GET']

    def test_preview_binds_root_flag_source_revision_inventory_and_explicit_native_date_only(self):
        data = self.call()
        self.assertTrue(data['dry_run'])
        self.assertEqual(data['route'], '/api/v1/courses/123/pages/page_id:9?no_verifiers=true')
        self.assertEqual(data['body'], {'wiki_page': {'publish_at': '2030-10-01T17:00:00+00:00', 'notify_of_update': False}})
        self.assertEqual(data['publication_feature']['root_account_id'], 2)
        self.assertEqual(data['revision']['revision_id'], 3)
        self.assertNotIn('synthetic-private', str(data))
        self.assertEqual(self.writes(), [])
        self.assertIn('future background', data['warning'])

    def test_schedule_one_exact_put_keeps_body_slug_roles_and_other_front_page(self):
        result = self.run_write()
        self.assertTrue(result['stored_date_verified'])
        self.assertTrue(result['draft_state_verified'])
        self.assertFalse(result['future_publication_verified'])
        self.assertEqual(result['scheduled_page']['page_id'], 9)
        self.assertEqual(self.client.pages[10]['title'], 'Numeric slug')
        self.assertTrue(self.client.pages[10]['front_page'])
        self.assertEqual(len(self.writes()), 1)
        self.assertNotIn('synthetic-private', str(result))
        self.assertIn('2030-10-01T17:00:00', brief(result))

    def test_cancelling_future_or_previously_published_stored_dates_leaves_draft_not_publish_now(self):
        for published, value in ((False, DATE), (True, '2025-01-01T12:00:00Z')):
            self.client = ScheduleClient()
            self.client.pages[9].update(published=published, publish_at=value)
            result = self.run_write(publish_at=None, cancel=True)
            self.assertIsNone(result['scheduled_page']['publish_at'])
            self.assertFalse(result['scheduled_page']['published'])
            self.assertEqual(result['operation'], 'cancel')
            self.assertEqual(self.writes()[0][2]['wiki_page'], {'publish_at': None, 'notify_of_update': False})
            self.assertIn('cancelled', brief(result))

    def test_normalized_native_date_equivalence_and_enabled_inherited_flags(self):
        for flag in ({'state': 'allowed_on'}, {'context_id': 1}, {'context_id': None, 'context_type': None}):
            self.client = ScheduleClient()
            self.client.flag.update(flag)
            self.client.normalize_date = True
            self.assertTrue(self.run_write()['stored_date_verified'])

    def test_invalid_options_flags_and_dates_fail_before_any_network(self):
        for options in ({'acknowledge_shared': False}, {'cancel': 1}, {'cancel': True}, {'publish_at': None},
                        {'publish_at': ''}, {'publish_at': '2030-10-01T17:00:00'}, {'publish_at': '2030-10-01T17:00:00-00:00'},
                        {'publish_at': '2020-01-01T12:00:00Z'}, {'max_pages': 0}, {'max_pages': True},
                        {'yes': True}, {'confirm': 'bad'}):
            self.client = ScheduleClient()
            with self.assertRaises(CanvasError):
                self.call(**options)
            self.assertEqual(self.client.calls, [])
        for course, page in (('0', '9'), ('123', '0'), ('123', 'welcome')):
            with self.assertRaises(CanvasError):
                schedule(self.client, course, page, acknowledge_shared=True, publish_at=DATE)
        self.assertEqual(self.client.calls, [])

    def test_manager_history_root_feature_required_not_creation_student_or_content_editing(self):
        for mode in ('manager', 'history', 'feature', 'root', 'foreign_course', 'concluded'):
            self.client = ScheduleClient()
            if mode == 'manager':
                self.client.permissions['manage_wiki_update'] = False
            elif mode == 'history':
                self.client.history_denied = True
            elif mode == 'feature':
                self.client.feature_denied = True
            elif mode == 'root':
                self.client.context['root_account_id'] = True
            elif mode == 'foreign_course':
                self.client.context['id'] = 999
            else:
                self.client.context['concluded'] = True
            with self.assertRaises(CanvasError):
                self.call()
            self.assertEqual(self.writes(), [])

    def test_off_hidden_wrong_foreign_or_malformed_flags_never_put(self):
        for flag in ({'state': 'off'}, {'state': 'allowed'}, {'state': 'hidden'}, {'feature': 'other'},
                     {'locked': 1}, {'context_type': 'Course'}, {'context_id': 0}, {'context_id': True},
                     {'context_id': None, 'context_type': 'Account'}):
            self.client = ScheduleClient()
            self.client.flag.update(flag)
            with self.assertRaises(CanvasError):
                self.call()
            self.assertEqual(self.writes(), [])

    def test_front_linked_block_and_unknown_dates_are_refused_not_implicitly_repaired(self):
        for change in ({'front_page': True}, {'assignment': {}}, {'editor': 'block_editor'},
                       {'body': None, 'block_editor_attributes': {'id': 17, 'blocks': []}}):
            self.client = ScheduleClient()
            self.client.pages[9].update(change)
            with self.assertRaises(CanvasError):
                self.call()
            self.assertEqual(self.writes(), [])
        self.client = ScheduleClient()
        self.client.pages[9].pop('publish_at')
        with self.assertRaisesRegex(CanvasError, 'explicit null'):
            self.call()
        self.assertEqual(self.writes(), [])

    def test_absent_cancel_and_equal_reschedule_are_noops_without_put(self):
        with self.assertRaisesRegex(CanvasError, 'no reported'):
            self.call(publish_at=None, cancel=True)
        self.client.pages[9]['publish_at'] = DATE
        with self.assertRaisesRegex(CanvasError, 'already reports'):
            self.call()
        self.assertEqual(self.writes(), [])

    def test_complete_inventory_and_latest_revision_consistency_required(self):
        for mode in ('pagination', 'inventory', 'revision'):
            self.client = ScheduleClient()
            if mode == 'inventory':
                self.client.inventory_failure = True
            elif mode == 'revision':
                self.client.revision_patch['updated_at'] = '2026-10-02T12:00:00Z'
            with self.assertRaises(CanvasError):
                self.call(**({'max_pages': 1} if mode == 'pagination' else {}))
            self.assertEqual(self.writes(), [])

    def test_stale_account_course_permissions_flag_root_content_date_and_inventory_do_not_put(self):
        for mode in ('identity', 'course', 'rights', 'flag', 'root', 'body', 'date', 'inventory', 'revision'):
            self.client = ScheduleClient()
            preview = self.call()
            if mode == 'identity':
                self.client.identity = 8
            elif mode == 'course':
                self.client.context['name'] = 'Changed'
            elif mode == 'rights':
                self.client.permissions['manage_wiki_create'] = True
            elif mode == 'flag':
                self.client.flag['locked'] = True
            elif mode == 'root':
                self.client.context['root_account_id'] = 3
            elif mode == 'body':
                self.client.pages[9]['body'] = 'Changed'
            elif mode == 'date':
                self.client.pages[9]['publish_at'] = '2031-01-01T12:00:00Z'
            elif mode == 'inventory':
                self.client.pages[10]['title'] = 'Changed'
            else:
                self.client.revision_id = 4
            with self.assertRaisesRegex(CanvasError, 'Preview changed'):
                self.call(yes=True, confirm=preview['confirm'])
            self.assertEqual(self.writes(), [])

    def test_preflight_source_change_and_date_expiry_refuse_before_put(self):
        reads = 0

        def change_on_second_read(client):
            nonlocal reads
            reads += 1
            if reads == 2:
                client.pages[9]['body'] = 'Concurrent edit'

        self.client.before_hook = change_on_second_read
        with self.assertRaisesRegex(CanvasError, 'changed during scheduling'):
            self.call()
        self.assertEqual(self.writes(), [])
        self.client = ScheduleClient()
        with patch('canvas_cli.page_scheduling.datetime') as clock:
            clock.now.side_effect = [datetime(2030, 10, 1, 16, 0, tzinfo=timezone.utc),
                                    datetime(2030, 10, 1, 16, 59, 10, tzinfo=timezone.utc)]
            with self.assertRaisesRegex(CanvasError, '60 seconds'):
                self.call()
        self.assertEqual(self.writes(), [])

    def test_second_course_account_and_inventory_reads_must_match_preflight(self):
        for mode in ('course', 'account', 'inventory'):
            self.client = ScheduleClient()
            if mode == 'course':
                self.client.feature_course_mismatch = True
            elif mode == 'account':
                self.client.preflight_account_switch = True
            else:
                self.client.inventory_patch = {'title': 'Other source'}
            with self.assertRaises(CanvasError):
                self.call()
            self.assertEqual(self.writes(), [])

    def test_final_account_switch_and_absent_stored_inventory_never_retry_or_repair(self):
        for mode in ('account', 'inventory'):
            self.client = ScheduleClient()
            preview = self.call()
            if mode == 'account':
                self.client.final_account_switch = True
            else:
                self.client.after_hook = lambda client: setattr(client, 'inventory_patch', {'title': 'Other source'})
            with self.assertRaisesRegex(CanvasError, 'Could not verify'):
                self.call(yes=True, confirm=preview['confirm'])
            self.assertEqual(len(self.writes()), 1)

    def test_native_denial_single_put_no_fallback_or_retry(self):
        preview = self.call()
        self.client.denied = True
        with self.assertRaisesRegex(CanvasError, 'blueprint'):
            self.call(yes=True, confirm=preview['confirm'])
        self.assertEqual(len(self.writes()), 1)

    def test_ignored_unsafe_ack_foreign_id_or_missing_date_is_uncertain_single_put(self):
        for mode in ('ignored', 'foreign', 'published', 'front', 'title', 'date', 'body', 'missing_date', 'delete_race'):
            self.client = ScheduleClient()
            preview = self.call()
            if mode == 'ignored':
                self.client.ignored = True
            elif mode == 'foreign':
                self.client.ack_patch['page_id'] = 11
            elif mode == 'published':
                self.client.ack_patch['published'] = True
            elif mode == 'front':
                self.client.ack_patch['front_page'] = True
            elif mode == 'title':
                self.client.ack_patch['title'] = 'Changed'
            elif mode == 'date':
                self.client.ack_patch['publish_at'] = '2031-01-01T12:00:00Z'
            elif mode == 'body':
                self.client.ack_patch['body'] = 'Changed'
            elif mode == 'missing_date':
                self.client.omit_ack_date = True
            else:
                self.client.delete_race = True
            with self.assertRaisesRegex(CanvasError, 'Could not verify'):
                self.call(yes=True, confirm=preview['confirm'])
            self.assertEqual(len(self.writes()), 1)

    def test_readback_loss_changes_or_front_inventory_race_are_uncertain_single_put(self):
        for mode in ('readback', 'body', 'date', 'identity', 'course', 'rights', 'feature', 'root', 'front', 'inventory'):
            self.client = ScheduleClient()
            preview = self.call()
            if mode == 'readback':
                self.client.readback_denied = True
            elif mode in ('body', 'date'):
                self.client.after_patch['body' if mode == 'body' else 'publish_at'] = 'Changed' if mode == 'body' else None
            else:
                def mutate(client, selected=mode):
                    if selected == 'identity':
                        client.identity = 8
                    elif selected == 'course':
                        client.context['name'] = 'Changed'
                    elif selected == 'rights':
                        client.permissions['manage_wiki_update'] = False
                    elif selected == 'feature':
                        client.flag['state'] = 'off'
                    elif selected == 'root':
                        client.context['root_account_id'] = 3
                    elif selected == 'front':
                        client.pages[10]['front_page'] = False
                    else:
                        client.pages.pop(9)
                self.client.after_hook = mutate
            with self.assertRaisesRegex(CanvasError, 'Could not verify'):
                self.call(yes=True, confirm=preview['confirm'])
            self.assertEqual(len(self.writes()), 1)
