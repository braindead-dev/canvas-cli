"""Read a discussion's visible top-level entries and paginated replies."""

from .client import CanvasError


def read_thread(client, course_id, topic_id, max_pages):
    base = f'/api/v1/courses/{course_id}/discussion_topics/{topic_id}'
    topic, _ = client.request(base)
    if (not isinstance(topic, dict) or str(topic.get('id')) != topic_id or
            (topic.get('context_id') is not None and str(topic['context_id']) != course_id)):
        raise CanvasError('Canvas returned a different discussion topic')
    if topic.get('published') is False or topic.get('locked_for_user') or topic.get('locked'):
        raise CanvasError('Discussion topic is unpublished or locked for this user')
    if topic.get('require_initial_post') and topic.get('user_can_see_posts') is False:
        raise CanvasError('This discussion requires your initial post before entries are visible')

    entries = client.list(base + '/entries?per_page=100', max_pages)
    output, unavailable = [], []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get('id'):
            raise CanvasError('Canvas returned a malformed discussion entry')
        if any(entry.get(key) is not None and str(entry[key]) != topic_id
               for key in ('discussion_topic_id', 'topic_id')):
            raise CanvasError('Canvas returned an entry from another topic')
        reply_list = entry.get('recent_replies') or []
        replies_complete = not entry.get('has_more_replies', False)
        if not isinstance(reply_list, list):
            raise CanvasError('Canvas returned malformed discussion replies')
        if not replies_complete:
            try:
                reply_list = client.list(base + f"/entries/{entry['id']}/replies?per_page=100",
                                         max_pages)
                replies_complete = True
            except CanvasError as error:
                if error.status not in (403, 404):
                    raise
                unavailable.append({'entry_id': entry['id'], 'status': error.status})
        if any(not isinstance(reply, dict) for reply in reply_list):
            raise CanvasError('Canvas returned malformed discussion replies')
        public_entry = {key: entry.get(key) for key in
                        ('id', 'user_id', 'user_name', 'message', 'created_at', 'updated_at',
                         'read_state', 'attachment')}
        public_entry.update({'replies': reply_list, 'replies_complete': replies_complete})
        output.append(public_entry)
    return {
        'course_id': int(course_id), 'topic_id': int(topic_id),
        'title': topic.get('title'), 'message': topic.get('message'),
        'html_url': topic.get('html_url'), 'entries': output,
        'complete': not unavailable, 'unavailable': unavailable,
        'note': 'Read-only GETs; a post-first restriction is respected, not bypassed.',
    }
