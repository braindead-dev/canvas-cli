# Feedback attention

[Coursework](coursework.md) · [Own comments](submission-comments.md) · [Safety](safety.md)

Inspect or deliberately acknowledge your own submission feedback indicators. These are not proof of viewing feedback, understanding it, turning in work or completing a course requirement. New behavior is synthetic-tested, not live-write validated.

## Inspect without changing indicators

```sh
canvas submission-attention 123 456 --format brief
canvas submission-attention 123 456 --include-feedback-markers
```

The default reads only exact assignment/own-submission metadata and native aggregate `readState`. The option adds two own preference booleans: document annotations and rubric feedback. No scores, answers, comment bodies, annotation content or assessment attempts are requested. REST `include[]=read_status` is never used because Canvas marks submissions read when it is included.

A missing own submission is unknown, not read or completed. No submission is initialized to inspect it. Foreign parents, hidden ownership, missing metadata, malformed booleans and account changes are errors rather than empty feedback.

## Acknowledge one surface

```sh
canvas submission-mark-read 123 456 --acknowledge-feedback-indicators
canvas submission-mark-read 123 456 --surface comment --acknowledge-feedback-indicators
canvas submission-mark-read 123 456 --surface annotations --acknowledge-feedback-indicators
canvas submission-mark-unread 123 456 --acknowledge-feedback-indicators
```

| Surface | Native effect | Independent evidence |
| --- | --- | --- |
| `overall` | Legacy read/unread route updates the default grade participation item when aggregate state differs | Effective aggregate state; other unread items can remain |
| `grade`, `comment`, `rubric` | Marks the selected participation item read | Effective aggregate only; individual item storage remains unverified |
| `annotations`, `rubric-feedback` | Clears the selected own unread preference | Separate boolean readback verifies that preference, not participation items |

Native unread is supported only for `overall`. The `rubric` participation item and `rubric-feedback` preference are different records. Marking `comment` also marks all natively visible submission comments viewed, including others' comments, without fetching their bodies. This is not a selected-comment action.

## Confirmation and limits

Acknowledgement is required even for preview. A preview binds the account, assignment policy, exact existing own submission, aggregate state and selected preference. Review it before repeating with `--yes --confirm DIGEST`.

One mutation is followed by a separate own inspection. Participation routes must return empty HTTP 204; preference routes must return a strict `read: true` boolean and matching independent readback. The result distinguishes acknowledgement, effective aggregate match and verified preference state. An acknowledged overall mark-read request can legitimately leave aggregate state unread; it is reported, not silently retried.

Native counters, activity and planner caches can change. Confirmation is not an atomic lock; the legacy overall route can initialize a concurrently missing submission. The CLI does not claim that unseen item storage, viewed-comment records, notifications or downstream effects were independently verified.

Denied, malformed or unavailable responses and changed context after a write produce uncertainty: the operation may already have applied. Check Canvas before repeating. There is no bulk acknowledgement, automatic retry or rollback, and no coursework completion is requested.

## One feedback comment

```sh
canvas feedback-comments 123 456 --format brief
canvas feedback-comments 123 456 --all-attempts
canvas feedback-comment-mark-read 123 456 987 --acknowledge-feedback-indicators
canvas feedback-comment-mark-read 123 456 987 --attempt 1 --acknowledge-feedback-indicators
```

These inspect visible **published** comments on your own existing submission, regardless of author, without requesting bodies or author identities. This is different from `submission-comments`, which selects your authored comments and drafts. Draft/provisional comments are excluded. The default is the current attempt; all-attempt inspection uses separate filtered connections within `--max-pages`, preserving the native shared 0/1 bucket.

Marking requires an exact reported comment ID and a fresh account/policy/attempt/inventory/indicator-bound preview. The native mutation receives exactly one ID, followed by a separate fully paginated own readback. It does not mark every comment, clear participation-item indicators or start an assessment. No unread inverse is provided.

Effective comment read can be true because the overall submission is read, even without an independently verified viewed-comment row. Results keep that distinction explicit, including for already-read comments. Other observed inventory/indicator changes are reported without exclusive attribution to the write. Hidden or truncated inventories are not empty feedback, and missing own submissions are not initialized. Uncertain outcomes are never automatically retried.

## Native contracts

[Submission API](https://developerdocs.instructure.com/services/canvas/resources/submissions), [indicator routes and acknowledgements](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/controllers/submissions_api_controller.rb), [aggregate/default-item semantics](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/models/content_participation.rb), [submission callbacks](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/models/submission.rb).

[Selected-comment mutation](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/graphql/mutations/mark_submission_comments_read.rb), [effective comment-read resolver](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/graphql/types/submission_comment_type.rb), [native attempt/author filtering](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/graphql/interfaces/submission_interface.rb).
