"""Optional attempted-write uncertainty must never hide a stale confirmation."""

import unittest

from canvas_cli.client import CanvasError
from canvas_cli.writes import confirmed, digest, own_id, review


class WriteClient:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail

    def request(self, route, method, body, **options):
        self.calls.append((route, method, body, options))
        if self.fail:
            raise CanvasError('synthetic-private-write-error', status=500)
        return None if options else {'id': 1}, ''


class ConfirmationTests(unittest.TestCase):
    def test_account_identity_requires_an_exact_positive_integer_not_truthiness(self):
        self.assertEqual(own_id({'id': 7}), 7)
        for profile in (None, [], {}, {'id': True}, {'id': 0}, {'id': -1}, {'id': '7'}):
            with self.subTest(profile=profile), self.assertRaises(CanvasError):
                own_id(profile)

    def test_confirmation_fingerprint_refuses_non_json_nonfinite_or_invalid_utf8_without_echoing(self):
        for value in ({'synthetic-private-json': set()}, {'synthetic-private-json': float('nan')}, {'synthetic-private-json': '\ud800'}):
            with self.subTest(value=value), self.assertRaisesRegex(CanvasError, 'malformed JSON') as result:
                digest(value)
            self.assertNotIn('synthetic-private-json', str(result.exception))

    def preview(self):
        return {'method': 'PUT', 'route': '/api/v1/courses/123/discussion_topics/9', 'body': {'podcast_enabled': True}}

    def test_preview_and_stale_digest_never_send_or_report_uncertain_mutation(self):
        client = WriteClient(fail=True)
        result = confirmed(client, self.preview(), uncertain_message='Uncertain attempt')
        self.assertTrue(result['dry_run'])
        with self.assertRaisesRegex(CanvasError, 'Preview changed'):
            confirmed(client, self.preview(), True, 'stale', uncertain_message='Uncertain attempt')
        self.assertEqual(client.calls, [])

    def test_explicit_uncertainty_redacts_attempted_error_and_does_not_retry(self):
        client = WriteClient(fail=True)
        preview = self.preview()
        with self.assertRaisesRegex(CanvasError, '^Uncertain attempt$') as result:
            confirmed(client, preview, True, review(preview)['confirm'], uncertain_message='Uncertain attempt')
        self.assertNotIn('synthetic-private', str(result.exception))
        self.assertEqual(len(client.calls), 1)

    def test_unselected_error_behavior_preserves_original_status(self):
        client = WriteClient(fail=True)
        preview = self.preview()
        with self.assertRaises(CanvasError) as result:
            confirmed(client, preview, True, review(preview)['confirm'])
        self.assertEqual(result.exception.status, 500)
        self.assertEqual(str(result.exception), 'synthetic-private-write-error')
        self.assertEqual(len(client.calls), 1)

    def test_normal_and_no_content_success_keep_exact_existing_response_contract(self):
        for empty in (False, True):
            client = WriteClient()
            preview = self.preview() | ({'expected_response': 'no_content'} if empty else {})
            result = confirmed(client, preview, True, review(preview)['confirm'], uncertain_message='Uncertain attempt')
            self.assertEqual(result, None if empty else {'id': 1})
            self.assertEqual(client.calls[0][3], {'expect_no_content': True} if empty else {})
