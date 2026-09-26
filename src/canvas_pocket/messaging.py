"""Find messageable users and preview one-recipient Canvas Inbox messages."""

import hashlib
import json
from urllib.parse import urlencode

from .client import CanvasError


def recipients(client, max_pages, search=None, user_id=None, course_id=None):
    if bool(search) == bool(user_id):
        raise CanvasError('Choose exactly one of search or user ID')
    if user_id and course_id:
        raise CanvasError('Canvas ignores context when searching by user ID; omit --course')
    query = [('type', 'user'), ('per_page', '100')]
    if user_id:
        query.append(('user_id', user_id))
    else:
        term = search.strip()
        if not term:
            raise CanvasError('Recipient search cannot be empty')
        query.append(('search', term))
        if course_id:
            query.append(('context', f'course_{course_id}'))
    return client.list('/api/v1/search/recipients?' + urlencode(query), max_pages)


def compose(client, max_pages, recipient_id, subject, message, course_id=None,
            yes=False, confirm=None):
    if bool(yes) != bool(confirm):
        raise CanvasError('Sending requires both --yes and --confirm from a prior preview')
    subject, message = subject.strip(), message.strip()
    if not subject or len(subject) > 255 or not message:
        raise CanvasError('Use a nonempty subject (at most 255 characters) and message')
    people = recipients(client, max_pages, user_id=recipient_id)
    if len(people) != 1 or str(people[0].get('id')) != recipient_id:
        raise CanvasError('Canvas did not confirm this user as a messageable recipient')
    person = {key: people[0].get(key) for key in ('id', 'name', 'full_name', 'type')}
    if person.get('type') not in (None, 'user'):
        raise CanvasError('Recipient is not an individual Canvas user')
    shared = people[0].get('common_courses')
    if course_id and isinstance(shared, dict) and str(course_id) not in shared:
        raise CanvasError('Recipient is not shown as sharing that course')
    body = {'recipients': [recipient_id], 'subject': subject, 'body': message}
    if course_id:
        body['context_code'] = f'course_{course_id}'
    route = '/api/v1/conversations'
    preview = {'recipient': person, 'course_id': course_id, 'route': route,
               'body': body, 'may_reuse_existing_private_thread': True}
    digest = hashlib.sha256(json.dumps(preview, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if not yes:
        return {'dry_run': True, **preview, 'confirm': digest,
                'next': 'Review recipient and exact message, then repeat with --yes --confirm DIGEST.'}
    if confirm != digest:
        raise CanvasError('Preview changed (recipient or message); review a fresh preview before sending')
    return client.request(route, 'POST', body)[0]
