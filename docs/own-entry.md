# Your discussion entries

[Documentation](README.md) · [Discussions](communication.md) · [Attachments](attachments.md) · [Safety](safety.md)

Inspect one of your posts or replies, or edit its text without removing the existing attachment. Course and group contexts are explicit; these commands do not edit the shared prompt.

## Inspect

```sh
canvas own-entry 123 456 789 --format brief
canvas own-entry 123 456 789 --context group --include-content
```

Native ownership, exact context and read permission are checked before requesting body or file metadata. Default output includes a rendered-body fingerprint, file metadata and the visible quoted-entry ID; `--include-content` additionally includes your rendered text. No file URL, download, quoted body or peer inventory is requested.

Anonymous ownership uses Canvas's native `current_user` marker. Participant IDs are never guessed to be user IDs. Missing ownership evidence or unavailable modern fields stop the operation before content is requested.

## Preserve an attachment while editing

```sh
canvas entry-edit 123 456 789 --message-file edit.txt --preserve-attachment
canvas entry-edit 123 456 789 --context group --message-file edit.txt --preserve-attachment
```

Review the preview, then repeat with `--yes --confirm DIGEST`. Local input is bounded UTF-8 plain text, escaped to HTML. Account, context, current revision/body fingerprint, file metadata, visible quote and requested text bind confirmation.

One native GraphQL mutation changes text. File-association and pin inputs stay omitted. Replies explicitly retain the visible quoted-entry ID because the native mutation otherwise clears it. Read/update rights are required; retaining a file does not require upload permission.

This mode is mutually exclusive with `--remove-attachment`. Uploading or replacing an entry's file is a separate, not-yet-supported operation.

## Evidence and limits

The acknowledgement must agree with an independent ownership-first readback, including rendered text and existing file/visible quote associations. Unexpected native HTML normalization is an unverified outcome, not silently accepted success.

Raw HTML storage, stored file bytes, hidden/dangling quote storage, participant access, grade credit and notification delivery remain unverified. Inspection does not initialize discussion participants or request read markers, submissions, checkpoints or assessment attempts.

Saving may affect native participation, editor history, graded discussion credit and notifications. Preflight is not an atomic lock. A failed acknowledgement/readback may follow an applied edit; check Canvas before repeating. No automatic retry, rollback, file deletion or cleanup occurs.

## Primary sources

Pinned Canvas [native entry update](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/graphql/mutations/update_discussion_entry.rb), [entry fields and anonymous ownership](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/graphql/types/discussion_entry_type.rb), and [file byte-size metadata](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/graphql/types/file_type.rb).
