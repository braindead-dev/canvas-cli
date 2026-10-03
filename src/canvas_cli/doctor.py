"""Read-only, content-free capability probe for one visible Canvas course."""

from .client import CanvasError

PROBES = (
    ('assignments', 'assignments'),
    ('assignment_groups', 'assignment_groups'),
    ('modules', 'modules'),
    ('pages', 'pages'),
    ('files', 'files'),
    ('folders', 'folders'),
    ('discussions', 'discussion_topics'),
    ('rubrics', 'rubrics'),
    ('classic_quizzes', 'quizzes'),
    ('sections', 'sections'),
)


def _status(error):
    if error.status == 403:
        return 'denied_403'
    if error.status == 404:
        return 'not_found_404'
    if error.status == 429:
        return 'rate_limited_429'
    raise error


def course_doctor(client, course_id):
    course, _ = client.request(f'/api/v1/courses/{course_id}')
    if not isinstance(course, dict) or str(course.get('id')) != course_id:
        raise CanvasError('Canvas returned a different course; refusing probe')
    routes = [(name, f'/api/v1/courses/{course_id}/{resource}?per_page=1')
              for name, resource in PROBES]
    routes.append(('new_quizzes', f'/api/quiz/v1/courses/{course_id}/quizzes?per_page=1'))
    results = []
    limited = False
    for name, route in routes:
        if limited:
            status = 'not_checked_after_rate_limit'
        else:
            try:
                client.request(route)
                status = 'readable'
            except CanvasError as error:
                status = _status(error)
                limited = status == 'rate_limited_429'
        results.append({'area': name, 'status': status})
    return {'course_id': course_id, 'probes': results,
            'note': 'Read-only API reachability, not a guarantee of published content or feature completeness.'}
