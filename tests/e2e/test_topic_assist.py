"""Installed language/summary preference workflows against independent native TLS state."""

import copy
import json
import ssl
from urllib.request import Request, urlopen

from . import topic_view
from .fixture import CanvasFixture


class TopicAssistE2E(CanvasFixture):
    def setUp(self):
        topic_view.initialize(type(self), enabled=True)

    def command(self, *extra, read=False):
        return ('topic-view' if read else 'topic-view-set', '131', '931',
                '--acknowledge-participant-initialization', *extra)

    def approved(self, *extra):
        preview = self.invoke(*self.command(*extra))
        self.assertEqual(preview.returncode, 0, preview.stderr)
        result = self.invoke(*self.command(*extra), '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        return result

    def test_catalog_is_a_pure_schema_query_with_complete_deprecated_values_and_correct_brief(self):
        self.view_language_type['enumValues'] = [{'name': f'LOCALE_{index}', 'isDeprecated': index == 2,
                                                 'private': 'synthetic-private'} for index in reversed(range(130))]
        before = len(self.calls)
        result = self.invoke('topic-languages')
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)['discussion_languages']['values']
        self.assertEqual(len(values), 130)
        self.assertEqual([row['enum'] for row in values], sorted(row['enum'] for row in values))
        self.assertEqual(self.calls[before:], [('POST', '/api/graphql')])
        self.assertFalse(self.view_initialized)
        self.assertEqual(self.view_mutations, [])
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)
        brief = self.invoke('topic-languages', '--format', 'brief')
        self.assertEqual(brief.returncode, 0, brief.stderr)
        self.assertIn('LOCALE_2 (deprecated)', brief.stdout)
        self.assertIn('not proof of translation service', brief.stdout)

    def test_default_read_does_not_fetch_assist_and_opt_in_shows_exact_enum_without_service_calls(self):
        result = self.invoke(*self.command(read=True))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('preferred_language', json.loads(result.stdout)['topic_view']['reported'])
        self.view_own.update(preferredLanguage='PT_BR', summaryEnabled=True)
        result = self.invoke(*self.command('--include-assist-preferences', read=True), '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('preferred_language=PT_BR', result.stdout)
        self.assertIn('summary_enabled=true', result.stdout)
        self.assertEqual(self.view_generation_requests, [])
        self.assertEqual(self.view_mutations, [])

    def test_language_and_summary_change_has_one_native_mutation_and_preserves_shared_and_marker_state(self):
        self.invoke(*self.command(read=True))
        before = copy.deepcopy(self.view_own)
        topic = copy.deepcopy(self.view_topic)
        result = self.approved('--preferred-language', 'PT_BR', '--summary-enabled')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(self.view_mutations, [{'discussionTopicId': '931', 'preferredLanguage': 'PT_BR', 'summaryEnabled': True}])
        self.assertEqual(self.view_topic, topic)
        self.assertEqual({key: value for key, value in self.view_own.items() if key not in ('preferredLanguage', 'summaryEnabled')},
                         {key: value for key, value in before.items() if key not in ('preferredLanguage', 'summaryEnabled')})
        for key in ('preferred_language', 'summary_enabled'):
            self.assertTrue(data['verification'][key]['stored_override_verified'])
        self.assertEqual(self.view_generation_requests, [])
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)

    def test_group_read_permission_allows_stored_summary_without_generation_manager_or_reply_authority(self):
        self.view_topic.update(contextType='Group')
        self.view_topic['permissions'].update(update=False, reply=False)
        result = self.approved('--context', 'group', '--summary-enabled')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.view_own['summaryEnabled'])
        self.assertEqual(self.view_generation_requests, [])
        self.assertEqual(len(self.view_mutations), 1)

    def test_known_language_clear_and_false_summary_do_not_require_catalog_and_do_not_claim_raw_clear(self):
        self.invoke(*self.command(read=True))
        self.view_own.update(preferredLanguage='FR', summaryEnabled=True)
        type(self).view_language_error = 403
        result = self.approved('--clear-preferred-language', '--no-summary-enabled')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertIsNone(self.view_own['preferredLanguage'])
        self.assertFalse(self.view_own['summaryEnabled'])
        self.assertEqual(self.view_mutations, [{'discussionTopicId': '931', 'preferredLanguage': None, 'summaryEnabled': False}])
        self.assertFalse(data['verification']['preferred_language']['stored_override_verified'])
        self.assertTrue(data['verification']['summary_enabled']['stored_override_verified'])
        self.assertEqual(self.view_generation_requests, [])

    def test_hidden_unsupported_locale_null_readback_does_not_verify_ignored_clear(self):
        self.invoke(*self.command(read=True))
        self.view_own['preferredLanguage'] = 'REMOVED_LOCALE'
        type(self).view_ignored = {'preferredLanguage'}
        result = self.approved('--clear-preferred-language')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(self.view_own['preferredLanguage'], 'REMOVED_LOCALE')
        self.assertIsNone(data['topic_view']['reported']['preferred_language'])
        self.assertFalse(data['verification']['preferred_language']['stored_override_verified'])
        self.assertEqual(len(self.view_mutations), 1)

    def test_deprecated_language_is_not_excluded_and_catalog_reordering_does_not_stale_confirmation(self):
        self.view_language_type['enumValues'][1]['isDeprecated'] = True
        preview = self.invoke(*self.command('--preferred-language', 'FR'))
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.view_language_type['enumValues'].reverse()
        result = self.invoke(*self.command('--preferred-language', 'FR'), '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.view_own['preferredLanguage'], 'FR')
        self.assertEqual(len(self.view_mutations), 1)

    def test_missing_unknown_or_denied_catalog_fails_before_initialization_without_retry_or_private_data(self):
        for mode in ('missing', 'unknown', 401, 403, 429, 302, 500, 'partial'):
            self.setUp()
            if mode == 'missing':
                type(self).view_language_type = None
            elif mode != 'unknown':
                type(self).view_language_error = mode
            before = len(self.calls)
            result = self.invoke(*self.command('--preferred-language', 'UNKNOWN' if mode == 'unknown' else 'FR'))
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertFalse(self.view_initialized)
            self.assertEqual(self.view_mutations, [])
            self.assertEqual(self.calls[before:].count(('POST', '/api/graphql')), 2)
            self.assertNotIn('synthetic-private', result.stdout + result.stderr)

    def test_catalog_and_own_language_or_summary_changes_invalidate_confirmation(self):
        for mode in ('catalog', 'language', 'summary'):
            self.setUp()
            flags = ('--preferred-language', 'FR', '--summary-enabled')
            preview = self.invoke(*self.command(*flags))
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'catalog':
                self.view_language_type['enumValues'].append({'name': 'NEW_ENUM', 'isDeprecated': False})
            elif mode == 'language':
                self.view_own['preferredLanguage'] = 'PT_BR'
            else:
                self.view_own['summaryEnabled'] = True
            result = self.invoke(*self.command(*flags), '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertEqual(result.returncode, 1)
            self.assertIn('Preview changed', result.stderr)
            self.assertEqual(self.view_mutations, [])

    def test_ignored_partial_or_failed_after_apply_preferences_never_succeed_or_repeat(self):
        for mode in ('ignored_language', 'ignored_summary', 'partial', 'error_after_apply', 'denied'):
            self.setUp()
            if mode == 'ignored_language':
                type(self).view_ignored = {'preferredLanguage'}
            elif mode == 'ignored_summary':
                type(self).view_ignored = {'summaryEnabled'}
            elif mode == 'partial':
                type(self).view_ack = {'errors': [{'attribute': 'synthetic-private'}]}
            elif mode == 'error_after_apply':
                type(self).view_ack = mode
            else:
                type(self).view_post_error = 403
            result = self.approved('--preferred-language', 'FR', '--summary-enabled')
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertEqual(len(self.view_mutations), 1)
            self.assertIn('repeating', result.stderr)
            self.assertNotIn('synthetic-private', result.stdout + result.stderr)
            self.assertEqual(self.view_generation_requests, [])

    def test_invalid_removed_reset_flags_fail_offline_before_initialization(self):
        for flags in (('--sort-order', 'inherit'), ('--clear-pinned-entry-preference',), ('--clear-summary-preference',),
                      ('--preferred-language', 'FR', '--clear-preferred-language')):
            before = len(self.calls)
            result = self.invoke(*self.command(*flags))
            self.assertEqual(result.returncode, 2)
            self.assertEqual(self.calls[before:], [])
            self.assertFalse(self.view_initialized)

    def test_fixture_independently_enforces_native_enum_boolean_and_not_null_storage_constraints(self):
        # Direct synthetic-server requests validate the oracle independently of CLI validation.
        document = ('mutation CanvasTopicViewSet($input: UpdateDiscussionTopicParticipantInput!) { '
                    'updateDiscussionTopicParticipant(input: $input) { errors { attribute } '
                    'discussionTopic { _id contextId contextType } } }')
        for key, value in (('sortOrder', None), ('showPinnedEntries', None), ('summaryEnabled', None),
                           ('hasUnreadPinnedEntry', None), ('hasUnreadPinnedEntry', 1),
                           ('sortOrder', 'inherit'), ('summaryEnabled', 1), ('expanded', 'true'),
                           ('preferredLanguage', 'UNKNOWN')):
            payload = {'query': document, 'operationName': 'CanvasTopicViewSet',
                       'variables': {'input': {'discussionTopicId': '931', key: value}}}
            request = Request(f'https://localhost:{self.server.server_port}/api/graphql', data=json.dumps(payload).encode(),
                              headers={'Authorization': 'Bearer synthetic-token', 'Content-Type': 'application/json'}, method='POST')
            context = ssl.create_default_context(cafile=str(self.cert))
            with urlopen(request, context=context, timeout=10) as response:
                result = json.load(response)
            self.assertIn('errors', result)
            self.assertFalse(self.view_initialized)
            self.assertFalse(self.view_written)

    def test_navigation_is_offline_and_classifies_catalog_and_participant_queries_differently(self):
        before = len(self.calls)
        for command, safety in (('topic-languages', 'Read-only'), ('topic-view', 'Canvas queries (server-side effects possible)'),
                                ('topic-view-set', 'Canvas writes (preview-first)')):
            result = self.invoke('help', command)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['safety'], safety)
        self.assertEqual(self.calls[before:], [])
