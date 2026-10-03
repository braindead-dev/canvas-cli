"""Installed-CLI HTTPS regression tests for content workflows."""

import json
from pathlib import Path

from .fixture import CanvasFixture


class ContentE2E(CanvasFixture):
    def test_group_content_reads_have_explicit_namespace_and_no_course_module_fallback(self):
        before = len(self.calls)
        for resource in ('files', 'folders', 'pages', 'tabs'):
            result = self.invoke(resource, '11', '--context', 'group')
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data['group_id'], 11)
            self.assertTrue(data['complete_for_endpoint'])
            self.assertNotIn('synthetic-private', result.stdout)
            self.assertNotIn('Synthetic hidden group page', result.stdout)
            self.assertNotIn('Synthetic group page body', result.stdout)
            self.assertNotIn('Synthetic hidden tab', result.stdout)
            if resource != 'tabs':
                capped = self.invoke(resource, '11', '--context', 'group', '--max-pages', '1')
                self.assertNotEqual(capped.returncode, 0)
                self.assertEqual(capped.stdout, '')
                self.assertIn('Page limit', capped.stderr)
        for command in (('page', '11', 'welcome'), ('page', '11', '411'), ('front-page', '11')):
            result = self.invoke(*command, '--context', 'group')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Synthetic group page body', result.stdout)
            self.assertNotIn('synthetic-private-page-verifier', result.stdout)
        brief = self.invoke('files', '11', '--context', 'group', '--format', 'brief')
        self.assertIn('Group 11 files', brief.stdout)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        self.assertFalse(any('/courses/' in path for _, path in self.calls[before:]))
        before = len(self.calls)
        for resource in ('files', 'pages'):
            result = self.invoke(resource, '11', '--context', 'group', '--best-effort')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertIn('do not apply to group spaces', result.stderr)
        self.assertEqual(self.calls[before:], [])


    def test_context_root_and_storage_quota_reads_verify_own_user_and_folder_association(self):
        original_folder = self.group_folder.copy()
        original_quota = self.storage_quota.copy()
        try:
            for context, item in (('course', '101'), ('group', '11'), ('user', '7')):
                result = self.invoke('root-folder', item, '--context', context)
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)
                self.assertEqual(data['root_folder']['context_type'], context.title())
                self.assertEqual(data['root_folder']['context_id'], int(item))
                result = self.invoke('file-quota', item, '--context', context, '--format', 'brief')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('20 / 1000 bytes; 980 remaining', result.stdout)
            before = len(self.calls)
            result = self.invoke('file-quota', '8', '--context', 'user')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertEqual(self.calls[before:], [('GET', '/api/v1/users/self/profile')])
            self.group_folder['context_id'] = 12
            result = self.invoke('root-folder', '11', '--context', 'group')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertIn('outside the requested context', result.stderr)
            self.storage_quota['quota_used'] = -1
            result = self.invoke('file-quota', '11', '--context', 'group')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
        finally:
            type(self).group_folder = original_folder
            type(self).storage_quota = original_quota


    def test_folder_path_resolves_unicode_hierarchy_in_explicit_contexts(self):
        for kind, item, prefix in (('course', '101', '/api/v1/courses/101'),
                                   ('group', '11', '/api/v1/groups/11'), ('user', '7', '/api/v1/users/self')):
            command = ('folder-path', item, '--context', kind, '--path', 'Week 1/Résumé % notes')
            before = len(self.calls)
            result = self.invoke(*command)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual([row['name'] for row in data['folders'][1:]], ['Week 1', 'Résumé % notes'])
            self.assertEqual(data['folder_id'], data['folders'][-1]['id'])
            self.assertTrue(data['complete_for_path'])
            self.assertIn('materialize', data['note'])
            self.assertNotIn('synthetic-private-folder-detail', result.stdout)
            self.assertEqual(self.calls[-1], ('GET', prefix + '/folders/by_path/Week%201/R%C3%A9sum%C3%A9%20%25%20notes'))
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
            root = self.invoke('folder-path', item, '--context', kind)
            self.assertEqual(root.returncode, 0, root.stderr)
            self.assertEqual(len(json.loads(root.stdout)['folders']), 1)


    def test_folder_path_not_found_invalid_path_and_other_user_are_not_empty_success(self):
        result = self.invoke('folder-path', '11', '--context', 'group', '--path', 'Missing')
        self.assertEqual(result.returncode, 1)
        self.assertIn('404', result.stderr)
        self.assertEqual(self.calls[-2:], [('GET', '/api/v1/groups/11'),
                                          ('GET', '/api/v1/groups/11/folders/by_path/Missing')])
        before = len(self.calls)
        for path in ('/Week 1', '../Readings', 'Week 1//Readings', 'Week 1\\Readings'):
            result = self.invoke('folder-path', '11', '--context', 'group', '--path', path)
            self.assertEqual(result.returncode, 1)
        self.assertEqual(self.calls[before:], [])
        result = self.invoke('folder-path', '8', '--context', 'user', '--path', 'Readings')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.calls[before:], [('GET', '/api/v1/users/self/profile')])


    def test_group_file_download_is_scoped_private_and_credential_free_at_storage(self):
        original = self.group_file.copy()
        original_page = self.group_page.copy()
        try:
            destination = Path(self.tmp.name) / 'group-content-download.txt'
            before = len(self.calls)
            result = self.invoke('download', '11', '891', '--context', 'group', '--output', str(destination))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(destination.read_bytes(), b'Synthetic file bytes')
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertIsNone(self.storage_download_auth)
            self.assertNotIn('/storage/', result.stdout)
            self.assertEqual(self.calls[before:], [('GET', '/api/v1/groups/11'),
                                                  ('GET', '/api/v1/groups/11/files/891'),
                                                  ('GET', '/storage/synthetic-file')])
            for flag in ('locked_for_user', 'hidden_for_user'):
                self.group_file[flag] = True
                before = len(self.calls)
                other = Path(self.tmp.name) / f'group-{flag}.txt'
                result = self.invoke('download', '11', '891', '--context', 'group', '--output', str(other))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertFalse(other.exists())
                self.assertFalse(any('/storage/' in path for _, path in self.calls[before:]))
                self.group_file[flag] = False
            self.group_page['published'] = False
            result = self.invoke('page', '11', 'welcome', '--context', 'group')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
        finally:
            type(self).group_file = original
            type(self).group_page = original_page


    def test_sync_over_tls_separates_viewers_and_preserves_legacy_files(self):
        directory = Path(self.tmp.name) / 'account-separated-sync'
        directory.mkdir()
        legacy = directory / 'legacy-course-101-999999.json'
        legacy.write_text('Synthetic legacy file is not read or rewritten')
        original = self.own_profile.copy()
        before = len(self.calls)
        try:
            first = self.invoke('sync', '101', '--directory', str(directory))
            self.assertEqual(first.returncode, 0, first.stderr)
            initial = json.loads(first.stdout)
            type(self).own_profile = {**original, 'id': 8}
            other = self.invoke('sync', '101', '--directory', str(directory))
            self.assertEqual(other.returncode, 0, other.stderr)
            other_data = json.loads(other.stdout)
            self.assertTrue(other_data['baseline'])
            self.assertIn('-user-8-course-101-', other_data['saved'])
            self.assertEqual(json.loads(Path(other_data['saved']).read_text())['viewer_user_id'], 8)
            type(self).own_profile = original
            again = self.invoke('sync', '101', '--directory', str(directory))
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(json.loads(again.stdout)['previous'], initial['saved'])
            self.assertEqual(legacy.read_text(), 'Synthetic legacy file is not read or rewritten')
            comparison = self.invoke('snapshot-diff', initial['saved'], other_data['saved'])
            self.assertEqual(comparison.returncode, 1)
            self.assertIn('different signed-in viewers', comparison.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        finally:
            type(self).own_profile = original


    def test_sync_over_tls_rejects_account_switch_during_capture_without_new_snapshot(self):
        directory = Path(self.tmp.name) / 'switched-account-sync'
        original = self.own_profile.copy()
        try:
            baseline = self.invoke('sync', '101', '--directory', str(directory))
            self.assertEqual(baseline.returncode, 0, baseline.stderr)
            saved = json.loads(baseline.stdout)['saved']
            prior_bytes = Path(saved).read_bytes()
            type(self).sync_switch_viewer = True
            failed = self.invoke('sync', '101', '--directory', str(directory))
            self.assertEqual(failed.returncode, 1)
            self.assertIn('account changed during capture', failed.stderr)
            self.assertNotIn('Synthetic page', failed.stdout + failed.stderr)
            self.assertEqual([str(path.resolve()) for path in directory.glob('*.json')], [saved])
            self.assertEqual(Path(saved).read_bytes(), prior_bytes)
        finally:
            type(self).own_profile = original
            type(self).sync_switch_viewer = False


    def test_bulk_own_submission_page_limit_and_foreign_owner_or_history_do_not_emit_partial_content(self):
        limited = self.invoke('--max-pages', '1', 'submissions', '101')
        self.assertNotEqual(limited.returncode, 0)
        self.assertEqual(limited.stdout, '')
        saved = type(self).student_submissions
        try:
            for row in ({**saved[0], 'user_id': 8},
                        {**saved[0], 'submission_history': [{'user_id': 8, 'body': 'Synthetic foreign work'}]}):
                type(self).student_submissions = [row]
                refused = self.invoke('submissions', '101', '--include-history', '--include-content')
                self.assertNotEqual(refused.returncode, 0)
                self.assertEqual(refused.stdout, '')
                self.assertNotIn('Synthetic foreign work', refused.stderr)
            type(self).student_submissions = [{**saved[0], 'assignment_visible': False}]
            withheld = self.invoke('submissions', '101', '--include-history', '--include-comments', '--include-content')
            self.assertEqual(withheld.returncode, 0, withheld.stderr)
            self.assertIn('content_withheld', withheld.stdout)
            self.assertNotIn('Synthetic private', withheld.stdout)
            self.assertNotIn('Synthetic first attempt', withheld.stdout)
        finally:
            type(self).student_submissions = saved


    def test_missing_work_page_limit_invalid_timezone_and_wrong_account_marker_fail_closed(self):
        before = len(self.calls)
        bad_zone = self.invoke('missing', '--timezone', 'No/Such_Zone')
        self.assertNotEqual(bad_zone.returncode, 0)
        self.assertEqual(len(self.calls), before)
        limited = self.invoke('--max-pages', '1', 'missing')
        self.assertNotEqual(limited.returncode, 0)
        self.assertNotIn('missing_assignments', limited.stdout)
        saved = type(self).missing_assignments
        try:
            type(self).missing_assignments = [{**saved[0], 'planner_override': {
                **saved[0]['planner_override'], 'user_id': 8}}]
            wrong = self.invoke('missing', '--include-planner')
            self.assertNotEqual(wrong.returncode, 0)
            self.assertIn('outside this own assignment', wrong.stderr)
            type(self).missing_assignments = []
            empty = self.invoke('missing')
            self.assertEqual(empty.returncode, 0, empty.stderr)
            self.assertEqual(json.loads(empty.stdout)['missing_assignments'], [])
            self.assertFalse(json.loads(empty.stdout)['complete_coursework_inventory'])
        finally:
            type(self).missing_assignments = saved


    def test_entry_list_page_limit_fails_without_silent_partial_result(self):
        result = self.invoke('entry', '101', '202', '301', '--max-pages', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Page limit reached', result.stderr)
        self.assertEqual(result.stdout, '')


    def test_personal_file_organization_and_subfolder_creation_over_tls(self):
        original_file, original_children = self.personal_file.copy(), self.personal_children.copy()
        try:
            root = self.invoke('my-root')
            self.assertEqual(root.returncode, 0, root.stderr)
            self.assertEqual(json.loads(root.stdout)['id'], 91)
            listing = self.invoke('my-folders')
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertEqual([row['id'] for row in json.loads(listing.stdout)], [91, 92])
            commands = [('my-folder-create', '92', '--name', 'Synthetic child'),
                        ('my-file-copy', '881', '--folder', '92'),
                        ('my-file-edit', '881', '--name', 'revised.txt', '--folder', '92'),
                        ('my-file-delete', '881', '--permanent')]
            for command in commands:
                with self.subTest(command=command):
                    before = len(self.calls)
                    preview = self.invoke(*command)
                    self.assertEqual(preview.returncode, 0, preview.stderr)
                    data = json.loads(preview.stdout)
                    self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                    denied = self.invoke(*command, '--yes', '--confirm', 'wrong')
                    self.assertNotEqual(denied.returncode, 0)
                    self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                    sent = self.invoke(*command, '--yes', '--confirm', data['confirm'], '--format', 'brief')
                    self.assertEqual(sent.returncode, 0, sent.stderr)
                    self.assertEqual(self.personal_write, data['body'] or {})
                    self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                                     [(data['method'], data['route'])])
                    if command[0] == 'my-file-copy': self.assertEqual(self.personal_file, original_file)
                    if command[0] == 'my-file-edit':
                        reread = self.invoke('file-info', '881')
                        self.assertEqual(json.loads(reread.stdout)['display_name'], 'revised.txt')
                        self.assertEqual(json.loads(reread.stdout)['folder_id'], 92)
            deleted = self.invoke('file-info', '881')
            self.assertNotEqual(deleted.returncode, 0)
            self.assertIn('HTTP 404', deleted.stderr)
            self.assertEqual(self.personal_children[0]['parent_folder_id'], 92)
        finally:
            self.__class__.personal_file, self.__class__.personal_children = original_file, original_children


    def test_personal_file_delete_requires_ack_and_foreign_destinations_are_refused(self):
        original = self.personal_destination.copy()
        try:
            before = len(self.calls)
            result = self.invoke('my-file-delete', '881')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('--permanent', result.stderr)
            self.assertEqual(len(self.calls), before)
            self.__class__.personal_destination = {**original, 'context_type': 'Course'}
            result = self.invoke('my-file-copy', '881', '--folder', '92')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('own accessible personal', result.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        finally:
            self.__class__.personal_destination = original


    def test_personal_folder_edit_move_and_empty_delete_are_stateful_over_tls(self):
        original = self.personal_children.copy()
        self.__class__.personal_children = [{**self.personal_destination, 'id': 94,
                                           'name': 'Synthetic child', 'parent_folder_id': 92}]
        try:
            commands = [('my-folder-edit', '94', '--name', 'Revised child', '--parent', '91'),
                        ('my-folder-delete', '94')]
            for command in commands:
                with self.subTest(command=command):
                    before = len(self.calls)
                    preview = self.invoke(*command)
                    self.assertEqual(preview.returncode, 0, preview.stderr)
                    data = json.loads(preview.stdout)
                    self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                    sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
                    self.assertEqual(sent.returncode, 0, sent.stderr)
                    self.assertEqual(self.folder_write, data['body'] or {})
                    self.assertNotIn('force', self.folder_write)
                    self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                                     [(data['method'], '/api/v1/folders/94')])
                    read = self.invoke('folder', '94')
                    if command[0] == 'my-folder-edit':
                        self.assertEqual(read.returncode, 0, read.stderr)
                        self.assertEqual(json.loads(read.stdout)['name'], 'Revised child')
                        self.assertEqual(json.loads(read.stdout)['parent_folder_id'], 91)
                    else:
                        self.assertNotEqual(read.returncode, 0)
                        self.assertIn('HTTP 404', read.stderr)
        finally:
            self.__class__.personal_children = original


    def test_async_export_read_preview_create_and_private_download(self):
        before = len(self.calls)
        index = self.invoke('exports', '105')
        self.assertEqual(index.returncode, 0, index.stderr)
        self.assertEqual([job['id'] for job in json.loads(index.stdout)], [51, 52])
        self.assertNotIn('signature', index.stdout)
        status = self.invoke('export-status', '105', '51', '--progress', '--format', 'brief')
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn('45%', status.stdout)
        self.assertIn('exporting', status.stdout)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        command = ('export-create', '105', '--type', 'zip', '--select', 'files', '777')
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertTrue(data['dry_run'])
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(json.loads(sent.stdout)['export']['workflow_state'], 'exporting')
        self.assertEqual([c for c in self.calls[before:] if c[0] == 'POST'],
                         [('POST', '/api/v1/courses/105/content_exports')])
        output = Path(self.tmp.name) / 'synthetic-export.zip'
        result = self.invoke('export-download', '105', '52', '--output', str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output.read_bytes(), b'Synthetic file bytes')
        self.assertIsNone(self.storage_download_auth)
        self.assertNotIn('/storage/', result.stdout)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        pending_output = Path(self.tmp.name) / 'pending-export.zip'
        result = self.invoke('export-download', '105', '51', '--output', str(pending_output))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(pending_output.exists())


    def test_deadlines_brief_and_linked_files_without_files_list(self):
        due = self.invoke('--format', 'brief', 'deadlines')
        self.assertEqual(due.returncode, 0, due.stderr)
        self.assertIn('88  Synthetic course: Synthetic paper', due.stdout)
        self.assertNotIn('unavailable', due.stdout)
        listing = self.invoke('files', '101')
        self.assertEqual(listing.returncode, 1)
        fallback = self.invoke('files', '101', '--best-effort', '--quick')
        self.assertEqual(fallback.returncode, 0, fallback.stderr)
        self.assertFalse(json.loads(fallback.stdout)['complete'])
        self.assertEqual(json.loads(fallback.stdout)['source'], 'linked-content')
        self.assertEqual(json.loads(fallback.stdout)['files'][0]['id'], 7)
        linked = self.invoke('linked-files', '101')
        self.assertEqual(linked.returncode, 0, linked.stderr)
        self.assertEqual(json.loads(linked.stdout)['files'][0]['display_name'], 'synthetic-syllabus.pdf')
        self.assertFalse(json.loads(linked.stdout)['files'][0]['downloadable'])
        self.assertIn('announcement: Synthetic announcement',
                      json.loads(linked.stdout)['files'][0]['sources'])
        self.assertIn('discussion prompt: Synthetic discussion prompt',
                      json.loads(linked.stdout)['files'][0]['sources'])
        brief = self.invoke('--format', 'brief', 'linked-files', '101')
        self.assertIn('not downloadable', brief.stdout)
        quick = self.invoke('linked-files', '101', '--quick')
        self.assertEqual(quick.returncode, 0, quick.stderr)
        self.assertTrue(json.loads(quick.stdout)['files'][0]['metadata_not_checked'])


    def test_batch_download_needs_matching_preview_and_excludes_bearer_from_storage(self):
        directory = Path(self.tmp.name) / 'synthetic-downloads'
        directory.mkdir(exist_ok=True)
        command = ('download-linked', '103', '--directory', str(directory))
        before = len(self.calls)
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        plan = json.loads(preview.stdout)
        self.assertTrue(plan['dry_run'])
        self.assertEqual(len(plan['files']), 1)
        self.assertFalse(list(directory.iterdir()))
        chosen = self.invoke(*command, '--file', '8')
        self.assertEqual(chosen.returncode, 0, chosen.stderr)
        self.assertEqual(json.loads(chosen.stdout)['selected_file_ids'], ['8'])
        unknown = self.invoke(*command, '--file', '999')
        self.assertEqual(unknown.returncode, 1)
        self.assertIn('not discovered', unknown.stderr)
        missing = self.invoke(*command, '--yes')
        self.assertEqual(missing.returncode, 1)
        self.assertIn('--confirm', missing.stderr)
        wrong = self.invoke(*command, '--yes', '--confirm', 'wrong')
        self.assertEqual(wrong.returncode, 1)
        self.assertFalse(list(directory.iterdir()))
        saved = self.invoke(*command, '--yes', '--confirm', plan['confirm'])
        self.assertEqual(saved.returncode, 0, saved.stderr)
        self.assertEqual((directory / '8-synthetic-reading.pdf').read_bytes(),
                         b'Synthetic file bytes')
        self.assertIsNone(self.storage_download_auth)
        self.assertEqual([call for call in self.calls[before:]
                          if call[1] == '/storage/synthetic-file'],
                         [('GET', '/storage/synthetic-file')])


    def test_file_title_search_has_partial_linked_fallback(self):
        result = self.invoke('find', '103', '--query', 'reading', '--area', 'files')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data['complete'])
        self.assertEqual(data['coverage']['files'], 'linked_files_only')
        self.assertEqual(data['results'][0]['id'], 8)


    def test_single_download_refuses_short_success_response(self):
        destination = Path(self.tmp.name) / 'synthetic-truncated.pdf'
        result = self.invoke('download', '103', '9', '--output', str(destination))
        self.assertEqual(result.returncode, 1)
        self.assertIn('differs from Canvas metadata', result.stderr)
        self.assertFalse(destination.exists())


    def test_new_read_commands_over_tls(self):
        before = len(self.calls)
        commands = [
            (['grades', '101'], lambda d: d[0]['grades']['current_score'] == 95),
            (['folders', '101'], lambda d: d[0]['id'] == 3),
            (['folder-files', '3'], lambda d: d[0]['id'] == 4),
            (['sections', '101'], lambda d: d[0]['id'] == 5),
            (['outline', '101'], lambda d: d[0]['items'][0]['title'] == 'Welcome'),
            (['calendar', '--start', '2026-09-25', '--end', '2026-09-30', '--course', '101'],
             lambda d: d[0]['id'] == 10),
        ]
        for command, check in commands:
            with self.subTest(command=command):
                result = self.invoke(*command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(check(json.loads(result.stdout)))
        outline = self.invoke('--format', 'brief', 'outline', '101')
        self.assertIn('Week 1\n  9  Welcome', outline.stdout)
        grades = self.invoke('--format', 'brief', 'grades', '101')
        self.assertIn('Course 101: 95', grades.stdout)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))


    def test_snapshot_over_tls_is_private_and_read_only(self):
        destination = Path(self.tmp.name) / 'course-snapshot.json'
        before = len(self.calls)
        result = self.invoke('snapshot', '101', '--output', str(destination))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['complete'])
        snapshot = json.loads(destination.read_text())
        self.assertEqual(snapshot['pages'][0]['body'], '<p>Synthetic page</p>')
        self.assertEqual(snapshot['announcements'][0]['id'], 22)
        self.assertEqual(snapshot['discussions'][0]['title'], 'Synthetic discussion prompt')
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        repeated = self.invoke('snapshot', '101', '--output', str(destination))
        self.assertEqual(repeated.returncode, 1)


    def test_snapshot_can_index_linked_file_metadata_without_binaries(self):
        destination = Path(self.tmp.name) / 'course-snapshot-files.json'
        before = len(self.calls)
        result = self.invoke('snapshot', '101', '--output', str(destination),
                             '--include-linked-files')
        self.assertEqual(result.returncode, 0, result.stderr)
        snapshot = json.loads(destination.read_text())
        self.assertEqual(snapshot['linked_file_scope'], 'readable-references-only')
        self.assertEqual(snapshot['linked_files'][0]['id'], 7)
        self.assertNotIn('url', snapshot['linked_files'][0])
        self.assertFalse(any(path == '/storage/synthetic-file'
                             for _, path in self.calls[before:]))


    def test_page_index_fallback_over_tls_is_explicitly_partial(self):
        before = len(self.calls)
        raw = self.invoke('pages', '102')
        self.assertEqual(raw.returncode, 1)
        fallback = self.invoke('pages', '102', '--best-effort')
        self.assertEqual(fallback.returncode, 0, fallback.stderr)
        result = json.loads(fallback.stdout)
        self.assertFalse(result['complete'])
        self.assertEqual(result['source'], 'module-pages')
        self.assertEqual([page['url'] for page in result['pages']], ['welcome'])
        self.assertNotIn('Should not be printed', fallback.stdout)
        self.assertNotIn('/pages/hidden', str(self.calls[before:]))
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))


    def test_page_title_search_falls_back_over_tls(self):
        before = len(self.calls)
        result = self.invoke('find', '102', '--query', 'welcome', '--area', 'pages')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data['complete'])
        self.assertEqual(data['coverage']['pages'], 'module_pages_only')
        self.assertEqual([row['id'] for row in data['results']], ['welcome'])
        self.assertNotIn('Should not be printed', result.stdout)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))


    def test_course_navigation_over_tls(self):
        before = len(self.calls)
        tabs = self.invoke('tabs', '101')
        self.assertEqual(tabs.returncode, 0, tabs.stderr)
        self.assertEqual(json.loads(tabs.stdout)[0]['id'], 'home')
        front = self.invoke('front-page', '101')
        self.assertEqual(front.returncode, 0, front.stderr)
        self.assertEqual(json.loads(front.stdout)['url'], 'welcome')
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))


    def test_private_sync_over_tls_keeps_snapshots_out_of_stdout(self):
        directory = Path(self.tmp.name) / 'private-sync'
        before = len(self.calls)
        first = self.invoke('sync', '101', '--directory', str(directory))
        self.assertEqual(first.returncode, 0, first.stderr)
        baseline = json.loads(first.stdout)
        self.assertTrue(baseline['baseline'])
        second = self.invoke('sync', '101', '--directory', str(directory))
        self.assertEqual(second.returncode, 0, second.stderr)
        changed = json.loads(second.stdout)
        self.assertFalse(changed['baseline'])
        self.assertEqual(changed['previous'], baseline['saved'])
        self.assertNotIn('<p>Synthetic page</p>', second.stdout)
        self.assertEqual(len(list(directory.glob('*.json'))), 2)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))


    def test_snapshot_diff_brief_runs_offline_and_never_prints_private_field_values(self):
        directory = Path(self.tmp.name) / 'offline-brief-diff'
        directory.mkdir()
        old = {'schema_version': 1, 'origin': 'https://canvas.example.edu', 'course_id': 12,
               'viewer_user_id': 7, 'captured_at': '2026-10-01T00:00:00Z',
               'course': {}, 'assignments': [{'id': 1, 'name': 'Synthetic paper',
                                             'description': 'Synthetic private old prompt'}],
               'modules': [], 'pages': [], 'announcements': [], 'discussions': [],
               'unavailable': {'pages': 'Synthetic denied'}}
        new = {**old, 'captured_at': '2026-10-02T00:00:00Z',
               'assignments': [{**old['assignments'][0], 'description': 'Synthetic private new prompt'}]}
        older, newer = directory / 'old.json', directory / 'new.json'
        older.write_text(json.dumps(old))
        newer.write_text(json.dumps(new))
        before = len(self.calls)
        result = self.invoke('snapshot-diff', str(older), str(newer), '--format', 'brief', token='invalid-secret')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('viewer 7', result.stdout)
        self.assertIn('assignments changed: Synthetic paper (1) [description]', result.stdout)
        self.assertIn('Unseen changes remain unknown', result.stdout)
        self.assertNotIn('Synthetic private', result.stdout + result.stderr)
        self.assertEqual(self.calls[before:], [])
        legacy = {key: value for key, value in old.items() if key != 'viewer_user_id'}
        older.write_text(json.dumps(legacy))
        result = self.invoke('snapshot-diff', str(older), str(newer), '--format', 'brief', token='invalid-secret')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('viewer unverified', result.stdout)
        self.assertEqual(self.calls[before:], [])


    def test_personal_upload_three_step_tls_and_no_storage_token(self):
        source = Path(self.tmp.name) / 'synthetic.txt'
        source.write_text('Synthetic upload bytes')
        command = ('upload-personal', '--file', str(source))
        before = len(self.calls)
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertTrue(data['dry_run'])
        self.assertEqual(self.calls[before:], [('GET', '/api/v1/users/self/profile')])
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(json.loads(sent.stdout)['uploaded_file_id'], 777)
        self.assertEqual(self.upload_initial['on_duplicate'], 'rename')
        self.assertIsNone(self.storage_auth)
        self.assertIn('multipart/form-data', self.storage_type)
        self.assertIn(b'synthetic-key', self.storage_body)
        self.assertIn(b'Synthetic upload bytes', self.storage_body)
        self.assertLess(self.storage_body.index(b'synthetic-key'),
                        self.storage_body.index(b'Synthetic upload bytes'))
        self.assertEqual(self.calls[-3:], [
            ('POST', '/api/v1/users/self/files'), ('POST', '/storage/upload'),
            ('GET', '/api/v1/files/777/create_success')])


    def test_scoped_uploads_verify_shared_contexts_and_own_folder_end_to_end(self):
        original = self.upload_scoped_record
        source = Path(self.tmp.name) / 'shared.txt'
        source.write_text('Synthetic shared file')
        commands = [
            (('upload-context', '101', '--context', 'course'), '/api/v1/courses/101', 96),
            (('upload-context', '11', '--context', 'group', '--folder', '95'), '/api/v1/groups/11', 95),
            (('upload-personal', '--folder', '92'), '/api/v1/users/self', 92)]
        try:
            for prefix, route, folder_id in commands:
                with self.subTest(command=prefix):
                    command = (*prefix, '--file', str(source))
                    before = len(self.calls)
                    preview = self.invoke(*command)
                    self.assertEqual(preview.returncode, 0, preview.stderr)
                    data = json.loads(preview.stdout)
                    self.assertEqual(data['init_route'], route + '/files')
                    self.assertEqual(data['destination']['folder']['id'], folder_id)
                    self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                    sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
                    self.assertEqual(sent.returncode, 0, sent.stderr)
                    self.assertEqual(json.loads(sent.stdout)['uploaded_file_id'], 777)
                    self.assertIn('no assignment submitted', json.loads(sent.stdout)['note'])
                    self.assertNotIn('synthetic-private-upload', sent.stdout + sent.stderr)
                    self.assertEqual(self.upload_initial['parent_folder_id'], folder_id)
                    self.assertEqual(self.upload_initial['on_duplicate'], 'rename')
                    self.assertIsNone(self.storage_auth)
                    self.assertIn(b'Synthetic shared file', self.storage_body)
                    self.assertEqual(self.calls[-4:], [('POST', route + '/files'), ('POST', '/storage/upload'),
                                                      ('GET', '/api/v1/files/777/create_success'),
                                                      ('GET', route + '/files/777')])
        finally:
            type(self).upload_scoped_record = original


    def test_scoped_upload_stale_and_foreign_folder_previews_never_write(self):
        original = self.group_folder.copy()
        source = Path(self.tmp.name) / 'scoped-stale.txt'
        source.write_text('Synthetic scoped file')
        command = ('upload-context', '11', '--context', 'group', '--file', str(source))
        try:
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.group_folder['name'] = 'Synthetic renamed folder'
            before = len(self.calls)
            sent = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertEqual(sent.returncode, 1)
            self.assertIn('Preview changed', sent.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
            self.group_folder['context_type'] = 'User'
            refused = self.invoke(*command)
            self.assertEqual(refused.returncode, 1)
            self.assertIn('outside the requested context', refused.stderr)
            before = len(self.calls)
            invalid = self.invoke('upload-context', '11', '--file', str(source))
            self.assertEqual(invalid.returncode, 2)
            self.assertEqual(self.calls[before:], [])
        finally:
            type(self).group_folder = original


    def test_scoped_upload_denial_and_ambiguous_confirmation_never_retry(self):
        original = self.upload_scoped_record
        source = Path(self.tmp.name) / 'scoped-uncertain.txt'
        source.write_text('Synthetic uncertain file')
        command = ('upload-context', '11', '--context', 'group', '--file', str(source))
        try:
            for phase in ('denied', 'confirmation', 'readback'):
                preview = self.invoke(*command)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                if phase == 'denied':
                    type(self).upload_denied = True
                elif phase == 'confirmation':
                    type(self).upload_ack_patch = {'folder_id': 96}
                else:
                    type(self).upload_readback_patch = {'size': 1}
                before = len(self.calls)
                sent = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
                self.assertEqual(sent.returncode, 1)
                posts = [route for method, route in self.calls[before:] if method == 'POST']
                self.assertEqual(posts, ['/api/v1/groups/11/files'] if phase == 'denied' else
                                 ['/api/v1/groups/11/files', '/storage/upload'])
                self.assertIn('denied access' if phase == 'denied' else 'may have succeeded', sent.stderr)
                self.assertNotIn('synthetic-private-upload', sent.stderr + sent.stdout)
                type(self).upload_denied = False
                type(self).upload_ack_patch = {}
                type(self).upload_readback_patch = {}
        finally:
            type(self).upload_scoped_record = original
            type(self).upload_denied = False
            type(self).upload_ack_patch = {}
            type(self).upload_readback_patch = {}


    def test_assignment_upload_is_not_assignment_submission(self):
        source = Path(self.tmp.name) / 'synthetic.txt'
        source.write_text('Synthetic upload bytes')
        command = ('upload-assignment-file', '101', '89', '--file', str(source))
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertTrue(data['dry_run'])
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertIn('not submitted', json.loads(sent.stdout)['note'])
        self.assertNotIn('on_duplicate', self.upload_initial)
        self.assertNotIn(('POST', '/api/v1/courses/101/assignments/89/submissions'),
                         self.calls)


    def test_submit_uploaded_file_preview_and_confirm(self):
        command = ('submit-file', '101', '89', '777')
        before = len(self.calls)
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertTrue(data['dry_run'])
        self.assertEqual(data['file']['name'], 'synthetic.txt')
        self.assertEqual(self.calls[before:], [
            ('GET', '/api/v1/users/self/profile'),
            ('GET', '/api/v1/courses/101/assignments/89'), ('GET', '/api/v1/files/777')])
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(self.calls[-3:], [
            ('GET', '/api/v1/courses/101/assignments/89'), ('GET', '/api/v1/files/777'),
            ('POST', '/api/v1/courses/101/assignments/89/submissions')])


    def test_multiple_uploaded_files_are_submitted_in_one_confirmed_request(self):
        command = ('submit-file', '101', '89', '777', '778')
        before = len(self.calls)
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertEqual(data['body']['submission']['file_ids'], [777, 778])
        self.assertEqual(len(data['files']), 2)
        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(json.loads(sent.stdout)['submission']['file_ids'], [777, 778])
        self.assertEqual([c for c in self.calls[before:] if c[0] == 'POST'],
                         [('POST', '/api/v1/courses/101/assignments/89/submissions')])
        before = len(self.calls)
        duplicate = self.invoke('submit-file', '101', '89', '777', '0777')
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertEqual(len(self.calls), before)


    def test_personal_file_discovery_and_metadata(self):
        found = self.invoke('my-files', '--search', 'synthetic')
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertEqual(json.loads(found.stdout)[0]['id'], 777)
        info = self.invoke('file-info', '777')
        self.assertEqual(info.returncode, 0, info.stderr)
        self.assertEqual(json.loads(info.stdout)['size'], 22)


    def test_course_doctor_reports_reachability_without_content(self):
        result = self.invoke('doctor', '101')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        statuses = {item['area']: item['status'] for item in data['probes']}
        self.assertEqual(statuses['files'], 'denied_403')
        self.assertEqual(statuses['pages'], 'not_found_404')
        self.assertEqual(statuses['assignments'], 'readable')
        self.assertNotIn('Synthetic course', result.stdout)


    def test_offline_snapshot_search_brief(self):
        source = Path(self.tmp.name) / 'synthetic-search.json'
        source.write_text(json.dumps({
            'schema_version': 1, 'course_id': 101, 'complete': False,
            'course': {'syllabus_body': '<p>Read about synthetic biology.</p>'},
            'assignments': [], 'announcements': [], 'modules': [], 'pages': [],
        }))
        result = self.invoke('--format', 'brief', 'snapshot-search', str(source),
                             '--query', 'synthetic biology')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('1 match(es)', result.stdout)
        self.assertIn('Snapshot incomplete', result.stdout)
        self.assertIn('Read about synthetic biology.', result.stdout)


    def test_live_title_find_single_area(self):
        result = self.invoke('--format', 'brief', 'find', '101', '--query', 'Synthetic',
                             '--area', 'assignments')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('1 result(s) in course 101', result.stdout)
        self.assertIn('assignment 88: Synthetic paper', result.stdout)
