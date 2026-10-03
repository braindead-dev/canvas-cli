"""Own reported grades/comments/rubric feedback, never assessment answers or read markers."""

import math
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import submissions
from .client import CanvasError


def _stamp(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})', value):
        raise CanvasError('Feedback dates must be ISO timestamps with seconds and an explicit offset')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise CanvasError('Canvas returned an invalid feedback timestamp') from None


def _number(value):
    return value is None or type(value) is int or type(value) is float and math.isfinite(value)


def read(client, course_id, max_pages=100, *, assignment_ids=None, include_text=False, since=None, time_zone='local'):
    if type(include_text) is not bool:
        raise CanvasError('Feedback text must be explicitly enabled')
    if since is not None and not isinstance(since, str):
        raise CanvasError('Feedback since must be an ISO timestamp with seconds and an explicit offset')
    cutoff = _stamp(since)
    try:
        zone = None if time_zone == 'local' else ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise CanvasError('Unknown IANA time zone; use e.g. America/Los_Angeles') from None
    source = submissions.read(client, course_id, max_pages, assignment_ids=assignment_ids,
                              include_comments=True, include_rubric=True, include_feedback_text=include_text)
    output, no_feedback, excluded, uncertain_dates = [], 0, 0, 0
    for row in source['submissions']:
        if (not _number(row.get('score')) or
                row.get('grade') is not None and not isinstance(row['grade'], str) or
                any(row.get(key) is not None and type(row[key]) is not bool for key in
                    ('grade_matches_current_submission', 'redo_request', 'excused', 'late', 'missing'))):
            raise CanvasError('Canvas returned invalid own feedback grade/state metadata')
        assignment = row.get('assignment') or {}
        if (not _number(assignment.get('points_possible')) or
                assignment.get('name') is not None and not isinstance(assignment['name'], str)):
            raise CanvasError('Canvas returned invalid feedback assignment metadata')
        comments = row.get('submission_comments')
        rubric = row.get('rubric_assessment')
        has_grade = row.get('grade') is not None or row.get('score') is not None
        dates = [stamp for stamp in (_stamp(row.get('graded_at')), _stamp(row.get('posted_at'))) if stamp is not None]
        unknown_dates = (has_grade or bool(rubric)) and not dates
        selected_comments, seen = [], set()
        for comment in comments or []:
            if (type(comment.get('id')) is not int or comment['id'] < 1 or comment['id'] in seen or
                    comment.get('author_id') is not None and (type(comment['author_id']) is not int or comment['author_id'] < 1)):
                raise CanvasError('Canvas returned invalid or duplicate feedback comments')
            seen.add(comment['id'])
            created, edited = _stamp(comment.get('created_at')), _stamp(comment.get('edited_at'))
            stamp = max((value for value in (created, edited) if value is not None), default=None)
            if stamp is None:
                unknown_dates = True
            else:
                dates.append(stamp)
            item = {key: comment[key] for key in ('id', 'author_id', 'created_at', 'edited_at') if key in comment}
            if include_text and 'comment' in comment:
                if comment['comment'] is not None and not isinstance(comment['comment'], str):
                    raise CanvasError('Canvas returned invalid feedback comment text')
                item['comment'] = comment['comment']
            # Do not expose media/provider tokens or attachment/signed URLs through a summary.
            selected_comments.append(item)
        if not (has_grade or dates or comments or rubric or row.get('redo_request') is True):
            no_feedback += 1
            continue
        latest = max(dates, default=None)
        if cutoff is not None and latest is not None and latest < cutoff and not unknown_dates:
            excluded += 1
            continue
        if unknown_dates or latest is None:
            uncertain_dates += 1
        applicability = ('earlier_attempt' if row.get('grade_matches_current_submission') is False else
                         'current_attempt' if row.get('grade_matches_current_submission') is True else 'unknown')
        item = {key: row[key] for key in ('assignment_id', 'attempt', 'workflow_state', 'grade', 'score',
                                         'graded_at', 'posted_at', 'grade_matches_current_submission',
                                         'redo_request', 'excused', 'late', 'missing') if key in row}
        item.update(assignment_name=assignment.get('name'), assignment_url=assignment.get('html_url'),
                    points_possible=assignment.get('points_possible'), grade_applicability=applicability,
                    comments=selected_comments, comment_count=len(comments) if comments is not None else None,
                    comments_reported=comments is not None, rubric_assessment=rubric,
                    rubric_reported=rubric is not None, latest_reported_feedback_at=latest.isoformat() if latest else None,
                    latest_feedback_display=(latest.astimezone(zone).strftime('%a %b %d %Y %I:%M %p %Z') if latest else None),
                    timestamp_coverage_uncertain=bool(unknown_dates or latest is None))
        for key in ('feedback_text_withheld', 'rubric_assessment_withheld'):
            if key in row:
                item[key] = row[key]
        output.append((latest, item))
    # Native reassignment flags first, then earlier-attempt grades, then most recently dated feedback.
    output.sort(key=lambda pair: (pair[1].get('redo_request') is not True,
                                  pair[1]['grade_applicability'] != 'earlier_attempt', pair[0] is None,
                                  -pair[0].timestamp() if pair[0] else 0, pair[1]['assignment_id']))
    return {'origin': source['origin'], 'user_id': source['user_id'], 'course_id': source['course_id'],
            'feedback': [item for _, item in output], 'include_text': include_text,
            'since': cutoff.isoformat() if cutoff else None, 'time_zone': time_zone,
            'endpoint_submission_count': len(source['submissions']), 'excluded_no_reported_feedback': no_feedback,
            'excluded_before_since': excluded, 'included_uncertain_dates': uncertain_dates,
            'complete_for_endpoint': True, 'complete_coursework_inventory': False,
            'note': 'Own reported grades, visible submission comments and native indexed rubric results only. '
                    'Reassignment flags sort first, earlier-attempt grades next; this is not a complete work/owed-review list. '
                    'Missing associations remain unknown; comments may be your own or from peers, not necessarily instructors. '
                    'No course grade, weighting or rubric descriptions are inferred. Since filters reported grading/posting/comment '
                    'timestamps, not an audit log; uncertain dates stay included. Submitted answers, media/attachment links and '
                    'history are never printed here. GET only; no read_status inclusion, marking feedback read, grading, '
                    'assessment attempts or submissions.'}
