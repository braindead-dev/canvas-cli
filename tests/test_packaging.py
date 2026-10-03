"""The installed distribution and console entry point use the public name."""

import os
import subprocess
import sys
import unittest
from importlib.metadata import distribution
from pathlib import Path


class PackagingTests(unittest.TestCase):
    def test_installed_project_name_and_canvas_console_entrypoint(self):
        package = distribution('canvas-cli')
        self.assertEqual(package.metadata['Name'], 'canvas-cli')
        scripts = {item.name: item.value for item in package.entry_points if item.group == 'console_scripts'}
        self.assertEqual(scripts, {'canvas': 'canvas_cli.cli:main'})

    def test_installed_canvas_executable_renders_offline_help_under_the_short_name(self):
        binary = Path(sys.executable).with_name('canvas.exe' if os.name == 'nt' else 'canvas')
        self.assertTrue(binary.is_file())
        environment = {**os.environ, 'CANVAS_ORIGIN': 'http://invalid.example', 'CANVAS_TOKEN': 'synthetic-not-used'}
        result = subprocess.run([str(binary), 'help', 'auth', '--format', 'brief'],
                                env=environment, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('usage: canvas auth', result.stdout)
        self.assertNotIn('synthetic-not-used', result.stdout + result.stderr)

    def test_module_invocation_help_still_uses_canvas_not_python_or_package_name(self):
        environment = {**os.environ, 'CANVAS_ORIGIN': 'http://invalid.example', 'CANVAS_TOKEN': 'synthetic-not-used'}
        result = subprocess.run([sys.executable, '-m', 'canvas_cli.cli', 'help', 'topic-create', '--format', 'brief'],
                                env=environment, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('usage: canvas topic-create', result.stdout)
        self.assertNotIn('synthetic-not-used', result.stdout + result.stderr)
