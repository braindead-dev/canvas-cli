"""Explicit course/group discussion namespaces and shared visibility checks."""

from .client import CanvasError


def require_entry_api(topic):
    """Legacy REST entry readback deliberately excludes anonymous discussions."""
    if topic.get('anonymous_state') is not None:
        raise CanvasError('Anonymous discussions require a separate native entry workflow; REST entry readback is unavailable')


def discussion_base(context_id, topic_id=None, context_type='course'):
    if context_type not in ('course', 'group'):
        raise CanvasError('Discussion context must be course or group')
    for value in (context_id, topic_id):
        if value is not None and (not isinstance(value, str) or not value.isdecimal() or int(value) < 1):
            raise CanvasError('Expected a positive discussion context/topic ID')
    route = f'/api/v1/{context_type}s/{context_id}/discussion_topics'
    return route + f'/{topic_id}' if topic_id else route


def read_topic(client, context_id, topic_id, context_type='course', require_entries=False, *, allow_locked=False):
    topic, _ = client.request(discussion_base(context_id, topic_id, context_type))
    if (not isinstance(topic, dict) or type(topic.get('id')) is not int or str(topic['id']) != topic_id or
            topic.get('context_id') is not None and str(topic['context_id']) != context_id or
            topic.get('context_type') is not None and str(topic['context_type']).lower() != context_type):
        raise CanvasError('Canvas returned a different discussion topic or context')
    if (topic.get('published') is False or topic.get('workflow_state') in ('unpublished', 'deleted') or
            not allow_locked and (topic.get('locked_for_user') or topic.get('locked'))):
        raise CanvasError('Discussion topic is unpublished or locked for this user')
    if require_entries and topic.get('require_initial_post') and topic.get('user_can_see_posts') is False:
        raise CanvasError('This discussion requires your initial post before entries are visible')
    return topic
