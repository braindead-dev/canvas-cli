"""Installed-CLI HTTPS regression tests for communication workflows."""

import json
from pathlib import Path

from .fixture import CanvasFixture


class CommunicationE2E(CanvasFixture):
    def test_discussion_rating_reads_return_own_votes_without_cached_bodies_or_read_writes(self):
        before = len(self.calls)
        result = self.invoke('topic-ratings', '101', '202')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['own_entry_ratings'], type(self).own_entry_ratings)
        self.assertEqual(data['snapshot_entry_ids'], [301, 302, 303])
        self.assertNotIn('Synthetic cached peer body', result.stdout)
        self.assertNotIn('Synthetic private participant', result.stdout)
        self.assertEqual(self.calls[before:], [
            ('GET', '/api/v1/users/self/profile'), ('GET', '/api/v1/courses/101/discussion_topics/202'),
            ('GET', '/api/v1/courses/101/discussion_topics/202/view?include_new_entries=1')])
        group = self.invoke('--format', 'brief', 'topic-ratings', '11', '203', '--context', 'group')
        self.assertEqual(group.returncode, 0, group.stderr)
        self.assertIn('Own ratings:', group.stdout)


    def test_like_and_unlike_course_and_group_use_account_bound_preview_and_leave_content_untouched(self):
        saved = type(self).own_entry_ratings.copy()
        entry = type(self).entry.copy()
        topic_state = type(self).topic_state.copy()
        try:
            for context_id, topic_id, context, value in (('101', '202', 'course', '0'), ('11', '203', 'group', '1')):
                command = ('entry-rate', context_id, topic_id, '301', '--rating', value, '--context', context)
                preview = self.invoke(*command)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                data = json.loads(preview.stdout)
                self.assertEqual(data['method'], 'POST')
                self.assertEqual(data['body'], {'rating': int(value)})
                self.assertNotIn(entry['message'], preview.stdout)
                before = len(self.calls)
                sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
                self.assertEqual(sent.returncode, 0, sent.stderr)
                self.assertEqual(json.loads(sent.stdout)['discussion_rating']['rating'], int(value))
                self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                                 [('POST', f'/api/v1/{context}s/{context_id}/discussion_topics/{topic_id}/entries/301/rating')])
                self.assertEqual(type(self).rating_write, {'rating': int(value)})
                self.assertEqual(type(self).entry, entry)
                self.assertEqual(type(self).topic_state, topic_state)
        finally:
            type(self).own_entry_ratings = saved


    def test_rating_changed_body_or_own_vote_invalidates_preview_and_pagination_limit_blocks_write(self):
        saved = type(self).own_entry_ratings.copy()
        entry = type(self).entry.copy()
        try:
            command = ('entry-rate', '101', '202', '301', '--rating', '0')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            digest = json.loads(preview.stdout)['confirm']
            for alteration in ('vote', 'body'):
                if alteration == 'vote':
                    type(self).own_entry_ratings = {}
                else:
                    type(self).own_entry_ratings = saved.copy()
                    type(self).entry = {**entry, 'message': 'Synthetic changed body, same timestamp'}
                before = len(self.calls)
                refused = self.invoke(*command, '--yes', '--confirm', digest)
                self.assertNotEqual(refused.returncode, 0)
                self.assertIn('Preview changed', refused.stderr)
                self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
            limited = self.invoke('--max-pages', '1', *command)
            self.assertNotEqual(limited.returncode, 0)
            self.assertIn('Page limit reached', limited.stderr)
        finally:
            type(self).own_entry_ratings = saved
            type(self).entry = entry


    def test_rating_post_first_disabled_and_ambiguous_ack_fail_without_retries_or_body_echo(self):
        saved_topic = type(self).topic_state.copy()
        saved_ratings = type(self).own_entry_ratings.copy()
        command = ('entry-rate', '101', '202', '301', '--rating', '0')
        try:
            for flags in ({'allow_rating': False}, {'require_initial_post': True, 'user_can_see_posts': False}):
                type(self).topic_state = {**saved_topic, **flags}
                before = len(self.calls)
                refused = self.invoke(*command)
                self.assertNotEqual(refused.returncode, 0)
                self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                self.assertFalse(any('/view?' in route or '/entry_list?' in route for _, route in self.calls[before:]))
            type(self).topic_state = saved_topic.copy()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            type(self).rating_ack_status = 200
            before = len(self.calls)
            ambiguous = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(ambiguous.returncode, 0)
            self.assertIn('empty 204 acknowledgement', ambiguous.stderr)
            self.assertNotIn('Synthetic response not for output', ambiguous.stderr + ambiguous.stdout)
            self.assertEqual(sum(method == 'POST' for method, _ in self.calls[before:]), 1)
        finally:
            type(self).topic_state = saved_topic
            type(self).own_entry_ratings = saved_ratings
            type(self).rating_ack_status = 204


    def test_activity_reads_paginate_without_marking_read_and_gate_cached_discussion_entries(self):
        original = self.topic_state.copy()
        try:
            type(self).topic_state.update({'require_initial_post': True, 'user_can_see_posts': False})
            before = len(self.calls)
            listing = self.invoke('activity')
            self.assertEqual(listing.returncode, 0, listing.stderr)
            data = json.loads(listing.stdout)
            self.assertEqual([row['id'] for row in data['activity']], [71, 72, 73])
            self.assertNotIn('Synthetic private body', listing.stdout)
            self.assertFalse(data['complete_coursework_inventory'])
            notices = self.invoke('activity', '--type', 'AssessmentRequest', '--format', 'brief')
            self.assertEqual(notices.returncode, 0, notices.stderr)
            self.assertIn('72 | AssessmentRequest', notices.stdout)
            self.assertNotIn('71 |', notices.stdout)
            content = self.invoke('activity', '--active', '--include-content')
            self.assertEqual(content.returncode, 0, content.stderr)
            self.assertIn('Synthetic current prompt', content.stdout)
            self.assertNotIn('Synthetic cached peer entry', content.stdout)
            self.assertNotIn('Synthetic private body', content.stdout)
            self.assertIn('entries_withheld', content.stdout)
            course = self.invoke('activity', '--course', '101')
            self.assertEqual(course.returncode, 0, course.stderr)
            self.assertEqual([row['id'] for row in json.loads(course.stdout)['activity']], [72, 73])
            counts = self.invoke('activity-summary', '--course', '101')
            self.assertEqual(counts.returncode, 0, counts.stderr)
            self.assertEqual(sum(row['count'] for row in json.loads(counts.stdout)['activity_summary']), 2)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
            self.assertEqual([row['read_state'] for row in self.activity_items], [False, False, True])
        finally:
            type(self).topic_state = original


    def test_activity_hiding_is_revision_bound_and_does_not_touch_underlying_messages(self):
        original_hidden = self.activity_hidden_ids.copy()
        original_items = [row.copy() for row in self.activity_items]
        try:
            command = ('activity-dismiss', '71')
            before = len(self.calls)
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            data = json.loads(preview.stdout)
            self.assertNotIn('Synthetic private body', preview.stdout)
            type(self).activity_items[0]['message'] = 'Changed synthetic body'
            stale = self.invoke(*command, '--yes', '--confirm', data['confirm'])
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn('Preview changed', stale.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
            type(self).activity_items = [row.copy() for row in original_items]
            sent = self.invoke(*command, '--yes', '--confirm', data['confirm'], '--format', 'brief')
            self.assertEqual(sent.returncode, 0, sent.stderr)
            self.assertIn('hide acknowledged: 71', sent.stdout)
            self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                             [('DELETE', '/api/v1/users/self/activity_stream/71')])
            current = self.invoke('activity')
            self.assertEqual([row['id'] for row in json.loads(current.stdout)['activity']], [72, 73])
            self.assertEqual(self.inbox_state['message_count'], 1)
            self.assertEqual(self.inbox_messages[0]['body'], 'Synthetic private message')
            before = len(self.calls)
            required = self.invoke('activity-dismiss-all')
            self.assertNotEqual(required.returncode, 0)
            self.assertEqual(len(self.calls), before)
            truncated = self.invoke('activity-dismiss-all', '--all', '--max-pages', '1')
            self.assertNotEqual(truncated.returncode, 0)
            self.assertIn('Page limit', truncated.stderr)
            all_preview = self.invoke('activity-dismiss-all', '--all')
            self.assertEqual(all_preview.returncode, 0, all_preview.stderr)
            all_data = json.loads(all_preview.stdout)
            self.assertIn('outside the current visible feed', all_data['effect'])
            all_sent = self.invoke('activity-dismiss-all', '--all', '--yes', '--confirm', all_data['confirm'])
            self.assertEqual(all_sent.returncode, 0, all_sent.stderr)
            current = self.invoke('activity')
            self.assertEqual(json.loads(current.stdout)['activity'], [])
            self.assertEqual(self.inbox_state['message_count'], 1)
        finally:
            type(self).activity_hidden_ids = original_hidden
            type(self).activity_items = original_items


    def test_group_discussion_reads_and_threads_use_the_group_namespace(self):
        before = len(self.calls)
        for command in (('discussions', '11'), ('announcements', '11'), ('topic', '11', '203'),
                        ('entries', '11', '203'), ('replies', '11', '203', '301')):
            result = self.invoke(*command, '--context', 'group')
            self.assertEqual(result.returncode, 0, result.stderr)
        result = self.invoke('thread', '11', '203', '--context', 'group')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['group_id'], 11)
        self.assertEqual(data['entries'][0]['replies'][0]['id'], 401)
        self.assertTrue(data['complete'])
        self.assertTrue(all(verb == 'GET' and route.startswith('/api/v1/groups/11/')
                            for verb, route in self.calls[before:]))


    def test_group_post_context_and_account_are_bound_to_exact_confirmation(self):
        source = Path(self.tmp.name) / 'group-post.txt'
        source.write_text('Synthetic group message')
        command = ('post', '11', '203', '--context', 'group', '--message-file', str(source))
        before = len(self.calls)
        result = self.invoke(*command)
        self.assertEqual(result.returncode, 0, result.stderr)
        preview = json.loads(result.stdout)
        self.assertEqual(preview['group_id'], '11')
        self.assertNotIn('course_id', preview)
        self.assertTrue(all(verb == 'GET' for verb, _ in self.calls[before:]))
        sent = self.invoke(*command, '--yes', '--confirm', preview['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                         [('POST', '/api/v1/groups/11/discussion_topics/203/entries')])


    def test_group_post_first_restriction_blocks_entry_read_before_list_request(self):
        before = len(self.calls)
        result = self.invoke('entries', '11', '205', '--context', 'group')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('initial post', result.stderr)
        self.assertEqual(self.calls[before:], [('GET', '/api/v1/groups/11/discussion_topics/205')])


    def test_own_entry_lifecycle_is_stateful_and_paginated_for_courses_and_groups(self):
        original = self.entry.copy()
        source = Path(self.tmp.name) / 'entry-edit.txt'
        source.write_text('Synthetic <edited> entry')
        try:
            for context, context_id, topic_id in [('course', '101', '202'), ('group', '11', '203')]:
                with self.subTest(context=context):
                    self.__class__.entry = original.copy()
                    args = (context_id, topic_id, '301', '--context', context)
                    before = len(self.calls)
                    read = self.invoke('entry', *args)
                    self.assertEqual(read.returncode, 0, read.stderr)
                    self.assertEqual(json.loads(read.stdout)['message'], original['message'])
                    for command in [('entry-edit', *args, '--message-file', str(source)), ('entry-delete', *args)]:
                        before = len(self.calls)
                        preview = self.invoke(*command)
                        self.assertEqual(preview.returncode, 0, preview.stderr)
                        data = json.loads(preview.stdout)
                        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                        rejected = self.invoke(*command, '--yes', '--confirm', 'not-the-digest')
                        self.assertNotEqual(rejected.returncode, 0)
                        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
                        self.assertEqual(sent.returncode, 0, sent.stderr)
                        method = 'DELETE' if command[0] == 'entry-delete' else 'PUT'
                        self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                                         [(method, f'/api/v1/{context}s/{context_id}/discussion_topics/{topic_id}/entries/301')])
                        reread = self.invoke('entry', *args)
                        self.assertEqual(reread.returncode, 0, reread.stderr)
                        state = json.loads(reread.stdout)
                        if method == 'DELETE':
                            self.assertTrue(json.loads(sent.stdout)['deleted'])
                            self.assertTrue(state['deleted'])
                        else:
                            self.assertEqual(state['message'], '<p>Synthetic &lt;edited&gt; entry</p>')
        finally:
            self.__class__.entry = original


    def test_entry_changes_reject_other_users_and_unacknowledged_attachment_loss_over_tls(self):
        original = self.entry.copy()
        source = Path(self.tmp.name) / 'attached-entry-edit.txt'
        source.write_text('Synthetic replacement')
        command = ('entry-edit', '101', '202', '301', '--message-file', str(source))
        try:
            self.__class__.entry = {**original, 'user_id': 99}
            before = len(self.calls)
            denied = self.invoke(*command)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn('own active', denied.stderr)
            self.__class__.entry = {**original, 'attachment': {'id': 71, 'display_name': 'synthetic.txt'}}
            denied = self.invoke(*command)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn('--remove-attachment', denied.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
            preview = self.invoke(*command, '--remove-attachment')
            self.assertEqual(preview.returncode, 0, preview.stderr)
            data = json.loads(preview.stdout)
            sent = self.invoke(*command, '--remove-attachment', '--yes', '--confirm', data['confirm'])
            self.assertEqual(sent.returncode, 0, sent.stderr)
            self.assertEqual(self.entry_write['remove_attachment'], '1')
            self.assertIsNone(self.entry['attachment'])
        finally:
            self.__class__.entry = original


    def test_discussion_subscriptions_and_read_markers_are_explicit_stateful_writes(self):
        original_entry, original_state = self.entry.copy(), self.topic_state.copy()
        commands = [('topic-subscribe', 'subscribed', None), ('topic-unsubscribe', 'subscribed', None),
                    ('topic-mark-read', 'read', None), ('topic-mark-unread', 'read', None),
                    ('entry-mark-read', 'entries/301/read', True), ('entry-mark-unread', 'entries/301/read', False)]
        try:
            for context, context_id, topic_id in [('course', '101', '202'), ('group', '11', '203')]:
                for name, suffix, forced in commands:
                    with self.subTest(context=context, name=name):
                        command = [name, context_id, topic_id, '--context', context]
                        if name.startswith('entry-'):
                            command += ['301', '--forced-read-state' if forced else '--no-forced-read-state']
                        before = len(self.calls)
                        preview = self.invoke(*command)
                        self.assertEqual(preview.returncode, 0, preview.stderr)
                        data = json.loads(preview.stdout)
                        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                        rejected = self.invoke(*command, '--yes', '--confirm', 'wrong')
                        self.assertNotEqual(rejected.returncode, 0)
                        self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'], '--format', 'brief')
                        self.assertEqual(sent.returncode, 0, sent.stderr)
                        self.assertIn('HTTP 204', sent.stdout)
                        method = 'DELETE' if name.endswith(('unsubscribe', 'unread')) else 'PUT'
                        self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                                         [(method, f'/api/v1/{context}s/{context_id}/discussion_topics/{topic_id}/{suffix}')])
                        if name.startswith('entry-'):
                            self.assertEqual(self.entry['forced_read_state'], forced)
                            self.assertEqual(self.entry['read_state'], 'unread' if method == 'DELETE' else 'read')
                            self.assertEqual(self.entry['message'], original_entry['message'])
                        elif suffix == 'subscribed':
                            self.assertEqual(self.topic_state['subscribed'], method == 'PUT')
                        else:
                            self.assertEqual(self.topic_state['read_state'], 'unread' if method == 'DELETE' else 'read')
        finally:
            self.__class__.entry, self.__class__.topic_state = original_entry, original_state


    def test_cross_course_news_over_tls_is_read_only(self):
        before = len(self.calls)
        result = self.invoke('news', '--course', '101')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['announcements'][0]['message'], '<p>Synthetic update</p>')
        self.assertEqual(len(self.calls[before:]), 1)
        self.assertEqual(self.calls[before][0], 'GET')
        self.assertIn('context_codes%5B%5D=course_101', self.calls[before][1])
        brief = self.invoke('--format', 'brief', 'news', '--course', '101')
        self.assertIn('Synthetic announcement', brief.stdout)


    def test_preview_then_post(self):
        message = Path(self.tmp.name) / 'message.txt'
        message.write_text('Synthetic message')
        before = len(self.calls)
        r = self.invoke('post', '101', '202', '--message-file', str(message))
        preview = json.loads(r.stdout)
        self.assertTrue(preview['dry_run'])
        self.assertEqual(self.calls[before:], [('GET', '/api/v1/users/self/profile'),
                                              ('GET', '/api/v1/courses/101/discussion_topics/202')])
        r = self.invoke('post', '101', '202', '--message-file', str(message), '--yes',
                        '--confirm', preview['confirm'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['id'], 999)
        self.assertEqual(self.calls[-2:], [
            ('GET', '/api/v1/courses/101/discussion_topics/202'),
            ('POST', '/api/v1/courses/101/discussion_topics/202/entries')])


    def test_discussion_thread_over_tls_follows_reply_pagination(self):
        before = len(self.calls)
        result = self.invoke('thread', '101', '202')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['complete'])
        self.assertEqual([reply['id'] for reply in data['entries'][0]['replies']], [401, 400])
        self.assertEqual(self.calls[before:], [
            ('GET', '/api/v1/courses/101/discussion_topics/202'),
            ('GET', '/api/v1/courses/101/discussion_topics/202/entries?per_page=100'),
            ('GET', '/api/v1/courses/101/discussion_topics/202/entries/301/replies?per_page=100')])


    def test_inbox_read_does_not_change_read_state(self):
        before = len(self.calls)
        inbox = self.invoke('inbox', '--scope', 'unread')
        self.assertEqual(inbox.returncode, 0, inbox.stderr)
        self.assertEqual(json.loads(inbox.stdout)[0]['id'], 12)
        thread = self.invoke('conversation', '12')
        self.assertEqual(thread.returncode, 0, thread.stderr)
        self.assertEqual(json.loads(thread.stdout)['messages'][0]['body'],
                         'Synthetic private message')
        self.assertEqual(self.calls[before:], [
            ('GET', '/api/v1/conversations?per_page=100&scope=unread'),
            ('GET', '/api/v1/conversations/12?auto_mark_as_read=false')])


    def test_inbox_organization_changes_only_requested_own_view_fields(self):
        original, messages = self.inbox_state.copy(), list(self.inbox_messages)
        try:
            for options, expected in [(('--state', 'read'), {'workflow_state': 'read'}),
                                      (('--state', 'unread'), {'workflow_state': 'unread'}),
                                      (('--state', 'archived'), {'workflow_state': 'archived'}),
                                      (('--starred', '--no-subscribed'), {'starred': True, 'subscribed': False}),
                                      (('--no-starred', '--subscribed'), {'starred': False, 'subscribed': True})]:
                with self.subTest(options=options):
                    command = ('inbox-edit', '12', *options)
                    before = len(self.calls)
                    preview = self.invoke(*command)
                    self.assertEqual(preview.returncode, 0, preview.stderr)
                    data = json.loads(preview.stdout)
                    self.assertEqual(data['body'], {'conversation': expected})
                    self.assertNotIn('Synthetic private message', preview.stdout)
                    rejected = self.invoke(*command, '--yes', '--confirm', 'wrong')
                    self.assertNotEqual(rejected.returncode, 0)
                    self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
                    sent = self.invoke(*command, '--yes', '--confirm', data['confirm'], '--format', 'brief')
                    self.assertEqual(sent.returncode, 0, sent.stderr)
                    self.assertIn('acknowledged', sent.stdout)
                    self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                                     [('PUT', '/api/v1/conversations/12')])
                    self.assertEqual(self.inbox_write, {'conversation': expected})
                    current = self.invoke('conversation', '12')
                    self.assertEqual(current.returncode, 0, current.stderr)
                    thread = json.loads(current.stdout)
                    for key, value in expected.items():
                        self.assertEqual(thread[key], value)
                    self.assertEqual(thread['messages'], messages)
        finally:
            type(self).inbox_state, type(self).inbox_messages = original, messages


    def test_inbox_delete_empties_own_view_only_and_requires_permanent_ack(self):
        original, messages = self.inbox_state.copy(), list(self.inbox_messages)
        try:
            before = len(self.calls)
            missing = self.invoke('inbox-delete', '12')
            self.assertNotEqual(missing.returncode, 0)
            self.assertEqual(self.calls[before:], [])
            command = ('inbox-delete', '12', '--permanent')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            sent = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertEqual(sent.returncode, 0, sent.stderr)
            self.assertTrue(json.loads(sent.stdout)['deleted_from_own_view'])
            self.assertEqual([call for call in self.calls[before:] if call[0] != 'GET'],
                             [('DELETE', '/api/v1/conversations/12')])
            current = json.loads(self.invoke('conversation', '12').stdout)
            self.assertEqual(current['messages'], [])
            self.assertEqual(current['message_count'], 0)
            self.assertFalse(any('/delete_for_all' in route for _, route in self.calls[before:]))
        finally:
            type(self).inbox_state, type(self).inbox_messages = original, messages


    def test_inbox_new_message_or_private_thread_refuses_old_preview_or_subscription(self):
        original, messages = self.inbox_state.copy(), list(self.inbox_messages)
        try:
            command = ('inbox-edit', '12', '--no-starred')
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            type(self).inbox_messages = messages + [{'id': 32, 'body': 'Synthetic later message'}]
            before = len(self.calls)
            changed = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn('Preview changed', changed.stderr)
            self.inbox_state['private'] = True
            refused = self.invoke('inbox-edit', '12', '--no-subscribed')
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn('group conversation', refused.stderr)
            self.assertTrue(all(method == 'GET' for method, _ in self.calls[before:]))
        finally:
            type(self).inbox_state, type(self).inbox_messages = original, messages


    def test_inbox_reply_preview_and_confirm_over_tls(self):
        message = Path(self.tmp.name) / 'inbox-reply.txt'
        message.write_text('Synthetic reply')
        before = len(self.calls)
        command = ('inbox-reply', '12', '--message-file', str(message))
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertTrue(data['dry_run'])
        self.assertEqual(self.calls[before:], [
            ('GET', '/api/v1/users/self/profile'),
            ('GET', '/api/v1/conversations/12?auto_mark_as_read=false')])
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(self.calls[-2:], [
            ('GET', '/api/v1/conversations/12?auto_mark_as_read=false'),
            ('POST', '/api/v1/conversations/12/add_message')])


    def test_recipient_lookup_and_compose_preview_over_tls(self):
        source = Path(self.tmp.name) / 'compose.txt'
        source.write_text('Synthetic hello')
        before = len(self.calls)
        found = self.invoke('recipients', '--search', 'Synthetic')
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertEqual(json.loads(found.stdout)[0]['id'], 7)
        command = ('inbox-compose', '--recipient', '7', '--subject', 'Synthetic subject',
                   '--message-file', str(source))
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        data = json.loads(preview.stdout)
        self.assertTrue(data['dry_run'])
        self.assertEqual([method for method, _ in self.calls[before:]], ['GET', 'GET', 'GET'])
        sent = self.invoke(*command, '--yes', '--confirm', data['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(self.calls[-3:], [
            ('GET', '/api/v1/search/recipients?type=user&per_page=100&user_id=7'),
            ('GET', '/api/v1/users/self/profile'),
            ('POST', '/api/v1/conversations')])


    def test_storage_201_location_is_confirmed(self):
        source = Path(self.tmp.name) / 'created.txt'
        source.write_text('Synthetic 201 upload')
        command = ('upload-personal', '--file', str(source))
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        sent = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertEqual(json.loads(sent.stdout)['uploaded_file_id'], 777)


    def test_foreign_confirmation_refused_without_token_leak(self):
        source = Path(self.tmp.name) / 'foreign.txt'
        source.write_text('Synthetic hostile redirect')
        command = ('upload-personal', '--file', str(source))
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        before = len(self.calls)
        sent = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertEqual(sent.returncode, 1)
        self.assertIn('confirmation failed', sent.stderr)
        self.assertEqual(self.calls[before:], [
            ('GET', '/api/v1/users/self/profile'),
            ('POST', '/api/v1/users/self/files'), ('POST', '/storage/upload-foreign')])
        self.assertIsNone(self.storage_auth)
        self.assertNotIn('untrusted.example.org', sent.stderr)
