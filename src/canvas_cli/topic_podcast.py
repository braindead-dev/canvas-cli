"""Shared native podcast flags, with credential-bearing feed URLs kept private."""

import re

from .access import query
from .client import CanvasError
from .writes import digest

MODES = ('disabled', 'enabled', 'moderator-posts', 'all-posts')
WARNING = ('Changes shared podcast settings, not a private subscription. Course feeds can include '
           'student posts; group requests accept only enable/disable and do not apply that course filter. '
           'Native forum moderation and exact topic update rights are required. Granular course options '
           'can silently discard fields. Feeds contain linked/embedded media, not a complete discussion '
           'transcript, and native visibility/locks still apply. Only stored flags inferred from native '
           'metadata are verified, not actual feed access, notifications, access-code revocation or '
           'recall of existing downloads. Feed URLs/access codes are fingerprinted, never printed or '
           'fetched. No peer-post enumeration, feed subscription, credential rotation, retry or rollback.')


def validate(mode, context_type):
    if not isinstance(mode, str) or mode not in MODES:
        raise CanvasError('Select an explicit native podcast mode')
    if context_type == 'group':
        if mode not in ('disabled', 'enabled'):
            raise CanvasError('Group podcasts accept disabled or enabled, not a course student-post filter')
        return {'podcast_enabled': mode == 'enabled'}
    if context_type != 'course' or mode == 'enabled':
        raise CanvasError('Course podcasts require disabled, moderator-posts or all-posts')
    # Native processing enables the podcast when the submitted student-post flag
    # is true. Disabling must explicitly clear both fields, not just one.
    return {'podcast_enabled': mode != 'disabled', 'podcast_has_student_posts': mode == 'all-posts'}


def metadata(row, identifier):
    if 'podcast_url' not in row or type(row.get('podcast_has_student_posts')) is not bool:
        raise CanvasError('Canvas did not report complete native podcast metadata')
    url = row['podcast_url']
    if url is not None and (not isinstance(url, str) or not re.fullmatch(
            r'/feeds/topics/' + identifier + r'/[A-Za-z0-9_-]{1,2048}\.rss', url)):
        raise CanvasError('Canvas returned malformed or foreign podcast metadata; no feed URL is disclosed')
    return {'podcast_enabled': url is not None,
            'podcast_has_student_posts': row['podcast_has_student_posts'], 'podcast_url_digest': digest(url)}


def authority(client, route):
    rights = query(client, route, ['moderate_forum'])
    if rights['moderate_forum'] is not True:
        raise CanvasError('Canvas did not grant native forum moderation for podcast settings in this exact context')
    return rights


def result(mode, values, after, context_type):
    return {'mode': mode, 'stored': {key: after[key] for key in values}, 'verified': True,
            'course_student_filter_selected': context_type == 'course',
            'feed_access_verified': False, 'feed_code_revocation_verified': False}
