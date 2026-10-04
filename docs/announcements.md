# Shared announcements

[Documentation](README.md) · [Communication](communication.md) · [Confirmation](safety.md#confirmation)

These commands change a course/group announcement, not your reply or a private note. Native announcements cannot be drafts. They may notify participants and observers and update activity/participant records. Use only a context you are authorized to manage.

## Create

```sh
canvas announcement-create 123 --title 'Team update' --message-file announcement.txt --acknowledge-shared-announcement --acknowledge-broadcast
canvas announcement-create 123 --context group --title 'Team update' --message-file announcement.txt --acknowledge-shared-announcement --acknowledge-broadcast
canvas announcement-create 123 --title 'Scheduled update' --message-file announcement.txt --post-at '2099-10-01T09:00:00-07:00' --acknowledge-shared-announcement --acknowledge-broadcast
```

Both acknowledgements are required even for preview. Title and UTF-8 plain-text message are required; the message is escaped to HTML. Creation checks the exact context's dynamic `create_announcement` permission with `include[]=permissions`, not a guessed role or permission to create discussions. Without it, the CLI refuses rather than risk a native fallback to an ordinary discussion.

Comments default to closed. `--comments` requests open comments; `--no-comments` explicitly selects the default. The request uses `lock_comment`, not the creator-preference-writing `locked` parameter. Course-level restrictions can override the choice; mismatched readback is uncertain, not automatically repaired. A stored open flag does not prove participants can reply.

`--post-at` is course-only. Supply an offset-aware, whole-second future timestamp; it is normalized to UTC and must still be at least 60 seconds ahead after preflight. Stored scheduling is not draft privacy, proof of immediate visibility, notification delivery or future execution. No scheduling poll or automatic retry runs.

Account, exact context/creation right, complete accessible announcement inventory, content, comment choice and date bind confirmation. One POST must return a new announcement ID and own author, then match independent announcement and inventory readback. Stored HTML normalization is labeled. The CLI does not inspect peer comments or explicitly change attachments, audience, assignments or creator preferences.

## Edit

```sh
canvas announcement-edit 123 456 --title 'Updated announcement' --acknowledge-shared-announcement --acknowledge-broadcast
canvas announcement-edit 123 456 --context group --message-file announcement.txt --acknowledge-shared-announcement --acknowledge-broadcast
```

Exact native per-announcement update permission governs access; creation permission is not required. Omitting title or message preserves that field. Text-only edits explicitly preserve the current comment lock because the native update path can otherwise reopen comments.

Account, context, existing content fingerprint, comment state, native rights and complete accessible inventory bind the preview. Text-only PUTs must agree with independent readback and preserve the comment lock. Other observed field changes are labeled, not silently rewritten or asserted causal. Existing message bodies, private audience records and signed URLs are omitted from management previews/results; your selected replacement text remains visible in the preview.

### Change comment access deliberately

```sh
canvas announcement-edit 123 456 --comments --acknowledge-shared-announcement --acknowledge-broadcast --acknowledge-comment-access-change
canvas announcement-edit 123 456 --context group --no-comments --acknowledge-shared-announcement --acknowledge-broadcast --acknowledge-comment-access-change
canvas announcement-edit 123 456 --comments --title 'Updated announcement' --acknowledge-shared-announcement --acknowledge-broadcast --acknowledge-comment-access-change
canvas announcement-edit 123 456 --comments --acknowledge-shared-announcement --acknowledge-broadcast --acknowledge-comment-access-change --acknowledge-closing-schedule-removal
```

`--comments` opens the stored comment lock; `--no-comments` closes it. Both require comment-access acknowledgement even for preview, because permission to add replies can change. They can be used alone or combined with text edits in one PUT. A close transition also requires the exact reported `can_lock` eligibility. Omission still preserves the lock. Existing replies are not rewritten, their read access is not verified, and no peer replies are read or explicit creator preference written.

Opening a closed announcement with a closing date implicitly clears that date in native Canvas. Only that case requires `--acknowledge-closing-schedule-removal`, and independent readback must show the cleared date. Opening an already open announcement does not cancel a future closing date. Unnecessary clearing consent is refused; a wholly matching text/comment choice is a no-op, not a broadcast request.

Results distinguish the stored lock from the reported global `comments_disabled` flag. A group can store an open lock while its parent still disables replies; a course restriction can force the lock closed. Stored-state verification is not participant reply-access, notification, future-job or global-setting proof. Ignored choices or unverified date clearing fail as uncertain without retry or repair.

## Delete

```sh
canvas announcement-delete 123 456 --acknowledge-shared-announcement --acknowledge-announcement-removal
canvas announcement-delete 123 456 --context group --acknowledge-shared-announcement --acknowledge-announcement-removal
```

Deletion uses the exact reported native delete permission, not ownership or a guessed reply count. It requires removal acknowledgement instead of broadcast acknowledgement. One soft DELETE must acknowledge the same Announcement ID as deleted, remove it from the complete accessible inventory and yield exact-ID 404/410. A 403 is not absence proof.

This does not recall notifications, prove permanent erasure, delete attachments explicitly or provide a CLI restore. Replies may become inaccessible. Uncertain outcomes require checking Canvas before repeating; no retry, cleanup or rollback occurs.

## Boundaries

Only readable, non-anonymous course/group announcements without assignment/root/child/group-set associations are supported. Attachments, section/participant targeting, general date edits on existing announcements, podcasts and bulk operations remain separate work. Native permissions, locks and blueprint restrictions stay authoritative. Preflight is not an atomic lock; concurrent edits can be overwritten.

Validation covers unit tests and subprocess/local HTTPS fixtures with synthetic records. No real announcement mutation has been live-tested. Delivery, future jobs, hidden inventory effects and remote preference storage remain unverified.

## Primary references

[Discussion topic API](https://developerdocs.instructure.com/services/canvas/resources/discussion_topics), [native announcement model](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/models/announcement.rb), [native announcement request handling](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/controllers/discussion_topics_controller.rb), [native lock/global-comment rules](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/models/discussion_topic.rb).
