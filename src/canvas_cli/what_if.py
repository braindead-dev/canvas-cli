"""Own saved hypothetical point scores, never official grades or submissions."""

import math

from .client import CanvasError
from .group_content import _number
from .own_submission import ASSIGNMENT_FIELDS, SUBMISSION_FIELDS, context
from .writes import account, check_flags, review

_READ = ('query CanvasWhatIfScore($assignmentId: ID!, $userId: ID!) { '
         'assignment(id: $assignmentId) { ' + ASSIGNMENT_FIELDS + ' } '
         'submission(assignmentId: $assignmentId, userId: $userId) { ' + SUBMISSION_FIELDS + ' studentEnteredScore } }')
_NOTE = ('Saved hypothetical assignment-point score, not an official grade, submission, completion or GPA prediction. '
         'Negative and above-possible point scores are native possibilities. Missing own submissions are unknown, not zero. '
         'No answers, comments, grade edits or assessment attempts are requested.')
_EFFECT = ('Updates or clears exactly one own saved what-if score, then invokes native course recalculation, which can be costly. '
           'The native endpoint requires own submission and submit permission; it changes the hypothetical score column, '
           'not official grades. Forecasts can include other saved what-if scores, native rules and cached grading-period data; '
           'they are not a promised final grade. No course-wide reset, polling, automatic retries or rollback. '
           'Confirmation is not an atomic lock.')
_UNCERTAIN = ('The what-if outcome is unverified; the saved hypothetical score may already have changed even if calculation failed. '
              'Inspect Canvas before repeating. No private response was logged. No automatic retries.')


def _score(value, *, string=False):
    if string and isinstance(value, str):
        try:
            value = float(value)
        except (ValueError, OverflowError):
            raise CanvasError('Canvas returned malformed hypothetical score; no private response was logged') from None
    if value is not None:
        if type(value) not in (int, float):
            raise CanvasError('Use a finite numeric hypothetical point score or explicit clearing, not a boolean or nonfinite value')
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise CanvasError('Use a finite numeric hypothetical point score or explicit clearing, not a boolean or nonfinite value')
    return value


def read(client, course_id, assignment_id):
    _number(course_id)
    _number(assignment_id)
    identity = account(client)
    data = client.graphql(_READ, {'assignmentId': assignment_id, 'userId': str(identity['user_id'])}, 'CanvasWhatIfScore')
    state = context(data, identity, course_id, assignment_id)
    value = None
    if state['submission'] is not None:
        if 'studentEnteredScore' not in data['submission']:
            raise CanvasError('Canvas omitted selected hypothetical score metadata')
        value = _score(data['submission']['studentEnteredScore'])
    if account(client) != identity:
        raise CanvasError('Signed-in account changed during what-if inspection; no mutation was sent')
    return {**state, 'student_entered_score': value,
            'what_if_status': 'unknown_no_accessible_submission' if state['submission'] is None else 'reported', 'note': _NOTE}


def _forecasts(rows):
    if not isinstance(rows, list) or len(rows) > 1:
        raise CanvasError('Canvas returned unavailable own what-if forecasts')
    result = []
    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(row.get(key), dict) for key in ('current', 'final')):
            raise CanvasError('Canvas returned malformed what-if forecast totals')
        result.append({kind: {key: _score(value) for key, value in row[kind].items()
                              if key in ('grade', 'total', 'possible', 'full_weight')} for kind in ('current', 'final')})
    return result


def change(client, course_id, assignment_id, score, *, acknowledge=False, include_forecasts=False, yes=False, confirm=None):
    check_flags(yes, confirm)
    score = _score(score)
    if not acknowledge:
        raise CanvasError('Use --acknowledge-forecast-change even for preview: ' + _EFFECT)
    before = read(client, course_id, assignment_id)
    if before['submission'] is None:
        raise CanvasError('No accessible existing own submission; the CLI will not initialize it or start an assessment')
    route = f"/api/v1/submissions/{before['submission']['id']}/what_if_grades"
    body = {'student_entered_score': score}
    preview = {**before, 'method': 'PUT', 'route': route, 'body': body, 'include_forecasts': include_forecasts, 'effect': _EFFECT}
    result = review(preview, yes, confirm)
    if result is not None:
        return result
    try:
        ack, _ = client.request(route, 'PUT', body)
        selected = ack.get('submission') if isinstance(ack, dict) else None
        if (not isinstance(selected, dict) or type(selected.get('id')) is not int
                or str(selected['id']) != before['submission']['id'] or 'student_entered_score' not in selected
                or _score(selected['student_entered_score'], string=True) != score):
            raise CanvasError(_UNCERTAIN)
        forecasts = _forecasts(ack.get('grades'))
        after = read(client, course_id, assignment_id)
        if after != {**before, 'student_entered_score': score}:
            raise CanvasError(_UNCERTAIN)
    except CanvasError as error:
        raise CanvasError(_UNCERTAIN, status=error.status) from None
    return {**after, 'mutation_acknowledged': True, 'hypothetical_score_readback_verified': True,
            'forecasts_included': include_forecasts, 'native_forecast_count': len(forecasts),
            **({'native_forecast_totals': forecasts} if include_forecasts else {}),
            'official_grade_change_requested': False, 'coursework_completion_requested': False, 'note': _NOTE + ' ' + _EFFECT}
