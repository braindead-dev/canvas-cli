# Personal discussion views

[Documentation](README.md) · [Shared discussions](communication.md) · [Safety](safety.md)

## Read your effective view

```sh
canvas topic-view 123 456 --acknowledge-participant-initialization
canvas topic-view 123 456 --context group --acknowledge-participant-initialization --format brief
```

These commands query native GraphQL on the configured Canvas origin with the same token and HTTPS transport as REST. They report your effective sort/expansion settings, directly stored pinned-entry preference, and shared defaults/locks, not peer identities or replies. Exact course/group/topic scope and native topic `read` permission are checked before requesting your participant. No manager, reply or ownership requirement is invented.

**A native participant query is not side-effect-free.** If your record is missing, Canvas can initialize it with default subscription/unread state and clear planner cache. The acknowledgement is required even for reading or previewing. Query/preflight is not an atomic lock; a later permission/context change can still fail after initialization. These controls never request assessment attempts, reply bodies or explicit subscription/read-marker changes.

## Change selected preferences

```sh
canvas topic-view-set 123 456 --sort-order asc --expanded --acknowledge-participant-initialization
canvas topic-view-set 123 456 --no-show-pinned-entries --acknowledge-participant-initialization
canvas topic-view-set 123 456 --sort-order inherit --inherit-expansion --clear-pinned-entry-preference --acknowledge-participant-initialization
```

Omitted fields are not sent. Inheritance/reset flags send explicit native nulls, not copies of current shared defaults. This is your own participant state, not `topic-configure`, prompt editing, grading or changing another participant. Readable announcements, graded/anonymous topics and child/group discussions are not arbitrarily excluded from personal display controls; native permission remains authoritative. No anonymous identity reconstruction is performed.

Review the preview, then repeat with `--yes --confirm DIGEST`. The digest binds account, exact context/topic, shared defaults/locks, own effective state and selected input. Initialization may already have occurred during preview, but the selected preference mutation is not sent until confirmation. This workflow supplies fixed typed operations, not an unrestricted GraphQL CLI or user-query-file executor.

## What readback proves

One native mutation must return an error-free, exact-scope acknowledgement. An independent query and identity check then verify the selected **native readback** against stable shared defaults/locks. The output calls these values `reported`, distinguishing their semantics below.

- `sort_order` and `expanded` resolve through shared defaults/locks. A lock can mask even a valid saved override. Matching the shared default after reset does not prove raw storage was cleared. Results always label their stored overrides **unverified**, including under locks or already-matching values.
- `show_pinned_entries` is a directly reported participant field; a matching independent readback verifies that stored value, not actual UI visibility. Null is not guessed to mean shown or hidden.
- Raw hidden sort/expansion overrides are unavailable for preview binding. Concurrent hidden changes cannot be detected from effective values alone. Preflight is not atomic.
- Observed field changes are not exclusive causal proof. Future view behavior, summary/translation features and downstream notifications/cache effects are not verified.

Ignored unlocked changes, partial GraphQL errors, foreign/malformed acknowledgements and unreadable or changed-context/account outcomes fail without automatically retrying, restoring or cleaning up. An error is not proof that a mutation did not apply. Inspect Canvas before repeating. Locked/reset outcomes are not silently represented as raw storage success.

## Validation

Unit and independent synthetic HTTPS tests cover query initialization, account/context checks, omissions/nulls, locked defaults, stale previews, partial/ignored writes and private errors. No live personal-view query or mutation is claimed: even reading can initialize state.

The implementation follows [Canvas GraphQL](https://developerdocs.instructure.com/services/canvas/basics/file.graphql), the [native participant mutation](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/graphql/mutations/update_discussion_topic_participant.rb), [participant resolvers](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/graphql/types/discussion_participant_type.rb) and [native permission loader](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/graphql/graphql_node_loader.rb).
