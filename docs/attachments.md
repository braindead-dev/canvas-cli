# Shared prompt attachments

[Documentation](README.md) · [Discussions](communication.md) · [Announcements](announcements.md) · [Safety](safety.md)

Upload one file to an existing readable, ungraded, non-anonymous discussion or announcement. This uses native multipart authoring, not a separate Files upload followed by an invented file-ID association.

## Add or replace

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

[Discussion API](https://developerdocs.instructure.com/services/canvas/resources/discussion_topics), pinned native [attachment processing](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/controllers/discussion_topics_controller.rb#L1857) and [attachment metadata](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/lib/api/v1/attachment.rb#L52).
