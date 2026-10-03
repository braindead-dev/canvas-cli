"""Own discussion likes, using native ratings without grading or hidden-entry access."""

from .client import CanvasError
from .contexts import discussion_base, read_topic
from .discussion import _entry, _revision
from .writes import account, check_flags, confirmed, digest


def _number(value):
    if (not isinstance(value, str) or not value.isascii() or not value.isdecimal() or
            int(value) < 1 or str(int(value)) != value):
        raise CanvasError('Expected a positive numeric discussion ID')
    return value


def _state(client, context_id, topic_id, context_type):
    _number(context_id)
    _number(topic_id)
    base = discussion_base(context_id, topic_id, context_type)
    topic = read_topic(client, context_id, topic_id, context_type, require_entries=True)
    if topic.get('user_can_see_posts') is False:
        raise CanvasError('Canvas does not confirm access to this discussion\'s entries')
    if type(topic.get('allow_rating')) is not bool:
        raise CanvasError('Canvas did not confirm whether discussion ratings are enabled')
    if not topic['allow_rating']:
        return base, topic, {}, None
    snapshot, _ = client.request(base + '/view?include_new_entries=1')
    if (not isinstance(snapshot, dict) or not isinstance(snapshot.get('entry_ratings'), dict) or
            not isinstance(snapshot.get('view'), list) or
            snapshot.get('new_entries') is not None and not isinstance(snapshot['new_entries'], list)):
        raise CanvasError('Canvas returned an invalid discussion rating snapshot')
    stack = list(snapshot['view']) + (snapshot.get('new_entries') or [])
    entry_ids = set()
    while stack:
        entry = stack.pop()
        if not isinstance(entry, dict) or type(entry.get('id')) is not int or entry['id'] < 1:
            raise CanvasError('Canvas returned invalid cached discussion entry IDs')
        replies = entry.get('replies')
        if replies is not None and not isinstance(replies, list):
            raise CanvasError('Canvas returned invalid cached discussion replies')
        entry_ids.add(entry['id'])
        stack.extend(replies or [])
    ratings = {}
    for key, value in snapshot['entry_ratings'].items():
        _number(key)
        if type(value) is not int or value not in (0, 1) or int(key) not in entry_ids:
            raise CanvasError('Canvas returned invalid or out-of-snapshot entry ratings')
        ratings[key] = value
    return base, topic, ratings, entry_ids


def read(client, context_id, topic_id, context_type='course'):
    _number(context_id)
    _number(topic_id)
    discussion_base(context_id, topic_id, context_type)
    identity = account(client)
    _, topic, ratings, entry_ids = _state(client, context_id, topic_id, context_type)
    return {**identity, 'context_type': context_type, f'{context_type}_id': int(context_id),
            'topic_id': int(topic_id), 'topic_title': topic.get('title'),
            'ratings_enabled': topic['allow_rating'], 'only_graders_can_rate': topic.get('only_graders_can_rate'),
            'own_entry_ratings': ratings,
            'snapshot_entry_ids': sorted(entry_ids) if entry_ids is not None else None,
            'note': 'Own native ratings only: 1 is liked, 0 removes a like; absent entries in this snapshot have '
                    'no recorded rating. The view is eventually consistent, not a complete fresh thread. '
                    'GET only; no rating or read-marker writes. Canvas may log content-access analytics.'}


def change(client, context_id, topic_id, entry_id, rating, *, context_type='course',
           max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    for value in (context_id, topic_id, entry_id):
        _number(value)
    if type(rating) is not int or rating not in (0, 1):
        raise CanvasError('Discussion ratings accept only integer 0 (remove like) or 1 (like)')
    discussion_base(context_id, topic_id, context_type)
    identity = account(client)
    base, topic, ratings, entry_ids = _state(client, context_id, topic_id, context_type)
    if not topic['allow_rating']:
        raise CanvasError('Ratings are disabled for this topic; no change requested')
    current = _entry(client, base, topic_id, entry_id, max_pages)
    if (current.get('deleted') or current.get('workflow_state') == 'deleted' or current.get('hidden_for_user') or
            current.get('locked_for_user')):
        raise CanvasError('Cannot rate a deleted, hidden or locked entry')
    permissions = current.get('permissions')
    if isinstance(permissions, dict) and permissions.get('rate') is False:
        raise CanvasError('Canvas does not permit rating this entry')
    if int(entry_id) not in entry_ids:
        raise CanvasError('This entry is not yet in the rating snapshot. Retry a fresh preview later; '
                          'its current rating is unknown, not zero.')
    topic_revision = {key: topic.get(key) for key in
                      ('id', 'title', 'message', 'updated_at', 'allow_rating', 'only_graders_can_rate',
                       'published', 'locked', 'locked_for_user', 'anonymous_state', 'require_initial_post')}
    preview = {**identity, 'context_type': context_type, f'{context_type}_id': int(context_id),
               'topic_id': int(topic_id), 'topic_title': topic.get('title'), 'entry_id': int(entry_id),
               'current_own_rating': ratings.get(entry_id), 'requested_rating': rating,
               'topic_revision': digest(topic_revision), 'entry_revision': digest(_revision(current)),
               'only_graders_can_rate': topic.get('only_graders_can_rate'),
               'method': 'POST', 'route': base + f'/entries/{entry_id}/rating', 'body': {'rating': rating},
               'expected_response': 'no_content',
               'effect': 'Set only your like on this visible entry. Does not change grades, author content or read markers.',
               'warning': 'Canvas enforces rating permissions, including grader-only settings. '
                          'Use entry to inspect the target; private entry bodies are hashed, not echoed here.'}
    response = confirmed(client, preview, yes, confirm)
    if not yes:
        return response
    return {'discussion_rating': {'context_type': context_type, f'{context_type}_id': int(context_id),
                                  'topic_id': int(topic_id), 'entry_id': int(entry_id), 'rating': rating},
            'acknowledged': True,
            'note': 'Canvas acknowledged the rating with empty HTTP 204. No grading or read-marker writes were issued.'}
