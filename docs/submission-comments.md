# Own submission comments

[Coursework](coursework.md) · [Draft submissions](submission-drafts.md) · [Safety](safety.md)

These commands manage comments you authored on your own existing submission. They are not assignment drafts, final submissions, grader feedback or peer-review completion. New behavior is synthetic-tested, not live-write validated.

## Inspect

```sh
canvas submission-comments 123 456 --format brief
canvas submission-comments 123 456 --attempt 1 --include-content
canvas submission-comments 123 456 --all-attempts
```

The default is the current attempt. Native attempts nil, 0 and 1 share a bucket. `--all-attempts` queries each bucket separately: Canvas's `allComments: true` disables the own-author filter, so it is never used. Every connection is paginated within `--max-pages`; malformed, duplicate, looping or truncated results fail closed.

Only ordinary, non-provisional comments on the exact own submission are selected. Unknown or hidden ownership is not an empty inventory. A missing submission is reported as unknown; the CLI will not turn in work or start an attempt to create one. All-attempt completeness covers the reported current-attempt range, not hidden group copies or provisional grading records.

JSON defaults to IDs, state and content fingerprints. `--include-content` opts in to private rendered HTML/text, with URL secrets redacted. Brief output never includes comment bodies. These fixed GraphQL metadata queries do not request read markers, assessment criteria, peer allocation or the single-assignment REST access event.

## Create and edit a draft

```sh
canvas comment-draft-create 123 456 --message-file comment.txt --acknowledge-native-effects
canvas comment-draft-create 123 456 --message-file comment.txt --file-id 789 --media-id existing-media --media-type audio --acknowledge-native-effects
canvas comment-draft-edit 123 456 987 --message-file revised.txt --acknowledge-native-effects
```

Plain text is escaped to HTML. Use `--html-file` only for intentional HTML; Canvas sanitization is not raw-storage proof. Empty text can clear an existing draft's text or accompany attachments/media on creation. Existing file/media IDs are subject to native permissions; these commands do not upload or record media. Editing changes text only and retains attachment/media associations.

Group assignments also require `--acknowledge-group-effects` when creating a draft. Group-graded assignments copy comments natively even without `--group-comment`; individually graded group assignments use that flag to request copying. Native creation can initialize group members' submission records and returns the first group copy, which need not be your copy. Independent own-inventory readback identifies your new draft without querying classmates' submissions.

If the acknowledgement names another group copy, a single newly observed own draft proves own presence, not linked-copy lineage. That distinction is reported explicitly; concurrent creation and hidden group records cannot be ruled out by these reads.

## Publish or delete

```sh
canvas comment-draft-publish 123 456 987 --acknowledge-native-effects
canvas comment-draft-delete 123 456 987 --acknowledge-native-effects
```

Choose an exact own draft in the selected attempt, adding `--attempt` for an older bucket. Students do not have native edit/delete permission for their published comments; these commands do not substitute grading privileges. Publishing also requires the reported own-draft `publishable` flag. Deletion has no CLI restore.

All writes require native-effects acknowledgement even for preview. Creation marks the returned new comment read. Publishing can notify native viewers and publish linked group drafts. Deleting can remove linked copies and refresh comment read state. Media saves can request captions. Instructor/admin authors can encounter moderated grader-slot allocation or implicit grade posting. These callbacks are not suppressed, and hidden copies, notifications, read state, captions and grading effects are not independently verified.

## Confirmation and evidence

Previews bind the account, exact assignment/submission, selected-attempt inventory and current rendered content. Old bodies and private response errors are not printed. Review the exact proposed body before repeating with `--yes --confirm DIGEST`.

One mutation is followed by a separate, fully paginated own readback. Create verifies a new own draft; edit/publish verify the target state; delete verifies scoped own absence. Reported text/file/media differences and other observed own-comment changes are labeled, not silently repaired or attributed exclusively to the write. Sanitized representations are not raw storage, acknowledgement is not proof of delivery, and confirmation is not an atomic lock.

Permission denial, malformed acknowledgements, changed context or unavailable readback produce an uncertain result. A mutation may already have applied, including partial group effects. Inspect Canvas before repeating; there is no automatic retry, cleanup or rollback.

## Native contracts

[Comment edit/delete API](https://developerdocs.instructure.com/services/canvas/resources/submission_comments), [GraphQL](https://developerdocs.instructure.com/services/canvas/basics/file.graphql), [attempt and own-author filtering](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/graphql/interfaces/submission_interface.rb), [creation](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/graphql/mutations/create_submission_comment.rb), [permissions and callbacks](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/models/submission_comment.rb).
