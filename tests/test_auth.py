import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from canvas_cli import auth
from canvas_cli.client import CanvasError


class AuthenticationTests(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    @patch('canvas_cli.auth.Client')
    @patch('canvas_cli.auth.secure_keyring')
    def test_rename_reuses_historical_config_credentials_and_snapshot_location(self, keyring, client):
        with tempfile.TemporaryDirectory() as folder:
            legacy = Path(folder) / '.config' / 'canvas-pocket' / 'config.json'
            legacy.parent.mkdir(parents=True)
            legacy.write_text(json.dumps({'origin': 'https://canvas.example.edu'}))
            keyring.return_value.get_password.return_value = 'synthetic-saved-token'
            with patch('canvas_cli.auth.Path.home', return_value=Path(folder)):
                self.assertEqual(auth.config_path(), legacy)
                self.assertIs(auth.connect(), client.return_value)
            keyring.return_value.get_password.assert_called_once_with('canvas-pocket', 'https://canvas.example.edu')
            client.assert_called_once_with('https://canvas.example.edu', 'synthetic-saved-token')
            keyring.return_value.set_password.assert_not_called()
            self.assertEqual(list(legacy.parent.parent.iterdir()), [legacy.parent])

    @patch.dict(os.environ, {'CANVAS_ORIGIN': 'https://canvas.example.edu/', 'CANVAS_TOKEN': 'synthetic-token'}, clear=True)
    @patch('canvas_cli.auth.Client')
    @patch('canvas_cli.auth.secure_keyring')
    @patch('canvas_cli.auth.config_path')
    def test_environment_connection_needs_no_config_or_keyring(self, configuration, keyring, client):
        self.assertIs(auth.connect(), client.return_value)
        client.assert_called_once_with('https://canvas.example.edu', 'synthetic-token')
        configuration.assert_not_called()
        keyring.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    @patch('canvas_cli.auth.Client')
    @patch('canvas_cli.auth.secure_keyring')
    @patch('canvas_cli.auth.load', return_value='https://canvas.example.edu')
    def test_saved_connection_uses_selected_origin_key(self, load, keyring, client):
        keyring.return_value.get_password.return_value = 'synthetic-saved-token'
        self.assertIs(auth.connect(), client.return_value)
        keyring.return_value.get_password.assert_called_once_with(auth.SERVICE, load.return_value)
        client.assert_called_once_with(load.return_value, 'synthetic-saved-token')

    @patch.dict(os.environ, {'CANVAS_ORIGIN': 'https://canvas.example.edu'}, clear=True)
    @patch('canvas_cli.auth.Client')
    @patch('canvas_cli.auth.secure_keyring')
    def test_missing_token_never_constructs_client(self, keyring, client):
        keyring.return_value.get_password.return_value = None
        with self.assertRaisesRegex(CanvasError, 'No credential found'):
            auth.connect()
        client.assert_not_called()

    def test_configuration_rejects_malformed_shapes_without_private_diagnostics(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            for value in ([], None, 7, {'origin': None}, {'origin': []},
                          {'origin': 'http://canvas.example.edu'}, {'private': 'Synthetic hidden record'}):
                path.write_text(json.dumps(value))
                with self.subTest(value=value), patch('canvas_cli.auth.config_path', return_value=path):
                    with self.assertRaises(CanvasError) as error:
                        auth.load()
                    self.assertRegex(str(error.exception), 'Run canvas-cli auth login|Use an HTTPS Canvas origin')
                    self.assertNotIn('Synthetic hidden record', str(error.exception))

    @patch('canvas_cli.auth.secure_keyring')
    @patch('canvas_cli.auth.Client')
    @patch('canvas_cli.auth.getpass.getpass')
    @patch('canvas_cli.auth.sys.stdin')
    def test_noninteractive_login_refuses_before_credentials_or_network(self, stdin, prompt, client, keyring):
        stdin.isatty.return_value = False
        with self.assertRaisesRegex(CanvasError, 'interactive terminal'):
            auth.login('https://canvas.example.edu')
        prompt.assert_not_called()
        client.assert_not_called()
        keyring.assert_not_called()

    @patch('canvas_cli.auth.secure_keyring')
    @patch('canvas_cli.auth.Client')
    @patch('canvas_cli.auth.getpass.getpass', return_value=' synthetic-token ')
    @patch('canvas_cli.auth.sys.stdin')
    def test_failed_authentication_never_saves_credentials_or_configuration(self, stdin, prompt, client, keyring):
        stdin.isatty.return_value = True
        client.return_value.request.side_effect = CanvasError('Authentication failed', status=401)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            with (patch('canvas_cli.auth.config_path', return_value=path),
                  redirect_stderr(StringIO()), self.assertRaises(CanvasError)):
                auth.login('https://canvas.example.edu')
            keyring.assert_not_called()
            self.assertFalse(path.exists())

    @patch('canvas_cli.auth.secure_keyring')
    @patch('canvas_cli.auth.Client')
    @patch('canvas_cli.auth.getpass.getpass', return_value=' synthetic-token ')
    @patch('canvas_cli.auth.sys.stdin')
    def test_login_stores_only_origin_privately_after_own_profile_validation(self, stdin, prompt, client, keyring):
        stdin.isatty.return_value = True
        client.return_value.host = 'https://canvas.example.edu'
        client.return_value.request.return_value = ({'id': 7}, '')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            output = StringIO()
            with patch('canvas_cli.auth.config_path', return_value=path), redirect_stderr(output):
                result = auth.login('https://canvas.example.edu/')
            client.assert_called_once_with('https://canvas.example.edu', 'synthetic-token')
            client.return_value.request.assert_called_once_with('/api/v1/users/self/profile')
            keyring.return_value.set_password.assert_called_once_with(auth.SERVICE, 'https://canvas.example.edu', 'synthetic-token')
            self.assertEqual(json.loads(path.read_text()), {'origin': 'https://canvas.example.edu'})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('synthetic-token', output.getvalue() + str(result))

    @patch('canvas_cli.auth.secure_keyring')
    @patch('canvas_cli.auth.Client')
    @patch('canvas_cli.auth.getpass.getpass', return_value='synthetic-token')
    @patch('canvas_cli.auth.sys.stdin')
    def test_unidentified_profile_never_saves_a_token(self, stdin, prompt, client, keyring):
        stdin.isatty.return_value = True
        for profile in (None, [], {}, {'id': True}, {'id': 0}, {'id': '7'}):
            with self.subTest(profile=profile):
                client.return_value.request.return_value = (profile, '')
                with redirect_stderr(StringIO()), self.assertRaisesRegex(CanvasError, 'did not identify'):
                    auth.login('https://canvas.example.edu')
        keyring.assert_not_called()

    @patch.dict(os.environ, {'CANVAS_ORIGIN': 'https://canvas.example.edu', 'CANVAS_TOKEN': 'synthetic-token'}, clear=True)
    @patch('canvas_cli.auth.Client')
    @patch('canvas_cli.auth.secure_keyring')
    def test_logout_removes_local_keyring_only_not_environment_or_server(self, keyring, client):
        keyring.return_value.get_password.return_value = 'synthetic-saved-token'
        result = auth.logout()
        self.assertTrue(result['local_credential_removed'])
        keyring.return_value.delete_password.assert_called_once_with(auth.SERVICE, 'https://canvas.example.edu')
        self.assertEqual(os.environ['CANVAS_TOKEN'], 'synthetic-token')
        client.assert_not_called()

    def test_plaintext_or_fallback_keyring_is_rejected(self):
        backend = type('SyntheticBackend', (), {'__module__': 'keyrings.alt.file'})
        fake = Mock(get_keyring=Mock(return_value=backend()))
        with (patch.dict('sys.modules', {'keyring': fake}),
              self.assertRaisesRegex(CanvasError, 'No supported OS keyring')):
            auth.secure_keyring()
