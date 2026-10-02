"""Guarded discussion entry and reply composition."""

import hashlib
import html
import json

from .client import CanvasError
from .contexts import discussion_base, read_topic
from .writes import account


def prepare(client, course_id, topic_id, reply_to, message, context_type='course'):
    if not isinstance(message, str) or not message.strip():
        raise CanvasError('Empty message refused')
    discussion_base(course_id, topic_id, context_type)
    identity = account(client)
    topic = read_topic(client, course_id, topic_id, context_type, require_entries=bool(reply_to))
    route = discussion_base(course_id, topic_id, context_type) + '/entries'
    if reply_to:
        route += f'/{reply_to}/replies'
    body = {'message': '<p>' + html.escape(message).replace('\n', '<br>') + '</p>'}
    preview = {**identity, f'{context_type}_id': course_id, 'context_type': context_type, 'topic_id': topic_id,
               'topic_title': topic.get('title'), 'published': topic.get('published'),
               'locked': topic.get('locked'), 'lock_at': topic.get('lock_at'),
               'reply_to': reply_to, 'route': route, 'body': body}
    digest = hashlib.sha256(json.dumps(preview, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return preview, digest


def post(client, course_id, topic_id, reply_to, message, yes=False, confirm=None, context_type='course'):
    if bool(yes) != bool(confirm):
        raise CanvasError('Posting requires both --yes and --confirm from a prior preview')
    preview, digest = prepare(client, course_id, topic_id, reply_to, message, context_type)
    if not yes:
        return {'dry_run': True, **preview, 'confirm': digest,
                'next': 'Review topic, reply target and exact message, then repeat with --yes --confirm DIGEST.'}
    if confirm != digest:
        raise CanvasError('Preview changed (topic or message); review a fresh preview before posting')
    return client.request(preview['route'], 'POST', preview['body'])[0]
