"""Installed-CLI HTTPS regression tests for account workflows."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .fixture import CanvasFixture


class AccountE2E(CanvasFixture):
    def test_notification_category_expands_exact_keys_and_preserves_other_categories_over_tls(self):
        original = {key: row.copy() for key, row in self.notification_preferences.items()}
        try:
            self.notification_preferences['announcement_reply'] = {'notification': 'announcement_reply',
                                                                    'category': 'announcement', 'frequency': 'weekly'}
            command = ('notification-category-set', '19', '--category', 'announcement', '--frequency', 'immediately')
            before = len(self.calls)
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            data = json.loads(preview.stdout)
            self.assertTrue(data['dry_run'])
            self.assertEqual(data['category_selection']['notification_count'], 2)
            self.assertEqual(set(data['body']['notification_preferences']), {'announcement_reply', 'new_announcement'})
            self.assertNotIn('synthetic-contact@example.edu', preview.stdout)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
            result = self.invoke(*command, '--yes', '--confirm', data['confirm'])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['category_selection'], data['category_selection'])
            self.assertEqual(self.notification_write, data['body'])
            self.assertEqual(self.notification_preferences['submission_comment'], original['submission_comment'])
            self.assertEqual(self.notification_preferences['announcement_reply']['frequency'], 'immediately')
            self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                             [('PUT', '/api/v1/users/self/communication_channels/19/notification_preferences')])
        finally:
            type(self).notification_preferences = original


    def test_notification_category_changed_inventory_unknown_category_and_partial_ack_fail_safely(self):
        original = {key: row.copy() for key, row in self.notification_preferences.items()}
        old_shape = self.notification_ack_shape
        try:
            command = ('notification-category-set', '19', '--category', 'announcement', '--frequency', 'weekly')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            digest = json.loads(preview.stdout)['confirm']
            self.notification_preferences['announcement_reply'] = {'notification': 'announcement_reply',
                                                                    'category': 'announcement', 'frequency': 'daily'}
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', digest)
            self.assertEqual(result.returncode, 1)
            self.assertIn('Preview changed', result.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
            result = self.invoke('notification-category-set', '19', '--category', 'unknown_category', '--frequency', 'weekly')
            self.assertEqual(result.returncode, 1)
            self.assertIn('Category is not reported', result.stderr)
            self.assertEqual(result.stdout, '')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            digest = json.loads(preview.stdout)['confirm']
            type(self).notification_ack_shape = 'ambiguous'
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', digest)
            self.assertEqual(result.returncode, 1)
            self.assertIn('partially applied', result.stderr)
            self.assertNotIn('Synthetic never log notification error', result.stderr)
            self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                             [('PUT', '/api/v1/users/self/communication_channels/19/notification_preferences')])
        finally:
            type(self).notification_preferences = original
            type(self).notification_ack_shape = old_shape


    def test_own_profile_is_metadata_first_with_explicit_bio_email_and_no_feed_secrets(self):
        before = len(self.calls)
        result = self.invoke('profile', '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Synthetic Student', result.stdout)
        self.assertNotIn('Synthetic private old biography', result.stdout)
        self.assertNotIn('synthetic-profile@example.edu', result.stdout)
        self.assertEqual(self.calls[before:], [('GET', '/api/v1/users/self/profile')])
        result = self.invoke('profile', '--include-bio', '--include-email')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)['own_profile']
        self.assertEqual(data['bio'], self.own_profile['bio'])
        self.assertEqual(data['primary_email'], self.own_profile['primary_email'])
        self.assertNotIn('synthetic-private-profile', result.stdout)


    def test_profile_edits_are_preview_first_shared_acknowledged_and_readback_verified(self):
        original = self.own_profile.copy()
        try:
            before = len(self.calls)
            command = ('profile-set', '--short-name', 'Synthetic new display', '--acknowledge-shared-profile')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            data = json.loads(preview.stdout)
            self.assertTrue(data['shared_profile_change'])
            self.assertEqual(data['body'], {'user': {'short_name': 'Synthetic new display'}, 'override_sis_stickiness': False})
            self.assertNotIn('Synthetic private old biography', preview.stdout)
            self.assertEqual(self.calls[before:], [('GET', '/api/v1/users/self/profile')])
            result = self.invoke(*command, '--yes', '--confirm', data['confirm'], '--format', 'brief')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('verified by read-back', result.stdout)
            self.assertEqual(self.profile_write, data['body'])
            self.assertEqual(self.own_profile['short_name'], 'Synthetic new display')
            self.assertEqual(self.own_profile['bio'], original['bio'])
            self.assertEqual(self.calls[-3:], [('GET', '/api/v1/users/self/profile'), ('PUT', '/api/v1/users/self'),
                                              ('GET', '/api/v1/users/self/profile')])
            # Own display timezone alone has no shared-profile acknowledgement requirement.
            command = ('profile-set', '--timezone', 'America/Los_Angeles')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            data = json.loads(preview.stdout)
            self.assertFalse(data['shared_profile_change'])
            result = self.invoke(*command, '--yes', '--confirm', data['confirm'])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)['read_back_verified'])
        finally:
            type(self).own_profile = original
            type(self).profile_written = False


    def test_profile_bio_file_is_exact_reloaded_utf8_bounded_and_optional_clear_works(self):
        original = self.own_profile.copy()
        path = Path(self.tmp.name) / 'synthetic-profile-bio.txt'
        try:
            path.write_text('New synthetic biography\nSecond line 🌿\n', encoding='utf-8')
            command = ('profile-set', '--bio-file', str(path), '--title', '', '--acknowledge-shared-profile')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            data = json.loads(preview.stdout)
            self.assertEqual(data['body']['user']['bio'], path.read_text(encoding='utf-8'))
            path.write_text('Changed input before confirmation', encoding='utf-8')
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', data['confirm'])
            self.assertEqual(result.returncode, 1)
            self.assertIn('Preview changed', result.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
            path.write_bytes(b'\xff')
            before = len(self.calls)
            result = self.invoke(*command)
            self.assertEqual(result.returncode, 1)
            self.assertIn('UTF-8', result.stderr)
            self.assertEqual(self.calls[before:], [])
            path.write_bytes(b'x' * 40001)
            result = self.invoke(*command)
            self.assertEqual(result.returncode, 1)
            self.assertIn('size bounds', result.stderr)
            self.assertEqual(self.calls[before:], [])
            path.write_text('', encoding='utf-8')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            data = json.loads(preview.stdout)
            result = self.invoke(*command, '--yes', '--confirm', data['confirm'])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['profile_changes'], {'bio': '', 'title': ''})
        finally:
            type(self).own_profile = original
            type(self).profile_written = False


    def test_profile_bad_flags_foreign_or_changed_state_never_write(self):
        original = self.own_profile.copy()
        try:
            before = len(self.calls)
            for command in (('profile-set',), ('profile-set', '--name', 'New'),
                            ('profile-set', '--name', '', '--acknowledge-shared-profile'),
                            ('profile-set', '--timezone', 'invalid/synthetic'),
                            ('profile-set', '--timezone', 'UTC', '--yes')):
                result = self.invoke(*command)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(self.calls[before:], [])
            command = ('profile-set', '--name', 'New synthetic name', '--acknowledge-shared-profile')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            data = json.loads(preview.stdout)
            for patch in ({'id': 8}, {'bio': 'Changed revision'}, {'name': 'Changed revision'}):
                type(self).own_profile = {**original, **patch}
                before = len(self.calls)
                result = self.invoke(*command, '--yes', '--confirm', data['confirm'])
                self.assertEqual(result.returncode, 1)
                self.assertIn('Preview changed', result.stderr)
                self.assertEqual(self.calls[before:], [('GET', '/api/v1/users/self/profile')])
        finally:
            type(self).own_profile = original


    def test_profile_native_denial_partial_update_and_readback_failure_are_not_retried(self):
        original = self.own_profile.copy()
        try:
            for mode in ('denied', 'ambiguous', 'ignored', 'readback_denied'):
                type(self).own_profile = original.copy()
                type(self).profile_written = False
                type(self).profile_denied = False
                type(self).profile_ack = 'normal'
                type(self).profile_ignored_fields = set()
                type(self).profile_fail_readback = False
                command = ('profile-set', '--name', 'New synthetic name', '--short-name', 'Synthetic new display',
                           '--acknowledge-shared-profile')
                preview = self.invoke(*command)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                digest = json.loads(preview.stdout)['confirm']
                type(self).profile_denied = mode == 'denied'
                type(self).profile_ack = 'ambiguous' if mode == 'ambiguous' else 'normal'
                type(self).profile_ignored_fields = {'name'} if mode == 'ignored' else set()
                type(self).profile_fail_readback = mode == 'readback_denied'
                before = len(self.calls)
                result = self.invoke(*command, '--yes', '--confirm', digest)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertEqual(result.stdout, '')
                self.assertNotIn('Synthetic never log profile error', result.stderr)
                self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'], [('PUT', '/api/v1/users/self')])
                if mode != 'denied':
                    self.assertIn('Some edits may have applied', result.stderr)
                    self.assertEqual(self.own_profile['short_name'], 'Synthetic new display')
                else:
                    self.assertEqual(self.own_profile, original)
        finally:
            type(self).own_profile = original
            type(self).profile_written = False
            type(self).profile_denied = False
            type(self).profile_ack = 'normal'
            type(self).profile_ignored_fields = set()
            type(self).profile_fail_readback = False


    def test_own_enrollments_paginate_native_filters_keep_sections_and_omit_private_data(self):
        before = len(self.calls)
        result = self.invoke('enrollments')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual([row['id'] for row in data['enrollments']], [77, 78, 99])
        self.assertTrue(data['complete_for_endpoint'])
        self.assertNotIn('synthetic-private-own', result.stdout)
        self.assertNotIn('grades', str(data['enrollments']))
        self.assertEqual(self.calls[before:], [('GET', '/api/v1/users/self/profile'),
                                             ('GET', '/api/v1/users/self/enrollments?per_page=100'),
                                             ('GET', '/api/v1/users/self/enrollments?per_page=100&page=2')])
        result = self.invoke('enrollments', '--type', 'StudentEnrollment', '--state', 'active',
                             '--state', 'invited', '--term', '12', '--course', '102', '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('99 | course 102', result.stdout)
        self.assertNotIn('77 | course', result.stdout)
        self.assertIn('not official university registration', result.stdout)
        query = parse_qs(urlsplit(self.calls[-1][1]).query)
        self.assertEqual(query['type[]'], ['StudentEnrollment'])
        self.assertEqual(query['state[]'], ['active', 'invited'])
        self.assertEqual(query['enrollment_term_id'], ['12'])
        self.assertNotIn('user_id', query)


    def test_own_invitation_accept_reject_lifecycles_require_acknowledgement_and_fresh_digest(self):
        original = self.enrollment_invitation.copy()
        try:
            before = len(self.calls)
            result = self.invoke('enrollment-accept', '102', '99')
            self.assertEqual(result.returncode, 2)
            self.assertEqual(self.calls[before:], [])
            for action, expected in (('accept', 'active'), ('reject', 'rejected')):
                type(self).enrollment_invitation = original.copy()
                command = ('enrollment-' + action, '102', '99', '--acknowledge-canvas-enrollment')
                before = len(self.calls)
                preview = self.invoke(*command)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                data = json.loads(preview.stdout)
                self.assertEqual(data['invitation']['user_id'], 7)
                self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                refused = self.invoke(*command, '--yes', '--confirm', 'wrong')
                self.assertEqual(refused.returncode, 1)
                self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                result = self.invoke(*command, '--yes', '--confirm', data['confirm'], '--format', 'brief')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(action + ' acknowledged', result.stdout)
                self.assertEqual(self.enrollment_invitation['enrollment_state'], expected)
                self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'], [('POST', data['route'])])
                result = self.invoke(*command)
                self.assertEqual(result.returncode, 1)
                self.assertIn('not returned as an invitation', result.stderr)
        finally:
            type(self).enrollment_invitation = original


    def test_ambiguous_or_denied_invitation_response_is_not_retried_or_logged(self):
        original = self.enrollment_invitation.copy()
        try:
            for action in ('accept', 'reject'):
                for mode in ('denied', 'ambiguous'):
                    type(self).enrollment_invitation = original.copy()
                    command = ('enrollment-' + action, '102', '99', '--acknowledge-canvas-enrollment')
                    preview = self.invoke(*command)
                    self.assertEqual(preview.returncode, 0, preview.stderr)
                    data = json.loads(preview.stdout)
                    type(self).invitation_denied = mode == 'denied'
                    type(self).invitation_ack = mode
                    before = len(self.calls)
                    result = self.invoke(*command, '--yes', '--confirm', data['confirm'])
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, '')
                    self.assertNotIn('Synthetic never log', result.stderr)
                    self.assertIn('denied access' if mode == 'denied' else 'may have succeeded', result.stderr)
                    self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'], [('POST', data['route'])])
                    type(self).invitation_denied = False
                    type(self).invitation_ack = 'normal'
        finally:
            type(self).enrollment_invitation = original
            type(self).invitation_denied = False
            type(self).invitation_ack = 'normal'


    def test_permission_views_have_exact_native_booleans_and_explicit_context_over_tls(self):
        before = len(self.calls)
        result = self.invoke('permissions', '101', '--permission', 'send_messages', '--permission', 'read_roster', '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('read_roster: true', result.stdout)
        self.assertIn('send_messages: false', result.stdout)
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertEqual(self.calls[before:], [('GET', '/api/v1/courses/101'),
                                             ('GET', '/api/v1/courses/101/permissions?permissions%5B%5D=read_roster&permissions%5B%5D=send_messages')])
        result = self.invoke('permissions', '11', '--context', 'group', '--permission', 'join', '--permission', 'leave')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['permissions'], {'join': True, 'leave': True})
        original = self.membership_permissions.copy()
        try:
            self.membership_permissions['join'] = 'true'
            result = self.invoke('permissions', '11', '--context', 'group', '--permission', 'join')
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, '')
        finally:
            type(self).membership_permissions = original
        before = len(self.calls)
        for arguments in (('--permission', '../join'), ('--permission', 'join', '--permission', 'join')):
            result = self.invoke('permissions', '11', '--context', 'group', *arguments)
            self.assertEqual(result.returncode, 1)
        self.assertEqual(self.calls[before:], [])


    def test_group_sets_and_category_groups_are_paginated_course_verified_private_metadata(self):
        before = len(self.calls)
        result = self.invoke('group-categories', '101', '--collaboration-state', 'all')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['complete_for_endpoint'])
        self.assertEqual(data['group_categories'][0]['self_signup'], 'restricted')
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertEqual(len(self.calls[before:]), 3)
        result = self.invoke('group-category', '101', '3')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['group_category']['id'], 3)
        result = self.invoke('category-groups', '101', '3', '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('self-signup restricted', result.stdout)
        self.assertIn('11 | Synthetic project team | native count 3', result.stdout)
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        self.assertFalse(any('/users' in route or 'export' in route for _, route in self.calls[before:]))


    def test_group_sets_denial_truncation_and_foreign_associations_are_not_empty_success(self):
        original_category, original_groups = self.group_category.copy(), list(self.category_groups)
        try:
            type(self).category_denied = True
            for command in (('group-categories', '101'), ('group-category', '101', '3'), ('category-groups', '101', '3')):
                result = self.invoke(*command)
                self.assertEqual(result.returncode, 1)
                self.assertIn('denied access', result.stderr)
                self.assertEqual(result.stdout, '')
            type(self).category_denied = False
            for command in (('group-categories', '101'), ('category-groups', '101', '3')):
                result = self.invoke(*command, '--max-pages', '1')
                self.assertEqual(result.returncode, 1)
                self.assertIn('Page limit', result.stderr)
                self.assertEqual(result.stdout, '')
            self.group_category['course_id'] = 102
            before = len(self.calls)
            result = self.invoke('category-groups', '101', '3')
            self.assertEqual(result.returncode, 1)
            self.assertIn('outside the requested course', result.stderr)
            self.assertEqual(self.calls[before:], [('GET', '/api/v1/courses/101'), ('GET', '/api/v1/group_categories/3')])
            type(self).group_category = original_category.copy()
            type(self).category_groups = [{**original_groups[0], 'group_category_id': 4}]
            result = self.invoke('category-groups', '101', '3')
            self.assertEqual(result.returncode, 1)
            self.assertIn('outside the requested group category', result.stderr)
            self.assertEqual(result.stdout, '')
        finally:
            type(self).category_denied = False
            type(self).group_category = original_category
            type(self).category_groups = original_groups


    def test_rosters_paginate_encode_filters_and_project_private_fields_over_tls(self):
        before = len(self.calls)
        result = self.invoke('course-users', '101', '--search', 'Example & Name',
                             '--enrollment-type', 'teacher', '--enrollment-type', 'ta',
                             '--enrollment-state', 'active', '--enrollment-state', 'invited',
                             '--section', '32', '--section', '31', '--include-enrollments')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['complete_for_endpoint'])
        self.assertEqual([row['id'] for row in data['users']], [7, 8])
        self.assertEqual(data['users'][1]['enrollments'][0]['enrollment_state'], 'invited')
        self.assertNotIn('synthetic-private-roster', result.stdout)
        self.assertNotIn('synthetic-roster-contact', result.stdout)
        self.assertNotIn('grades', str(data['users']))
        calls = self.calls[before:]
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(method == 'GET' for method, _ in calls))
        query = parse_qs(urlsplit(calls[1][1]).query)
        self.assertEqual(query['search_term'], ['Example & Name'])
        self.assertEqual(query['enrollment_type[]'], ['ta', 'teacher'])
        self.assertEqual(query['section_ids[]'], ['31', '32'])
        self.assertEqual(query['include[]'], ['enrollments'])
        result = self.invoke('group-users', '11', '--no-exclude-inactive', '--include-email', '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Visible roster (group 11): 2 returned', result.stdout)
        self.assertIn('synthetic-roster-contact@example.edu', result.stdout)
        self.assertNotIn('synthetic-private-roster', result.stdout)
        self.assertEqual(parse_qs(urlsplit(self.calls[-1][1]).query)['exclude_inactive'], ['false'])
        result = self.invoke('group-users', '11')
        data = json.loads(result.stdout)
        self.assertEqual(data['returned_user_count'], 2)
        self.assertEqual(data['reported_members_count'], 20)
        self.assertFalse(data['native_is_full'])
        self.assertNotIn('exclude_inactive', urlsplit(self.calls[-1][1]).query)


    def test_roster_denied_truncated_invalid_and_foreign_enrollments_emit_no_partial_success(self):
        original = list(self.roster_users)
        try:
            for command in (('course-users', '102'), ('course-users', '101', '--max-pages', '1'),
                            ('group-users', '11', '--max-pages', '1')):
                result = self.invoke(*command)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, '')
            before = len(self.calls)
            result = self.invoke('course-users', '101', '--search', 'x')
            self.assertEqual(result.returncode, 1)
            self.assertEqual(self.calls[before:], [])
            type(self).roster_users = [*original, original[0]]
            result = self.invoke('group-users', '11')
            self.assertEqual(result.returncode, 1)
            self.assertIn('duplicate', result.stderr)
            self.assertEqual(result.stdout, '')
            type(self).roster_users = [{**original[0], 'enrollments': [{**original[0]['enrollments'][0], 'course_id': 102}]}]
            result = self.invoke('course-users', '101', '--include-enrollments')
            self.assertEqual(result.returncode, 1)
            self.assertIn('outside the requested course/user', result.stderr)
            self.assertEqual(result.stdout, '')
        finally:
            type(self).roster_users = original


    def test_own_group_membership_join_request_leave_lifecycle_is_preview_first(self):
        original_members, original_options = list(self.group_memberships), self.membership_group_options.copy()
        try:
            before = len(self.calls)
            result = self.invoke('group-membership', '11')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsNone(json.loads(result.stdout)['membership'])
            for role, level, expected_state in (('student_organized', 'parent_context_auto_join', 'accepted'),
                                                 ('communities', 'parent_context_request', 'requested')):
                self.membership_group_options.update(role=role, join_level=level)
                for action in ('join', 'leave'):
                    command = ('group-' + action, '11')
                    start = len(self.calls)
                    preview = self.invoke(*command)
                    self.assertEqual(preview.returncode, 0, preview.stderr)
                    data = json.loads(preview.stdout)
                    self.assertEqual(data['user_id'], 7)
                    self.assertTrue(all(method == 'GET' for method, _ in self.calls[start:]))
                    refused = self.invoke(*command, '--yes', '--confirm', 'wrong')
                    self.assertEqual(refused.returncode, 1)
                    self.assertTrue(all(method == 'GET' for method, _ in self.calls[start:]))
                    result = self.invoke(*command, '--yes', '--confirm', data['confirm'])
                    self.assertEqual(result.returncode, 0, result.stderr)
                    accepted = json.loads(result.stdout)
                    self.assertTrue(accepted['acknowledged'])
                    self.assertEqual(self.membership_write, {'user_id': 'self'} if action == 'join' else {})
                    self.assertEqual([call for call in self.calls[start:] if call[0] != 'GET'], [(data['method'], data['route'])])
                    self.assertEqual([row for row in self.group_memberships if row['user_id'] == 8], original_members)
                    self.assertEqual(accepted['membership']['workflow_state'] if action == 'join' else accepted['membership'],
                                     expected_state if action == 'join' else None)
                    current = self.invoke('group-membership', '11', '--format', 'brief')
                    self.assertEqual(current.returncode, 0, current.stderr)
                    self.assertIn(expected_state if action == 'join' else 'no active record returned', current.stdout)
            self.assertFalse(any('/courses/' in route or '/users/8' in route for _, route in self.calls[before:]))
        finally:
            type(self).group_memberships = original_members
            type(self).membership_group_options = original_options


    def test_group_membership_guard_stale_preview_and_truncated_inventory_never_write(self):
        original_members, original_options = list(self.group_memberships), self.membership_group_options.copy()
        original_permissions = self.membership_permissions.copy()
        try:
            before = len(self.calls)
            preview = self.invoke('group-join', '11')
            digest = json.loads(preview.stdout)['confirm']
            self.membership_group_options['join_level'] = 'parent_context_request'
            result = self.invoke('group-join', '11', '--yes', '--confirm', digest)
            self.assertEqual(result.returncode, 1)
            self.assertIn('Preview changed', result.stderr)
            for options in ({'role': None}, {'non_collaborative': True}, {'concluded': True}):
                self.membership_group_options.update(options)
                result = self.invoke('group-join', '11')
                self.assertEqual(result.returncode, 1)
                self.assertIn('project groups', result.stderr)
                self.membership_group_options.update(original_options)
            self.membership_permissions['join'] = False
            result = self.invoke('group-join', '11')
            self.assertEqual(result.returncode, 1)
            self.assertIn('explicitly grant', result.stderr)
            self.membership_permissions.update(original_permissions)
            result = self.invoke('group-join', '11', '--max-pages', '1')
            self.assertEqual(result.returncode, 1)
            self.assertIn('Page limit', result.stderr)
            self.group_memberships.append({'id': 71, 'group_id': 12, 'user_id': 7, 'workflow_state': 'accepted', 'moderator': False})
            result = self.invoke('group-membership', '11')
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, '')
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        finally:
            type(self).group_memberships = original_members
            type(self).membership_group_options = original_options
            type(self).membership_permissions = original_permissions


    def test_ambiguous_and_denied_membership_writes_are_never_retried(self):
        original_members = list(self.group_memberships)
        try:
            for action in ('join', 'leave'):
                for mode in ('denied', 'ambiguous'):
                    type(self).group_memberships = list(original_members)
                    if action == 'leave':
                        self.group_memberships.append({'id': 71, 'group_id': 11, 'user_id': 7,
                                                       'workflow_state': 'accepted', 'moderator': False})
                    command = ('group-' + action, '11')
                    preview = self.invoke(*command)
                    self.assertEqual(preview.returncode, 0, preview.stderr)
                    data = json.loads(preview.stdout)
                    type(self).membership_denied = mode == 'denied'
                    type(self).membership_ack = mode
                    before = len(self.calls)
                    result = self.invoke(*command, '--yes', '--confirm', data['confirm'])
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, '')
                    self.assertNotIn('Synthetic never log', result.stderr)
                    self.assertIn('denied access' if mode == 'denied' else 'may have succeeded', result.stderr)
                    self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'], [(data['method'], data['route'])])
                    type(self).membership_denied = False
                    type(self).membership_ack = 'normal'
        finally:
            type(self).group_memberships = original_members
            type(self).membership_denied = False
            type(self).membership_ack = 'normal'


    def test_nickname_lifecycle_is_account_bound_and_preserves_actual_course_name(self):
        original = self.course_nicknames.copy()
        try:
            listing = self.invoke('nicknames')
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertEqual([row['course_id'] for row in json.loads(listing.stdout)], [101, 102])
            commands = [('nickname-set', '101', '--name', 'Synthetic alias'),
                        ('nickname-clear', '101'), ('nicknames-reset',)]
            for command in commands:
                before = len(self.calls)
                preview = self.invoke(*command)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                data = json.loads(preview.stdout)
                refused = self.invoke(*command, '--yes', '--confirm', 'wrong')
                self.assertNotEqual(refused.returncode, 0)
                self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                sent = self.invoke(*command, '--yes', '--confirm', data['confirm'], '--format', 'brief')
                self.assertEqual(sent.returncode, 0, sent.stderr)
                self.assertIn('nicknames' if command[0] == 'nicknames-reset' else 'Nickname', sent.stdout)
                self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                                 [(data['method'], data['route'])])
                self.assertEqual(self.preference_write, data['body'] or {})
                current = self.invoke('nickname', '101')
                self.assertEqual(current.returncode, 0, current.stderr)
                current = json.loads(current.stdout)
                self.assertEqual(current['name'], 'Synthetic course')
                self.assertEqual(current['nickname'], 'Synthetic alias' if command[0] == 'nickname-set' else None)
            self.assertEqual(self.course_nicknames, {})
        finally:
            type(self).course_nicknames = original


    def test_nickname_reset_refuses_changed_or_truncated_inventory_over_tls(self):
        original = self.course_nicknames.copy()
        try:
            preview = self.invoke('nicknames-reset')
            self.assertEqual(preview.returncode, 0, preview.stderr)
            type(self).course_nicknames[102] = 'Changed after preview'
            before = len(self.calls)
            changed = self.invoke('nicknames-reset', '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn('Preview changed', changed.stderr)
            truncated = self.invoke('nicknames-reset', '--max-pages', '1')
            self.assertNotEqual(truncated.returncode, 0)
            self.assertIn('Page limit', truncated.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        finally:
            type(self).course_nicknames = original


    def test_course_group_and_personal_calendar_colors_over_tls(self):
        original = self.custom_colors.copy()
        try:
            for context, item in [('course', '101'), ('group', '11'), ('user', '7')]:
                command = ('color-set', item, '--context', context, '--hex', 'AABBCC')
                before = len(self.calls)
                preview = self.invoke(*command)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                data = json.loads(preview.stdout)
                self.assertEqual(data['body'], {'hexcode': '#aabbcc'})
                refused = self.invoke(*command, '--yes', '--confirm', 'wrong')
                self.assertNotEqual(refused.returncode, 0)
                self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
                self.assertEqual(sent.returncode, 0, sent.stderr)
                self.assertTrue(json.loads(sent.stdout)['acknowledged'])
                self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'], [('PUT', data['route'])])
                current = self.invoke('color', item, '--context', context)
                self.assertEqual(current.returncode, 0, current.stderr)
                self.assertEqual(json.loads(current.stdout)['hexcode'], '#aabbcc')
            current = self.invoke('color', '102')
            self.assertIsNone(json.loads(current.stdout)['hexcode'])
            before = len(self.calls)
            denied = self.invoke('color-set', '8', '--context', 'user', '--hex', 'abc')
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn('own personal calendar', denied.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        finally:
            type(self).custom_colors = original


    def test_own_settings_changes_preserve_unrequested_fields_and_reject_stale_state(self):
        original = self.user_settings.copy()
        try:
            listing = self.invoke('settings')
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertEqual(json.loads(listing.stdout)['settings'], original)
            command = ('settings-set', '--set', 'manual_mark_as_read=true', '--set', 'collapse_course_nav=true')
            before = len(self.calls)
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            data = json.loads(preview.stdout)
            refused = self.invoke(*command, '--yes', '--confirm', 'wrong')
            self.assertNotEqual(refused.returncode, 0)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
            sent = self.invoke(*command, '--yes', '--confirm', data['confirm'], '--format', 'brief')
            self.assertEqual(sent.returncode, 0, sent.stderr)
            self.assertIn('manual_mark_as_read: True', sent.stdout)
            self.assertEqual(self.preference_write, {'manual_mark_as_read': True, 'collapse_course_nav': True})
            self.assertEqual(self.user_settings['collapse_global_nav'], original['collapse_global_nav'])
            self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                             [('PUT', '/api/v1/users/self/settings')])
            before = len(self.calls)
            stale = self.invoke(*command, '--yes', '--confirm', data['confirm'])
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn('Preview changed', stale.stderr)
            missing = self.invoke('settings-set', '--set', 'widget_dashboard_dark_mode=true')
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn('not reported', missing.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        finally:
            type(self).user_settings = original


    def test_own_channels_and_wrapped_preferences_are_private_and_paginated_over_tls(self):
        before = len(self.calls)
        listing = self.invoke('channels')
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertEqual(len(json.loads(listing.stdout)['communication_channels']), 2)
        for secret in ('synthetic-contact@example.edu', 'synthetic-private-push-token', 'Synthetic private bounce details'):
            self.assertNotIn(secret, listing.stdout)
        explicit = self.invoke('channels', '--include-addresses', '--format', 'brief')
        self.assertEqual(explicit.returncode, 0, explicit.stderr)
        self.assertIn('synthetic-contact@example.edu', explicit.stdout)
        self.assertNotIn('synthetic-private-push-token', explicit.stdout)
        reading = self.invoke('notification-preferences', '19', '--category', 'announcement', '--format', 'brief')
        self.assertEqual(reading.returncode, 0, reading.stderr)
        self.assertIn('new_announcement | daily | announcement', reading.stdout)
        self.assertNotIn('submission_comment |', reading.stdout)
        self.assertIn('default notification-policy', reading.stdout)
        for command in (('channels',), ('notification-preferences', '19')):
            capped = self.invoke(*command, '--max-pages', '1')
            self.assertNotEqual(capped.returncode, 0)
            self.assertEqual(capped.stdout, '')
            self.assertIn('Page limit', capped.stderr)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))


    def test_notification_batch_is_exact_and_bound_to_channel_and_current_frequencies(self):
        original = {key: row.copy() for key, row in self.notification_preferences.items()}
        original_channels = [row.copy() for row in self.communication_channels]
        try:
            command = ('notification-preferences-set', '19', '--set', 'new_announcement=immediately')
            before = len(self.calls)
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            data = json.loads(preview.stdout)
            self.assertEqual(data['body'], {'notification_preferences': {'new_announcement': {'frequency': 'immediately'}}})
            self.assertNotIn('synthetic-contact@example.edu', preview.stdout)
            refused = self.invoke(*command, '--yes', '--confirm', 'wrong')
            self.assertNotEqual(refused.returncode, 0)
            self.communication_channels[0]['address'] = 'changed-contact@example.edu'
            stale = self.invoke(*command, '--yes', '--confirm', data['confirm'])
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn('Preview changed', stale.stderr)
            self.communication_channels[0]['address'] = original_channels[0]['address']
            self.notification_preferences['new_announcement']['frequency'] = 'never'
            stale = self.invoke(*command, '--yes', '--confirm', data['confirm'])
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn('Preview changed', stale.stderr)
            self.notification_preferences['new_announcement']['frequency'] = 'daily'
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
            sent = self.invoke(*command, '--yes', '--confirm', data['confirm'], '--format', 'brief')
            self.assertEqual(sent.returncode, 0, sent.stderr)
            self.assertIn('new_announcement | immediately', sent.stdout)
            self.assertEqual(self.notification_write, data['body'])
            self.assertEqual(self.notification_preferences['submission_comment'], original['submission_comment'])
            self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'], [('PUT', data['route'])])
            before = len(self.calls)
            for command in (('notification-preferences-set', '19', '--set', 'unknown_notice=never'),
                            ('notification-preferences-set', '99', '--set', 'new_announcement=never'),
                            ('notification-preferences-set', '19', '--set', 'new_announcement=asap')):
                denied = self.invoke(*command)
                self.assertNotEqual(denied.returncode, 0)
                self.assertEqual(denied.stdout, '')
            self.communication_channels[0]['user_id'] = 8
            denied = self.invoke('notification-preferences', '19')
            self.assertNotEqual(denied.returncode, 0)
            self.assertEqual(denied.stdout, '')
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        finally:
            type(self).notification_preferences = original
            type(self).communication_channels = original_channels


    def test_ambiguous_notification_ack_is_one_write_and_requires_manual_verification(self):
        original = {key: row.copy() for key, row in self.notification_preferences.items()}
        old_shape = self.notification_ack_shape
        try:
            command = ('notification-preferences-set', '19', '--set', 'new_announcement=weekly',
                       '--set', 'submission_comment=daily')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            data = json.loads(preview.stdout)
            type(self).notification_ack_shape = 'ambiguous'
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', data['confirm'])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertIn('partially applied', result.stderr)
            self.assertNotIn('Synthetic never log notification error', result.stderr)
            self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'], [('PUT', data['route'])])
            self.assertEqual(self.notification_preferences['new_announcement']['frequency'], 'weekly')
            self.assertEqual(self.notification_preferences['submission_comment']['frequency'], 'daily')
        finally:
            type(self).notification_preferences = original
            type(self).notification_ack_shape = old_shape


    def test_dashboard_order_and_single_position_are_confirmed_merges_over_tls(self):
        original = self.dashboard_positions.copy()
        try:
            commands = [('dashboard-order', 'course_102', 'course_101', 'group_11'),
                        ('dashboard-position-set', '7', '--context', 'user', '--position', '-1')]
            for command in commands:
                before = len(self.calls)
                preview = self.invoke(*command)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                data = json.loads(preview.stdout)
                refused = self.invoke(*command, '--yes', '--confirm', 'wrong')
                self.assertNotEqual(refused.returncode, 0)
                self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
                self.assertEqual(sent.returncode, 0, sent.stderr)
                self.assertTrue(json.loads(sent.stdout)['acknowledged'])
                self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                                 [('PUT', '/api/v1/users/self/dashboard_positions')])
                self.assertEqual(self.preference_write, data['body'])
            current = self.invoke('dashboard-positions')
            self.assertEqual(current.returncode, 0, current.stderr)
            self.assertEqual(json.loads(current.stdout)['dashboard_positions'],
                             {'course_101': 1, 'course_102': 0, 'group_11': 2, 'group_12': '9', 'user_7': -1})
            before = len(self.calls)
            for command in [('dashboard-order', 'course_101', 'course_101'), ('dashboard-order', 'course_01'),
                            ('dashboard-position-set', '8', '--context', 'user', '--position', '0')]:
                denied = self.invoke(*command)
                self.assertNotEqual(denied.returncode, 0)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        finally:
            type(self).dashboard_positions = original


    def test_favorites_changes_are_preview_first_and_reset_restores_defaults(self):
        original = {context: ids.copy() for context, ids in self.favorite_ids.items()}
        try:
            for context, target in [('course', '102'), ('group', '11')]:
                type(self).favorite_ids = {'course': set(), 'group': set()}
                displayed = self.invoke('favorites', '--context', context)
                self.assertEqual(displayed.returncode, 0, displayed.stderr)
                self.assertEqual(len(json.loads(displayed.stdout)), 2)
                for command in [('favorite-add', target), ('favorite-remove', target),
                                ('favorite-remove', target), ('favorites-reset',)]:
                    with self.subTest(context=context, command=command):
                        args = (*command, '--context', context)
                        before = len(self.calls)
                        preview = self.invoke(*args)
                        self.assertEqual(preview.returncode, 0, preview.stderr)
                        data = json.loads(preview.stdout)
                        self.assertFalse(data['manual_selection_known'])
                        wrong = self.invoke(*args, '--yes', '--confirm', 'wrong')
                        self.assertNotEqual(wrong.returncode, 0)
                        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                        sent = self.invoke(*args, '--yes', '--confirm', data['confirm'], '--format', 'brief')
                        self.assertEqual(sent.returncode, 0, sent.stderr)
                        self.assertIn('acknowledged', sent.stdout)
                        method = 'POST' if command[0] == 'favorite-add' else 'DELETE'
                        route = f'/api/v1/users/self/favorites/{context}s' + (f'/{target}' if len(command) > 1 else '')
                        self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'], [(method, route)])
                        if command[0] == 'favorite-add':
                            current = self.invoke('favorites', '--context', context)
                            self.assertEqual([row['id'] for row in json.loads(current.stdout)], [int(target)])
                self.assertEqual(self.favorite_ids[context], set())
                reset = self.invoke('favorites', '--context', context)
                self.assertEqual(len(json.loads(reset.stdout)), 2)
        finally:
            type(self).favorite_ids = original


    def test_favorite_preview_rejects_truncated_inventory_and_changed_selection(self):
        original = {context: ids.copy() for context, ids in self.favorite_ids.items()}
        try:
            type(self).favorite_ids = {'course': set(), 'group': set()}
            command = ('favorite-add', '102')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            type(self).favorite_ids['course'].add(101)
            before = len(self.calls)
            changed = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn('Preview changed', changed.stderr)
            truncated = self.invoke(*command, '--max-pages', '1')
            self.assertNotEqual(truncated.returncode, 0)
            self.assertIn('Page limit', truncated.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        finally:
            type(self).favorite_ids = original
