import unittest
from unittest.mock import Mock

from canvas_cli.client import CanvasError
from canvas_cli.feedback import comment


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.profile = {'id': 7}
        self.assignment = {'id': 8, 'course_id': 9, 'name': 'Synthetic project', 'published': True}
        self.submission = {'id': 41, 'assignment_id': 8, 'user_id': 7,
                           'attempt': 2, 'workflow_state': 'submitted',
                           'submitted_at': '2026-10-02T12:00:00Z', 'assignment_visible': True}

    def reads(self, submission=None, assignment=None):
        return [(self.profile, ''), (assignment or self.assignment, ''),
                (submission or self.submission, '')]

    def test_comment_is_plain_text_own_submission_and_preview_only(self):
        self.client.request.side_effect = self.reads()
        preview = comment(self.client, '9', '8', '<b>Question</b>', attempt=1)
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['route'], '/api/v1/courses/9/assignments/8/submissions/7')
        self.assertEqual(preview['body'], {'comment': {'text_comment': '<b>Question</b>',
                                                      'attempt': 1, 'group_comment': False}})
        self.assertTrue(all(len(c.args) == 1 for c in self.client.request.call_args_list))

    def test_exact_confirmation_adds_comment_without_grade_or_submission_fields(self):
        self.client.request.side_effect = self.reads()
        preview = comment(self.client, '9', '8', 'Synthetic question')
        self.client.request.reset_mock()
        self.client.request.side_effect = self.reads() + [({'id': 41}, '')]
        comment(self.client, '9', '8', 'Synthetic question', yes=True, confirm=preview['confirm'])
        self.client.request.assert_called_with(preview['route'], 'PUT', preview['body'])
        self.assertEqual(set(preview['body']), {'comment'})
        self.assertEqual(len([c for c in self.client.request.call_args_list if len(c.args) > 1]), 1)

    def test_wrong_owner_assignment_and_future_attempt_are_rejected(self):
        for changed in ({'user_id': 99}, {'user_id': True}, {'assignment_id': 99},
                        {'assignment_visible': False}, {'attempt': None}):
            self.client.request.side_effect = self.reads(submission={**self.submission, **changed})
            with self.subTest(changed=changed), self.assertRaises(CanvasError):
                comment(self.client, '9', '8', 'Synthetic', attempt=1)
        self.client.request.side_effect = self.reads()
        with self.assertRaisesRegex(CanvasError, 'attempt has not been confirmed'):
            comment(self.client, '9', '8', 'Synthetic', attempt=3)

    def test_group_audience_is_explicit_and_changes_invalidate_digest(self):
        self.client.request.side_effect = self.reads()
        with self.assertRaisesRegex(CanvasError, 'group assignment'):
            comment(self.client, '9', '8', 'Synthetic', group_comment=True)
        group_assignment = {**self.assignment, 'group_category_id': 20}
        self.client.request.side_effect = self.reads(assignment=group_assignment)
        preview = comment(self.client, '9', '8', 'Synthetic', group_comment=True)
        self.assertTrue(preview['body']['comment']['group_comment'])
        self.client.request.reset_mock()
        self.client.request.side_effect = self.reads(assignment=group_assignment)
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            comment(self.client, '9', '8', 'Synthetic', group_comment=False,
                    yes=True, confirm=preview['confirm'])
        self.assertTrue(all(len(c.args) == 1 for c in self.client.request.call_args_list))

    def test_new_attempt_changes_destination_preview_and_ambiguous_put_is_never_retried(self):
        self.client.request.side_effect = self.reads()
        preview = comment(self.client, '9', '8', 'Synthetic')
        self.client.request.side_effect = self.reads(submission={**self.submission, 'attempt': 3})
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            comment(self.client, '9', '8', 'Synthetic', yes=True, confirm=preview['confirm'])
        self.client.request.reset_mock()
        self.client.request.side_effect = self.reads() + [CanvasError('Outcome uncertain')]
        with self.assertRaises(CanvasError):
            comment(self.client, '9', '8', 'Synthetic', yes=True, confirm=preview['confirm'])
        self.assertEqual(self.client.request.call_count, 4)

    def test_invalid_input_and_partial_confirmation_do_not_read(self):
        for text, kwargs in [(' ', {}), ('Synthetic', {'attempt': 0}),
                             ('Synthetic', {'yes': True}), ('Synthetic', {'confirm': 'wrong'})]:
            with self.subTest(text=text, kwargs=kwargs), self.assertRaises(CanvasError):
                comment(self.client, '9', '8', text, **kwargs)
        self.client.request.assert_not_called()


if __name__ == '__main__': unittest.main()
