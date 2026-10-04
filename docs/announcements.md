# Shared announcements

[Documentation](README.md) · [Communication](communication.md) · [Confirmation](safety.md#confirmation)

These commands change a course/group announcement, not your reply or a private note. Native announcements cannot be drafts. They may notify participants and observers and update activity/participant records. Use only a context you are authorized to manage.

## Create

```sh
canvas announcement-create 123 --title 'Team update' --message-file announcement.txt --acknowledge-shared-announcement --acknowledge-broadcast
canvas announcement-create 123 --context group --title 'Team update' --message-file announcement.txt --acknowledge-shared-announcement --acknowledge-broadcast
canvas announcement-create 123 --title 'Scheduled update' --message-file announcement.txt --post-at '2099-10-01T09:00:00-07:00' --acknowledge-shared-announcement --acknowledge-broadcast
canvas announcement-create 123 --title 'Section update' --message-file announcement.txt --section-id 33 --section-id 34 --acknowledge-shared-announcement --acknowledge-broadcast --acknowledge-audience-change
```

Both acknowledgements are required even for preview. Title and UTF-8 plain-text message are required; the message is escaped to HTML. Creation checks the exact context's dynamic `create_announcement` permission with `include[]=permissions`, not a guessed role or permission to create discussions. Without it, the CLI refuses rather than risk a native fallback to an ordinary discussion.

Comments default to closed. `--comments` requests open comments; `--no-comments` explicitly selects the default. The request uses `lock_comment`, not the creator-preference-writing `locked` parameter. Course-level restrictions can override the choice; mismatched readback is uncertain, not automatically repaired. A stored open flag does not prove participants can reply.

`--post-at` is course-only. Supply an offset-aware, whole-second future timestamp; it is normalized to UTC and must still be at least 60 seconds ahead after preflight. Stored scheduling is not draft privacy, proof of immediate visibility, notification delivery or future execution. No scheduling poll or automatic retry runs.

Optionally set the initial course audience with repeatable `--section-id` or explicit `--all-sections`. Either choice requires `--acknowledge-audience-change`, even for preview, and the complete active section catalog must be readable. Omission preserves native default targeting and does not require a catalog lookup or extra audience consent. Group contexts reject both selectors. Posting/comment choices may be combined with initial targeting in one POST. Section-list access does not grant authoring authority; native creation and section-visibility checks remain authoritative.

Account, exact context/creation right, complete accessible announcement inventory, content, comment choice/date and any selected section catalog bind confirmation. One POST must return a new announcement ID and own author, then match independent announcement/inventory readback and any exact selected filter. Catalog names/private metadata are fingerprinted, not printed. A used creation preview cannot be reused after the inventory changes; the CLI does not retry or delete an uncertain creation. Stored state is not proof of parameter acceptance, effective participant visibility, participant-record effects or delivery. Stored HTML normalization is labeled. No peer comments, participant overrides, assignments, explicit attachments or creator-preference changes are requested.

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

## Course dates

```sh
canvas announcement-schedule 123 456 --post-at '2099-10-01T09:00:00-07:00' --closes-at '2099-10-02T12:00:00-07:00' --acknowledge-shared-announcement --acknowledge-broadcast --acknowledge-availability-change
canvas announcement-schedule 123 456 --clear-posting --acknowledge-shared-announcement --acknowledge-broadcast --acknowledge-availability-change
canvas announcement-schedule 123 456 --closes-at '2020-10-02T12:00:00-07:00' --acknowledge-shared-announcement --acknowledge-broadcast --acknowledge-availability-change
canvas announcement-schedule 123 456 --clear-closing --acknowledge-shared-announcement --acknowledge-broadcast --acknowledge-availability-change
```

Set or explicitly clear either date on an existing course announcement. All three acknowledgements are required even for preview. Group dates are excluded by the native group parameter set. Date operations are separate from text/comment edits and deletion, use the exact announcement update right, and do not require creation permission.

Use whole-second instants with `Z` or an explicit UTC offset. Unlike creation's future-only scheduling guard, existing date edits accept past instants. Closing must follow posting, including a preserved date. A closing instant at course-local midnight is refused because Canvas rewrites it to end of day; select the intended non-midnight instant instead. The reported course time zone is required for closing validation, not guessed.

Date processing can activate a delayed announcement or reopen/close comments. A changed future closing date can reopen a currently closed announcement, even though the request includes its current comment lock. Clearing a closing date can also reopen comments. Native comment-state handling can clear an unselected closing date. Omitted dates are not sent; any observed collateral changes are labeled, not silently assumed preserved or attributed exclusively to this write. Announcements remain published, never private drafts.

Account, context/time zone, exact prior content/date/state/rights and complete accessible inventory bind confirmation. Matching instants are a no-op, not a broadcast. One PUT must match independent announcement/inventory readback and every selected instant or clearing; equivalent offset representations are accepted. Ignored, shifted or unverifiable dates fail as uncertain without retry or repair. Results report observed comment state and global restrictions, not participant visibility/reply access, notification delivery or future execution. No peer comments or explicit creator preference are read/written.

## Delete

```sh
canvas announcement-delete 123 456 --acknowledge-shared-announcement --acknowledge-announcement-removal
canvas announcement-delete 123 456 --context group --acknowledge-shared-announcement --acknowledge-announcement-removal
```

Deletion uses the exact reported native delete permission, not ownership or a guessed reply count. It requires removal acknowledgement instead of broadcast acknowledgement. One soft DELETE must acknowledge the same Announcement ID as deleted, remove it from the complete accessible inventory and yield exact-ID 404/410. A 403 is not absence proof.

This does not recall notifications, prove permanent erasure, delete attachments explicitly or provide a CLI restore. Replies may become inaccessible. Uncertain outcomes require checking Canvas before repeating; no retry, cleanup or rollback occurs.

## Course sections

```sh
canvas announcement-sections 123 456 --section-id 33 --section-id 34 --acknowledge-shared-announcement --acknowledge-broadcast --acknowledge-audience-change
canvas announcement-sections 123 456 --all-sections --acknowledge-shared-announcement --acknowledge-broadcast --acknowledge-audience-change
```

Replace the section filter on an existing course announcement. All three acknowledgements are required even for preview; audience access to the announcement and existing comments can change. This command does not accept group contexts, text/comment/date edits or deletion. Use `announcement-create` for initial targeting.

Repeat unique active course section IDs, or restore `--all-sections`. The complete paginated section catalog is checked without roster reads. Exact announcement update permission is required, not creation or modern Assign To permission; native old/new section visibility checks remain authoritative. Announcements report null ungraded participant overrides, not a discussion override list. All sections disables this filter, not every other visibility restriction.

Account, context, prior announcement metadata/content fingerprint, exact rights, complete accessible announcement inventory and section catalog bind confirmation. Names and private metadata are fingerprinted rather than printed. A matching filter is a no-op. One PUT sends only the filter, announcement kind and preserved comment lock, then independently verifies the exact section IDs/flag, unchanged catalog, comment lock and matching announcement/inventory readback.

Native section changes can synchronize participant/read-tracking records and activity. Stored-filter verification does not prove effective access for each participant, comment access, participant-record updates or notification delivery. Other observed metadata changes are labeled, not automatically repaired.

Section associations may persist before the endpoint reports an authorization or validation error. **An HTTP error does not prove nothing changed.** Every attempted section update with failed or unverifiable readback is uncertain; inspect Canvas before repeating. No peer comments, participant overrides, enrollment/settings changes, retry, cleanup or rollback are requested.

## Boundaries

Only readable, non-anonymous course/group announcements without assignment/root/child/group-set associations are supported. Attachments, podcasts and bulk operations remain separate work. Native permissions, locks and blueprint restrictions stay authoritative. Preflight is not an atomic lock; concurrent edits can be overwritten.

Validation covers unit tests and subprocess/local HTTPS fixtures with synthetic records. No real announcement mutation has been live-tested. Delivery, future jobs, hidden inventory effects and remote preference storage remain unverified.

## Primary references

[Discussion topic API](https://developerdocs.instructure.com/services/canvas/resources/discussion_topics), [native announcement model](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/models/announcement.rb), [native announcement request handling](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/controllers/discussion_topics_controller.rb), [native lock/audience rules](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/models/discussion_topic.rb), [native serialization](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/lib/api/v1/discussion_topics.rb).
