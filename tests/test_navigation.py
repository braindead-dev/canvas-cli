import argparse
import unittest
from unittest.mock import patch

from canvas_pocket.cli import brief, parser, run
from canvas_pocket.client import CanvasError
from canvas_pocket.navigation import command_help


class NavigationTests(unittest.TestCase):
    def test_every_command_is_classified_and_all_help_pages_render(self):
        root = parser()
        action = next(item for item in root._actions if isinstance(item, argparse._SubParsersAction))
        data = command_help(root)
        names = [row['command'] for rows in data['command_index'].values() for row in rows]
        self.assertEqual(set(names), set(action.choices))
        self.assertEqual(len(names), len(set(names)))
        for name in names:
            with self.subTest(name=name):
                help_page = command_help(root, name)
                self.assertIn('usage:', help_page['help_text'])
                self.assertIn(name, help_page['help_text'])

    @patch('canvas_pocket.cli.Client')
    @patch('canvas_pocket.cli.secure_keyring')
    def test_help_does_not_access_credentials_or_canvas(self, keyring, client):
        result = run(parser().parse_args(['help', 'task-delete']))
        self.assertIn('--confirm', result['help_text'])
        self.assertIn('Canvas writes', result['safety'])
        self.assertIn('task-delete', brief(result))
        keyring.assert_not_called()
        client.assert_not_called()

    def test_search_filters_actual_command_options_and_safety(self):
        data = command_help(parser(), search='submission')
        names = [row['command'] for rows in data['command_index'].values() for row in rows]
        self.assertIn('submission-comment', names)
        self.assertNotIn('pages', names)
        self.assertIn('Read-only', data['command_index'])
        self.assertIn('Canvas writes (preview-first)', data['command_index'])
        empty = command_help(parser(), search='nonexistent-synthetic-command')
        self.assertIn('No matching commands', brief(empty))
        for kwargs in ({'topic': 'planner', 'search': 'planner'}, {'search': ' '}, {'topic': 'not-real'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                command_help(parser(), **kwargs)

    def test_native_get_side_effects_are_not_classified_as_side_effect_free(self):
        for name in ('notification-preferences', 'get'):
            self.assertEqual(command_help(parser(), name)['safety'], 'Canvas GET (server-side effects possible)')
        self.assertEqual(command_help(parser(), 'channels')['safety'], 'Read-only')
        self.assertEqual(command_help(parser(), 'notification-preferences-set')['safety'], 'Canvas writes (preview-first)')


if __name__ == '__main__': unittest.main()
