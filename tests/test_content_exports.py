import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from canvas_cli.client import CanvasError
from canvas_cli.content_exports import (
    create,
    download_export,
    list_exports,
    status,
    summary,
)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(host='https://canvas.example.edu')
        self.profile = {'id': 7}
        self.course = {'id': 8, 'name': 'Synthetic course'}
        self.job = {'id': 51, 'user_id': 7, 'export_type': 'zip', 'workflow_state': 'exported',
                    'attachment': {'url': 'https://storage.example.edu/secret?signature=synthetic', 'size': 12},
                    'progress_url': 'https://canvas.example.edu/api/v1/progress/61'}

    def test_list_is_paginated_and_signed_urls_are_not_printed(self):
        self.client.list.return_value = [self.job]
        data = list_exports(self.client, '8', 4)
        self.assertTrue(data[0]['download_available'])
        self.assertNotIn('signature', json.dumps(data))
        self.assertNotIn('storage.example.edu', json.dumps(data))
        self.assertNotIn('progress_url', json.dumps(data))
        self.client.list.assert_called_once_with('/api/v1/courses/8/content_exports?per_page=100', 4)

    def test_status_only_reads_progress_when_explicitly_selected(self):
        self.client.request.return_value = (self.job, '')
        data = status(self.client, '8', '51')
        self.assertIsNone(data['progress'])
        self.client.request.assert_called_once_with('/api/v1/courses/8/content_exports/51')
        self.client.request.side_effect = [(self.job, ''),
                                           ({'id': 61, 'workflow_state': 'completed', 'completion': 100,
                                             'results': {'private': 'not displayed'}}, '')]
        data = status(self.client, '8', '51', with_progress=True)
        self.assertEqual(data['progress']['completion'], 100)
        self.assertNotIn('results', data['progress'])
        self.client.request.assert_called_with('/api/v1/progress/61')

    def test_progress_links_cannot_redirect_bearer_to_other_host_or_resource(self):
        for url in ('https://foreign.example.edu/api/v1/progress/61',
                    '/api/v1/conversations/61', '/api/v1/progress/61?access_token=secret',
                    '/api/v1/progress/61#secret', 'https://user:secret@canvas.example.edu/api/v1/progress/61'):
            self.client.request.reset_mock()
            self.client.request.return_value = ({**self.job, 'progress_url': url}, '')
            with self.subTest(url=url), self.assertRaises(CanvasError):
                status(self.client, '8', '51', with_progress=True)
            self.client.request.assert_called_once_with('/api/v1/courses/8/content_exports/51')

    def test_export_selection_preview_and_confirmation_are_explicit(self):
        self.client.request.side_effect = [(self.profile, ''), (self.course, '')]
        preview = create(self.client, '8', select=[('files', '12'), ('folders', '13')])
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['body'], {'export_type': 'zip', 'skip_notifications': False,
                                          'select': {'files': [12], 'folders': [13]}})
        self.assertTrue(all(len(call.args) == 1 for call in self.client.request.call_args_list))
        self.client.request.side_effect = [(self.profile, ''), (self.course, ''), (self.job, '')]
        result = create(self.client, '8', select=[('files', '12'), ('folders', '13')],
                        yes=True, confirm=preview['confirm'])
        self.assertEqual(result['export']['id'], 51)
        self.assertNotIn('signature', json.dumps(result))
        self.client.request.assert_called_with('/api/v1/courses/8/content_exports', 'POST', preview['body'])

    def test_invalid_or_duplicate_selection_fails_before_read(self):
        for kwargs in ({'export_type': 'qti'}, {'select': [('pages', '12')]},
                       {'select': [('files', '12'), ('files', '012')]},
                       {'select': [('files', 'bad')]}, {'yes': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                create(self.client, '8', **kwargs)
        self.client.request.assert_not_called()

    def test_changed_course_or_account_prevents_creation_and_uncertain_post_is_not_retried(self):
        self.client.request.side_effect = [(self.profile, ''), (self.course, '')]
        preview = create(self.client, '8')
        self.client.request.reset_mock()
        self.client.request.side_effect = [({'id': 99}, ''), (self.course, '')]
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            create(self.client, '8', yes=True, confirm=preview['confirm'])
        self.assertEqual(self.client.request.call_count, 2)
        self.client.request.reset_mock()
        self.client.request.side_effect = [(self.profile, ''), (self.course, ''), (None, '')]
        with self.assertRaisesRegex(CanvasError, 'outcome uncertain'):
            create(self.client, '8', yes=True, confirm=preview['confirm'])
        self.assertEqual(self.client.request.call_count, 3)

    @patch('canvas_cli.content_exports.download')
    def test_download_uses_separate_no_bearer_binary_transport(self, binary):
        self.client.request.return_value = (self.job, '')
        binary.return_value = {'saved': '/private/synthetic.zip', 'bytes': 12}
        result = download_export(self.client, '8', '51', Path('/private/synthetic.zip'), 20)
        binary.assert_called_once_with(self.job['attachment']['url'], Path('/private/synthetic.zip'),
                                       20, expected_bytes=12)
        self.assertNotIn('signature', json.dumps(result))
        self.assertEqual(result['export_id'], 51)

    @patch('canvas_cli.content_exports.download')
    def test_pending_failed_expired_or_locked_exports_do_not_download(self, binary):
        for fields in ({'workflow_state': 'exporting'}, {'workflow_state': 'failed'},
                       {'attachment': None}, {'attachment': {'url': 'https://storage.example.edu/file',
                                                            'locked_for_user': True}}):
            self.client.request.return_value = ({**self.job, **fields}, '')
            with self.subTest(fields=fields), self.assertRaises(CanvasError):
                download_export(self.client, '8', '51', Path('/private/synthetic.zip'))
        binary.assert_not_called()

    def test_malformed_and_wrong_job_is_rejected(self):
        for record in (None, {'id': True}, {'id': 51, 'attachment': 'bad'}, {'id': 52}):
            with self.subTest(record=record), self.assertRaises(CanvasError):
                summary(record, '51')
        self.client.request.side_effect = CanvasError('denied', status=403)
        with self.assertRaises(CanvasError) as error:
            status(self.client, '8', '51')
        self.assertEqual(error.exception.status, 403)


if __name__ == '__main__': unittest.main()
