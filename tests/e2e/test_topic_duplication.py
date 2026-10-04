"""Installed native copying, independent eligibility/copy semantics and position-map proof."""

import copy
import json

from . import topic_management
from .fixture import CanvasFixture


class TopicDuplicationE2E(CanvasFixture):
    def setUp(self):
        self.reset()

    def reset(self):
        topic_management.initialize(type(self), enabled=True)
        type(self).topic_duplicate_enabled = True
        self.managed_topics[902]['pinned'] = True

    def command(self, *extra, group=False):
        return ('topic-duplicate', '119' if group else '111', '901', '--context', 'group' if group else 'course',
                '--acknowledge-shared-topic', '--acknowledge-copy-effects', *extra)

    def approved(self, command):
        preview = self.invoke(*command)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        return self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])

    def writes(self, before):
        return [row for row in self.calls[before:] if row[0] != 'GET']

    def test_preview_is_source_bound_explicit_native_copy_without_prompt_or_peer_inspection(self):
        before = len(self.calls)
        result = self.invoke(*self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        preview = json.loads(result.stdout)
        self.assertEqual(preview['route'], '/api/v1/courses/111/discussion_topics/901/duplicate?no_verifiers=true')
        self.assertIsNone(preview['body'])
        self.assertEqual(preview['source_topic']['id'], 901)
        self.assertTrue(preview['acknowledge_copy_effects'])
        self.assertIn('widening the new audience', preview['warning'])
        self.assertNotIn('synthetic-private', result.stdout)
        self.assertEqual(self.writes(before), [])
        self.assertTrue(any('page=2' in route for _, route in self.calls[before:]))
        self.assertFalse(any('/entries' in route or '/view' in route for _, route in self.calls[before:]))

    def test_course_and_group_copy_have_new_id_own_author_source_readback_and_independent_pin_map(self):
        for group in (False, True):
            self.reset()
            source = copy.deepcopy(self.managed_topics[901])
            before = len(self.calls)
            result = self.approved(self.command(group=group))
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertTrue(data['new_id_verified'])
            self.assertTrue(data['source_metadata_unchanged_at_readback'])
            self.assertEqual(data['copied_topic']['id'], 903)
            self.assertEqual(data['copied_topic']['author_id'], 7)
            self.assertEqual(data['pinned_ordering'], {'accessible_positions_verified': True,
                             'native_pre_insertion_position': 3, 'stored_copy_position': 2, 'unverified_position_count': 0})
            self.assertEqual(self.managed_topics[902]['position'], 3)
            self.assertEqual(self.managed_topics[901], source)
            self.assertEqual(data['source_attachment_count'], 1)
            self.assertEqual(data['copy_attachment_count'], 0)
            self.assertEqual(self.managed_topics[903]['discussion_subentry_count'], 0)
            self.assertEqual(self.managed_topics[903]['message'], source['message'])
            self.assertEqual(self.managed_topics[903]['attachments'], [])
            self.assertEqual(self.managed_topics[903]['ungraded_discussion_overrides'], [])
            self.assertFalse(data['stored_fields_match_source']['audience_digest'])
            self.assertEqual(self.topic_entries, [{'id': 991, 'message': 'synthetic-private-peer-reply'}])
            self.assertFalse(self.topic_attachment_deleted)
            prefix = 'groups/119' if group else 'courses/111'
            self.assertEqual(self.writes(before), [('POST', f'/api/v1/{prefix}/discussion_topics/901/duplicate?no_verifiers=true')])
            self.assertNotIn('synthetic-private', result.stdout)

    def test_native_instructor_and_group_predicates_are_not_replaced_by_moderation_or_source_edit_permissions(self):
        type(self).topic_context_admin = False
        type(self).topic_instructor = True
        self.managed_topics[901]['permissions'].update(update=False, delete=False)
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['copied_topic']['published'])
        self.reset()
        type(self).topic_context_admin = type(self).topic_instructor = False
        type(self).topic_moderator = True
        before = len(self.calls)
        result = self.approved(self.command())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.writes(before)), 1)
        self.assertEqual(set(self.managed_topics), {901, 902})
        self.assertNotIn('synthetic-private', result.stderr)
        self.reset()
        type(self).topic_context_admin = type(self).topic_instructor = False
        result = self.approved(self.command(group=True))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_native_draft_auto_publication_copied_dates_sections_and_missing_overrides_are_observable(self):
        self.managed_topics[901].update(is_section_specific=True, sections=[{'id': 222}],
                                        delayed_post_at='2040-10-01T19:00:00Z', lock_at='2040-10-02T19:00:00Z')
        type(self).topic_moderator = True
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data['copied_topic']['published'])
        self.assertTrue(data['stored_fields_match_source']['section_ids'])
        self.assertTrue(data['stored_fields_match_source']['delayed_post_at'])
        self.assertTrue(data['stored_fields_match_source']['lock_at'])
        self.assertFalse(data['stored_fields_match_source']['audience_digest'])
        self.reset()
        self.managed_topics[901]['pinned'] = False
        type(self).topic_moderator = True
        type(self).topic_publication_override = True
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['copied_topic']['published'])
        self.assertIsNone(json.loads(result.stdout)['pinned_ordering'])

    def test_initial_post_gate_and_unsupported_graded_root_group_set_anonymous_topics_never_write(self):
        for field, value in (('require_initial_post', True), ('assignment_id', 88), ('root_topic_id', 89),
                             ('group_category_id', 90), ('anonymous_state', 'full_anonymity'), ('position', None),
                             ('topic_children', [91]), ('is_announcement', True)):
            self.reset()
            self.managed_topics[901][field] = value
            if field == 'require_initial_post':
                self.managed_topics[901]['subscription_hold'] = 'initial_post_required'
            before = len(self.calls)
            result = self.invoke(*self.command())
            self.assertNotEqual(result.returncode, 0, (field, result.stderr))
            self.assertEqual(self.writes(before), [])
            self.assertFalse(any('/entries' in route or '/view' in route for _, route in self.calls[before:]))
        self.reset()
        self.managed_topics[901].update(require_initial_post=True, user_can_see_posts=True)
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.reset()
        self.managed_topics[901].update(require_initial_post=True, user_can_see_posts=False)
        type(self).topic_duplicate_associated_posted = True
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.reset()
        self.managed_topics[901]['require_initial_post'] = True
        before = len(self.calls)
        result = self.approved(self.command())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.writes(before)), 1)
        self.assertEqual(set(self.managed_topics), {901, 902})

    def test_stale_source_context_permissions_account_inventory_and_audience_do_not_copy(self):
        for mode in ('source', 'context', 'creation', 'admin', 'moderation', 'account', 'inventory', 'audience'):
            self.reset()
            command = self.command()
            preview = self.invoke(*command)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            if mode == 'source':
                self.managed_topics[901]['message'] = 'Changed'
            elif mode == 'context':
                self.topic_context['name'] = 'Changed'
            elif mode == 'creation':
                type(self).topic_create_permission = False
            elif mode == 'admin':
                type(self).topic_context_admin = False
            elif mode == 'moderation':
                type(self).topic_moderator = True
            elif mode == 'account':
                type(self).topic_viewer = 8
            elif mode == 'inventory':
                self.managed_topics[902]['title'] = 'Changed'
            else:
                self.managed_topics[901]['ungraded_discussion_overrides'] = []
            before = len(self.calls)
            result = self.invoke(*command, '--yes', '--confirm', json.loads(preview.stdout)['confirm'])
            self.assertNotEqual(result.returncode, 0, (mode, result.stderr))
            self.assertEqual(self.writes(before), [])

    def test_missing_wrong_malformed_maps_or_changed_pin_acknowledgements_fail_once_without_cleanup(self):
        for value in ({}, [], {'903': 2}, {'901': 1, '902': 3, '903': True},
                      {'901': 1, '902': 2, '903': 2}, {'901': 1, '902': 3, '0903': 2},
                      {'901': 1, '902': 3, '903': -1}):
            self.reset()
            type(self).topic_duplicate_positions = value
            before = len(self.calls)
            result = self.approved(self.command())
            self.assertNotEqual(result.returncode, 0, (value, result.stderr))
            self.assertIn('may already have succeeded', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)
            self.assertIn(903, self.managed_topics)
            self.assertNotIn('synthetic-private', result.stderr)
        self.reset()
        type(self).topic_duplicate_copy_pinned = False
        before = len(self.calls)
        result = self.approved(self.command())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.writes(before)), 1)

    def test_unavailable_wrong_source_or_existing_copy_acknowledgement_does_not_retry_or_emit_private_data(self):
        for field, value in (('topic_duplicate_return_existing', True), ('topic_duplicate_source_changed', True),
                             ('topic_duplicate_hidden_after', True), ('topic_readback_denied', True),
                             ('topic_account_changed', True), ('topic_denied', True),
                             ('topic_ack_patch', []), ('topic_ack_patch', {'author': {'id': 8}}),
                             ('topic_ack_patch', {'title': 'synthetic-private-wrong-copy-title'})):
            self.reset()
            setattr(type(self), field, value)
            before = len(self.calls)
            result = self.approved(self.command())
            self.assertNotEqual(result.returncode, 0, (field, result.stderr))
            self.assertEqual(result.stdout, '')
            self.assertNotIn('synthetic-private', result.stderr)
            self.assertEqual(len(self.writes(before)), 1)
            self.assertFalse(self.topic_attachment_deleted)

    def test_ambiguous_accessible_inventory_positions_are_not_mistaken_for_complete_order_proof(self):
        for patch in ({902: {'pinned': None}}, {902: {'position': None}}, {902: {'position': 1}}, {902: {'position': True}}):
            self.reset()
            type(self).topic_duplicate_inventory_patch = patch
            before = len(self.calls)
            result = self.approved(self.command())
            self.assertNotEqual(result.returncode, 0, (patch, result.stderr))
            self.assertEqual(len(self.writes(before)), 1)

    def test_additional_native_position_ids_and_brief_output_are_labeled_without_leaking_the_map(self):
        type(self).topic_duplicate_extra_position = True
        result = self.approved(self.command())
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['pinned_ordering']['unverified_position_count'], 1)
        self.assertNotIn('new_positions', data)
        self.assertNotIn(999, data['observed_inventory_changes']['added_ids'])
        self.reset()
        result = self.approved(self.command('--format', 'brief'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('901 → 903 copied', result.stdout)
        self.assertIn('Copy differs from source: audience_digest', result.stdout)
        self.assertIn('Attachment associations: 1 in source, 0 in copy.', result.stdout)
        self.assertNotIn('synthetic-private', result.stdout)

    def test_local_flags_partial_pagination_and_offline_help_never_copy(self):
        before = len(self.calls)
        for command in (('topic-duplicate', '111', '901', '--acknowledge-shared-topic'),
                        self.command('--max-pages', '1'), self.command('--max-pages', '0'),
                        ('topic-duplicate', '111', '0', '--acknowledge-shared-topic', '--acknowledge-copy-effects')):
            result = self.invoke(*command)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.writes(before), [])
        type(self).topic_create_permission = False
        result = self.invoke(*self.command())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.writes(before), [])
        result = self.invoke('help', 'topic-duplicate', '--format', 'brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('usage: canvas topic-duplicate', result.stdout)
