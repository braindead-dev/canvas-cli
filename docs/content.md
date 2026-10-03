# Content and files

[Documentation](README.md) · [Safety](safety.md)

## Discover visible content

```sh
canvas-cli syllabus 123
canvas-cli tabs 123
canvas-cli front-page 123
canvas-cli find 123 --query 'reading' --area files
canvas-cli linked-files 123
canvas-cli doctor 123
```

Syllabus returns the course body, not every linked document. Tabs list visible paths without launching external tools. Front page requires accessible published content.

Find searches titles/names and verifies matches locally if Canvas ignores a filter. Denied Pages/Files listing can use readable module pages/linked-file fallback, explicitly partial. Omitted embedded module items are not an empty-search guarantee. Body search is offline over snapshots.

Doctor probes sequentially without printing content and stops on rate limits. Reachability is not complete publication/access or a restriction bypass.

## Files, folders, and groups

```sh
canvas-cli files 123 --best-effort
canvas-cli linked-files 123 --all-pages --quick
canvas-cli files 456 --context group
canvas-cli page 456 welcome --context group
canvas-cli folder-path 456 --context group --path 'Week 1/Readings'
canvas-cli file-quota 456 --context group
```

Course files preserves the raw native list. Best-effort falls back only when denied and reports incomplete coverage. Linked-files indexes references in readable syllabus, modules/pages, assignments, announcements, and discussion prompts, not student replies. Hidden/unpublished/locked sources are skipped. All-pages adds readable pages outside modules; quick skips per-file availability checks, so availability is unknown. Neither is a complete Files inventory.

Files/folders/pages/page/tabs/front-page/download support explicit group context. Group reads verify the group and native scope, omit uploader/viewer/download associations from file indexes, and exclude hidden page metadata. Denied listings remain errors; no global-ID/course-module fallback bypasses scope.

Root-folder, folder-path, and file-quota support explicit course/group/user context; user must be your signed-in ID. Free quota is not upload permission. Path resolution verifies exact context/names/parent chain/access. Empty paths select the root; dot/empty segments, edge separators, backslashes, and controls are refused. UTF-8/spaces/literal percent characters are encoded safely.

Native root/path GETs can materialize a missing Canvas root, including upload root previews. They do not create arbitrary subfolders; this side effect is labeled in help/output.

## Download privately

```sh
canvas-cli download 123 789 --output /private/path/reading.pdf
canvas-cli download-linked 123 --directory /private/path/readings --file 789
```

Downloads use private/no-overwrite/no-Git rules, default to 100 MiB, remove failed partial files, and check advertised size. Storage receives no bearer token/cookies/redirects; signed URLs are not logged.

Batches require an existing private directory and [confirmation](safety.md#confirmation) bound to selection, discovery scope, metadata, destination, and limits. Oversized previews show limit issues; execution refuses them. Collisions/unsafe server filenames are guarded. Earlier successful files remain after later failure, with partial progress reported.

## Private snapshots

```sh
canvas-cli snapshot 123 --output /private/path/course.json
canvas-cli sync 123 --include-linked-files
canvas-cli snapshot-diff /private/path/older.json /private/path/newer.json --format brief
canvas-cli snapshot-search /private/path/course.json --query 'research paper'
canvas-cli snapshot-markdown /private/path/course.json --output /private/path/course.md
```

Capture includes course/syllabus, assignments, modules/items, readable published pages, announcements, and visible discussion prompts, not classmates' replies/questions/attempts. Optional linked files are metadata references, not binary downloads/full inventory. Requests are sequential to respect throttling.

Permission/not-found gaps are incomplete; denied Pages can fall back to module links while remaining partial. Auth/rate-limit/network/malformed failures stop capture rather than save false empty state.

Snapshots are immutable mode-0600 files outside Git with no overwrite, including symlinked parents. Known token-shaped fields/credential-like query parameters are removed, but academic/copyrighted material and other expiring links can remain private.

### Account-separated sync

Baselines are per origin, numeric signed-in viewer, and course. Identity is checked before/after capture; a changed account refuses saving, not an atomic content/permission lock.

Legacy unscoped files and other viewers' histories stay untouched and are never automatic baselines. The upgraded naming scheme starts fresh without migration/rename/deletion/implicit merge. Files accumulate until you prune them. Failed refreshes preserve the prior baseline.

Offline diff refuses known viewer mismatches and labels explicit legacy comparisons identity-unverified. File metadata is not current authorization. Output shows titles/changed field names, not full bodies. Incomplete categories skip full add/remove claims; overlapping partial pages/files report observed changes. Absent older discussion/file coverage is skipped, not invented as additions.

Brief diff and sync share a field-name index: additions/removals, changed fields, observed partial changes, and skipped inventories. Zero observed changes is not a claim that unseen content is unchanged.

### Offline search and Markdown

Search returns short plain-text snippets, ranking title matches first. No hits are not proof of absent content, especially with incomplete/older coverage. Results can be private.

Markdown is a readable projection, not a lossless backup. HTML becomes plain text, not active HTML or external images. Coverage warnings and safe same-origin assignment links remain. Output follows private/no-overwrite/no-Git rules; review before sharing.

## Upload files

```sh
canvas-cli upload-personal --folder 789 --file notes.pdf
canvas-cli upload-context 123 --context group --folder 789 --file shared-notes.pdf
canvas-cli upload-assignment-file 123 456 --file paper.pdf
```

Three-step uploads bind source SHA-256/size/destination/account in a preview. Default maximum is 25 MiB. Personal/shared duplicates request rename, never overwrite. Storage gets no token/cookies/redirects; initiation/confirmation stay on Canvas.

Shared uploads require explicit context/native Manage Files permission and may expose content to that audience. Readable folders/free quota do not prove permission. Existing folder/root association is checked; hidden/locked/foreign/submission-only folders fail. No implicit path creation or visibility/sharing flags.

Completed size/folder and exact scoped readback are verified. Unverified completion may still have uploaded: check before repeating. Upload is not [submission](coursework.md#turn-in-work-deliberately).

## Organize personal files

| Commands | Effect / guard |
| --- | --- |
| `my-root`, `my-folders`, `my-files` | Own inventory; root lookup may create a missing native root |
| `file-info` | Exact accessible metadata; filenames can be private |
| `my-folder-create` | One own non-submission child; account/sibling inventory checks |
| `my-folder-edit` | Rename/move non-root contents with ancestry/cycle/collision checks |
| `my-folder-delete` | Empty non-root only; no recursive force |
| `my-file-edit` | Rename/move own non-submission file; no overwrite |
| `my-file-copy` | Copy accessible file into own folder if permitted; source unchanged |
| `my-file-delete --permanent` | Irreversible removal, not trash; can break references |

Mutations use confirmation. File edits/copies request rename-on-duplicate; inspect actual returned name. No explicit publication/sharing/lock changes, but moves can alter inherited access/links. Metadata fingerprints do not prove unchanged bytes.

Folder ancestry/siblings are verified; root/self/descendant/cycle/foreign/submission moves fail. Delete checks both files/subfolders and omits recursive force, so newly added content is not forcibly removed. File delete omits privileged replace and cannot combine with edit/copy.

## Canvas export jobs

```sh
canvas-cli exports 123
canvas-cli export-create 123 --type zip --select files 789
canvas-cli export-status 123 456 --progress --format brief
canvas-cli export-download 123 456 --output /private/path/course.zip
```

Creation is asynchronous, role-dependent, and previewed. ZIP selects files/folders; Common Cartridge additionally supports documented course-content types shown in help. Skip-notifications is a job option, not a preference edit.

Status reads the same job/optional same-origin progress, without polling or duplicate creation. Output distinguishes exporting/exported/failed and omits signed URLs. Download requires a finished accessible attachment, refusing expired/hidden/locked packages.

After uncertain creation, inspect existing jobs first. Packages may be private/copyrighted; students may not have export permission.

## Sources

[Files/Folders](https://developerdocs.instructure.com/services/canvas/resources/files), [Pages](https://developerdocs.instructure.com/services/canvas/resources/pages), [Tabs](https://developerdocs.instructure.com/services/canvas/resources/tabs), [Uploads](https://developerdocs.instructure.com/services/canvas/basics/file.file_uploads), [Exports](https://developerdocs.instructure.com/services/canvas/resources/content_exports), [Throttling](https://developerdocs.instructure.com/services/canvas/basics/file.throttling), [Native root behavior](https://github.com/instructure/canvas-lms/blob/master/app/models/folder.rb).
