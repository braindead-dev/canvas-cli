import unittest

from canvas_pocket.client import CanvasError
from canvas_pocket.doctor import course_doctor


class FakeClient:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def request(self, route):
        self.calls.append(route)
        if len(self.calls) == 1:
            return {'id': 101}, ''
        if self.error:
            raise self.error
        return [], ''


class DoctorTests(unittest.TestCase):
    def test_rate_limit_stops_remaining_probes(self):
        client = FakeClient(CanvasError('Canvas rate limit reached. Wait before retrying', status=429))
        data = course_doctor(client, '101')
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(data['probes'][0]['status'], 'rate_limited_429')
        self.assertTrue(all(row['status'] == 'not_checked_after_rate_limit'
                            for row in data['probes'][1:]))

    def test_wrong_course_is_rejected(self):
        client = FakeClient()
        with self.assertRaisesRegex(CanvasError, 'different course'):
            course_doctor(client, '999')
        self.assertEqual(len(client.calls), 1)

    def test_network_failure_is_not_a_permission_probe(self):
        client = FakeClient(CanvasError('Network failure'))
        with self.assertRaises(CanvasError):
            course_doctor(client, '101')
        self.assertEqual(len(client.calls), 2)
