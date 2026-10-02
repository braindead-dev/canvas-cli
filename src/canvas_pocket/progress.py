"""Read reported module requirements without viewing or completing their content."""

from urllib.parse import urlencode

from .client import CanvasError


def published(record):
    return (isinstance(record, dict) and record.get('published') is not False
            and record.get('workflow_state') not in ('unpublished', 'deleted')
            and record.get('state') != 'unpublished' and not record.get('hidden_for_user'))


def module_progress(client, course_id, max_pages):
    base = f'/api/v1/courses/{course_id}'
    modules = client.list(base + '/modules?per_page=100', max_pages)
    result, unavailable = [], []
    for module in modules:
        if not isinstance(module, dict) or type(module.get('id')) is not int or module['id'] < 1:
            raise CanvasError('Canvas returned a malformed module record')
        if not published(module):
            continue
        row = {key: module.get(key) for key in ('id', 'name', 'position', 'state',
               'completed_at', 'unlock_at', 'require_sequential_progress',
               'requirement_type', 'prerequisite_module_ids', 'items_count')}
        row.update(items=[], requirements=None, item_inventory_complete=False)
        # Names/state can be returned for future modules. Do not request their content.
        if module.get('state') == 'locked' or module.get('locked_for_user'):
            unavailable.append({'module_id': module['id'], 'reason': 'locked; items not requested'})
            result.append(row)
            continue
        try:
            query = urlencode([('per_page', '100'), ('include[]', 'content_details')])
            items = client.list(base + f"/modules/{module['id']}/items?" + query, max_pages)
        except CanvasError as error:
            if error.status not in (403, 404):
                raise
            unavailable.append({'module_id': module['id'], 'status': error.status})
            result.append(row)
            continue
        counts = {'required': 0, 'completed': 0, 'incomplete': 0, 'unknown': 0}
        for item in items:
            if not isinstance(item, dict) or type(item.get('id')) is not int or item['id'] < 1:
                raise CanvasError('Canvas returned a malformed module item')
            if not published(item):
                continue
            requirement = item.get('completion_requirement')
            if requirement is not None and not isinstance(requirement, dict):
                raise CanvasError('Canvas returned malformed completion requirements')
            completion = 'not_required'
            if requirement:
                completion = ('completed' if requirement.get('completed') is True else
                              'incomplete' if requirement.get('completed') is False else 'unknown')
                counts['required'] += 1
                counts[completion] += 1
            details = item.get('content_details') or {}
            if not isinstance(details, dict):
                raise CanvasError('Canvas returned malformed module content details')
            row['items'].append({key: item.get(key) for key in
                                 ('id', 'title', 'type', 'position', 'html_url')} |
                                {'requirement': requirement, 'completion': completion,
                                 'locked_for_user': bool(item.get('locked_for_user') or
                                                         details.get('locked_for_user')),
                                 'due_at': details.get('due_at'),
                                 'unlock_at': details.get('unlock_at')})
        row['requirements'] = counts
        row['item_inventory_complete'] = True
        result.append(row)
    return {'course_id': int(course_id), 'module_progress': result,
            'complete': not unavailable, 'unavailable': unavailable,
            'note': 'Counts describe visible requirements, not a grade or inferred module completion. '
                    'Canvas module state is authoritative; "one" modules need only one requirement. '
                    'Missing completion status is unknown. No view/completion events were sent.'}
