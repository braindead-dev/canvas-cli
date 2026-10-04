"""Shared comment controls over synthetic HTTPS, without any real Canvas write."""

import copy
import json
from pathlib import Path

from . import announcement_authoring
from .fixture import CanvasFixture


class AnnouncementCommentsE2E(CanvasFixture):
    def setUp(self):
        announcement_authoring.initialize(type(self), enabled=True)

    def command(self, *, group=False, comments=True):
        return ('announcement-edit', '123', '9', '--context', 'group' if group else 'course',
                '--comments' if comments else '--no-comments', '--acknowledge-comment-access-change',
                '--acknowledge-shared-announcement', '--acknowledge-broadcast')

    def approved(self, command):
        result = self.invoke(*command)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(result.stdout)['confirm'])

    def writes(self, before):
        return [call for call in self.calls[before:] if call[0] != 'GET']

    def test_course_and_group_open_close_verify_flag_without_reading_peers_or_replacing_content(self):
        for group in (False, True):
            announcement_authoring.initialize(type(self), enabled=True)
            before = len(self.calls)
            original = copy.deepcopy(self.announcements[9])
            result = self.approved(self.command(group=group))
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertFalse(data['announcement_comment_state']['comments_locked'])
            self.assertFalse(data['announcement_comment_state']['participant_reply_access_verified'])
            self.assertFalse(data['comment_lock_preserved'])
            self.assertEqual(data['stored_text_matches_request'], {})
            self.assertNotIn('synthetic-private', result.stdout)
            result = self.approved((*self.command(group=group, comments=False), '--format', 'brief'))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Stored comments: closed', result.stdout)
            self.assertIn('reply access is unverified', result.stdout)
            self.assertEqual(self.announcements[9], original)
            self.assertEqual([row[2] for row in self.announcement_mutations],
                             [{'is_announcement': True, 'lock_comment': False},
                              {'is_announcement': True, 'lock_comment': True}])
            self.assertEqual(len(self.writes(before)), 2)
            self.assertEqual(self.announcement_preference_writes, 0)
            self.assertEqual(self.announcement_entries, [{'id': 301, 'message': 'synthetic-private-peer-comment'}])
            self.assertFalse(any('/entries' in route or '/view' in route for _, route in self.calls[before:]))

    def test_closed_announcement_date_clearing_requires_separate_consent_and_exact_readback(self):
        for group in (False, True):
            announcement_authoring.initialize(type(self), enabled=True)
            self.announcements[9]['lock_at'] = '2099-10-01T19:00:00Z'
            before = len(self.calls)
            result = self.invoke(*self.command(group=group))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('closing date', result.stderr)
            self.assertEqual(self.writes(before), [])
            result = self.approved((*self.command(group=group), '--acknowledge-closing-schedule-removal', '--format', 'brief'))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Closing schedule cleared with explicit acknowledgement', result.stdout)
            self.assertIsNone(self.announcements[9]['lock_at'])
            self.assertEqual(self.announcement_mutations[0][2], {'is_announcement': True, 'lock_comment': False})
            self.assertEqual(len(self.writes(before)), 1)

    def test_global_disabled_group_state_is_distinct_from_lock_and_course_override_is_uncertain(self):
        self.announcements[9]['comments_disabled'] = True
        type(self).announcement_force_lock = True
        result = self.approved(self.command(group=True))
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)['announcement_comment_state']
        self.assertTrue(state['reported_context_comments_disabled'])
        self.assertFalse(state['comments_locked'])
        self.assertFalse(state['participant_reply_access_verified'])
        announcement_authoring.initialize(type(self), enabled=True)
        type(self).announcement_force_lock = True
        before = len(self.calls)
        result = self.approved(self.command())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('may already have succeeded', result.stderr)
        self.assertEqual(len(self.writes(before)), 1)

    def test_combined_content_and_comments_uses_one_put_and_labels_native_html_processing(self):
        source = Path(self.tmp.name) / 'synthetic-announcement-update.txt'
        source.write_text('One <two>\n🌿', encoding='utf-8')
        type(self).announcement_sanitize = True
        before = len(self.calls)
        result = self.approved((*self.command(), '--title', 'Changed title', '--message-file', str(source), '--format', 'brief'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Stored text differs', result.stdout)
        self.assertIn('Stored comments: open', result.stdout)
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertEqual(len(self.writes(before)), 1)
        self.assertEqual(self.announcement_mutations[0][2], {'title': 'Changed title',
                        'message': '<p>One &lt;two&gt;<br>🌿</p>', 'is_announcement': True, 'lock_comment': False})

    def test_missing_consent_unknown_closing_effect_noop_and_missing_native_eligibility_do_not_write(self):
        for mode in ('consent', 'unused_clearing', 'noop', 'can_lock', 'permission'):
            announcement_authoring.initialize(type(self), enabled=True)
            command = self.command()
            if mode == 'consent':
                command = tuple(value for value in command if value != '--acknowledge-comment-access-change')
            elif mode == 'unused_clearing':
                command += ('--acknowledge-closing-schedule-removal',)
            elif mode == 'noop':
                self.announcements[9]['locked'] = False
            elif mode == 'can_lock':
                self.announcements[9].update(locked=False, can_lock=False)
                command = self.command(comments=False)
            else:
                self.announcements[9]['permissions']['update'] = False
            before = len(self.calls)
            result = self.invoke(*command)
            self.assertNotEqual(result.returncode, 0, (mode, result.stderr))
            self.assertEqual(result.stdout, '')
            self.assertEqual(self.writes(before), [])

    def test_stale_date_global_policy_choice_and_body_invalidate_confirmation_without_put(self):
        for mode in ('date', 'policy', 'choice', 'text'):
            announcement_authoring.initialize(type(self), enabled=True)
            command = self.command()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'date':
                self.announcements[9]['lock_at'] = '2099-10-01T19:00:00Z'
                command += ('--acknowledge-closing-schedule-removal',)
            elif mode == 'policy':
                self.announcements[9]['comments_disabled'] = True
            elif mode == 'choice':
                self.announcements[9]['locked'] = False
            else:
                self.announcements[9]['message'] = '<p>Changed prior body</p>'
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, (mode, result.stderr))
            self.assertEqual(self.writes(before), [])

    def test_ignored_closing_or_implicit_clearing_never_get_retried_or_claimed_as_success(self):
        for mode in ('lock', 'date'):
            announcement_authoring.initialize(type(self), enabled=True)
            command = self.command()
            if mode == 'lock':
                self.announcements[9]['locked'] = False
                type(self).announcement_ignore_comment_lock = True
                command = self.command(comments=False)
            else:
                self.announcements[9]['lock_at'] = '2099-10-01T19:00:00Z'
                type(self).announcement_keep_closing_date = True
                command += ('--acknowledge-closing-schedule-removal',)
            before = len(self.calls)
            result = self.approved(command)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('may already have succeeded', result.stderr)
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertEqual(len(self.writes(before)), 1)
