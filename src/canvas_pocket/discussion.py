"""Guarded discussion entry and reply composition."""

import hashlib
import html
import json

from .client import CanvasError
from .writes import account


def prepare(client, course_id, topic_id, reply_to, message):
    identity = account(client)
    topic, _ = client.request(f'/api/v1/courses/{course_id}/discussion_topics/{topic_id}')
    if (not isinstance(topic, dict) or str(topic.get('id')) != topic_id or
            (topic.get('context_id') is not None and
             str(topic['context_id']) != course_id)):
        raise CanvasError('Canvas returned a different topic; refusing post')
    if (topic.get('published') is False or topic.get('locked') or topic.get('locked_for_user')
            or topic.get('workflow_state') in ('unpublished', 'deleted')):
        raise CanvasError('Discussion topic is unpublished or locked')
    if not message.strip():
        raise CanvasError('Empty message refused')
    route = f'/api/v1/courses/{course_id}/discussion_topics/{topic_id}/entries'
    if reply_to:
        route += f'/{reply_to}/replies'
    body = {'message': '<p>' + html.escape(message).replace('\n', '<br>') + '</p>'}
    preview = {**identity, 'course_id': course_id, 'topic_id': topic_id,
               'topic_title': topic.get('title'), 'published': topic.get('published'),
               'locked': topic.get('locked'), 'lock_at': topic.get('lock_at'),
               'reply_to': reply_to, 'route': route, 'body': body}
    digest = hashlib.sha256(json.dumps(preview, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return preview, digest


def post(client, course_id, topic_id, reply_to, message, yes=False, confirm=None):
    if bool(yes) != bool(confirm):
        raise CanvasError('Posting requires both --yes and --confirm from a prior preview')
    preview, digest = prepare(client, course_id, topic_id, reply_to, message)
    if not yes:
        return {'dry_run': True, **preview, 'confirm': digest,
                'next': 'Review topic, reply target and exact message, then repeat with --yes --confirm DIGEST.'}
    if confirm != digest:
        raise CanvasError('Preview changed (topic or message); review a fresh preview before posting')
    return client.request(preview['route'], 'POST', preview['body'])[0]
