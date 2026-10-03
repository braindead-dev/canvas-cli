"""The installed distribution and console entry point use the public name."""

import unittest
from importlib.metadata import distribution


class PackagingTests(unittest.TestCase):
    def test_installed_name_and_console_entrypoint_are_canvas_cli(self):
        package = distribution('canvas-cli')
        self.assertEqual(package.metadata['Name'], 'canvas-cli')
        scripts = {item.name: item.value for item in package.entry_points if item.group == 'console_scripts'}
        self.assertEqual(scripts, {'canvas-cli': 'canvas_cli.cli:main'})

