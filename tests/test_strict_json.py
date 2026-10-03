"""The same unambiguous decoder is used online and for local snapshots."""

import io
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from canvas_cli.client import CanvasError, Client
from canvas_cli.snapshot import save_private
from canvas_cli.snapshot_diff import read
from canvas_cli.strict_json import load
from canvas_cli.writes import confirmed, digest


class StrictJSONTests(unittest.TestCase):
    def test_finite_native_values_keep_their_types_order_unicode_and_empty_shapes(self):
        data = load(io.BytesIO(b'{"name":"Synthetic \\u2603", "values":[1, -2, 3.5, -0.0, 1e2, true, null], "empty":{}}'))
        self.assertEqual(list(data), ['name', 'values', 'empty'])
        self.assertEqual(data['name'], 'Synthetic \u2603')
        self.assertEqual(data['values'], [1, -2, 3.5, -0.0, 100.0, True, None])
        self.assertEqual(math.copysign(1, data['values'][3]), -1)
        self.assertIs(type(data['values'][0]), int)
        self.assertIs(type(data['values'][2]), float)
        self.assertEqual(load(io.StringIO('[{"id":1}, {"id":2}]')), [{'id': 1}, {'id': 2}])
        for value in ('null', 'true', 'false', '"NaN"', '"Infinity"', '[]', '{}', '0'):
            load(io.StringIO(value))

    def test_duplicate_keys_at_any_depth_including_escaped_equivalents_are_rejected(self):
        for text in ('{"id":7,"id":8}', '{"id":7,"id":7}', '{"id":7,"\\u0069d":8}',
                     '{"record":{"user_id":7,"user_id":8}}', '[{"name":"one","name":"two"}]',
                     '{"Synthetic private key":1,"Synthetic private key":2}'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'Duplicate JSON') as error:
                load(io.StringIO(text))
            self.assertNotIn('Synthetic private', str(error.exception))

    def test_nonfinite_constants_and_float_overflow_are_rejected_without_values_in_diagnostics(self):
        for value in ('NaN', 'Infinity', '-Infinity', '1e309', '-1e309', '1.7976931348623159e308'):
            for text in (value, '[' + value + ']', '{"Synthetic private grade":' + value + '}'):
                with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'Non-finite JSON') as error:
                    load(io.StringIO(text))
                self.assertNotIn('Synthetic private', str(error.exception))
        self.assertEqual(load(io.StringIO('1.7976931348623157e308')), float('1.7976931348623157e308'))

    def test_snapshot_decoder_rejects_duplicate_identity_and_nonfinite_values_without_logging_path_or_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'Synthetic-private-path.json'
            for content in ('{"schema_version":1,"schema_version":1}',
                            '{"schema_version":1,"viewer_user_id":7,"viewer_user_id":8}',
                            '{"schema_version":1,"assignments":[{"points_possible":NaN}]}',
                            '{"schema_version":1,"assignments":[{"points_possible":1e999}]}'):
                path.write_text(content, encoding='utf-8')
                with self.assertRaisesRegex(CanvasError, 'valid JSON snapshot') as error:
                    read(path)
                self.assertNotIn('Synthetic-private', str(error.exception))
            for version in ('true', '1.0', 'null', '"1"'):
                path.write_text('{"schema_version":' + version + '}', encoding='utf-8')
                with self.assertRaisesRegex(CanvasError, 'schema'):
                    read(path)
            path.write_text('{"schema_version":1,"assignments":[{"points_possible":3.5}]}', encoding='utf-8')
            self.assertEqual(read(path)['assignments'][0]['points_possible'], 3.5)

    def test_nonfinite_private_snapshot_save_removes_only_its_failed_new_file(self):
        with tempfile.TemporaryDirectory() as folder:
            protected = Path(folder) / 'existing.txt'
            protected.write_text('Synthetic existing user content', encoding='utf-8')
            destination = Path(folder) / 'capture.json'
            for value in (float('nan'), float('inf'), float('-inf')):
                with self.assertRaises(ValueError):
                    save_private(destination, {'complete': True, 'unavailable': {}, 'Synthetic private grade': value})
                self.assertFalse(destination.exists())
                self.assertEqual(protected.read_text(), 'Synthetic existing user content')

    def test_malformed_or_nonfinite_preview_never_generates_a_confirmation_or_request(self):
        client = Mock()
        for value in (float('nan'), float('inf'), float('-inf'), b'Synthetic private bytes', 'Synthetic private \ud800'):
            preview = {'route': '/api/v1/example', 'method': 'POST', 'body': {'content': value}}
            with self.assertRaisesRegex(CanvasError, 'Preview contains malformed JSON') as error:
                confirmed(client, preview)
            self.assertNotIn('Synthetic private', str(error.exception))
        client.request.assert_not_called()
        self.assertEqual(digest({'score': 3.5}), digest({'score': 3.5}))
        self.assertNotEqual(digest({'score': 3.5}), digest({'score': 3.6}))

    def test_invalid_request_payload_fails_before_transport_and_does_not_log_private_values(self):
        transport = Mock()
        client = Client('https://canvas.example.edu', 'synthetic-private-token', transport)
        for value in (float('nan'), float('inf'), float('-inf'), b'Synthetic private bytes', 'Synthetic private \ud800'):
            with self.assertRaisesRegex(CanvasError, 'no request was sent') as error:
                client.request('/api/v1/example', 'POST', {'content': value})
            self.assertNotIn('Synthetic private', str(error.exception))
        transport.assert_not_called()
