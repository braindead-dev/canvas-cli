import unittest
from unittest.mock import Mock

from canvas_pocket.client import CanvasError
from canvas_pocket.submit import submit, submit_file


class SubmitTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.assignment = {'id': 8, 'course_id': 7, 'name': 'Synthetic project',
                           'published': True, 'locked_for_user': False,
                           'submission_types': ['online_url', 'online_text_entry'],
                           'due_at': '2026-10-01T00:00:00Z'}
        self.client.request.return_value = (self.assignment, '')

    def test_preview_does_not_submit_and_url_is_validated(self):
        preview = submit(self.client, '7', '8', 'online_url', 'https://example.edu/project')
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['body']['submission']['url'], 'https://example.edu/project')
        self.client.request.assert_called_once_with('/api/v1/courses/7/assignments/8')
        for invalid in ('file:///tmp/work', 'https://user:secret@example.edu/work',
                        'https://example.edu/a b', 'not-a-url'):
            with self.subTest(url=invalid), self.assertRaises(CanvasError):
                submit(self.client, '7', '8', 'online_url', invalid)

    def test_text_is_escaped_and_changed_assignment_cannot_be_sent(self):
        preview = submit(self.client, '7', '8', 'online_text_entry', '<script>hello</script>')
        self.assertEqual(preview['body']['submission']['body'],
                         '<p>&lt;script&gt;hello&lt;/script&gt;</p>')
        with self.assertRaisesRegex(CanvasError, 'both --yes and --confirm'):
            submit(self.client, '7', '8', 'online_text_entry', 'hello', yes=True)
        self.client.request.reset_mock()
        self.client.request.return_value = ({**self.assignment, 'due_at': '2026-10-02T00:00:00Z'}, '')
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            submit(self.client, '7', '8', 'online_text_entry', '<script>hello</script>',
                   yes=True, confirm=preview['confirm'])
        self.client.request.assert_called_once_with('/api/v1/courses/7/assignments/8')

    def test_confirmed_submission_posts_once(self):
        preview = submit(self.client, '7', '8', 'online_url', 'https://example.edu/project')
        self.client.request.side_effect = [(self.assignment, ''), ({'workflow_state': 'submitted'}, '')]
        result = submit(self.client, '7', '8', 'online_url', 'https://example.edu/project',
                        yes=True, confirm=preview['confirm'])
        self.assertEqual(result['workflow_state'], 'submitted')
        self.assertEqual(self.client.request.call_args.args,
                         ('/api/v1/courses/7/assignments/8/submissions', 'POST',
                          {'submission': {'submission_type': 'online_url',
                                          'url': 'https://example.edu/project'}}))

    def test_wrong_or_locked_assignment_is_refused(self):
        for changed in ({'id': 9}, {'course_id': 99}, {'locked_for_user': True},
                        {'published': False}, {'submission_types': ['online_upload']}):
            with self.subTest(changed=changed):
                self.client.request.return_value = ({**self.assignment, **changed}, '')
                with self.assertRaises(CanvasError):
                    submit(self.client, '7', '8', 'online_url', 'https://example.edu/project')

    def test_file_submission_preview_binds_file_and_assignment(self):
        assignment = {**self.assignment, 'submission_types': ['online_upload'],
                      'allowed_extensions': ['txt']}
        file_record = {'id': 42, 'display_name': 'paper.txt', 'size': 12,
                       'uuid': 'first-version'}
        self.client.request.side_effect = [(assignment, ''), (file_record, '')]
        preview = submit_file(self.client, '7', '8', '42')
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['body']['submission'],
                         {'submission_type': 'online_upload', 'file_ids': [42]})
        self.client.request.reset_mock()
        self.client.request.side_effect = [(assignment, ''),
                                           ({**file_record, 'uuid': 'changed-version'}, '')]
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            submit_file(self.client, '7', '8', '42', yes=True, confirm=preview['confirm'])
        self.assertEqual(self.client.request.call_count, 2)

    def test_file_submission_rejects_bad_file(self):
        assignment = {**self.assignment, 'submission_types': ['online_upload'],
                      'allowed_extensions': ['txt']}
        for file_record in ({'id': 43, 'display_name': 'paper.txt', 'size': 12},
                            {'id': 42, 'display_name': 'paper.pdf', 'size': 12},
                            {'id': 42, 'display_name': 'paper.txt', 'size': 0},
                            {'id': 42, 'display_name': 'paper.txt', 'size': 12,
                             'locked_for_user': True}):
            self.client.request.side_effect = [(assignment, ''), (file_record, '')]
            with self.assertRaises(CanvasError):
                submit_file(self.client, '7', '8', '42')


if __name__ == '__main__': unittest.main()
