# Content and files

[Documentation](README.md) · [Safety](safety.md)

## Discover visible content

```sh
canvas syllabus 123
canvas tabs 123
canvas front-page 123
canvas find 123 --query 'reading' --area files
canvas linked-files 123
canvas doctor 123
```

Syllabus returns the course body, not every linked document. Tabs list visible paths without launching external tools. Front page requires accessible published content.

Find searches titles/names and verifies matches locally if Canvas ignores a filter. Denied Pages/Files listing can use readable module pages/linked-file fallback, explicitly partial. Omitted embedded module items are not an empty-search guarantee. Body search is offline over snapshots.

Doctor probes sequentially without printing content and stops on rate limits. Reachability is not complete publication/access or a restriction bypass.

## Files, folders, and groups

```sh
canvas files 123 --best-effort
canvas linked-files 123 --all-pages --quick
canvas files 456 --context group
canvas page 456 welcome --context group
canvas folder-path 456 --context group --path 'Week 1/Readings'
canvas file-quota 456 --context group
```

Course files preserves the raw native list. Best-effort falls back only when denied and reports incomplete coverage. Linked-files indexes references in readable syllabus, modules/pages, assignments, announcements, and discussion prompts, not student replies. Hidden/unpublished/locked sources are skipped. All-pages adds readable pages outside modules; quick skips per-file availability checks, so availability is unknown. Neither is a complete Files inventory.

Files/folders/pages/page/tabs/front-page/download support explicit group context. Group reads verify the group and native scope, omit uploader/viewer/download associations from file indexes, and exclude hidden page metadata. Denied listings remain errors; no global-ID/course-module fallback bypasses scope.

Root-folder, folder-path, and file-quota support explicit course/group/user context; user must be your signed-in ID. Free quota is not upload permission. Path resolution verifies exact context/names/parent chain/access. Empty paths select the root; dot/empty segments, edge separators, backslashes, and controls are refused. UTF-8/spaces/literal percent characters are encoded safely.

Native root/path GETs can materialize a missing Canvas root, including upload root previews. They do not create arbitrary subfolders; this side effect is labeled in help/output.

## Download privately

```sh
canvas download 123 789 --output /private/path/reading.pdf
canvas download-linked 123 --directory /private/path/readings --file 789
```

Downloads use private/no-overwrite/no-Git rules, default to 100 MiB, remove failed partial files, and check advertised size. Storage receives no bearer token/cookies/redirects; signed URLs are not logged.

Batches require an existing private directory and [confirmation](safety.md#confirmation) bound to selection, discovery scope, metadata, destination, and limits. Oversized previews show limit issues; execution refuses them. Collisions/unsafe server filenames are guarded. Earlier successful files remain after later failure, with partial progress reported.

## Author shared wiki pages

```sh
canvas page-create 123 --context course --title 'Shared notes' --body-file notes.html --acknowledge-shared-page
canvas page-edit 456 789 --context group --body-file notes.html --acknowledge-shared-page
canvas page-edit 123 789 --context course --title 'New title' --published --acknowledge-shared-page
```

Both commands use [confirmation](safety.md#confirmation) and require audience acknowledgement even for previews. HTML inputs are bounded UTF-8; empty clears content. These are shared wiki pages, not private notes or assignment submissions. Native reads/edits can record module read/contribution progress.

Edits take an exact numeric **page ID**, not a slug. Native numeric slugs take precedence over IDs; reads can explicitly use `page_id:789`. Title edits can change the URL, so verification uses the original numeric ID and returns the new page link. Missing preflight pages fail without a PUT. Canvas's update API is an upsert, not an atomic compare-and-swap: concurrent deletion can still create an unwanted page; concurrent edits can be overwritten. Revision/body fingerprints reject changed previews, not races during execution.

Course-wide student wiki opt-in/native permissions and page-level edit-history authorization are checked. Readable pages/course membership alone do not grant editing. Body-only contributors cannot change titles or request notifications. Native role, blueprint, institution and OAuth-scope restrictions remain authoritative.

Creation uses POST, never replacement. Existing title matches are counted; Canvas chooses a unique locator. Native defaults are explicit in previews: course wiki managers create drafts, while student/group creation defaults to published. A draft is not necessarily private from teachers/managers. Publication, editing-role and front-page controls require Manage Wiki Update; changing the front page is context-wide and binds the paginated current inventory. A front page must remain published unless explicitly unset. Native creation of a default-named front page can select it implicitly; use `--front-page` when intended. Unexpected context-wide selection is reported as uncertain, not successful. Notifications default off; `--notify` requests them but does not prove delivery.

Exact page ID, selected metadata, fresh identity/permissions and separate acknowledgement/readback are verified. Stored HTML may be sanitized or rewritten; `html_matches_request` distinguishes literal equality and JSON includes the stored body when requested. Unobserved changes, conflicting readbacks, denied verification and foreign acknowledgements are uncertain outcomes, never automatically retried. Previous bodies/editors/history are fingerprinted or omitted, not dumped in previews.

Block-editor/Horizon authoring and scheduling changes remain separate work. Authorized RCE drafts can be edited without bypassing publication; existing publication schedules are preserved, and future-scheduled pages refuse implicit publication/front-page changes.

## Inspect and restore page history

```sh
canvas page-revisions 123 789 --context course --format brief
canvas page-revision 123 789 2 --context course --include-content
canvas page-revision 456 789 latest --context group --include-editors
canvas page-restore 123 789 2 --context course --acknowledge-shared-page
```

Exact numeric page IDs avoid slug collisions. History follows all pagination or fails rather than return a partial inventory. Default output is revision IDs/dates/latest flags, not old titles, HTML or editor records. One-revision `--include-content` opts into potentially private historical title/URL/HTML; `--include-editors` adds only IDs/display names. Brief output indexes metadata even when JSON includes content. Native latest-detail read requires page-read permission; numeric detail/history require read-revisions permission. Draft access stays native, never inferred from fabricated manager rights. These GETs can record module read progress or repair legacy imported YAML revisions, so are not classified as entirely side-effect-free.

Restore uses [confirmation](safety.md#confirmation) and one native POST to an exact numeric revision. It restores **title, body and URL**, not historical publication, editing roles, scheduling or deleted pages. Full page-update permission and native history authorization are required; body-only contribution permission is insufficient. Previews bind account, context, permissions, current page/revision, selected historical body fingerprint and full page/front-page inventory without dumping old HTML/editors. Inspect historical content before confirming. Native restrictions remain authoritative.

Renaming a front page can deselect it; `--acknowledge-front-page-change` is required for that risk. Links/modules can also be affected. Separate page/revision/front-page readbacks verify the observed result; no automatic front-page repair or rollback is issued. A current-revision no-op does not falsely claim a new revision. Native HTML/URL normalization is labeled (`html_matches_revision`, `url_matches_revision`), not treated as literal equivalence. Title collisions, ignored changes, lost permissions or inconsistent readbacks are uncertain outcomes. Check Canvas before repeating. Neither confirmation nor readback prevents concurrent edits during execution.

[Native Pages API](https://developerdocs.instructure.com/services/canvas/resources/pages), [revision authorization/restore implementation](https://github.com/instructure/canvas-lms/blob/master/app/controllers/wiki_pages_api_controller.rb), [title/URL/front-page/version behavior](https://github.com/instructure/canvas-lms/blob/master/app/models/wiki_page.rb), [HTML rewriting](https://github.com/instructure/canvas-lms/blob/master/lib/api.rb).

## Delete a shared wiki page

```sh
canvas page-delete 123 789 --context course --acknowledge-page-deletion
canvas page-delete 456 789 --context group --acknowledge-page-deletion
canvas page-delete 123 789 --context course --acknowledge-page-deletion --acknowledge-linked-assignment-deletion
```

This is native soft deletion of shared content, not a private note, permanent erasure, or a promise of recovery. Use [confirmation](safety.md#confirmation) after reviewing the preview. The exact numeric page ID avoids native numeric-slug ambiguity. Manage Wiki Delete is required separately from editing/ownership/history permission; native role, blueprint and OAuth restrictions still apply. Front pages are refused without automatic unsetting or replacement.

If the native Page API reports a linked wiki assignment, deletion can also delete that assignment and affect its gradebook presence. The separate cascade acknowledgement is required even for a preview. Its exact course association, type and metadata are checked independently. Only one Page DELETE is sent, never a second assignment DELETE. Links/module entries may be affected; this is not proof of every downstream consequence or physical removal of grades/submissions.

Previews bind the account, context, delete permission, latest revision, content fingerprint, full paginated page inventory and any reported assignment. RCE HTML and readable native block/external payloads are fingerprinted, not exposed or replayed as edits; this does not add block-editor authoring. Page/assignment GET can record module read progress; latest-revision GET can repair legacy imported YAML. No incomplete inventory or unreadable content is treated as safe deletion evidence.

Verification combines exact-ID acknowledgement, inventory removal, an inaccessible exact ID, old-URL resolution, stable account/permission and an unchanged front page. Native exact-ID lookup can include deleted records and return **403**, so 403 alone is not success. An old numeric slug may resolve to another existing page; that rebound is verified against the inventory and reported, never deleted. A reported linked assignment must independently return **404**; denied or still-readable assignment access is uncertain. Inconsistent/lost readback is uncertain, with no automatic retry, rollback or undelete. Confirmation/readback are not an atomic lock against concurrent changes.

[Native delete and front-page restrictions](https://github.com/instructure/canvas-lms/blob/master/app/controllers/wiki_pages_api_controller.rb), [exact-ID/slug lookup](https://github.com/instructure/canvas-lms/blob/master/app/models/wiki.rb), [native assignment cascade](https://github.com/instructure/canvas-lms/blob/master/lib/submittable.rb), [soft-deletion implementation](https://github.com/instructure/canvas-lms/blob/master/lib/canvas/soft_deletable.rb).

## Duplicate a course wiki page

```sh
canvas page-duplicate 123 789 --acknowledge-shared-page
canvas page-duplicate 123 789 --acknowledge-shared-page --acknowledge-linked-assignment-copy
```

Uses [confirmation](safety.md#confirmation) and one native course-only duplication POST with an empty body, not HTML replay or a create/edit fallback. Creation requires Manage Wiki Create or course-wide student wiki opt-in, not editing/ownership/history permission. Exact numeric source IDs avoid slug collisions. Native restrictions remain authoritative; no group duplication route is invented.

Canvas chooses a unique, potentially localized title/URL and creates an unpublished page. Editing roles and todo date are retained; publication schedules are not copied. Copying a front-page source does not select the copy or unset the source. A draft is not private from teachers/managers. Student opt-in can allow creating a draft that the student cannot subsequently read: failed verification is uncertain, never a reason for automatic publication or deletion.

A reported linked wiki assignment requires separate acknowledgement even for previews. Native duplication can also copy rubric, plagiarism-tool or asset-processor associations and reset selected settings. The new assignment is read independently and must report the exact original assignment/course IDs, a different assignment ID and the copied page's title. Unsupported/missing lineage or inconsistent associations are uncertain. No second assignment POST, submission, assessment attempt or explicit grading action is sent. Separate integrations/background work and every copied association are not verified by this command.

Previews bind account, course/create rights, source page/todo date, latest revision, private HTML/block/external-content fingerprints, any linked assignment/configuration, and full page/front-page inventory. Source bodies, rubric contents, tokens, editors and submission/grade records are not emitted. Reads can record native module progress; latest revision reads can repair legacy imported YAML. Unreadable content or incomplete inventories fail before posting; source changes during execution remain possible despite confirmation.

Exact new-page acknowledgement and separate readback, unchanged source page/assignment, stable account/create rights and an unchanged front page are verified. `content_matches_source` labels literal HTML or portable block-data equality; block comparisons exclude the newly allocated block ID, which must not reuse the source's ID. Native content rewrites or representation changes are reported, not presented as faithful backup. Assignment comparisons expose only field names that changed, were compared, or remain unknown when unavailable; no missing setting is assumed unchanged. No automatic retry, publication, deletion or rollback follows an uncertain result.

[Native course-only route and copy authorization](https://github.com/instructure/canvas-lms/blob/master/app/controllers/wiki_pages_api_controller.rb), [native wiki copy defaults](https://github.com/instructure/canvas-lms/blob/master/app/models/wiki_page.rb), [assignment-copy resets and associated entities](https://github.com/instructure/canvas-lms/blob/master/app/models/abstract_assignment.rb), [native assignment lineage fields](https://github.com/instructure/canvas-lms/blob/master/lib/api/v1/assignment.rb).

## Schedule a course page

```sh
canvas page-schedule 123 789 --publish-at 2030-10-01T10:00:00-07:00 --acknowledge-shared-page
canvas page-schedule 123 789 --cancel --acknowledge-shared-page
```

Uses [confirmation](safety.md#confirmation). Both operations leave the page unpublished. Cancelling a stored date is **not** publish-now, even if an old scheduled date belongs to a currently published page. A new date must have an explicit offset and remain at least 60 seconds ahead after preflight; equivalent dates and absent cancellations are refused without a write.

This course-only command requires native Manage Wiki Update, readable RCE/edit history and a reported enabled root-account feature. The exact course's `root_account_id` determines the feature-flag read; course enabled-feature lists do not prove this root-only setting. An unreadable, missing or disabled flag stops before writing. Group/block pages, front pages and reported linked wiki assignments are not supported by this command. No feature setting, front-page deselection or assignment control is changed implicitly.

Previews bind account, course/permissions/root flag, exact page ID, current revision/private body fingerprint, stored date and full page/front-page inventory. One native PUT sends only the date and disabled update notifications, never content or an explicit publication toggle. Exact acknowledgement and separate page/inventory reads must verify the stored date, draft state, unchanged content/title/URL/roles and stable account/feature/front page. Missing dates are unknown, not an assumed null. No private body/editor/flag extras are emitted.

Canvas can ignore unavailable features and PUT can create a page after concurrent deletion. Uncertain results never trigger retry, publish-now, rollback or repair. Stored-date verification does not prove future background execution, cache propagation or student visibility; ordinary native authorization still applies.

[Native schedule parameters](https://developerdocs.instructure.com/services/canvas/resources/pages), [publication/cancellation callbacks](https://github.com/instructure/canvas-lms/blob/master/app/models/scheduled_publication.rb), [root-account feature definition](https://github.com/instructure/canvas-lms/blob/master/config/feature_flags/00_standard.yml), [feature-flag reads](https://developerdocs.instructure.com/services/canvas/resources/feature_flags).

## Private snapshots

```sh
canvas snapshot 123 --output /private/path/course.json
canvas sync 123 --include-linked-files
canvas snapshot-diff /private/path/older.json /private/path/newer.json --format brief
canvas snapshot-search /private/path/course.json --query 'research paper'
canvas snapshot-markdown /private/path/course.json --output /private/path/course.md
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
canvas upload-personal --folder 789 --file notes.pdf
canvas upload-context 123 --context group --folder 789 --file shared-notes.pdf
canvas upload-assignment-file 123 456 --file paper.pdf
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
canvas exports 123
canvas export-create 123 --type zip --select files 789
canvas export-status 123 456 --progress --format brief
canvas export-download 123 456 --output /private/path/course.zip
```

Creation is asynchronous, role-dependent, and previewed. ZIP selects files/folders; Common Cartridge additionally supports documented course-content types shown in help. Skip-notifications is a job option, not a preference edit.

Status reads the same job/optional same-origin progress, without polling or duplicate creation. Output distinguishes exporting/exported/failed and omits signed URLs. Download requires a finished accessible attachment, refusing expired/hidden/locked packages.

After uncertain creation, inspect existing jobs first. Packages may be private/copyrighted; students may not have export permission.

## Sources

[Files/Folders](https://developerdocs.instructure.com/services/canvas/resources/files), [Pages](https://developerdocs.instructure.com/services/canvas/resources/pages), [Native page authorization/upsert](https://github.com/instructure/canvas-lms/blob/master/app/controllers/wiki_pages_api_controller.rb), [Wiki role/default policy](https://github.com/instructure/canvas-lms/blob/master/app/models/wiki.rb), [Page edit policy](https://github.com/instructure/canvas-lms/blob/master/app/models/wiki_page.rb), [Tabs](https://developerdocs.instructure.com/services/canvas/resources/tabs), [Uploads](https://developerdocs.instructure.com/services/canvas/basics/file.file_uploads), [Exports](https://developerdocs.instructure.com/services/canvas/resources/content_exports), [Throttling](https://developerdocs.instructure.com/services/canvas/basics/file.throttling), [Native root behavior](https://github.com/instructure/canvas-lms/blob/master/app/models/folder.rb).
