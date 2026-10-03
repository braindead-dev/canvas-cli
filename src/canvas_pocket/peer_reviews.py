"""Read native peer-review records without confusing recipient and assessor."""

from urllib.parse import urlencode

from .client import CanvasError
from .writes import account


def read(client, course_id, assignment_id, max_pages=100, *, scope='received', comments=False, users=False):
    if scope not in ('received', 'visible'):
        raise CanvasError('Peer-review scope must be received or visible')
    for number in (course_id, assignment_id):
        if (not isinstance(number, str) or not number.isascii() or not number.isdecimal() or
                int(number) < 1 or str(int(number)) != number):
            raise CanvasError('Expected positive numeric course and assignment IDs')
    if type(comments) is not bool or type(users) is not bool:
        raise CanvasError('Peer-review associations must be explicit booleans')
    identity = account(client)
    base = f'/api/v1/courses/{course_id}/assignments/{assignment_id}'
    assignment, _ = client.request(base)
    if (not isinstance(assignment, dict) or type(assignment.get('id')) is not int or
            str(assignment['id']) != assignment_id or (assignment.get('course_id') is not None and
            (type(assignment['course_id']) is not int or str(assignment['course_id']) != course_id))):
        raise CanvasError('Canvas returned a different assignment; refusing peer-review output')
    if assignment.get('published') is False or assignment.get('locked_for_user'):
        raise CanvasError('Assignment is unpublished or locked for this user')
    query = [('per_page', '100')]
    if comments:
        query.append(('include[]', 'submission_comments'))
    if users:
        query.append(('include[]', 'user'))
    rows = client.list(base + '/peer_reviews?' + urlencode(query), max_pages)
    seen, result = set(), []
    for row in rows:
        if (not isinstance(row, dict) or any(type(row.get(key)) is not int or row[key] < 1
                for key in ('id', 'asset_id', 'user_id')) or row['id'] in seen or
                (row.get('assessor_id') is not None and
                 (type(row['assessor_id']) is not int or row['assessor_id'] < 1))):
            raise CanvasError('Canvas returned malformed or duplicate peer-review records; refusing output')
        seen.add(row['id'])
        if scope == 'received' and row['user_id'] != identity['user_id']:
            continue
        # Do not recover a missing assessor ID/name: Canvas intentionally omits it for anonymous reviews.
        item = {key: row.get(key) for key in ('id', 'asset_id', 'asset_type', 'user_id', 'workflow_state')}
        if 'assessor_id' in row:
            item['assessor_id'] = row['assessor_id']
        item['about_own_submission'] = row['user_id'] == identity['user_id']
        item['assigned_to_self'] = (row['assessor_id'] == identity['user_id'] if row.get('assessor_id') is not None else None)
        associations = (['submission_comments'] if comments else []) + (['user'] if users else [])
        if users and row.get('assessor_id') is not None:
            associations.append('assessor')
        for association in associations:
            if association in row:
                item[association] = row[association]
        result.append(item)
    return {**identity, 'course_id': int(course_id), 'assignment_id': int(assignment_id),
            'assignment_name': assignment.get('name'), 'scope': scope, 'peer_reviews': result,
            'endpoint_record_count': len(rows), 'excluded_by_scope': len(rows) - len(result),
            'complete_for_endpoint': True, 'owed_review_inventory_complete': False,
            'note': ('This endpoint normally lists reviews OF your work, not reviews you owe. '
                     'Visible scope shows only what Canvas authorizes for your role. Missing assessor identity '
                     'may be anonymous and is not recovered. Included submission comments can repeat across '
                     'reviews and are not necessarily written by the assessor. No review is allocated, completed or marked read.')}
