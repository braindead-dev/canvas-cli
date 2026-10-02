import unittest
from unittest.mock import Mock

from canvas_pocket.client import CanvasError
from canvas_pocket.progress import module_progress


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.module = {'id': 2, 'name': 'Synthetic module', 'state': 'started',
                       'requirement_type': 'one'}

    def test_requirements_distinguish_reported_false_and_unknown(self):
        self.client.list.side_effect = [[self.module], [
            {'id': 3, 'title': 'Read', 'completion_requirement':
             {'type': 'must_view', 'completed': True}},
            {'id': 4, 'title': 'Submit', 'completion_requirement':
             {'type': 'must_submit', 'completed': False},
             'content_details': {'locked_for_user': True, 'due_at': '2026-10-02T00:00:00Z'}},
            {'id': 5, 'title': 'Unknown', 'completion_requirement': {'type': 'must_contribute'}},
            {'id': 6, 'title': 'Optional'}, {'id': 7, 'published': False}]]
        result = module_progress(self.client, '1', 4)
        row = result['module_progress'][0]
        self.assertEqual(row['requirements'], {'required': 3, 'completed': 1,
                                              'incomplete': 1, 'unknown': 1})
        self.assertEqual([x['completion'] for x in row['items']],
                         ['completed', 'incomplete', 'unknown', 'not_required'])
        self.assertTrue(row['items'][1]['locked_for_user'])
        self.assertEqual(row['state'], 'started')  # one satisfied requirement is not an inferred completion.
        self.assertTrue(result['complete'])
        self.client.request.assert_not_called()
        self.assertEqual(self.client.list.call_args.args,
                         ('/api/v1/courses/1/modules/2/items?per_page=100&include%5B%5D=content_details', 4))

    def test_locked_and_unpublished_modules_do_not_fetch_items(self):
        self.client.list.return_value = [
            {**self.module, 'state': 'locked'}, {'id': 8, 'published': False}]
        result = module_progress(self.client, '1', 4)
        self.assertFalse(result['complete'])
        self.assertEqual(len(result['module_progress']), 1)
        self.assertIsNone(result['module_progress'][0]['requirements'])
        self.client.list.assert_called_once_with('/api/v1/courses/1/modules?per_page=100', 4)

    def test_permission_denial_is_partial_but_auth_and_rate_limit_fail(self):
        for status in (403, 404, 401, 429, 500):
            self.client.list.side_effect = [[self.module], CanvasError('Synthetic error', status=status)]
            with self.subTest(status=status):
                if status in (403, 404):
                    result = module_progress(self.client, '1', 3)
                    self.assertFalse(result['complete'])
                    self.assertEqual(result['unavailable'][0]['status'], status)
                else:
                    with self.assertRaises(CanvasError) as error:
                        module_progress(self.client, '1', 3)
                    self.assertEqual(error.exception.status, status)

    def test_malformed_data_fails_without_completion_events(self):
        for bad in ({'id': True}, {'id': 3, 'completion_requirement': 'bad'},
                    {'id': 3, 'content_details': 'bad'}):
            self.client.list.side_effect = [[self.module], [bad]]
            with self.subTest(bad=bad), self.assertRaises(CanvasError):
                module_progress(self.client, '1', 3)
        self.client.request.assert_not_called()


if __name__ == '__main__': unittest.main()
