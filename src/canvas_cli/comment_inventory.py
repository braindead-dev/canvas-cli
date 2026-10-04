"""Exact own-submission comment connections, with bounded per-attempt pagination."""

from .client import CanvasError
from .group_content import _number
from .own_submission import context, with_read_state
from .writes import account


def _attempt(value, current):
    selected = current if value is None else value
    if type(selected) is not int or selected < 0 or selected > max(current, 1):
        raise CanvasError('Choose an existing nonnegative comment attempt; native attempts 0 and 1 share a bucket')
    return selected


def inspect(client, course_id, assignment_id, document, operation, project, *, attempt=None,
            all_attempts=False, max_pages=100, feedback=False):
    _number(course_id)
    _number(assignment_id)
    if (type(max_pages) is not int or max_pages < 1 or all_attempts and attempt is not None
            or attempt is not None and (type(attempt) is not int or attempt < 0)):
        raise CanvasError('Use a positive page cap and either --attempt or --all-attempts, not both')
    identity, baseline, comments = account(client), None, {}
    pending, selected_attempts, pages, cursor, cursors = [attempt], [], 0, None, set()
    while pending:
        if pages >= max_pages:
            raise CanvasError('Own comment inventory exceeded the page cap; completeness is unknown, no mutation sent')
        selected = pending[0]
        data = client.graphql(document, {'assignmentId': assignment_id, 'userId': str(identity['user_id']),
                                        'attempt': selected, 'after': cursor}, operation)
        pages += 1
        state = context(data, identity, course_id, assignment_id)
        if feedback:
            state = with_read_state(state, data)
        if baseline is None:
            baseline = state
            if state['submission'] is not None:
                selected = _attempt(selected, state['submission']['attempt'])
                pending[0] = selected
                if all_attempts:
                    if max(state['submission']['attempt'], 1) > max_pages:
                        raise CanvasError('Own comment attempt inventory exceeds the page cap; no mutation sent')
                    pending += [value for value in range(1, max(state['submission']['attempt'], 1) + 1)
                                if value != max(selected, 1)]
        elif state != baseline:
            raise CanvasError('Own comment account/assignment/submission changed during pagination; no mutation sent')
        if state['submission'] is None:
            break
        connection = data['submission'].get('commentsConnection')
        if (not isinstance(connection, dict) or not isinstance(connection.get('nodes'), list)
                or not isinstance(connection.get('pageInfo'), dict)):
            raise CanvasError('Canvas returned unavailable own comment inventory')
        for row in connection['nodes']:
            item = project(row, state, selected)
            if item['id'] in comments:
                raise CanvasError('Canvas returned duplicate own comment IDs; inventory is not complete')
            comments[item['id']] = item
        page = connection['pageInfo']
        if (type(page.get('hasNextPage')) is not bool or 'endCursor' not in page
                or page['endCursor'] is not None and not isinstance(page['endCursor'], str)):
            raise CanvasError('Canvas returned malformed comment pagination')
        if page['hasNextPage']:
            if not page['endCursor'] or page['endCursor'] in cursors or not connection['nodes']:
                raise CanvasError('Canvas returned looping or empty comment pagination')
            cursor = page['endCursor']
            cursors.add(cursor)
        else:
            selected_attempts.append(pending.pop(0))
            cursor, cursors = None, set()
    if account(client) != identity:
        raise CanvasError('Signed-in account changed during comment inspection; no mutation was sent')
    audience = 'visible_published' if feedback else 'own'
    status = 'unknown_no_accessible_submission' if baseline['submission'] is None else (
        f'complete_reported_{audience}_all_attempts' if all_attempts else f'complete_reported_{audience}_selected_attempt')
    return {**baseline, 'selected_attempts': sorted(selected_attempts), 'comments': comments, 'inventory_status': status}
