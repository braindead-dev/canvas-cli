# Submission drafts

[Coursework](coursework.md) · [Safety](safety.md) · [Capabilities](../CAPABILITIES.md)

Drafts save progress; they **do not turn in work**. These commands use native GraphQL and only the signed-in user's submission. No other-student selector or arbitrary GraphQL document is accepted.

## Inspect

```sh
canvas draft 123 456 --format brief
canvas draft 123 456 --include-content
```

The native getter exposes only the next attempt. Default output contains IDs, type, attachment IDs and private content fingerprints. Content opt-in includes rendered HTML/URLs and retained fields from other draft types. Keep output private.

Assignment policy is selected in the same GraphQL query. The CLI does not call the single-assignment REST GET, which can record assignment/module access. No content-view event or criteria query is requested.

Null submission means no accessible existing record, not proof that no work exists. Draft mutations cannot create the underlying submission. The CLI will not submit work or start an assessment to manufacture one. Null draft on a verified submission means next-attempt absence, not empty historical inventory.

## Save without submitting

```sh
canvas draft-save 123 456 --type online_text_entry --text-file response.txt
canvas draft-save 123 456 --type online_url --url-file project-url.txt
canvas draft-save 123 456 --type online_upload --file-id 789 --file-id 790
canvas draft-save 123 456 --type media_recording --media-id existing-media-id
canvas draft-save 123 456 --type basic_lti_launch --external-tool-id 321 --lti-url-file tool-url.txt
canvas draft-save 123 456 --type student_annotation
canvas draft-save 123 456 --type online_text_entry --clear-content
```

All writes are [preview-first](safety.md#confirmation). Repeat the exact reviewed command with `--yes --confirm DIGEST`. The preview binds identity, assignment policy, current submission/attempt, returned draft-state fingerprints and selected inputs. It is not an atomic lock.

Plain text is escaped to HTML; `--html-file` explicitly supplies HTML. Incomplete URL drafts are allowed, without embedded credentials. Files/media/tools must already exist; these commands do not upload, record or launch them. Canvas verifies file ownership/group eligibility, replacements, extensions and native read/submit permission. An unsupported final-submission type can still be drafted natively; storage is not proof of submission eligibility.

Saving changes the selected type and its explicit fields. Other type fields are retained by Canvas. `--clear-content` explicitly clears text, URL, file or media content, not all retained fields. Annotation selects that draft tab only; it neither creates annotations nor checks annotation criteria. Tool metadata does not authenticate or open an LTI application.

The CLI fixes the attempt at current + 1. Concurrent final submission can move it into hidden history; that outcome fails independent verification rather than being retried. Historical-attempt editing is not currently exposed.

## Delete all drafts

```sh
canvas draft-delete 123 456 --acknowledge-all-drafts
```

**Native deletion removes every draft attempt for the submission**, including history the read query cannot expose. The acknowledgement is required even for preview. This works when no next draft is visible but historical drafts may exist; Canvas decides whether there are drafts to delete. Deleted drafts cannot be restored by the CLI.

The result distinguishes server-reported deleted IDs from independently verified next-attempt absence. It does not claim independent historical absence or a complete inventory. The underlying final submission is not deleted.

## Evidence and limits

Each confirmed command sends one mutation and independently re-reads own identity, submission/attempt and draft. Payload errors, incomplete acknowledgements, scope changes and inaccessible readback report an uncertain outcome without leaking private responses. A failed mutation can still leave a partially created draft; inspect Canvas before repeating. Canvas itself can clean up duplicate draft records. No automatic retries, rollback or cleanup are attempted.

Content readback is a processed representation, not raw storage. Differences can reflect HTML sanitization, URL normalization, replacement attachment IDs, deleted associations or concurrent edits. Matching representations do not prove submission criteria, annotations, provider readiness, or final completion. No criteria queries are sent because native annotation checks can initialize annotation context.

Implementation is based on [Canvas GraphQL](https://developerdocs.instructure.com/services/canvas/basics/file.graphql), the native [create](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/graphql/mutations/create_submission_draft.rb), [delete](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/graphql/mutations/delete_submission_draft.rb) and [draft getter](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/graphql/interfaces/submission_interface.rb). New behavior is tested with synthetic HTTPS fixtures, not real coursework mutations.
