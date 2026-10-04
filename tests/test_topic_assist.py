"""Schema-discovered preferences do not grant translation or summary access."""

import copy
import io
import json
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from test_topic_view import ViewClient

from canvas_cli.arguments import parser
from canvas_cli.cli import run
from canvas_cli.client import CanvasError
from canvas_cli.formatting import brief
from canvas_cli.navigation import command_help
from canvas_cli.topic_view import change, languages, read


class TopicAssistTests(unittest.TestCase):
    def setUp(self):
        self.client = ViewClient()

    def preview(self, values, **kwargs):
        return change(self.client, '123', '9', values, acknowledge=True, **kwargs)

    def execute(self, values):
        preview = self.preview(values)
        return self.preview(values, yes=True, confirm=preview['confirm'])

    def mutations(self):
        return [row for row in self.client.calls if row[0] == 'CanvasTopicViewSet']

    def test_catalog_is_sorted_complete_deprecation_aware_and_has_no_participant_or_identity_query(self):
        rows = [{'name': f'LOCALE_{index}', 'isDeprecated': index == 2, 'private': 'synthetic-private'}
                for index in reversed(range(300))]
        self.client.language_type['enumValues'] = rows
        result = languages(self.client)
        values = result['discussion_languages']['values']
        self.assertEqual(len(values), 300)
        self.assertEqual([row['enum'] for row in values], sorted(row['name'] for row in rows))
        self.assertEqual(next(row for row in values if row['enum'] == 'LOCALE_2'), {'enum': 'LOCALE_2', 'deprecated': True})
        self.assertEqual([row[0] for row in self.client.calls], ['CanvasDiscussionLanguages'])
        self.assertEqual(self.client.calls[0][2], {})
        self.assertIn('includeDeprecated: true', self.client.calls[0][1])
        self.assertFalse(result['discussion_languages']['translation_service_access_verified'])
        self.assertIn('LOCALE_2 (deprecated)', brief(result))
        self.assertNotIn('synthetic-private', json.dumps(result))
        self.assertEqual(command_help(parser(), 'topic-languages')['safety'], 'Read-only')

    def test_missing_denied_duplicate_or_malformed_catalog_never_guesses_fallback_or_leaks(self):
        for row in (None, {}, {'name': 'Other', 'kind': 'ENUM', 'enumValues': []},
                    {'name': 'PreferredLanguageType', 'kind': 'OBJECT', 'enumValues': []},
                    {'name': 'PreferredLanguageType', 'kind': 'ENUM', 'enumValues': None},
                    {'name': 'PreferredLanguageType', 'kind': 'ENUM', 'enumValues': []}):
            self.client = ViewClient()
            self.client.language_type = row
            with self.subTest(row=row), self.assertRaises(CanvasError) as caught:
                languages(self.client)
            self.assertNotIn('synthetic-private', str(caught.exception))
            self.assertEqual(len(self.client.calls), 1)
        for rows in ([None], [{'name': 'FR'}], [{'name': 'FR', 'isDeprecated': 1}],
                     [{'name': 'FR\nsynthetic-private', 'isDeprecated': False}],
                     [{'name': 1, 'isDeprecated': False}],
                     [{'name': 'FR', 'isDeprecated': False}, {'name': 'FR', 'isDeprecated': True}]):
            self.client = ViewClient()
            self.client.language_type['enumValues'] = rows
            with self.subTest(rows=rows), self.assertRaises(CanvasError) as caught:
                languages(self.client)
            self.assertNotIn('synthetic-private', str(caught.exception))
        self.client = ViewClient()
        self.client.language_error = True
        with self.assertRaises(CanvasError):
            languages(self.client)
        self.assertEqual(len(self.client.calls), 1)

    def test_default_read_avoids_assist_fields_and_opt_in_reads_only_own_stored_metadata(self):
        read(self.client, '123', '9', acknowledge=True)
        documents = [row[1] for row in self.client.calls if row[0] == 'CanvasTopicView']
        self.assertFalse(any(key in document for key in ('preferredLanguage', 'summaryEnabled') for document in documents))
        self.client.calls.clear()
        self.client.own.update(preferredLanguage='PT_BR', summaryEnabled=True)
        result = read(self.client, '123', '9', acknowledge=True, include_assist=True)
        self.assertEqual(result['topic_view']['reported']['preferred_language'], 'PT_BR')
        self.assertTrue(result['topic_view']['reported']['summary_enabled'])
        self.assertIn('preferred_language=PT_BR', brief(result))
        document = next(row[1] for row in self.client.calls if row[0] == 'CanvasTopicView' and 'participant {' in row[1])
        self.assertIn('preferredLanguage summaryEnabled', document)
        self.assertFalse(any(key in document for key in ('summary ', 'translation ', 'discussionEntries', 'message')))
        self.assertFalse(any(row[0] == 'CanvasDiscussionLanguages' for row in self.client.calls))

    def test_language_catalog_precedes_initialization_and_only_selected_optional_field_is_queried(self):
        preview = self.preview({'preferred_language': 'PT_BR'})
        self.assertEqual([row[0] for row in self.client.calls],
                         ['GET', 'CanvasTopicView', 'CanvasDiscussionLanguages', 'CanvasTopicView', 'GET'])
        self.assertEqual(preview['body']['variables']['input'], {'discussionTopicId': '9', 'preferredLanguage': 'PT_BR'})
        self.assertEqual(preview['language_catalogue'], languages(ViewClient())['discussion_languages']['values'])
        own_query = self.client.calls[3][1]
        self.assertIn('preferredLanguage', own_query)
        self.assertNotIn('summaryEnabled', own_query)
        self.assertEqual(self.mutations(), [])

    def test_unknown_locale_or_denied_schema_stops_before_participant_query(self):
        for value in ('UNKNOWN', 'pt_BR', 'pt', 'ENGLISH'):
            self.client = ViewClient()
            with self.subTest(value=value), self.assertRaisesRegex(CanvasError, 'not accepted'):
                self.preview({'preferred_language': value})
            self.assertEqual(self.mutations(), [])
            self.assertFalse(any('participant {' in row[1] for row in self.client.calls if row[0] == 'CanvasTopicView'))
        self.client = ViewClient()
        self.client.language_error = True
        with self.assertRaises(CanvasError):
            self.preview({'preferred_language': 'FR'})
        self.assertFalse(any('participant {' in row[1] for row in self.client.calls if row[0] == 'CanvasTopicView'))

    def test_invalid_language_syntax_or_summary_types_fail_before_network(self):
        for values in ({'preferred_language': ''}, {'preferred_language': 'pt-BR'}, {'preferred_language': True},
                       {'preferred_language': []}, {'preferred_language': 'FR) { private }'},
                       {'summary_enabled': 0}, {'summary_enabled': 'false'}, {'summary_enabled': None}):
            with self.subTest(values=values), self.assertRaises(CanvasError):
                self.preview(values)
        self.assertEqual(self.client.calls, [])

    def test_selected_language_and_summary_are_saved_once_without_shared_marker_or_generation_changes(self):
        source = copy.deepcopy(self.client.row)
        result = self.execute({'preferred_language': 'FR', 'summary_enabled': True})
        self.assertEqual(self.mutations()[0][2]['input'], {'discussionTopicId': '9', 'preferredLanguage': 'FR', 'summaryEnabled': True})
        self.assertEqual(len(self.mutations()), 1)
        self.assertEqual(self.client.row, source)
        self.assertEqual(self.client.own['sortOrder'], 'inherit')
        for field in ('preferred_language', 'summary_enabled'):
            self.assertTrue(result['verification'][field]['stored_override_verified'])
            self.assertFalse(result['verification'][field]['effective_value_verified'])
        self.assertIn('not translation/summary access or generation proof', result['note'])
        self.assertFalse(any('/summaries' in row[1] or '/translate' in row[1] for row in self.client.calls))

    def test_deprecated_schema_value_remains_accepted_and_catalog_order_is_not_confirmation_state(self):
        self.client.language_type['enumValues'][1]['isDeprecated'] = True
        preview = self.preview({'preferred_language': 'FR'})
        self.client.language_type['enumValues'].reverse()
        result = self.preview({'preferred_language': 'FR'}, yes=True, confirm=preview['confirm'])
        self.assertTrue(result['verification']['preferred_language']['stored_override_verified'])
        self.assertEqual(len(self.mutations()), 1)

    def test_summary_setting_and_language_clearing_do_not_depend_on_introspection_or_generation_authority(self):
        self.client.language_error = True
        self.client.own.update(preferredLanguage='FR', summaryEnabled=True)
        result = self.execute({'preferred_language': None, 'summary_enabled': False})
        self.assertEqual(self.mutations()[0][2]['input'], {'discussionTopicId': '9', 'preferredLanguage': None, 'summaryEnabled': False})
        self.assertIsNone(result['topic_view']['reported']['preferred_language'])
        self.assertFalse(result['topic_view']['reported']['summary_enabled'])
        self.assertFalse(result['verification']['preferred_language']['stored_override_verified'])
        self.assertTrue(result['verification']['summary_enabled']['stored_override_verified'])
        self.assertFalse(any(row[0] == 'CanvasDiscussionLanguages' for row in self.client.calls))

    def test_ignored_clear_of_hidden_unsupported_locale_cannot_claim_raw_storage_cleared(self):
        self.client.own['preferredLanguage'] = 'UNSUPPORTED_OLD_LOCALE'
        self.client.ignored = {'preferredLanguage'}
        result = self.execute({'preferred_language': None})
        self.assertIsNone(result['topic_view']['reported']['preferred_language'])
        self.assertEqual(self.client.own['preferredLanguage'], 'UNSUPPORTED_OLD_LOCALE')
        self.assertFalse(result['verification']['preferred_language']['stored_override_verified'])
        self.assertIn('clearing its raw storage stays unverified', brief(result))

    def test_supported_ignored_language_or_summary_write_fails_without_retry(self):
        for ignored, values in (('preferredLanguage', {'preferred_language': 'FR'}),
                                ('summaryEnabled', {'summary_enabled': True})):
            self.client = ViewClient()
            self.client.ignored = {ignored}
            with self.subTest(ignored=ignored), self.assertRaisesRegex(CanvasError, 'Some changes may have applied'):
                self.execute(values)
            self.assertEqual(len(self.mutations()), 1)
        self.client = ViewClient()
        self.client.own['preferredLanguage'] = 'FR'
        self.client.ignored = {'preferredLanguage'}
        with self.assertRaises(CanvasError):
            self.execute({'preferred_language': None})

    def test_catalog_or_selected_own_preferences_change_invalidates_confirmation(self):
        for mode in ('catalog', 'deprecated', 'language', 'summary'):
            self.client = ViewClient()
            values = {'preferred_language': 'FR', 'summary_enabled': True}
            preview = self.preview(values)
            if mode == 'catalog':
                self.client.language_type['enumValues'].append({'name': 'NEW_LOCALE', 'isDeprecated': False})
            elif mode == 'deprecated':
                self.client.language_type['enumValues'][0]['isDeprecated'] = True
            elif mode == 'language':
                self.client.own['preferredLanguage'] = 'PT_BR'
            else:
                self.client.own['summaryEnabled'] = True
            with self.subTest(mode=mode), self.assertRaisesRegex(CanvasError, 'Preview changed'):
                self.preview(values, yes=True, confirm=preview['confirm'])
            self.assertEqual(self.mutations(), [])

    def test_malformed_own_assist_readback_is_sanitized_and_nullable_metadata_is_not_invented(self):
        for values in ({'preferredLanguage': 1}, {'preferredLanguage': 'FR\nsynthetic-private'}, {'summaryEnabled': 'true'}):
            self.client = ViewClient()
            own = {'sortOrder': 'desc', 'expanded': False, 'showPinnedEntries': True,
                   'preferredLanguage': None, 'summaryEnabled': False, **values}
            self.client.query_patch = {'participant': own}
            with self.subTest(values=values), self.assertRaises(CanvasError) as caught:
                read(self.client, '123', '9', acknowledge=True, include_assist=True)
            self.assertNotIn('synthetic-private', str(caught.exception))
        self.client = ViewClient()
        self.client.own['summaryEnabled'] = None
        result = read(self.client, '123', '9', acknowledge=True, include_assist=True)
        self.assertIsNone(result['topic_view']['reported']['summary_enabled'])

    def test_post_mutation_optional_readback_failure_does_not_leak_or_retry(self):
        self.client.after_patch = {'participant': {'sortOrder': 'desc', 'expanded': False, 'showPinnedEntries': True,
                                                  'preferredLanguage': 'FR\nsynthetic-private'}}
        with self.assertRaises(CanvasError) as caught:
            self.execute({'preferred_language': 'FR'})
        self.assertEqual(len(self.mutations()), 1)
        self.assertIn('could not be independently verified', str(caught.exception))
        self.assertNotIn('synthetic-private', str(caught.exception))

    @patch('canvas_cli.auth.connect')
    def test_parser_dispatch_optional_read_catalog_and_false_clear_values(self, connect):
        connect.return_value = self.client
        root = parser()
        self.assertIn('discussion_languages', run(root.parse_args(['topic-languages'])))
        result = run(root.parse_args(['topic-view', '123', '9', '--include-assist-preferences',
                                      '--acknowledge-participant-initialization']))
        self.assertIn('preferred_language', result['topic_view']['reported'])
        for flags, values in ((('--preferred-language', 'PT_BR', '--summary-enabled'),
                               {'preferred_language': 'PT_BR', 'summary_enabled': True}),
                              (('--clear-preferred-language', '--no-summary-enabled'),
                               {'preferred_language': None, 'summary_enabled': False})):
            result = run(root.parse_args(['topic-view-set', '123', '9', *flags, '--acknowledge-participant-initialization']))
            self.assertEqual(result['requested'], values)

    def test_removed_invalid_resets_and_conflicting_options_are_rejected_offline(self):
        root = parser()
        for flags in (('--sort-order', 'inherit'), ('--clear-pinned-entry-preference',), ('--clear-summary-preference',),
                      ('--preferred-language', 'FR', '--clear-preferred-language'), ('--expanded', '--inherit-expansion')):
            with self.subTest(flags=flags), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                root.parse_args(['topic-view-set', '123', '9', *flags])
        self.assertEqual(self.client.calls, [])
