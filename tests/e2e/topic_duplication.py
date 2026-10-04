"""Independent native copy predicate, association loss and serialize-before-insert behavior."""

import copy
from urllib.parse import parse_qs

from .appointments import _send


def initialize(state):
    state.topic_duplicate_enabled = False
    state.topic_context_admin = True
    state.topic_instructor = False
    state.topic_duplicate_positions = None
    state.topic_duplicate_copy_pinned = None
    state.topic_duplicate_extra_position = False
    state.topic_duplicate_source_changed = False
    state.topic_duplicate_return_existing = False
    state.topic_duplicate_hidden_after = False
    state.topic_duplicate_hidden_id = None
    state.topic_duplicate_inventory_patch = None
    state.topic_duplicate_associated_posted = False


def write(state, handler, body, url, prefix):
    if prefix is None or handler.command != 'POST' or not url.path.endswith('/duplicate'):
        return False
    identifier = int(url.path.split('/')[-2])
    row = state.managed_topics.get(identifier)
    course = prefix.startswith('/api/v1/courses/')
    if (not state.topic_duplicate_enabled or row is None or state.topic_denied or not state.topic_create_permission or
            course and not (state.topic_context_admin or state.topic_instructor) or
            row.get('require_initial_post') and row.get('user_can_see_posts') is not True and not state.topic_duplicate_associated_posted):
        _send(handler, {'private': 'synthetic-private-native-duplicate-denial'}, 403)
        return True
    if body or parse_qs(url.query) != {'no_verifiers': ['true']}:
        _send(handler, {'private': 'synthetic-private-native-duplicate-parameters'}, 400)
        return True
    if state.topic_duplicate_return_existing:
        _send(handler, copy.deepcopy(row))
        return True
    identifier = max(state.managed_topics) + 1
    result = copy.deepcopy(row)
    result.update(id=identifier, title='Synthetic Copy ' + row['title'], author={'id': state.topic_viewer},
                  published=not state.topic_moderator, attachments=[], discussion_subentry_count=0,
                  created_at='2026-10-02T12:00:00Z', posted_at='2026-10-02T12:00:00Z', last_reply_at=None,
                  ungraded_discussion_overrides=[], position=max(topic['position'] for topic in state.managed_topics.values()) + 1)
    if state.topic_duplicate_copy_pinned is not None:
        result['pinned'] = state.topic_duplicate_copy_pinned
    state.topic_written = True
    state.managed_topics[identifier] = result
    response = copy.deepcopy(result)  # native API serializes before insert_at
    if row['pinned']:
        target = row['position'] + 1
        for topic in state.managed_topics.values():
            if topic['id'] != identifier and topic['pinned'] and topic['position'] >= target:
                topic['position'] += 1
        result['position'] = target
        response['new_positions'] = {str(topic['id']): topic['position'] for topic in state.managed_topics.values() if topic['pinned']}
        if state.topic_duplicate_extra_position:
            response['new_positions']['999'] = 20
        if state.topic_duplicate_positions is not None:
            response['new_positions'] = state.topic_duplicate_positions
    if state.topic_duplicate_source_changed:
        row['title'] = 'synthetic-private-concurrent-source-change'
    if state.topic_duplicate_hidden_after:
        state.topic_duplicate_hidden_id = identifier
    if state.topic_publication_override is not None:
        result['published'] = response['published'] = state.topic_publication_override
    if state.topic_ack_patch is not None:
        response = {**response, **state.topic_ack_patch} if isinstance(state.topic_ack_patch, dict) else state.topic_ack_patch
    _send(handler, response)
    return True
