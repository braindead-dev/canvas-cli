"""Own native feedback indicators, never proof of viewing or coursework completion."""

from .client import CanvasError
from .group_content import _number
from .own_submission import ASSIGNMENT_FIELDS, SUBMISSION_FIELDS, context
from .writes import account, check_flags, review

SURFACES = ('overall', 'grade', 'comment', 'rubric', 'annotations', 'rubric-feedback')
_PREFERENCES = {'annotations': 'document_annotations', 'rubric-feedback': 'rubric_assessments'}
_READ = ('query CanvasSubmissionAttention($assignmentId: ID!, $userId: ID!) { '
         'assignment(id: $assignmentId) { ' + ASSIGNMENT_FIELDS + ' } '
         'submission(assignmentId: $assignmentId, userId: $userId) { ' + SUBMISSION_FIELDS + ' readState } }')
_NOTE = ('Own feedback indicators only, not proof of reading, understanding, submission or coursework completion. '
         'No grade values, answers, peer comment bodies, assessment attempts or annotation initialization are queried. '
         'Aggregate read state and annotation/rubric-feedback preferences are distinct native surfaces.')
_EFFECT = ('The native overall read/unread endpoint uses a default grade participation item; it does not clear every '
           'unread comment/rubric item. An acknowledged read request can leave the aggregate unread. Item grade/comment/rubric '
           'markers have no independently exposed storage getter here. Comment-item marking also marks all natively visible '
           'submission comments viewed, without fetching bodies. Native counters, activity and planner caches can change. '
           'Preference markers clear only the selected own annotation/rubric-feedback flag, not participation items. '
           'Confirmation is not an atomic lock; the legacy overall route can initialize a concurrently missing submission. '
           'No automatic retries, bulk acknowledgement or rollback.')
_UNCERTAIN = ('The feedback-indicator operation outcome is unverified; it may have applied. Inspect Canvas before repeating. '
              'No private response was logged. No automatic retries.')


def _base(state):
    return (f"/api/v1/courses/{state['course_id']}/assignments/{state['assignment_id']}/"
            f"submissions/{state['user_id']}")


def _boolean(row):
    if not isinstance(row, dict) or type(row.get('read')) is not bool:
        raise CanvasError('Canvas returned unavailable feedback-indicator metadata; no private response was logged')
    return row['read']


def _inspect(client, course_id, assignment_id, preferences=()):
    _number(course_id)
    _number(assignment_id)
    identity = account(client)
    data = client.graphql(_READ, {'assignmentId': assignment_id, 'userId': str(identity['user_id'])}, 'CanvasSubmissionAttention')
    state = context(data, identity, course_id, assignment_id)
    selected, read_state = {}, None
    if state['submission'] is not None:
        read_state = data['submission'].get('readState')
        if read_state not in ('read', 'unread'):
            raise CanvasError('Canvas returned unavailable aggregate submission read state')
        for name in preferences:
            row, _ = client.request(_base(state) + '/' + _PREFERENCES[name] + '/read')
            selected[name] = _boolean(row)
    if account(client) != identity:
        raise CanvasError('Signed-in account changed during feedback-indicator inspection; no mutation was sent')
    return {**state, 'aggregate_read_state': read_state, 'preference_read_markers': selected,
            'attention_status': 'unknown_no_accessible_submission' if state['submission'] is None else 'reported', 'note': _NOTE}


def read(client, course_id, assignment_id, *, include_preferences=False):
    return _inspect(client, course_id, assignment_id, tuple(_PREFERENCES) if include_preferences else ())


def change(client, course_id, assignment_id, new_state, *, surface='overall', acknowledge=False, yes=False, confirm=None):
    check_flags(yes, confirm)
    if new_state not in ('read', 'unread') or surface not in SURFACES or new_state == 'unread' and surface != 'overall':
        raise CanvasError('Native unread is supported only for the overall indicator; choose a supported read surface')
    if not acknowledge:
        raise CanvasError('Use --acknowledge-feedback-indicators even for preview: ' + _EFFECT)
    preferences = (surface,) if surface in _PREFERENCES else ()
    before = _inspect(client, course_id, assignment_id, preferences)
    if before['submission'] is None:
        raise CanvasError('No accessible existing own submission; the CLI will not initialize it or start an assessment')
    route = _base(before) + '/read'
    if preferences:
        route = _base(before) + '/' + _PREFERENCES[surface] + '/read'
    elif surface != 'overall':
        route += '/' + surface
    preview = {**before, 'method': 'DELETE' if new_state == 'unread' else 'PUT', 'route': route, 'body': None,
               'surface': surface, 'requested_state': new_state, 'effect': _EFFECT,
               'expected_response': 'read_boolean' if preferences else 'no_content'}
    result = review(preview, yes, confirm)
    if result is not None:
        return result
    try:
        ack, _ = client.request(route, preview['method'], expect_no_content=not preferences)
        if preferences and _boolean(ack) is not True:
            raise CanvasError(_UNCERTAIN)
        after = _inspect(client, course_id, assignment_id, preferences)
        excluded = ('aggregate_read_state', 'preference_read_markers')
        if {key: value for key, value in after.items() if key not in excluded} != {
                key: value for key, value in before.items() if key not in excluded}:
            raise CanvasError(_UNCERTAIN)
        if preferences and after['preference_read_markers'][surface] is not True:
            raise CanvasError(_UNCERTAIN)
    except CanvasError as error:
        raise CanvasError(_UNCERTAIN, status=error.status) from None
    return {**after, 'mutation_acknowledged': True, 'surface': surface, 'requested_state': new_state,
            'aggregate_matches_requested_state': after['aggregate_read_state'] == new_state if surface == 'overall' else None,
            'selected_preference_readback_verified': bool(preferences), 'participation_item_storage_verified': False,
            'before_aggregate_read_state': before['aggregate_read_state'], 'coursework_completion_requested': False,
            'note': _NOTE + ' ' + _EFFECT}
