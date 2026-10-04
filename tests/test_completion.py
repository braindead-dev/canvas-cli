"""Offline parser-derived completion, including actual Bash/Zsh function invocation."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from canvas_cli.arguments import parser
from canvas_cli.cli import run
from canvas_cli.client import CanvasError
from canvas_cli.completion import candidates, script
from canvas_cli.formatting import brief


class CompletionTests(unittest.TestCase):
    def complete(self, *words):
        return candidates(parser(), ['canvas', *words], len(words))['completion_candidates']

    def test_root_prefix_executable_and_global_options_come_from_actual_parser(self):
        self.assertIn('courses', self.complete(''))
        self.assertEqual(self.complete('what-if-r'), ['what-if-reset'])
        self.assertEqual(self.complete('--max-p'), ['--max-pages'])
        self.assertEqual(self.complete('--ver'), ['--version'])
        self.assertEqual(self.complete('courses', '--ver'), [])
        self.assertEqual(candidates(parser(), ['can'], 0)['completion_candidates'], ['canvas'])
        self.assertEqual(candidates(parser(), ['not-canvas'], 0)['completion_candidates'], [])
        self.assertIn('courses', candidates(parser(), ['canvas'], 1)['completion_candidates'])

    def test_nested_auth_commands_and_required_origin_flag_are_discovered_offline(self):
        self.assertEqual(self.complete('auth', 'l'), ['login', 'logout'])
        self.assertEqual(self.complete('auth', 'login', '--ori'), ['--origin'])
        self.assertEqual(self.complete('auth', 'login', '--origin', ''), [])
        self.assertIn('--origin', self.complete('--format', 'brief', 'auth', 'login', ''))

    def test_enum_choices_required_free_values_and_long_equals_values_are_distinct(self):
        self.assertEqual(self.complete('files', '123', '--context', 'g'), ['group'])
        self.assertEqual(self.complete('files', '123', '--context=g'), ['--context=group'])
        self.assertEqual(self.complete('files', '123', '--context='), ['--context=course', '--context=group'])
        self.assertEqual(self.complete('files', '123', '--max-pages', '--f'), [])
        self.assertEqual(self.complete('files', '123', '--max-pages', '--format=b'), [])
        self.assertEqual(self.complete('files', '123', '--yes=true'), [])
        self.assertEqual(self.complete('courses', '--active=true', ''), [])
        self.assertEqual(self.complete('topic-pod'), ['topic-podcast'])
        self.assertEqual(self.complete('announcement-pod'), ['announcement-podcast'])
        self.assertEqual(self.complete('topic-podcast', '123', '456', '--mode', 'm'), ['moderator-posts'])
        self.assertEqual(self.complete('announcement-podcast', '123', '456', '--acknowledge-pod'), ['--acknowledge-podcast-feed-change'])

    def test_bash_split_equals_keeps_only_rhs_candidates_and_later_command_navigation(self):
        self.assertEqual(self.complete('files', '123', '--context', '=', 'g'), ['group'])
        self.assertEqual(self.complete('files', '123', '--context', '='), ['=course', '=group'])
        self.assertEqual(self.complete('--format', '=', 'brief', 'files', '123', '--cont'), ['--context'])

    def test_boolean_aliases_nonrepeatable_flags_and_repeatable_append_choices(self):
        self.assertEqual(self.complete('group-users', '123', '--no-ex'), ['--no-exclude-inactive'])
        values = self.complete('group-users', '123', '--no-exclude-inactive', '--ex')
        self.assertNotIn('--exclude-inactive', values)
        self.assertIn('--enrollment-type', self.complete('course-users', '123', '--enrollment-type', 'student', '--en'))
        self.assertEqual(self.complete('course-users', '123', '--enrollment-type', 't'), ['ta', 'teacher'])

    def test_positional_choice_optional_help_target_and_mutual_exclusion_are_preserved(self):
        self.assertEqual(self.complete('completion', 'z'), ['zsh'])
        self.assertEqual(self.complete('help', 'what-if-r'), ['what-if-reset'])
        values = self.complete('feedback-comments', '123', '456', '--all-attempts', '--att')
        self.assertEqual(values, [])
        self.assertNotIn('--all-attempts', self.complete('feedback-comments', '123', '456', '--attempt', '1', '--all'))

    def test_numeric_or_filename_values_are_never_queried_or_guessed(self):
        self.assertEqual(self.complete('files', '12'), [])
        self.assertEqual(self.complete('post', '123', '456', '--message-file', 'synthetic-private'), [])
        self.assertEqual(self.complete('not-a-command', ''), [])
        self.assertEqual(self.complete('files', '123', '--unknown-option', ''), [])
        self.assertEqual(self.complete('files', '123', 'unexpected-positional', ''), [])
        self.assertEqual(self.complete('files', '123', '--', '--cont'), [])

    def test_synthetic_variable_and_fixed_nargs_are_completed_without_type_converters(self):
        root = argparse.ArgumentParser()
        root.add_argument('--many', nargs='+', choices=('one', 'two'))
        root.add_argument('--optional', nargs='?', choices=('optional',))
        root.add_argument('--pair', nargs=2, choices=('left', 'right'))
        root.add_argument('--enabled', action='store_true')
        root.add_argument('position', nargs='*', choices=('tail',))
        self.assertEqual(candidates(root, ['canvas', '--many', 'o'], 2)['completion_candidates'], ['one'])
        self.assertIn('--enabled', candidates(root, ['canvas', '--many', 'one', '--e'], 3)['completion_candidates'])
        self.assertEqual(candidates(root, ['canvas', '--pair', 'left', 'r'], 3)['completion_candidates'], ['right'])
        self.assertEqual(candidates(root, ['canvas', '--optional', '--enabled', 't'], 3)['completion_candidates'], ['tail'])
        self.assertEqual(candidates(root, ['canvas', '--many=one', 't'], 2)['completion_candidates'], ['two'])
        self.assertEqual(candidates(root, ['canvas', 'tail', 't'], 2)['completion_candidates'], ['tail'])

    def test_hidden_arguments_and_control_characters_are_never_emitted(self):
        root = argparse.ArgumentParser()
        root.add_argument('--hidden', help=argparse.SUPPRESS, choices=('hidden-choice',))
        root.add_argument('--visible', choices=('good', 'bad\nvalue', 'bad\x1bvalue', 1))
        self.assertEqual(candidates(root, ['canvas', '--h'], 1)['completion_candidates'], ['--help'])
        self.assertEqual(candidates(root, ['canvas', '--hidden', ''], 2)['completion_candidates'], [])
        self.assertEqual(candidates(root, ['canvas', '--visible', ''], 2)['completion_candidates'], ['1', 'good'])
        for words, cursor in (([], -1), ([], True), ([], 2), ('canvas', 1), ([None], 0),
                              (['canvas', 'bad\nword'], 1), (['canvas', 'bad\x00word'], 1),
                              (['canvas', 'x' * 4097], 1), (['canvas'] * 129, 1)):
            with self.subTest(cursor=cursor), self.assertRaises(CanvasError):
                candidates(parser(), words, cursor)

    def test_remainder_words_are_literal_even_when_they_resemble_known_flags(self):
        root = argparse.ArgumentParser()
        root.add_argument('--enabled', action='store_true')
        root.add_argument('--global-flag', action='store_true')
        root.add_argument('rest', nargs=argparse.REMAINDER, choices=('one', 'two', '--enabled'))
        self.assertEqual(candidates(root, ['canvas', 'one', '--enabled', ''], 3)['completion_candidates'], ['--enabled', 'one', 'two'])

    def test_new_commands_and_enum_values_appear_without_a_second_manual_catalog(self):
        root = argparse.ArgumentParser()
        commands = root.add_subparsers()
        commands.add_parser('synthetic-new').add_argument('--mode', choices=('new-mode',))
        self.assertEqual(candidates(root, ['canvas', 'synthetic'], 1)['completion_candidates'], ['synthetic-new'])
        self.assertEqual(candidates(root, ['canvas', 'synthetic-new', '--mode', 'n'], 3)['completion_candidates'], ['new-mode'])

    @patch('canvas_cli.auth.connect')
    @patch('canvas_cli.auth.config_path')
    def test_cli_completion_and_scripts_do_not_access_auth_config_or_canvas(self, config, connect):
        args = parser().parse_args(['--format', 'brief', 'complete', '--cword', '1', '--', 'canvas', 'cou'])
        self.assertEqual(brief(run(args)), 'course-groups\ncourse-users\ncourses')
        args = parser().parse_args(['completion', 'bash'])
        result = run(args)
        self.assertEqual(result['completion_shell'], 'bash')
        self.assertIn('complete -o default -F _canvas canvas', brief(result))
        connect.assert_not_called()
        config.assert_not_called()

    def test_scripts_only_register_reviewable_functions_without_dotfile_or_token_access(self):
        for shell in ('bash', 'zsh'):
            result = script(shell)
            self.assertIn('canvas --format brief complete', result['completion_script'])
            self.assertNotIn('CANVAS_TOKEN', result['completion_script'])
            self.assertNotIn('eval', result['completion_script'])
            self.assertIn('No dotfiles', result['note'])
        with self.assertRaises(CanvasError):
            script('unsupported-shell')


class ShellCompletionTests(unittest.TestCase):
    def invoke(self, *args):
        environment = {**os.environ, 'CANVAS_ORIGIN': 'http://invalid.example', 'CANVAS_TOKEN': 'synthetic-secret-not-used'}
        return subprocess.run([sys.executable, '-m', 'canvas_cli.cli', *args], env=environment,
                              capture_output=True, text=True, timeout=15, check=False)

    def shell(self, name, code):
        binary = shutil.which(name)
        if not binary:
            self.skipTest(name + ' is unavailable')
        environment = {**os.environ, 'CANVAS_ORIGIN': 'http://invalid.example', 'CANVAS_TOKEN': 'synthetic-secret-not-used',
                       'PATH': str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', '')}
        return subprocess.run([binary, '-c', code], env=environment, capture_output=True, text=True, timeout=15, check=False)

    def test_root_help_is_short_offline_and_command_help_keeps_exact_native_options(self):
        result = self.invoke('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(len(result.stdout.splitlines()), 60)
        self.assertLess(len(result.stdout), 3000)
        self.assertIn('canvas help COMMAND', result.stdout)
        self.assertIn('Safety categories', result.stdout)
        result = self.invoke('what-if-set', '--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--acknowledge-forecast-change', result.stdout)

    def test_installed_offline_candidates_and_invalid_words_do_not_echo_secret_inputs(self):
        result = self.invoke('--format', 'brief', 'complete', '--cword', '3', '--', 'canvas', 'files', '123', '--co')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '--context')
        result = self.invoke('complete', '--cword', '3', '--', 'canvas', 'files', '123', 'synthetic-private-word')
        self.assertEqual(json.loads(result.stdout)['completion_candidates'], [])
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)
        result = self.invoke('complete', '--cword', '-1', '--', 'canvas', 'synthetic-private-word')
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)

    def test_actual_bash_function_dispatches_only_offline_completion_and_handles_split_equals(self):
        code = script('bash')['completion_script'] + '''
COMP_WORDS=(canvas files 123 --context = g)
COMP_CWORD=5
_canvas
printf '%s\n' "${COMPREPLY[@]}"
'''
        result = self.shell('bash', code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'group')

    def test_actual_zsh_function_registers_and_provides_nested_auth_candidates(self):
        code = '''compdef() { :; }
compadd() { shift; printf '%s\n' "$@"; }
''' + script('zsh')['completion_script'] + '''
words=(canvas auth login --ori)
CURRENT=4
_canvas
'''
        result = self.shell('zsh', code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '--origin')

    def test_actual_zsh_uses_native_filename_fallback_only_when_parser_has_no_candidates(self):
        code = '''compdef() { :; }
compadd() { return 99; }
_files() { printf '%s\n' 'synthetic-filename-fallback'; }
''' + script('zsh')['completion_script'] + '''
words=(canvas post 123 456 --message-file example)
CURRENT=6
_canvas
'''
        result = self.shell('zsh', code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'synthetic-filename-fallback')
