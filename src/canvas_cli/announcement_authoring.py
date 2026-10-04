"""Native announcement authoring, distinct from discussion drafts and replies."""

from datetime import datetime, timedelta, timezone

from . import topic_dates, topic_podcast, topic_sections
from .client import CanvasError
from .events import timestamp
from .group_content import _id, _number, base
from .topic_dates import instant, matches
from .topic_management import (
    _changes,
    _inventory,
    _inventory_delta,
    _matches,
    _parent,
    _read,
    _scope,
    _topic,
)
from .writes import account, check_flags, confirmed, digest

WARNING = ('Changes a shared announcement, not a private draft, reply or note. Native announcements '
           'are always published; future posting is scheduling, not draft privacy. Creation/updates '
           'can notify participants and observers and update activity/participant records. Delivery '
           'and future execution are not verified. Native permissions, HTML processing, course comment '
           'locks and blueprint restrictions remain authoritative. Deletion does not recall notifications '
           'or prove permanent erasure. No peer replies, grading, attachment transfer or settings '
           'beyond selected comment/date/section/podcast operations, explicitly acknowledged attachment removal or closing-date clearing, '
           'automatic retry, cleanup or rollback are requested. Preflight is not an atomic lock.')
UNCERTAIN = ('Could not verify the announcement operation. It may already have succeeded; check Canvas '
             'before repeating. No automatic retry, cleanup, rollback or private response-body logging.')
COMMENTS_WARNING = ('Changing the shared comment lock affects whether participants may add replies; '
                    'it does not rewrite existing replies or verify who can read them. '
                    'Opening a closed announcement can clear its closing date. Only the stored lock and '
                    'any acknowledged date clearing are verified, not participant reply access, global '
                    'course/account restrictions, notifications or future jobs. No peer comments are read.')
DATES_WARNING = ('Changing or clearing course announcement dates can activate a delayed announcement, '
                 'change availability, reopen or close comments and trigger native activity/participant/observer effects. '
                 'Announcements remain published, never private drafts. Changed closing dates can override the '
                 'requested current comment lock; native reply-state handling can clear an unselected closing date. '
                 'Only selected stored instants and observed changes are verified, not participant visibility/reply '
                 'access, notifications or future jobs. Course-midnight closing is rewritten to end of day; '
                 'select an explicit non-midnight instant. No peer comments, retry or rollback.')
ATTACHMENT_WARNING = ('Removes the announcement attachment and asks native Canvas to soft-delete its file record, '
                      'not just hide a link. Native deletion can remove content tags, detach media/LTI/draft associations '
                      'and update downstream records. Copies, existing downloads, message-body links and other uses may '
                      'remain or become broken. Only the exact announcement attachment-list clearing is verified, not '
                      'file-record deletion, related-record effects, storage erasure, other references or notification recall. Native attach '
                      'permission is separate from update permission; it can cause silent parameter omission. '
                      'An error does not prove the file or association was unchanged. No file download, peer reads, '
                      'automatic retry, restoration or cleanup.')


def _local(item, context_type, max_pages, acknowledge_shared):
    if context_type not in ('course', 'group'):
        raise CanvasError('Announcement authoring requires a course or group context')
    base(item, context_type)
    if acknowledge_shared is not True or type(max_pages) is not int or max_pages < 1:
        raise CanvasError('Use --acknowledge-shared-announcement and a positive inventory limit, including previews')


def _posting(value, context_type):
    if value is None:
        return None
    if context_type != 'course':
        raise CanvasError('Native group announcement creation does not accept posting dates')
    value = instant(value)
    if timestamp(value) <= datetime.now(timezone.utc) + timedelta(seconds=60):
        raise CanvasError('Scheduled announcement posting must remain at least 60 seconds in the future')
    return value


def _published(parsed):
    if parsed['published'] is not True or parsed['can_unpublish'] is not False:
        raise CanvasError('Canvas did not report native always-published, non-draft announcement semantics')
    return {**parsed, 'is_announcement': True}


def _metadata(row, item, identifier, context_type, *, require_audience=False, require_attach=False, require_podcast=False):
    return _published(_topic(row, item, identifier, context_type, announcement=True, require_audience=require_audience,
                             require_attach=require_attach, require_podcast=require_podcast))


def _current(client, route, item, identifier, context_type, *, require_audience=False, require_attach=False, require_podcast=False):
    return _published(_read(client, route, item, identifier, context_type, announcement=True, require_audience=require_audience,
                            require_attach=require_attach, require_podcast=require_podcast))


def _listed(row):
    return {key: row[key] for key in ('id', 'title', 'published', 'locked', 'pinned', 'position')}


def _creation_rights(client, item, context_type):
    route, context = _scope(client, item, context_type)
    row, _ = client.request(route + '?include%5B%5D=permissions')
    if _id(row) != int(item) or {key: row.get(key) for key in context} != context:
        raise CanvasError('Announcement context changed while reading native creation permission')
    rights = row.get('permissions')
    if not isinstance(rights, dict) or rights.get('create_announcement') is not True:
        raise CanvasError('Canvas did not grant dynamic native announcement creation in this context')
    return route, context


def _section_result(after, sections):
    return {'specific_sections': sections['specific_sections'], 'section_ids': after['section_ids'],
            'is_section_specific': after['is_section_specific'], 'verified': True,
            'audience_change_acknowledged': True, 'effective_participant_visibility_verified': False,
            'participant_record_effects_verified': False}


def create(client, item, *, title, message, context_type='course', post_at=None, comments=False,
           acknowledge_shared=False, acknowledge_broadcast=False, sections=None, acknowledge_audience=False,
           max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    _local(item, context_type, max_pages, acknowledge_shared)
    if acknowledge_broadcast is not True or type(comments) is not bool or title is None or message is None:
        raise CanvasError('Announcement creation needs a title, message, boolean comment choice and --acknowledge-broadcast')
    if type(acknowledge_audience) is not bool or acknowledge_audience != (sections is not None):
        raise CanvasError('Selecting initial announcement sections needs --acknowledge-audience-change, including previews; not for the default audience')
    if sections is not None:
        sections = topic_sections.validate(sections, context_type)
    body = {**_changes(title, message), 'is_announcement': True, 'lock_comment': not comments}
    if sections is not None:
        body.update(sections)
    posting = _posting(post_at, context_type)
    if posting is not None:
        body['delayed_post_at'] = posting
    identity = account(client)
    route, context = _creation_rights(client, item, context_type)
    section_inventory = topic_sections.inventory(client, route, item, max_pages) if sections is not None else None
    if sections is not None:
        topic_sections.check_selection(sections, section_inventory)
    inventory = _inventory(client, route, item, context_type, max_pages, announcement=True)
    if (_creation_rights(client, item, context_type) != (route, context) or
            _inventory(client, route, item, context_type, max_pages, announcement=True) != inventory or
            account(client) != identity):
        raise CanvasError('Announcement context, permission, inventory or account changed during preflight')
    if sections is not None and topic_sections.inventory(client, route, item, max_pages) != section_inventory:
        raise CanvasError('Active course sections changed during creation preflight; review a fresh preview')
    _posting(posting, context_type)
    preview = {**identity, 'context_type': context_type, f'{context_type}_id': int(item), 'context': context,
               'permissions': {'create_announcement': True}, 'inventory_digest': digest(inventory),
               'acknowledge_shared_announcement': True, 'acknowledge_broadcast': True,
               'posting_choice': 'scheduled' if posting else 'post_now',
               'method': 'POST', 'route': route + '/discussion_topics?no_verifiers=true', 'body': body, 'warning': WARNING}
    if sections is not None:
        preview.update(acknowledge_audience_change=True, section_inventory_digest=digest(section_inventory),
                       active_section_ids=[row['id'] for row in section_inventory], warning=WARNING + ' ' + topic_sections.WARNING)
    response = confirmed(client, preview, yes, confirm, uncertain_message=UNCERTAIN if sections is not None else None)
    if not yes:
        return response
    try:
        identifier = _id(response)
        if identifier in {row['id'] for row in inventory}:
            raise CanvasError('Canvas acknowledged an existing announcement')
        after = _metadata(response, item, str(identifier), context_type, require_audience=sections is not None)
        if (after['author_id'] != identity['user_id'] or after['locked'] is not (not comments) or
                not matches(after, 'delayed_post_at', posting)):
            raise CanvasError('Canvas did not store the requested announcement author/comment state/posting instant')
        if (_creation_rights(client, item, context_type) != (route, context) or account(client) != identity or
                _current(client, route, item, str(identifier), context_type, require_audience=sections is not None) != after):
            raise CanvasError('Announcement acknowledgement and independent readback do not agree')
        if sections is not None and (not topic_sections.matches(after, sections) or
                                    topic_sections.inventory(client, route, item, max_pages) != section_inventory):
            raise CanvasError('Initial announcement section filter or active course section inventory did not agree')
        remaining = _inventory(client, route, item, context_type, max_pages, announcement=True)
        if _listed(after) not in remaining or account(client) != identity:
            raise CanvasError('The new announcement was not verified in the complete accessible inventory')
    except CanvasError:
        raise CanvasError(UNCERTAIN) from None
    result = {'created_announcement': {**after, 'html_url': client.host + f'/{context_type}s/{item}/discussion_topics/{identifier}'},
            'context_type': context_type, f'{context_type}_id': int(item), 'new_id_verified': True,
            'acknowledgement_matches_readback': True,
            'stored_text_matches_request': {key: _matches(after, key, body[key]) for key in ('title', 'message')},
            'comments_locked': after['locked'], 'stored_posting_at': after['delayed_post_at'],
            'future_execution_verified': False, 'notification_delivery_verified': False,
            'observed_inventory_changes': _inventory_delta(inventory, remaining),
            'note': 'One native POST, own author/new announcement ID, exact comment/date state and independent '
                    'topic/inventory readback verified with stable identity/context/creation permission. '
                    'Text normalization and other inventory changes are labeled. Published is not delivery or '
                    'availability proof; no private prompt, peer replies, retry or cleanup.'}
    if sections is not None:
        result.update(announcement_section_filter=_section_result(after, sections), note=result['note'] + ' ' + topic_sections.WARNING)
    return result


def change(client, item, identifier, *, context_type='course', title=None, message=None, delete=False,
           acknowledge_shared=False, acknowledge_broadcast=False, acknowledge_removal=False,
           comments=None, acknowledge_comments=False, acknowledge_schedule_removal=False,
           schedule=None, acknowledge_availability=False,
           sections=None, acknowledge_audience=False,
           remove_attachment=False, acknowledge_attachment_removal=False, podcast=None, acknowledge_podcast=False,
           max_pages=100, yes=False, confirm=None):
    check_flags(yes, confirm)
    _local(item, context_type, max_pages, acknowledge_shared)
    _number(identifier)
    if (type(delete) is not bool or type(acknowledge_removal) is not bool or delete != acknowledge_removal or
            type(acknowledge_broadcast) is not bool or acknowledge_broadcast != (not delete)):
        raise CanvasError('Editing requires --acknowledge-broadcast; deletion instead needs --acknowledge-announcement-removal')
    if (comments is not None and type(comments) is not bool or acknowledge_comments is not (comments is not None) or
            type(acknowledge_schedule_removal) is not bool or comments is None and acknowledge_schedule_removal):
        raise CanvasError('Select --comments/--no-comments with --acknowledge-comment-access-change; date-removal consent is separate')
    if delete and (title is not None or message is not None or comments is not None):
        raise CanvasError('Announcement deletion cannot include text or comment-state edits')
    if type(acknowledge_availability) is not bool or acknowledge_availability != (schedule is not None):
        raise CanvasError('Announcement scheduling needs --acknowledge-availability-change, including previews; not for other edits')
    if schedule is not None:
        if context_type != 'course' or delete or title is not None or message is not None or comments is not None:
            raise CanvasError('Select course announcement dates separately from text, comment-state and deletion operations')
        schedule = topic_dates.validate(schedule, context_type)
    if type(acknowledge_audience) is not bool or acknowledge_audience != (sections is not None):
        raise CanvasError('Announcement section filtering needs --acknowledge-audience-change, including previews; not for other edits')
    if sections is not None:
        if delete or title is not None or message is not None or comments is not None or schedule is not None:
            raise CanvasError('Select announcement sections separately from text, comments, dates and deletion')
        sections = topic_sections.validate(sections, context_type)
    if (type(remove_attachment) is not bool or type(acknowledge_attachment_removal) is not bool or
            remove_attachment != acknowledge_attachment_removal):
        raise CanvasError('Announcement attachment removal needs --acknowledge-attachment-removal, including previews; not for other edits')
    if remove_attachment and (delete or title is not None or message is not None or comments is not None or
                              schedule is not None or sections is not None):
        raise CanvasError('Remove an announcement attachment separately from text, comments, dates, audience and announcement deletion')
    if type(acknowledge_podcast) is not bool or acknowledge_podcast != (podcast is not None):
        raise CanvasError('Podcast settings need --acknowledge-podcast-feed-change, including previews; not for other operations')
    if podcast is not None and (delete or title is not None or message is not None or comments is not None or
                                schedule is not None or sections is not None or remove_attachment):
        raise CanvasError('Select announcement podcast settings separately from other operations')
    podcast_values = topic_podcast.validate(podcast, context_type) if podcast is not None else None
    if delete:
        changes = None
    elif remove_attachment:
        changes = {'remove_attachment': True}
    elif podcast is not None:
        changes = podcast_values
    elif sections is not None:
        changes = sections
    elif schedule is not None:
        changes = schedule
    elif title is not None or message is not None or comments is None:
        changes = _changes(title, message)
    else:
        changes = {}
    identity = account(client)
    route, context = _scope(client, item, context_type)
    before = _current(client, route, item, identifier, context_type, require_audience=sections is not None,
                      require_attach=remove_attachment, require_podcast=podcast is not None)
    if before['permissions']['delete' if delete else 'update'] is not True:
        raise CanvasError('Canvas does not permit this exact announcement operation')
    if remove_attachment and (before['permissions']['attach'] is not True or len(before['attachments']) != 1):
        raise CanvasError('Removal requires exact native attach permission and one existing announcement attachment')
    podcast_rights = topic_podcast.authority(client, route) if podcast is not None else None
    section_inventory = topic_sections.inventory(client, route, item, max_pages) if sections is not None else None
    if sections is not None:
        topic_sections.check_selection(sections, section_inventory)
    if schedule is not None:
        topic_dates.validate_current(schedule, before, context)
    locked = before['locked'] if comments is None else not comments
    clearing = comments is True and before['locked'] is True and before['lock_at'] is not None
    if acknowledge_schedule_removal is not clearing:
        raise CanvasError('Opening this closed announcement clears its closing date; use --acknowledge-closing-schedule-removal only for that change')
    if comments is False and before['locked'] is False and before['can_lock'] is not True:
        raise CanvasError('Canvas did not report eligibility to close this announcement to comments')
    if not delete and not remove_attachment and all(_matches(before, key, value) for key, value in changes.items()) and before['locked'] is locked:
        raise CanvasError('The selected announcement state already matches; no update needed')
    inventory = _inventory(client, route, item, context_type, max_pages, announcement=True)
    if (_listed(before) not in inventory or
            _current(client, route, item, identifier, context_type, require_audience=sections is not None,
                     require_attach=remove_attachment, require_podcast=podcast is not None) != before or
            _scope(client, item, context_type) != (route, context) or
            _inventory(client, route, item, context_type, max_pages, announcement=True) != inventory or account(client) != identity):
        raise CanvasError('Announcement/context/inventory/account changed during preflight')
    if sections is not None and topic_sections.inventory(client, route, item, max_pages) != section_inventory:
        raise CanvasError('Active course sections changed during preflight; review a fresh preview')
    if podcast is not None:
        topic_podcast.authority(client, route)
    # Native updates default locked=false. Send only the selected/preserved
    # comment state; the original locked parameter can write creator preferences.
    body = None if delete else {**changes, 'is_announcement': True, 'lock_comment': locked}
    preview = {**identity, 'context_type': context_type, f'{context_type}_id': int(item), 'context': context,
               'announcement': before, 'inventory_digest': digest(inventory),
               'acknowledge_shared_announcement': True, 'acknowledge_broadcast': acknowledge_broadcast,
               'acknowledge_comment_access_change': acknowledge_comments,
               'acknowledge_closing_schedule_removal': acknowledge_schedule_removal,
               'comment_choice': 'preserve' if comments is None else 'open' if comments else 'closed',
               'acknowledge_announcement_removal': acknowledge_removal, 'method': 'DELETE' if delete else 'PUT',
               'route': route + '/discussion_topics/' + identifier + '?no_verifiers=true', 'body': body,
               'warning': WARNING + (' ' + COMMENTS_WARNING if comments is not None else '')}
    if schedule is not None:
        preview.update(acknowledge_availability_change=True, comment_policy='native_date_effects',
                       warning=WARNING + ' ' + DATES_WARNING)
    if sections is not None:
        preview.update(acknowledge_audience_change=True, section_inventory_digest=digest(section_inventory),
                       active_section_ids=[row['id'] for row in section_inventory], warning=WARNING + ' ' + topic_sections.WARNING)
    if remove_attachment:
        preview.update(acknowledge_attachment_removal=True, removed_attachment_id=before['attachments'][0]['id'],
                       warning=WARNING + ' ' + ATTACHMENT_WARNING)
    if podcast is not None:
        preview.update(acknowledge_podcast_feed_change=True, podcast_mode=podcast, podcast_permissions=podcast_rights,
                       warning=WARNING + ' ' + topic_podcast.WARNING)
    response = confirmed(client, preview, yes, confirm,
                         uncertain_message=UNCERTAIN if sections is not None or remove_attachment or podcast is not None else None)
    if not yes:
        return response
    try:
        if _scope(client, item, context_type) != (route, context) or account(client) != identity:
            raise CanvasError('Announcement context/account changed during verification')
        if delete:
            if _id(response) != int(identifier) or response.get('workflow_state') != 'deleted' or response.get('type') != 'Announcement':
                raise CanvasError('Canvas did not acknowledge the exact native announcement soft deletion')
            _parent(response, item, context_type)
            remaining = _inventory(client, route, item, context_type, max_pages, announcement=True)
            if any(row['id'] == int(identifier) for row in remaining):
                raise CanvasError('Deleted announcement remains in the active inventory')
            try:
                _current(client, route, item, identifier, context_type)
            except CanvasError as error:
                if error.status not in (404, 410):
                    raise
                missing_status = error.status
            else:
                raise CanvasError('Deleted announcement remains readable')
        else:
            after = _metadata(response, item, identifier, context_type, require_audience=sections is not None,
                              require_attach=remove_attachment, require_podcast=podcast is not None)
            if (_current(client, route, item, identifier, context_type, require_audience=sections is not None,
                         require_attach=remove_attachment, require_podcast=podcast is not None) != after or
                    schedule is None and after['locked'] is not locked or
                    clearing and after['lock_at'] is not None):
                raise CanvasError('Announcement readback or selected/preserved comment lock/date clearing did not agree')
            if remove_attachment and after['attachments'] != []:
                raise CanvasError('Canvas did not clear the announcement attachment list')
            if podcast is not None:
                if (any(after[key] is not value for key, value in podcast_values.items()) or
                        after['permissions']['update'] is not True):
                    raise CanvasError('Canvas did not store the selected podcast flags and retain the native update right')
                topic_podcast.authority(client, route)
            if schedule is not None and not all(matches(after, key, value) for key, value in schedule.items()):
                raise CanvasError('Canvas did not store every selected announcement date as an exact instant or explicit clearing')
            if sections is not None and (not topic_sections.matches(after, sections) or
                                        topic_sections.inventory(client, route, item, max_pages) != section_inventory):
                raise CanvasError('Announcement section filter or active course section inventory did not agree')
            remaining = _inventory(client, route, item, context_type, max_pages, announcement=True)
            if _listed(after) not in remaining:
                raise CanvasError('Edited announcement is absent from its accessible inventory')
        if account(client) != identity:
            raise CanvasError('Account changed during announcement verification')
    except CanvasError:
        raise CanvasError(UNCERTAIN) from None
    shared = {'context_type': context_type, f'{context_type}_id': int(item),
              'observed_inventory_changes': _inventory_delta(inventory, remaining),
              'notification_delivery_verified': False}
    if delete:
        return {**shared, 'deleted_announcement': {'id': int(identifier), 'title': before['title']},
                'removed_from_active_inventory': True, 'exact_id_read_status': missing_status,
                'note': 'Native announcement soft deletion, active-inventory absence and exact-ID not-found '
                        'verified with stable context/account. No permanent-erasure, attachment cleanup or '
                        'notification-recall proof; no retry or rollback.'}
    requested = {'message_digest' if key == 'message' else key for key in changes}
    if sections is not None:
        requested.update(('is_section_specific', 'section_ids'))
    if remove_attachment:
        requested.add('attachments')
    if comments is not None:
        requested.add('locked')
    if clearing:
        requested.add('lock_at')
    changed = [key for key in before if before[key] != after[key]]
    result = {**shared, 'edited_announcement': {**after, 'html_url': client.host + f'/{context_type}s/{item}/discussion_topics/{identifier}'},
            'acknowledgement_matches_readback': True, 'comment_lock_preserved': after['locked'] is before['locked'],
            **({'announcement_comment_state': {'comments_locked': after['locked'], 'closing_schedule_cleared': clearing,
                                              'reported_context_comments_disabled': after['comments_disabled'],
                                              'participant_reply_access_verified': False}} if comments is not None else {}),
            'stored_text_matches_request': {key: _matches(after, key, value) for key, value in changes.items() if key in ('title', 'message')},
            'changed_fields': changed, 'unrequested_changed_fields': [key for key in changed if key not in requested],
            'note': 'One native PUT, independent announcement/inventory readback and selected text/comment/date/section/attachment state '
                    'verified with stable context/account. HTML normalization and other observed changes are '
                    'labeled, not causal proof. No private prompt, peer replies, explicit preference write, retry or rollback.' +
                    (' ' + COMMENTS_WARNING if comments is not None else '')}
    if schedule is not None:
        result.update(scheduled_announcement_dates={
            'requested': schedule, 'stored': {key: after[key] for key in schedule}, 'verified': True,
            'availability_change_acknowledged': True,
            'observed_states': {key: {'before': before[key], 'after': after[key]} for key in ('published', 'locked')},
            'reported_context_comments_disabled': after['comments_disabled'],
            'participant_visibility_verified': False, 'participant_reply_access_verified': False,
            'future_execution_verified': False}, note=result['note'] + ' ' + DATES_WARNING)
    if sections is not None:
        result.update(announcement_section_filter=_section_result(after, sections), note=result['note'] + ' ' + topic_sections.WARNING)
    if remove_attachment:
        result.update(announcement_attachment_removal={'removed_attachment_id': before['attachments'][0]['id'],
                      'attachment_list_cleared': True, 'verified': True, 'file_record_deletion_verified': False,
                      'related_record_effects_verified': False, 'storage_erasure_verified': False, 'other_references_verified': False},
                      note=result['note'] + ' ' + ATTACHMENT_WARNING)
    if podcast is not None:
        result.update(podcast_settings=topic_podcast.result(podcast, podcast_values, after, context_type),
                      note=result['note'] + ' ' + topic_podcast.WARNING)
    return result
