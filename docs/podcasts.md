# Podcast settings

[Documentation](README.md) · [Discussions](communication.md) · [Announcements](announcements.md) · [Safety](safety.md)

Change native shared media-feed settings on a readable ungraded discussion or announcement. This is not a personal subscription or a complete discussion export.

## Course modes

```sh
canvas topic-podcast 123 456 --mode moderator-posts --acknowledge-shared-topic --acknowledge-podcast-feed-change
canvas topic-podcast 123 456 --mode all-posts --acknowledge-shared-topic --acknowledge-podcast-feed-change
canvas announcement-podcast 123 789 --mode disabled --acknowledge-shared-announcement --acknowledge-broadcast --acknowledge-podcast-feed-change
```

`moderator-posts` enables the feed without student posts; native course-admin filtering and participant visibility remain authoritative. `all-posts` enables it and includes student posts. `disabled` explicitly clears both flags because submitting a true student-post flag also enables the podcast. Course `enabled` is rejected as an ambiguous filter choice.

Announcements additionally require broadcast consent and preserve the current comment lock through `lock_comment`, without setting creator preferences. Announcements remain published; a feed change is not a draft or availability change.

## Group modes

```sh
canvas topic-podcast 123 456 --context group --mode enabled --acknowledge-shared-topic --acknowledge-podcast-feed-change
canvas announcement-podcast 123 789 --context group --mode disabled --acknowledge-shared-announcement --acknowledge-broadcast --acknowledge-podcast-feed-change
```

Groups accept only `enabled` or `disabled`. Native group requests ignore the course student-post option, and group feeds do not use that course filter. The CLI does not send or claim to change it. Other topic fields are left unselected.

## Review and evidence

All acknowledgements are required even for preview. Review the exact account, context, topic and body, then repeat with `--yes --confirm DIGEST`. Native topic update and exact context `moderate_forum` permission are required; creation/delete rights or guessed authorship/roles are not substitutes.

Confirmation binds private content/feed-code fingerprints, current flags, author/attachments/audience metadata, rights and complete accessible inventory. One PUT must produce an acknowledgement matching an independent exact-topic read, selected flags, preserved comment lock, retained rights and a matching inventory entry. Stale previews refuse before sending. Ignored fields, errors after sending, denied readback or mismatches are uncertain and never retried automatically.

`podcast_enabled` is inferred from the native serializer's null/non-null feed URL; the serializer does not expose that stored flag directly. Feed URLs contain access codes. They are fingerprinted, never printed or fetched by these commands. JSON and brief output verify stored mode only, not actual feed access, notifications, code revocation or recall of existing downloads.

## Boundaries

Feeds contain linked/embedded media rather than all text replies. Initial-post protections and native visibility/locks still apply. No peer replies, feed downloads/subscriptions, credential rotation, assessments or restoration are requested. Preflight is not an atomic lock. Graded, anonymous and root/child/group-set topics require separate workflows.

Granular course discussion-option permissions can silently discard fields even with moderation rights. Independent readback catches an unfulfilled request; a granted permission does not promise success on every deployment.

## Primary sources

[Discussion API](https://developerdocs.instructure.com/services/canvas/resources/discussion_topics), pinned native [field filtering and moderation](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/controllers/discussion_topics_controller.rb#L1314), [feed URL serialization](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/lib/api/v1/discussion_topics.rb#L280), [RSS behavior](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/controllers/discussion_entries_controller.rb#L159) and [course-only filtering](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/models/discussion_topic.rb#L2004).
