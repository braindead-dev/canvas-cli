# Discussion attachments

[Documentation](README.md) · [Discussions](communication.md) · [Announcements](announcements.md) · [Safety](safety.md)

Attach one file to your new post/reply or an existing shared prompt. Both use native multipart forms, not a separate Files upload followed by an invented file-ID association. Their permissions, storage and failure effects differ.

## Attach to your post or reply

```sh
canvas post 123 456 --message-file post.txt --attachment notes.pdf --acknowledge-attachment-upload
canvas post 123 456 --context group --reply-to 789 --message-file reply.txt --attachment notes.pdf --acknowledge-attachment-upload
```

Review the preview, then repeat with `--yes --confirm DIGEST`. Upload consent is required even for previews. `--max-attachment-bytes` can lower the 25 MiB file limit; attachment flags without a file are refused. Plain text is escaped to HTML, not treated as an uploaded HTML body. Local message inputs are bounded UTF-8.

Posting uses native **entry create/attach** rights, not shared-prompt update/attach rights. The new-entry attachment permission is not separately exposed for preverification. Student attachment settings can silently discard a file; the CLI reports an uncertain outcome if the posted entry lacks it. Graded discussions are permitted by this workflow when Canvas allows posting, but grade/submission credit is not verified.

An initial root post does not inspect peers' entries. A reply requires its exact visible parent and cannot bypass an initial-post restriction. Anonymous topics are refused before posting because native REST entry readback rejects them; they need a separate modern workflow. Account, context, prompt fingerprint, optional parent, message, file hash/source-path fingerprint and upload consent bind confirmation. Bytes are privately frozen before the write. No bulk peer inventory or download is requested.

One POST must return your exact author ID and selected parent, then agree with an independent exact-entry read and reported attachment ID/size. Native HTML/file-name normalization is labeled; byte integrity, historical new-ID uniqueness, storage location, participant access, grade credit and notification delivery remain unverified. Identity must be exposed to verify your own entry.

Canvas saves the entry and native participation effects **before** storing/linking the file. Native storage uses the current user, with submissions-folder placement for graded topics and possible duplicate renaming. A later failure can leave a posted entry without its attachment or an orphan file. Inspect Canvas before repeating; no retry, post deletion, orphan cleanup or rollback occurs.

To retain an existing entry attachment during a text edit, use the separate [modern own-entry edit](own-entry.md) with `--preserve-attachment`. It does not upload a replacement or promise stored-byte integrity.

## Add or replace

These commands change a readable, ungraded, non-anonymous shared discussion or announcement prompt, not your entry attachment.

```sh
canvas topic-attachment-set 123 456 notes.pdf --acknowledge-shared-topic --acknowledge-attachment-upload
canvas topic-attachment-set 123 456 notes.pdf --context group --acknowledge-shared-topic --acknowledge-attachment-upload --acknowledge-attachment-replacement
canvas announcement-attachment-set 123 789 notes.pdf --acknowledge-shared-announcement --acknowledge-broadcast --acknowledge-attachment-upload --acknowledge-attachment-replacement
```

Add `--acknowledge-attachment-replacement` only when there is an existing attachment. It is required even for preview and refused on an empty prompt. Shared/upload consent is always required; announcements additionally need broadcast consent. Multiple existing attachments, linked assignments, anonymous and root/child/group-set topics require separate workflows.

The file must be regular, nonempty and no larger than 25 MiB. `--max-bytes` can lower that bound. Unicode/spaces in basenames are supported; header controls, quotes, path separators and overlong names are refused. Source paths and file content are not printed; filename, size, media type and SHA-256 are visible. Output still contains private academic metadata and must stay out of public repositories.

Exact native topic `update` and `attach` permissions are both required. Creation or Manage Files permission is not a substitute. Native quota restrictions apply to attachments larger than 1 KiB; publication, blueprint and institution restrictions still govern the operation. Granted rights do not promise success.

## Confirmation and evidence

Review the preview, then repeat the same command with `--yes --confirm DIGEST`. Identity, exact context, private prompt/attachment metadata, complete accessible inventory, file hash/source-path fingerprint and selected consents bind confirmation. Bytes are staged privately before any write. Changing the file or destination invalidates confirmation.

One authenticated multipart PUT must agree with an independent exact-topic read and complete inventory, retain update/attach rights and preserve publication/comment lock. Announcements use `lock_comment`, not creator preferences. Other observed field changes are labeled, not automatically rewritten or asserted causal.

Results verify a new attachment ID and reported size, not stored byte integrity. Native duplicate-name processing may rename the file. Usage-right defaults and visibility remain native; the CLI does not choose a copyright claim, download files or prove participant access/notification delivery.

## Destructive replacement

Native replacement can clear the old association and soft-delete the old file record **before** storing the new file. Related content tags, media/LTI/draft associations and other references can be affected. A later failure can leave the old file removed or a new file orphaned; an HTTP error is not proof that nothing changed.

Ignored parameters, denied readback or mismatched evidence are uncertain outcomes. Check Canvas before repeating. No automatic retry, separate file-delete call, restoration, orphan cleanup, peer reads or assessment attempt occurs. Preflight is not an atomic lock. Old-file deletion, storage erasure, other-reference effects and recall of existing downloads remain unverified.

Removing an announcement attachment without replacement is a [separate operation](announcements.md#remove-an-attachment).

## Primary sources

[Discussion API](https://developerdocs.instructure.com/services/canvas/resources/discussion_topics), pinned native [entry-before-file processing](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/controllers/discussion_topics_api_controller.rb#L1204), [prompt replacement](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/controllers/discussion_topics_controller.rb#L1857) and [attachment metadata](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/lib/api/v1/attachment.rb#L52).
