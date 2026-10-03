import argparse
import json
import unittest
from unittest.mock import patch

from canvas_pocket.cli import brief, parser, run
from canvas_pocket.client import CanvasError
from canvas_pocket.navigation import command_help, command_schema


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
        for name in ('notification-preferences', 'root-folder', 'my-root', 'folder-path', 'get'):
            self.assertEqual(command_help(parser(), name)['safety'], 'Canvas GET (server-side effects possible)')
        self.assertEqual(command_help(parser(), 'channels')['safety'], 'Read-only')
        self.assertEqual(command_help(parser(), 'notification-preferences-set')['safety'], 'Canvas writes (preview-first)')

    def test_all_schemas_derive_from_the_actual_parser_are_serializable_and_classified(self):
        root = parser()
        selector = next(action for action in root._actions if isinstance(action, argparse._SubParsersAction))
        data = command_schema(root)
        self.assertEqual(data['schema_version'], 1)
        self.assertEqual({command['command'] for command in data['commands']}, set(selector.choices))
        self.assertEqual(json.loads(json.dumps(data)), data)
        for command in data['commands']:
            self.assertEqual(command['safety'], command_help(root, command['command'])['safety'])
            actions = [action for action in selector.choices[command['command']]._actions
                       if not isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)) and action.help != argparse.SUPPRESS]
            self.assertEqual([row['destination'] for row in command['arguments']], [action.dest for action in actions])

    def test_schema_preserves_boolean_negation_repeatable_choices_and_suppressed_global_defaults(self):
        data = command_schema(parser(), 'group-users')['commands'][0]
        arguments = {row['destination']: row for row in data['arguments']}
        self.assertEqual(arguments['exclude_inactive']['flags'], ['--exclude-inactive', '--no-exclude-inactive'])
        self.assertEqual(arguments['exclude_inactive']['action'], 'BooleanOptionalAction')
        self.assertTrue(arguments['max_pages']['default_suppressed'])
        self.assertNotIn('default', arguments['max_pages'])
        course = command_schema(parser(), 'course-users')['commands'][0]
        roles = next(row for row in course['arguments'] if row['destination'] == 'enrollment_type')
        self.assertTrue(roles['accumulates_values'])
        self.assertIn('ta', roles['choices'])
        self.assertEqual(roles['default'], [])
        required = next(row for row in course['arguments'] if row['destination'] == 'context_id')
        self.assertTrue(required['positional'])
        self.assertTrue(required['required'])
        self.assertEqual(required['value_type'], 'identifier')

    def test_schema_includes_nested_auth_commands_and_parser_defined_exclusion_groups(self):
        auth = command_schema(parser(), 'auth')['commands'][0]['subcommand_selectors'][0]
        self.assertTrue(auth['required'])
        self.assertEqual(set(auth['commands']), {'login', 'status', 'logout'})
        origin = next(row for row in auth['commands']['login']['arguments'] if row['destination'] == 'origin')
        self.assertTrue(origin['required'])
        synthetic = argparse.ArgumentParser()
        sub = synthetic.add_subparsers(dest='command', required=True)
        child = sub.add_parser('help')
        group = child.add_mutually_exclusive_group(required=True)
        group.add_argument('--one', action='store_true')
        group.add_argument('--two', action='store_true')
        data = command_schema(synthetic, 'help')['commands'][0]
        self.assertEqual(data['mutually_exclusive_groups'], [{'required': True, 'destinations': ['one', 'two']}])

    @patch('canvas_pocket.cli.Client')
    @patch('canvas_pocket.cli.secure_keyring')
    @patch('canvas_pocket.cli.config_path')
    def test_schema_and_search_run_offline_without_credentials_or_configuration(self, config, keyring, client):
        data = run(parser().parse_args(['schema', '--search', 'invitation']))
        self.assertIn('enrollment-accept', [row['command'] for row in data['commands']])
        self.assertIn('Runtime account checks', data['note'])
        self.assertIn('Canvas writes', brief(data))
        config.assert_not_called()
        keyring.assert_not_called()
        client.assert_not_called()
        empty = command_schema(parser(), search='nonexistent-synthetic-command')
        self.assertEqual(empty['commands'], [])
        self.assertIn('No matching commands', brief(empty))
        for kwargs in ({'topic': 'schema', 'search': 'schema'}, {'search': ' '}, {'topic': 'not-real'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanvasError):
                command_schema(parser(), **kwargs)

    def test_unsupported_parser_defaults_fail_without_dumping_a_value_or_path(self):
        synthetic = argparse.ArgumentParser()
        sub = synthetic.add_subparsers(dest='command', required=True)
        child = sub.add_parser('help')
        child.add_argument('--value', default=object())
        with self.assertRaisesRegex(CanvasError, 'no value was printed'):
            command_schema(synthetic, 'help')


if __name__ == '__main__': unittest.main()
