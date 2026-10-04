# Personal discussion views

[Documentation](README.md) · [Shared discussions](communication.md) · [Safety](safety.md)

## Read your effective view

```sh
canvas topic-view 123 456 --acknowledge-participant-initialization
canvas topic-view 123 456 --context group --acknowledge-participant-initialization --format brief
canvas topic-view 123 456 --include-assist-preferences --acknowledge-participant-initialization
```

These commands query native GraphQL on the configured Canvas origin with the same token and HTTPS transport as REST. They report effective sort/expansion, directly stored pinned-entry preference and shared defaults/locks, not peer identities or replies. Language and summary preferences are fetched only with the opt-in flag. Exact course/group/topic scope and native topic `read` permission are checked before requesting your participant. No manager, reply or ownership requirement is invented.

**A native participant query is not side-effect-free.** If your record is missing, Canvas can initialize it with default subscription/unread state and clear planner cache. The acknowledgement is required even for reading or previewing. Query/preflight is not an atomic lock; a later permission/context change can still fail after initialization. These controls never request assessment attempts, reply bodies or explicit subscription/entry/topic read-state changes.

## Change selected preferences

```sh
canvas topic-view-set 123 456 --sort-order asc --expanded --acknowledge-participant-initialization
canvas topic-view-set 123 456 --no-show-pinned-entries --acknowledge-participant-initialization
canvas topic-view-set 123 456 --inherit-expansion --acknowledge-participant-initialization
```

Omitted fields are not sent. Expansion inheritance sends native null, not a copy of the shared default. Sort accepts only `asc`/`desc`; pinned-entry and summary settings accept explicit booleans. Although their GraphQL inputs are nullable, native storage is not. Canvas exposes no valid reset to stored sort inheritance; copying a shared sort value is not equivalent and is not offered as a reset.

This is your own participant state, not `topic-configure`, prompt editing, grading or changing another participant. Readable announcements, graded/anonymous topics and child/group discussions are not arbitrarily excluded from preference storage; native permission remains authoritative. No anonymous identity reconstruction is performed.

Review the preview, then repeat with `--yes --confirm DIGEST`. The digest binds account, exact context/topic, shared defaults/locks, queried own state and selected input. Initialization may already have occurred during preview, but the selected preference mutation is not sent until confirmation. This workflow supplies fixed typed operations, not an unrestricted GraphQL CLI or user-query-file executor.

## Language and summary preferences

```sh
canvas topic-languages --format brief
canvas topic-view-set 123 456 --preferred-language PT_BR --acknowledge-participant-initialization
canvas topic-view-set 123 456 --clear-preferred-language --acknowledge-participant-initialization
canvas topic-view-set 123 456 --summary-enabled --acknowledge-participant-initialization
canvas topic-view-set 123 456 --no-summary-enabled --acknowledge-participant-initialization
```

Use an exact enum value reported by your server, not a guessed UI locale. The catalog includes deprecated values and does not initialize a participant. A non-null language change checks that catalog before participant initialization and binds it into the confirmation. Missing, denied or malformed schema metadata stops the change without guessing a fallback. Language clearing does not need the catalog and sends explicit null.

These are stored preferences only. They neither request nor prove access to translation or AI summaries. Native generation has separate service/feature/role checks; storing a summary preference requires native topic read permission, not invented instructor authority. No reply content is fetched or sent to either service.

## Pinned-reply unread indicator

```sh
canvas topic-view 123 456 --include-pinned-marker --acknowledge-participant-initialization
canvas topic-view-set 123 456 --pinned-unread --acknowledge-pinned-marker-change --acknowledge-participant-initialization
canvas topic-view-set 123 456 --no-pinned-unread --acknowledge-pinned-marker-change --acknowledge-participant-initialization
```

This is your own native `hasUnreadPinnedEntry` flag, not a list of unread replies, entry/topic read status, proof of viewing content, or a shared pin/unpin operation. Reads opt in to this field. Changes require a separate acknowledgement before any query, bind the current flag into the preview, and independently verify the direct stored boolean after one mutation. Omission preserves it; null resets are invalid. Future UI or pin/read events are not verified. No peer content, unread-count, subscription or assessment change is requested.

## What readback proves

One native mutation must return an error-free, exact-scope acknowledgement. An independent query and identity check then verify the selected **native readback** against stable shared defaults/locks. The output calls these values `reported`, distinguishing their semantics below.

- `sort_order` and `expanded` resolve through shared defaults/locks. A lock can mask even a valid saved override. Matching the shared default after reset does not prove raw storage was cleared. Results always label their stored overrides **unverified**, including under locks or already-matching values.
- `show_pinned_entries`, `summary_enabled` and `has_unread_pinned_entry` are direct participant fields. Matching independent readback verifies stored values, not UI visibility, content reading, summary generation or service access. Nullable read metadata is not guessed to mean enabled or disabled.
- A non-null `preferred_language` readback verifies a supported stored preference. Native resolution can also return null for an unsupported saved locale. Matching null after clearing therefore does not prove raw storage was cleared; that result stays unverified.
- Raw hidden sort/expansion overrides are unavailable for preview binding. Concurrent hidden changes cannot be detected from effective values alone. Preflight is not atomic.
- Observed field changes are not exclusive causal proof. Future view behavior, summary/translation features and downstream notifications/cache effects are not verified.

Ignored unlocked changes, partial GraphQL errors, foreign/malformed acknowledgements and unreadable or changed-context/account outcomes fail without automatically retrying, restoring or cleaning up. An error is not proof that a mutation did not apply. Inspect Canvas before repeating. Locked/reset outcomes are not silently represented as raw storage success.

## Validation

Unit and independent synthetic HTTPS tests cover query initialization, account/context checks, native storage constraints, catalog changes/denials, omitted and cleared preferences, locked defaults, stale previews, partial/ignored writes and private errors. No live personal-view query or mutation is claimed: even reading can initialize state.

The implementation follows [Canvas GraphQL](https://developerdocs.instructure.com/services/canvas/basics/file.graphql), the [native mutation](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/graphql/mutations/update_discussion_topic_participant.rb), [participant resolvers](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/graphql/types/discussion_participant_type.rb), [language enum](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/graphql/types/preferred_language_type.rb) and [native storage constraints](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/db/migrate/20101210192618_init_canvas_db.rb).
