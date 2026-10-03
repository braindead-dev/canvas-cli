# Canvas Pocket

A small Canvas LMS CLI under development. JSON in your terminal, credentials in your OS keyring, no telemetry. Unofficial and not affiliated with Instructure.

## Personal development testing

Canvas permits manually generated personal tokens for testing with your own account. Its [OAuth guide](https://developerdocs.instructure.com/services/canvas/oauth2/file.oauth) says applications used by multiple users must use OAuth. This release is a developer preview for the owner's account. An institution must enable a developer key before the OAuth path can be finished.

### Install

Requires Python 3.10+ and an available OS keyring.

```sh
pipx install git+https://github.com/braindead-dev/canvas-pocket.git
canvas-pocket auth login --origin https://canvas.example.edu
canvas-pocket auth status
canvas-pocket courses
```

Login prompts for a token from your own account without echoing it. Create one in Canvas Account → Settings → Approved Integrations, if your institution permits it. Prefer an expiration date and revoke unused tokens. No passwords or browser cookies are collected. macOS Keychain, Windows Credential Locker, Secret Service and KWallet backends are supported; unsupported backends fail closed. Linux may require selecting its secure keyring backend explicitly.

For ephemeral/headless use, supply `CANVAS_ORIGIN` and `CANVAS_TOKEN` through a secret manager/environment. Do not put tokens in command arguments, shell history, source control, or bug reports.

## Commands

Use `canvas-pocket help --format brief` for the command index, grouped by read-only actions, local file writes and preview-first Canvas writes. `help --search TEXT` searches the actual command names and descriptions, and `help COMMAND --format brief` shows exact options. Help works offline without opening the keyring or authenticating.

```sh
canvas-pocket courses
canvas-pocket courses --active
canvas-pocket doctor 123
canvas-pocket find 123 --query 'paper'
canvas-pocket find 123 --query 'lab' --area assignments
canvas-pocket favorites
canvas-pocket favorites --context group
canvas-pocket favorite-add 123
canvas-pocket favorite-remove 456 --context group
canvas-pocket favorites-reset --context course
canvas-pocket groups
canvas-pocket course-groups 123
canvas-pocket my-files --search 'paper'
canvas-pocket nicknames
canvas-pocket nickname 123
canvas-pocket nickname-set 123 --name 'My short course name'
canvas-pocket nickname-clear 123
canvas-pocket nicknames-reset
canvas-pocket colors
canvas-pocket color 123
canvas-pocket color-set 123 --hex '#abc123'
canvas-pocket color-set 456 --context group --hex 'abc'
canvas-pocket color-set 789 --context user --hex '123abc'  # 789 must be your own user ID
canvas-pocket settings
canvas-pocket settings-set --set manual_mark_as_read=true --set collapse_course_nav=false
canvas-pocket dashboard-positions
canvas-pocket dashboard-position-set 123 --position 0
canvas-pocket dashboard-order course_123 course_456 group_789
canvas-pocket activity --format brief
canvas-pocket activity --active --include-content
canvas-pocket activity --course 123 --type AssessmentRequest
canvas-pocket activity-summary
canvas-pocket activity-dismiss 789  # 789 is an activity ID, not the source assignment ID
canvas-pocket activity-dismiss-all --all
canvas-pocket topic-ratings 123 456
canvas-pocket entry-rate 123 456 789 --rating 1
canvas-pocket entry-rate 123 456 789 --rating 0  # remove your like, not the entry
canvas-pocket topic-ratings 123 456 --context group
canvas-pocket file-info 789
canvas-pocket inbox --scope unread --course 123
canvas-pocket conversation 456
canvas-pocket inbox-edit 456 --state archived
canvas-pocket inbox-edit 456 --state unread --starred
canvas-pocket inbox-edit 456 --no-subscribed  # group conversation only
canvas-pocket inbox-delete 456 --permanent
canvas-pocket recipients --search 'Example Name' --course 123
canvas-pocket recipients --user-id 789
canvas-pocket inbox-compose --recipient 789 --subject 'Question' --message-file message.txt
canvas-pocket inbox-reply 456 --message-file reply.txt
canvas-pocket overview
canvas-pocket --format brief overview
canvas-pocket deadlines --days 30
canvas-pocket work --days 30
canvas-pocket submissions 123 --state submitted
canvas-pocket submissions 123 --assignment 456 --include-history
canvas-pocket submissions 123 --include-comments --include-content
canvas-pocket --format brief missing --timezone America/Los_Angeles
canvas-pocket missing --course 123 --course 456 --submittable --current-grading-period
canvas-pocket missing --include-planner
canvas-pocket --format brief agenda --days 21 --timezone America/Los_Angeles
canvas-pocket --format brief agenda --course 123 --course 456 --include-undated
canvas-pocket --format brief work --course 123 --status unsubmitted
canvas-pocket --format brief news --days 30
canvas-pocket news --course 123 --course 456
canvas-pocket linked-files 123
canvas-pocket linked-files 123 --quick
canvas-pocket upcoming
canvas-pocket planner --start 2026-10-01 --end 2026-10-14 --format brief
canvas-pocket planner --course 123 --group 456 --filter incomplete_items
canvas-pocket planner-notes --course 123 --personal
canvas-pocket planner-note 789
canvas-pocket planner-overrides
canvas-pocket planner-override 789
canvas-pocket planner-override-create planner_note 456 --complete
canvas-pocket planner-override-create assignment 456 --complete --allow-module-progress --start 2026-10-01 --end 2026-10-14
canvas-pocket planner-override-edit 789 --dismiss
canvas-pocket planner-override-edit 789 --no-complete --allow-module-progress
canvas-pocket planner-override-delete 789
canvas-pocket task-create --title 'Read chapter' --date 2026-10-05 --course 123
canvas-pocket task-edit 789 --date 2026-10-06
canvas-pocket task-delete 789
canvas-pocket calendar --start 2026-09-25 --end 2026-10-09 --active --personal
canvas-pocket calendar --type assignment --course 123
canvas-pocket calendar --group 456 --undated
canvas-pocket calendar --all --active --personal
canvas-pocket event 789
canvas-pocket event-create --title 'Study block' --start 2026-10-05T19:00:00-07:00 --end 2026-10-05T20:00:00-07:00
canvas-pocket event-create --title 'Read chapter' --date 2026-10-05 --timezone America/Los_Angeles
canvas-pocket event-edit 789 --title 'New study block'
canvas-pocket event-delete 789 --reason 'Schedule changed'
canvas-pocket assignments 123
canvas-pocket assignment-groups 123
canvas-pocket rubrics 123
canvas-pocket quizzes 123
canvas-pocket quiz 123 456
canvas-pocket new-quizzes 123
canvas-pocket new-quiz 123 456  # 456 is the assignment ID for a New Quiz
canvas-pocket submission 123 456
canvas-pocket peer-reviews 123 456
canvas-pocket peer-reviews 123 456 --include-comments --include-users
canvas-pocket peer-reviews 123 456 --scope visible  # only records Canvas permits for your role
canvas-pocket submission-comment 123 456 --message-file question.txt
canvas-pocket submit-url 123 456 --url-file project-url.txt
canvas-pocket submit-text 123 456 --text-file response.txt
canvas-pocket upload-personal --file ./notes.pdf
canvas-pocket upload-assignment-file 123 456 --file ./paper.pdf
canvas-pocket submit-file 123 456 789  # 789 is the resulting uploaded file ID
canvas-pocket submit-file 123 456 789 790  # submit both already uploaded files together
canvas-pocket grades 123
canvas-pocket syllabus 123
canvas-pocket tabs 123
canvas-pocket front-page 123
canvas-pocket modules 123
canvas-pocket module-progress 123 --format brief
canvas-pocket outline 123
canvas-pocket pages 123
canvas-pocket pages 123 --best-effort
canvas-pocket files 123
canvas-pocket files 123 --best-effort --quick
canvas-pocket folders 123
canvas-pocket folder 456
canvas-pocket folder-files 456
canvas-pocket folder-folders 456
canvas-pocket sections 123
canvas-pocket exports 123
canvas-pocket export-status 123 456 --progress --format brief
canvas-pocket export-create 123 --type zip --select files 789
canvas-pocket export-download 123 456 --output /private/path/course-files.zip
canvas-pocket announcements 123
canvas-pocket discussions 123
canvas-pocket discussions 456 --context group
canvas-pocket announcements 456 --context group
canvas-pocket thread 456 789 --context group --format brief
canvas-pocket post 456 789 --context group --message-file response.txt
canvas-pocket topic 123 456
canvas-pocket --format brief thread 123 456
canvas-pocket entries 123 456
canvas-pocket replies 123 456 789
canvas-pocket assignment 123 456
canvas-pocket page 123 introduction
canvas-pocket module-items 123 456
canvas-pocket todo
canvas-pocket download 123 456 --output /private/path/syllabus.pdf
canvas-pocket capabilities
canvas-pocket help --format brief
canvas-pocket help --search export --format brief
canvas-pocket help submit-file --format brief
canvas-pocket get '/api/v1/courses/123/tabs' --paginate
canvas-pocket --max-pages 200 assignments 123
canvas-pocket linked-files 123 --all-pages --quick
canvas-pocket download-linked 123 --directory /private/path/course-files --max-files 100
# Review this exact preview and copy its digest. Keep the same options for execution.
canvas-pocket download-linked 123 --directory /private/path/course-files --max-files 100 --yes --confirm DIGEST
# Or select a few IDs from `linked-files` rather than raising limits for every file.
canvas-pocket download-linked 123 --directory /private/path/course-files --file 456 --file 789
canvas-pocket download-linked 123 --directory /private/path/course-files --file 456 --file 789 --yes --confirm DIGEST
canvas-pocket snapshot 123 --output /private/path/course-123.json
canvas-pocket snapshot 123 --output /private/path/course-123-with-files.json --include-linked-files
canvas-pocket sync 123  # private baseline, then field-level changes on later runs
canvas-pocket sync 123 --directory /private/path/snapshots
canvas-pocket sync 123 --include-linked-files
canvas-pocket snapshot-diff /private/path/older.json /private/path/newer.json
canvas-pocket snapshot-search /private/path/course-123.json --query 'research paper'
canvas-pocket snapshot-markdown /private/path/course-123.json --output /private/path/course-123.md
```

List commands follow Canvas Link pagination, including empty pages. A page limit fails explicitly, never silently truncates. JSON is the complete output; `--format brief` gives a compact human index. `--format` and `--max-pages` work before or after the command. `overview` adds deadlines derived from active course assignments because Canvas's upcoming feed may be empty. `deadlines` lists due dates over a chosen window and reports courses whose assignments could not be read. `work` lists assignments with the current user's Canvas submission status and effective due date (including individual overrides). It shows all dated and undated work by default, or only upcoming dated work with `--days`; missing submission data is labeled `unknown`, never assumed unsubmitted. It reports unavailable courses without hiding other results. [Canvas documents `include[]=submission` for the current user](https://developerdocs.instructure.com/services/canvas/resources/assignments). `calendar` defaults to your personal calendar; use `--active` or repeated `--course` for course calendars, and `--personal` to include your own calendar alongside them. The [Canvas calendar API](https://developerdocs.instructure.com/services/canvas/resources/calendar_events) allows at most ten contexts, so the CLI fails instead of silently dropping extras. `grades` requests the signed-in user's numeric ID and rejects any enrollment returned for another user or course. It reports only grades Canvas makes visible. `submission` reads only your own status, grade, comments and rubric feedback; it issues no submission or read-status mutation. `outline` fetches each module's items separately because Canvas may omit them from the module listing. Use `page` for a page body and `module-items` for paginated module contents. `folders` lists a course's flat folder inventory; `folder-files` and `folder-folders` browse one folder. These may be unavailable when the course Files tab is disabled.

`pages COURSE` retains the raw Canvas list response. Some courses return 403/404 for that list even while individual module pages are readable. `pages COURSE --best-effort` returns an explicit coverage envelope: it uses the normal page list if available, otherwise fetches only readable pages linked from visible modules. A fallback result is always marked incomplete, because pages outside modules may exist. It does not return page bodies. `page COURSE SLUG` reads one known accessible page.

`agenda` is a read-only, submission-aware view of unfinished dated assignments. It displays due times in the system's local time zone by default or an explicit IANA zone, handles daylight saving at each deadline, and separates undated items from actual deadlines. Repeat `--course` to focus on current classes. Its urgency labels describe **time until due only**, not workload, grade impact, or instructor priority. It cannot infer recurring meetings or requirements embedded in external tools, and a missing Canvas submission record is labeled unknown rather than presumed unsubmitted.

`planner` reads the current user's [Canvas planner feed](https://developerdocs.instructure.com/services/canvas/resources/planner), including personal tasks. It follows pagination and defaults to today through thirteen days later; use `--start`/`--end`, repeat `--course`/`--group`, or select `--filter incomplete_items`, `complete_items`, or `new_activity`. A planner completion override is a personal checkbox, not proof an assignment was submitted. This feed complements `agenda`, assignment lists and course instructions; an empty feed does not establish that there is no coursework. `planner-notes` lists personal tasks, with optional date/course filters and `--personal` to include unassociated tasks when filtering courses. `planner-note` reads one, and `planner-overrides` reads completion/visibility overrides without changing them.

`task-create`, `task-edit` and `task-delete` operate only on the signed-in user's personal planner notes. Each first returns a preview, then requires the same command with `--yes --confirm DIGEST`. The preview binds the Canvas origin, signed-in user, exact changes and current destination. Edit sends only fields you specify; `--details-file` reads plain UTF-8, including an empty file to clear details. `--clear-course` explicitly removes a course association. Linked tasks cannot change course. Delete removes only the named personal task, not an assignment, and cannot be combined with editing. A changed task, account or destination invalidates confirmation. These commands have synthetic HTTPS tests only; no personal task was created or removed in a live account.

`module-progress` separately paginates visible [module items](https://developerdocs.instructure.com/services/canvas/resources/modules) with reported completion requirements. It distinguishes completed, incomplete, unknown and not-required items, and preserves Canvas's module state and all/one requirement rule rather than inferring completion from counts. Locked modules are listed without fetching their items, denied item lists are explicitly partial, and hidden/unpublished metadata is skipped. It does not view content, send completion events, start assessments, or change grades.

`exports COURSE` lists authorized [course content-export jobs](https://developerdocs.instructure.com/services/canvas/resources/content_exports) through pagination. `export-status COURSE EXPORT_ID` reads one existing job; `--progress` also reads its linked same-origin Canvas progress resource. It does not create another job or automatically poll. Output distinguishes exporting/exported/failed state and download availability, omitting signed attachment URLs. `export-create COURSE` previews a new asynchronous export, then requires `--yes --confirm DIGEST` bound to account, course and exact options. The default `--type zip` exports files; `common_cartridge` packages course content. Repeat `--select RESOURCE ID` to choose specific documented resources. ZIP supports only `files`/`folders`; Common Cartridge also supports `attachments`, `assignments`, `announcements`, `calendar_events`, `discussion_topics`, `modules`, `module_items`, `pages` and `rubrics`. `--skip-notifications` is an explicit job option, not a settings change. Role permissions may deny this feature, especially for students; no restriction is bypassed and no live export was started.

After the **same job** reports `exported` with an available attachment, `export-download COURSE EXPORT_ID --output /private/path/export.zip` downloads it with the separate credential-free file transport. It refuses unfinished, failed, expired, hidden or locked packages, overwrites and Git-checkout destinations; the local file is mode `0600` and the byte limit defaults to 100 MiB. It never sends the API bearer token to storage or prints signed download URLs. Course packages can contain private or copyrighted material; keep them local. A timeout or uncertain creation response is not permission to create a duplicate job: inspect the existing jobs first. These paths have synthetic HTTPS tests only.

`tabs COURSE` lists visible course navigation labels and Canvas paths, including external-tool tabs, without launching those tools. `front-page COURSE` reads the published course home page where Canvas provides one. External tools such as Zoom or Piazza need their own authorization and are not controlled through these commands.

### Group content and storage metadata

`files`, `folders`, `pages`, `page`, `tabs`, `front-page` and `download` accept `--context group`, using an explicit group ID instead of a course ID. Course behavior stays the default. Each group read first verifies the authorized group record, and native scoped routes keep group files/pages separate from course content. Group collection output is an endpoint-coverage envelope with metadata in `items`, not a claim that every external-tool resource was discovered. File lists omit download/viewer URLs and uploader associations; page indexes omit bodies and exclude explicitly unpublished/hidden/locked pages. Folder records must match the exact group context. Hidden navigation paths are omitted and external tabs are never launched. Full page reads accept a single slug or numeric page ID and preserve access/publication checks.

`download GROUP FILE --context group --output /private/path/file.pdf` obtains metadata through the native group-file route and reuses the credential-free binary transport, overwrite/Git guards, private permissions, byte limit and size check. An unavailable or mismatched file is refused; no global-file-ID fallback bypasses group scope. `--best-effort`, `--quick` and `--all-pages` course fallbacks do not apply to group spaces, which do not have the same modules model. Denied group listings remain errors, not a fabricated complete empty inventory.

`root-folder CONTEXT --context course|group|user` reads the native root-folder metadata and verifies its context and root association. `file-quota CONTEXT --context course|group|user` reports native quota/used/remaining bytes, including an over-quota flag. User-context reads require your signed-in numeric user ID; they never accept another user's storage. A positive remaining quota does not establish permission to upload. These are GET-only operations with no membership, uploads, publication or enrollment changes; Canvas may record content-access analytics. Group support and quota/root reads have synthetic HTTPS coverage only. See the [official Files/Folders API](https://developerdocs.instructure.com/services/canvas/resources/files), [Pages API](https://developerdocs.instructure.com/services/canvas/resources/pages) and [Tabs API](https://developerdocs.instructure.com/services/canvas/resources/tabs).

```sh
canvas-pocket files 123 --context group --format brief
canvas-pocket folders 123 --context group
canvas-pocket pages 123 --context group
canvas-pocket page 123 welcome --context group
canvas-pocket tabs 123 --context group
canvas-pocket root-folder 123 --context group
canvas-pocket file-quota 123 --context group
```

`linked-files` discovers links in readable syllabus, modules, module pages, assignments, announcements and discussion prompts, useful when a course's Files tab is hidden. It skips explicitly unpublished, hidden or locked sources; it does not read student discussion entries, is not a complete inventory, and reports when a linked file is hidden or locked for the user. `--all-pages` adds accessible published pages outside modules. `--quick` skips per-file metadata requests, so availability is unknown, but is substantially faster for courses with many files. Requests remain sequential to avoid Canvas's [parallel-request throttling penalty](https://developerdocs.instructure.com/services/canvas/basics/file.throttling). Downloads use an explicit output path, refuse overwrites and Git-checkout destinations, remove failed partial files, compare received bytes with Canvas's advertised file size when available, default to a 100 MiB limit and never send the API token to file storage. Signed download URLs are not logged. `syllabus` returns the course's syllabus body, not all linked documents. `me` returns your private profile; `auth status` only reports authentication validity.

`files COURSE` preserves Canvas's raw Files list. If that list is denied, `files COURSE --best-effort` falls back to `linked-files` and returns an explicit `complete: false` envelope. It never claims that linked files are every file in the course. `--quick` and `--all-pages` work with the fallback option.

`snapshot` reads the syllabus-bearing course record, assignments, module items, accessible published pages, announcements, and visible discussion prompts into one local JSON file. It does not fetch classmates' replies, make quiz attempts, or write to Canvas. `--include-linked-files` additionally indexes metadata for files referenced by readable course content, without downloading binaries or claiming a complete Files inventory. It can be slow because file records are checked sequentially. If an endpoint is unavailable, the snapshot says `complete: false` and records the missing resource. When the pages list is unavailable, it tries readable page links from modules but still marks the snapshot incomplete. It removes token-shaped JSON fields such as Canvas `secure_params` and credential-like URL query parameters before saving. The file is mode `0600`, cannot overwrite an existing file, and cannot be placed inside a Git checkout, including through a symlinked parent. It may still contain copyrighted course materials, private academic information or other expiring links; keep it local and do not post it to a public repo.

`sync COURSE` does the private capture-and-diff cycle in one read-only Canvas command. It defaults to a private snapshots directory under the app config folder, or accepts `--directory`. The first run creates a baseline; later runs compare with the latest same-origin/course snapshot and return field names and visible titles, never full bodies. Add `--include-linked-files` to track references and metadata; comparing against an older snapshot without that option skips the file category instead of inventing additions. Raw snapshots are immutable mode-`0600` files outside Git and accumulate until you remove ones you no longer need. A failed capture or comparison does not overwrite the previous snapshot.

Partial-coverage results are reserved for permission-denied or not-found course resources. Authentication failures, rate limits, network failures and malformed responses stop a snapshot, file scan or multi-course summary instead of being mistaken for an empty class. A failed `sync` leaves the last saved baseline intact.

`snapshot-diff` works offline and reports added/removed resources and which fields changed, without printing full assignment descriptions, page bodies or discussion prompts. It skips full inventories for categories incomplete in either snapshot, avoiding false “removed” claims. For pages and linked files observed in both partial snapshots, it separately reports changed fields under `observed_changes` without claiming that no others exist. Older snapshots lack discussion and optional linked-file coverage; comparison skips those categories rather than inventing additions or removals. It does not need a Canvas credential.

`snapshot-search` works offline over that same private JSON. It searches syllabus, assignment descriptions, announcements, discussion prompts, pages, module titles and optional linked-file names, returning short plain-text snippets and ranking title matches first. It reports when the source snapshot was incomplete or predates discussion capture; no hits never proves the course contains no such material. Its output can contain private course information, so do not paste it into public issues or logs.

`snapshot-markdown` also works offline. It turns a snapshot into one readable Markdown file with syllabus, assignments, announcements, discussion prompts, modules, pages and optional linked-file names. It converts Canvas HTML to plain text rather than embedding active HTML or external images, marks incomplete snapshots, and includes only safe same-origin Canvas assignment links. Like raw snapshots, the output is mode `0600`, never overwrites and cannot be written inside a Git checkout. Review it before sharing; course content may be copyrighted or private. This is a readable projection, not a lossless Canvas backup.

`inbox` lists your Canvas conversations; `conversation` fetches one with `auto_mark_as_read=false`. The [Canvas Conversations API](https://developerdocs.instructure.com/services/canvas/resources/conversations) otherwise marks an unread thread read by default on a GET. The transport blocks that unsafe GET even through the expert `get` command unless the query explicitly sets `auto_mark_as_read=false`. It also blocks `include[]=read_status` on GET, since the [Submissions API](https://developerdocs.instructure.com/services/canvas/resources/submissions) says including it marks submissions read. These commands do not send or intentionally alter read state; other undocumented server-side effects remain outside this guarantee. `inbox-reply` previews the current participants and exact message and also uses the safe GET. It only sends with both `--yes` and a matching `--confirm` digest from that preview, and refuses to send if the message or thread audience changes between preview and execution. This send route has synthetic TLS tests but has not been exercised against a live account. `groups` returns only your active groups; `course-groups` returns only groups visible to your Canvas role.

`recipients` searches Canvas's [messageable-user directory](https://developerdocs.instructure.com/services/canvas/resources/search) or confirms one numeric user ID. Text search can be limited to a course; Canvas ignores course context in an ID lookup, so the CLI refuses that misleading combination. `inbox-compose` addresses exactly one verified individual, previews their identity and exact subject/body, then requires `--yes` and a matching digest to send. Canvas may reuse an existing private thread with that recipient. The lookup and preview were live-tested without sending; actual sends have synthetic TLS tests only. Do not use a course or group ID as a recipient.

`news` lists recently posted announcements across active or selected courses using Canvas's dedicated [Announcements API](https://developerdocs.instructure.com/services/canvas/resources/announcements). It fetches each course separately so one inaccessible course does not hide all the others, and reports any unavailable course. JSON includes the full visible announcement body; brief output is a title/date index. The date window is based on posting time, not subsequent edits, so older edited announcements need a longer `--days` window.

`thread COURSE TOPIC` reads a visible discussion's top-level entries and all replies. Canvas embeds only the ten most recent replies in each entry; the command follows the separate [paginated replies API](https://developerdocs.instructure.com/services/canvas/resources/discussion_topics) when more exist. It refuses unpublished or locked topics and respects an initial-post requirement. If some replies are denied, the result is marked partial rather than silently claiming completeness. It sends only GET requests and never posts or invokes Canvas's mark-read endpoints. JSON may contain classmates' names and posts; keep it private.

`assignment-groups` shows Canvas's group weights and grading rules. `rubrics`/`rubric` read visible criteria. `quizzes`/`quiz` read metadata for Classic Quizzes, including dates, attempt limits and time limits. `new-quizzes`/`new-quiz` read metadata from Canvas's separate [New Quizzes API](https://developerdocs.instructure.com/services/canvas/resources/new_quizzes); the single-item command takes its associated assignment ID. These commands never list quiz questions or create an attempt. Availability depends on Canvas permissions and which quiz engine a course uses.

`download-linked` previews a batch of downloadable files referenced by readable content, then writes only with `--yes --confirm DIGEST` from a matching fresh preview. Use repeatable `--file ID` to choose specific discovered files; requesting an absent, hidden or locked file fails without downloading. Changing the selection, file set, metadata, destination, discovery scope or limits invalidates the digest. A preview still lists files when default file/byte limits would be exceeded, with `within_limits: false` and the exact `limit_issues`; an actual download refuses those limits before writing. It requires an existing destination outside Git, refuses filename collisions, limits file count and total bytes, and sanitizes server filenames. Successful earlier files remain if a later download fails, and the error reports that partial batch progress. It never sends the Canvas API token to storage URLs. It does not promise a complete course file inventory or access beyond your account's permissions.

`upload-personal` and `upload-assignment-file` follow [Canvas's three-step upload protocol](https://developerdocs.instructure.com/services/canvas/basics/file.file_uploads). They preview the source path, size, SHA-256 hash and destination, then require `--yes --confirm DIGEST`. Personal uploads request rename-on-duplicate because Canvas otherwise overwrites a same-named file. Assignment uploads check that the current assignment permits file submissions and any listed extension, but **do not submit the assignment**. The CLI sends your token only to Canvas for initiation and confirmation; its separate storage request has no token, cookies or redirects. A failed/ambiguous upload is not retried automatically. Default maximum file size is 25 MiB; use `--max-bytes` deliberately if needed. These writes have synthetic HTTPS tests but no live-upload validation. Do not assume a successful upload means your work was turned in. To turn it in, separately preview `submit-file COURSE ASSIGNMENT FILE_ID` and confirm its digest. [Canvas documents this distinct file-ID submission step](https://developerdocs.instructure.com/services/canvas/resources/submissions).

`my-files` and `file-info` use the [Files API](https://developerdocs.instructure.com/services/canvas/resources/files) to locate and verify an accessible uploaded file ID. `my-files --search` filters by partial filename and follows pagination; `file-info` requires an exact numeric ID. These are read-only and may show personal filenames in terminal output.

`submit-file COURSE ASSIGNMENT FILE_ID [FILE_ID ...]` supports one or several already uploaded files in one submission. It verifies every file's identity, size, access and permitted extension, and binds the selected list plus metadata to the preview. Duplicate IDs are refused; changing any selected file or the account invalidates confirmation. The single-file `file` preview field is retained alongside the uniform `files` array for existing callers. Canvas ultimately determines whether the files belong to the submitting user or their submission group. URL, text and file submission previews are bound to the signed-in user and Canvas origin as well.

`submission-comment COURSE ASSIGNMENT --message-file question.txt` previews a plain-text comment on **your own submission**, using the [Submissions API](https://developerdocs.instructure.com/services/canvas/resources/submissions). It verifies current-user identity, assignment identity and submission ownership, then requires `--yes --confirm DIGEST`. It sends only `comment` fields, never grading or submission content. Optional `--attempt N` targets an existing confirmed attempt; `--group-comment` explicitly expands the audience and requires a group assignment. Comments can be visible to graders and others permitted to view that submission. New attempts or audience changes invalidate the preview. It has synthetic HTTPS coverage only, with no live comment posted.

`doctor COURSE` makes small, sequential GET requests to a visible course's major read APIs and reports only reachability states, not course content. A 403 or 404 may reflect role, publication, or institution configuration, and a readable endpoint does not guarantee every item is visible. It stops probing on a rate limit. This is a diagnostic map, not a way around access controls.

`find COURSE --query TEXT` searches visible titles/names through the documented assignment, discussion, page, file and module filters, then verifies matches locally in case Canvas ignores a filter. It returns IDs, titles and due dates, not bodies, and reports endpoints that were restricted or not found. Use `--area` to search one area faster. If Canvas denies the pages search, it searches readable pages linked from visible modules and labels page coverage incomplete; it does not claim to have searched pages outside modules. If Canvas denies the Files list, it searches accessible files linked from readable course content and labels the result partial. This linked-file fallback can be slow because it checks each file sequentially. Canvas can omit module items from a module response; the result flags that incomplete coverage rather than claiming there were no matches. For body-text searches, first create a private snapshot and use `snapshot-search` offline.

See [the capability map](CAPABILITIES.md) for implemented features, permission boundaries and the broader roadmap. The expert `get` command extends read coverage without exposing arbitrary write methods.

### Posting deliberately

```sh
canvas-pocket post 123 456 --message-file reply.txt
# Review the JSON preview. Nothing was posted.
canvas-pocket post 123 456 --message-file reply.txt --yes --confirm DIGEST
# Add --reply-to 789 for a reply to an entry.

canvas-pocket inbox-reply 456 --message-file reply.txt
# Read the preview and copy its confirm digest.
canvas-pocket inbox-reply 456 --message-file reply.txt --yes --confirm DIGEST

canvas-pocket inbox-compose --recipient 789 --subject 'Question' --message-file message.txt
# Read the recipient and message preview, then use its digest.
canvas-pocket inbox-compose --recipient 789 --subject 'Question' --message-file message.txt --yes --confirm DIGEST

canvas-pocket submit-url 123 456 --url-file project-url.txt
# Read the assignment, due date and exact URL in the preview, then use its digest.
canvas-pocket submit-url 123 456 --url-file project-url.txt --yes --confirm DIGEST
# submit-text uses the same two-step flow with --text-file.

canvas-pocket upload-personal --file ./notes.pdf
canvas-pocket upload-personal --file ./notes.pdf --yes --confirm DIGEST
canvas-pocket upload-assignment-file 123 456 --file ./paper.pdf
canvas-pocket upload-assignment-file 123 456 --file ./paper.pdf --yes --confirm DIGEST
# The upload reports the new file ID; this only stages the file.
canvas-pocket submit-file 123 456 789
canvas-pocket submit-file 123 456 789 --yes --confirm DIGEST
canvas-pocket submit-file 123 456 789 790
canvas-pocket submit-file 123 456 789 790 --yes --confirm DIGEST

canvas-pocket task-edit 789 --date 2026-10-06
canvas-pocket task-edit 789 --date 2026-10-06 --yes --confirm DIGEST
canvas-pocket submission-comment 123 456 --message-file question.txt
canvas-pocket submission-comment 123 456 --message-file question.txt --yes --confirm DIGEST
```

Discussion-post and text-entry submission inputs are plain UTF-8 text, safely escaped to HTML. Discussion posts also re-check the topic ID, title and lock state before a separately confirmed send. Inbox replies use the plain UTF-8 body specified by the Canvas API. URL submissions read one absolute HTTP(S) URL from a file, keeping private URLs out of shell history. Assignment submission previews check the current assignment ID, publication/lock state and allowed type, then require `--yes` with a matching digest from the preview. These commands can publish real content under your account. Follow your course rules and review the destination and content. Writes are never retried automatically; after a timeout verify Canvas before retrying. The guarded send routes have synthetic TLS end-to-end tests; URL preview was tested against a live assignment, but no live submission was made. The CLI does not take quizzes, change grades, or bypass initial-post restrictions.

## Peer-review read scope

`peer-reviews COURSE ASSIGNMENT` reads the native paginated endpoint and defaults to reviews **of your own submission**. This is not a complete inventory of reviews you owe: student permissions normally restrict this endpoint to the assessee, not the assessor. Output always says `owed_review_inventory_complete: false`. `--scope visible` includes other returned records only if Canvas authorizes them for your role; it does not elevate permissions or enumerate other submissions.

`--include-comments` and `--include-users` explicitly request the native associations. Submission comments can repeat across peer-review records and are not necessarily authored by that review's assessor. Anonymous/missing assessor IDs are never reconstructed or looked up, and an assessor association is omitted when the API does not provide an assessor ID. Assignment identity/publication/lock checks run first, and malformed or duplicate IDs and truncated pagination fail rather than producing a false complete result. These are read-only commands: no allocation, review completion, rubric grading, assessment attempts or read-status writes. Synthetic HTTPS tests cover scopes, pagination and anonymous records; live coverage remains unverified. See the [official Peer Reviews API](https://developerdocs.instructure.com/services/canvas/resources/peer_reviews).

## Inbox organization

`inbox-edit` can set `--state read|unread|archived`, `--starred`/`--no-starred` and, for a confirmed group conversation, `--subscribed`/`--no-subscribed`. Only specified fields are sent. Archive preserves messages; setting the state to read or unread brings an archived thread back. Subscription changes affect only your unread flags and Inbox ordering, not other participants or whether you retain access.

`inbox-delete ID --permanent` removes all messages from **your own view**, not other people's copies. There is no Pocket restore command, so use archive if you want to keep the thread. Both commands first read with `auto_mark_as_read=false`, bind the signed-in account/site, current state and a private message-revision digest, then require `--yes --confirm DIGEST`. Previews do not echo message bodies. A new message or changed state invalidates an old preview. No message is sent by these commands, and ordinary reads never issue state edits. State changes, explicit false values, deletion, stale previews and the group-only subscription rule have synthetic HTTPS tests, not live write validation. See the [official Conversations API](https://developerdocs.instructure.com/services/canvas/resources/conversations).

## Dashboard favorites

`favorites` defaults to courses; `--context group` selects groups. This read-only list can be Canvas's automatic default selection, not proof that every item was explicitly starred. `favorite-add`, `favorite-remove` and `favorites-reset` change only your own favorites, never enrollment, membership or course content. They preview the current account, exact context/target and full paginated displayed selection, then require `--yes --confirm DIGEST`.

Adding the first custom favorite can replace the default displayed selection. Removing a course with no custom favorites can first save the other default courses as favorites. Removing the last custom favorite or resetting can make defaults appear again. Reset clears **all custom favorites of the selected type**, not just the listed IDs. Canvas enforces membership/permissions, and inaccessible targets are not bypassed. An acknowledged remove may be a no-op if there was no explicit favorite; the output does not falsely claim that a displayed default disappeared. Course/group lifecycle and pagination have synthetic HTTPS coverage only. See the [official Favorites API](https://developerdocs.instructure.com/services/canvas/resources/favorites).

## Own display preferences

`nicknames` lists your saved course aliases with full pagination; `nickname COURSE` shows the actual course name and your optional alias. `nickname-set COURSE --name NAME`, `nickname-clear COURSE` and `nicknames-reset` are preview-first writes requiring `--yes --confirm DIGEST`. Set changes only the calling user's nickname, not the shared course name. Clearing one restores its actual name in your subsequent API responses; resetting clears **all** your course nicknames, not just one course. Names must be nonempty, shorter than 60 characters and free of control characters. An absent nickname is not silently treated as a successful removal.

`colors` and `color ITEM --context course|group|user` report only saved custom colors; an unset custom value is `null`, not a claim about the default UI color. `color-set` accepts a three- or six-digit RGB hex value, previews the exact target and current preference, then requires matching confirmation. User-context changes are restricted to your own personal calendar. Colors affect only your display preferences; there is no documented color-clear endpoint, so Pocket does not invent one. These actions have synthetic HTTPS lifecycle tests, not live write validation. See the [official Users and course-nickname API](https://developerdocs.instructure.com/services/canvas/resources/users).

`settings` reads the known own-user interface booleans and reports keys the deployment did not return. It never requests mobile settings or prints unknown response fields. `settings-set --set KEY=true --set OTHER=false` accepts exact, distinct supported keys; it sends only those fields after an account/current-state-bound preview and matching confirmation. A requested setting missing from the deployment's read response is refused rather than guessed. `manual_mark_as_read` changes future browser discussion read behavior, not existing read markers; feature-gated settings may not visibly affect the current UI. No setting changes automatically during login or ordinary reads.

`dashboard-positions` reads your saved positions, not a complete inventory of visible dashboard cards. `dashboard-position-set ITEM --position N --context course|group|user` sets one position from -1000 through 1000. `dashboard-order course_123 course_456 group_789` assigns positions 0, 1 and 2 in that order. Both preview the current full map and verified targets, then require `--yes --confirm DIGEST`. The API **merges** specified positions; unspecified positions remain, equal positions may be ambiguous, and neither favorites nor card visibility change. User-context writes require your own user ID. These settings/order actions have synthetic HTTPS tests only, not live write validation. They use the [documented Users API and official implementation](https://github.com/instructure/canvas-lms/blob/master/app/controllers/users_controller.rb).

## Contact channels and notification frequencies

`channels` paginates only your own [communication channels](https://developerdocs.instructure.com/services/canvas/resources/communication_channels) and defaults to IDs, types, positions, state and bounce metadata. `--include-addresses` explicitly prints own email/SMS addresses to identify the destination; push/provider addresses, tokens and bounce summaries are never printed. Channel state does not prove that delivery works. The CLI does not create or delete channels.

`notification-preferences CHANNEL_ID` reads the native wrapped preference inventory and reports exact notification/category keys and frequencies. `--category KEY` filters that inventory locally, and a category absent from the deployment is an error rather than a misleading empty success. Unknown, duplicate or malformed metadata is refused. These are GET requests, but **Canvas may persist default policy records when preferences are read**; Pocket does not select new frequencies automatically. This behavior comes from the [official notification controller](https://github.com/instructure/canvas-lms/blob/master/app/controllers/notification_preferences_controller.rb) and [policy model](https://github.com/instructure/canvas-lms/blob/master/app/models/notification_policy.rb), not an assumption that every GET is side-effect-free.

`notification-preferences-set CHANNEL_ID --set new_announcement=immediately --set submission_comment=daily` previews only those named settings, then requires the same command with `--yes --confirm DIGEST`. The supported frequencies are `immediately`, `daily`, `weekly` and `never`. Unknown notification keys, duplicate selections and stale account/site/channel/current-preference revisions are refused; private contact addresses are hashed rather than echoed in previews. Unselected preferences are not sent. Execution uses one native batch PUT, and **a failed or ambiguous batch can have partially applied**, so verify in Canvas before repeating. No automatic retries or response-body logging occur. These preferences apply to the selected own channel; course overrides and institution configuration can also affect delivery. Disabling emails can hide deadline alerts. No channel, enrollment or Inbox read state is changed by this write.

These commands have synthetic HTTPS coverage only; no real account's notification frequencies were changed to test them. See the [official notification-preferences API](https://developerdocs.instructure.com/services/canvas/resources/notification_preferences).

```sh
canvas-pocket channels
canvas-pocket channels --include-addresses --format brief
canvas-pocket notification-preferences 123 --category announcement
canvas-pocket notification-preferences-set 123 --set new_announcement=immediately
```

## Own submission inventory

`submissions COURSE` uses Canvas's [paginated multi-assignment submission API](https://developerdocs.instructure.com/services/canvas/resources/submissions) with the signed-in user's numeric ID explicitly selected. It never accepts another student or `all`. Repeat `--assignment ID` and use `--state submitted|unsubmitted|graded|pending_review` for native filters. Every returned parent record must match the own user, selected assignment and course association; mismatches and page-limit failures produce errors without partial output.

Default output is status/grade/attempt metadata and assignment titles, not private work or feedback. `--include-history` adds attempt metadata; `--include-comments` adds comment metadata; `--include-content` explicitly enables authorized bodies, attachment links and fetched feedback text. Historical nulls or absent associations remain unknown, not fabricated attempts. Content for an explicitly invisible or unpublished assignment is withheld. `grade_matches_current_submission=false` means an earlier attempt's grade may still be shown. These are GET-only reads with no `read_status` inclusion, no assessment attempts and no grading/submission writes. This is submission-endpoint coverage, not a complete coursework checklist, and has synthetic HTTPS coverage only.

## Native missing work

`missing` reads the signed-in student's [native missing-submission list](https://developerdocs.instructure.com/services/canvas/resources/users), following all pages. Repeat `--course COURSE` to restrict courses; `--submittable` and `--current-grading-period` use Canvas's documented filters rather than inferring a late policy locally. Output is assignment metadata with effective due times in `--timezone IANA_ZONE` (system local by default), not prompts or submission bodies. An unknown or timezone-free due time stays unknown. The native list can include locked assignments; being listed does not guarantee a late submission will be accepted.

`--include-planner` adds verified own assignment checkmarks/dismissals, but these **do not** submit work or clear a missing-submission flag. An empty list is not proof that all coursework, external tools, reading or attendance is finished. Coverage describes this endpoint only; permission, authentication or pagination failures are errors rather than an empty success. This command is GET-only, does not mark feedback read or start assessments, and has synthetic HTTPS coverage only.

## Activity notifications

`activity` reads the own global activity stream with full pagination; `--course COURSE` selects the authorized course stream, and `--active` filters the global feed to active courses. `--type AssessmentRequest` (or another exact native type) filters after pagination and preserves the endpoint count. Default output includes identifiers, titles, dates, read state and safe links, not private bodies. `activity-summary` reads Canvas's native notification counts, optionally by course or active courses. Neither an empty feed nor its unread count proves there is no coursework or peer review owed.

`--include-content` opts in to bodies and selected associations; these can contain private academic or message data. Discussion prompts are read from the current authorized topic rather than a stale cached prompt. Cached peer entries require a fresh published/unlocked topic and confirmed entry access; unknown or initial-post-restricted access is withheld. Standalone discussion-entry notices lacking a verified topic are metadata-only. Cached replies and message previews can be incomplete or outdated; use `thread`, `conversation` or `submission` for the full source. Reads do not issue read-marker writes.

`activity-dismiss ID` previews hiding only that notification from your own feed. `activity-dismiss-all --all` explicitly previews hiding **all your stream items**, including any outside the visible feed; it is not limited to the displayed page or list. Both bind the account, site and full current item revisions without echoing private bodies, then require `--yes --confirm DIGEST`. Hiding neither deletes the underlying message/content nor submits, grades or completes anything; Pocket has no restore command. Canvas's native acknowledgement is not a task-completion check. Pagination, content boundaries and hiding have synthetic HTTPS tests only. See the [official activity-stream API](https://developerdocs.instructure.com/services/canvas/resources/users) and [serialization source](https://github.com/instructure/canvas-lms/blob/master/lib/api/v1/stream_item.rb).

## Discussion contexts and entry changes

`topic-ratings CONTEXT TOPIC` reads only your own native likes and the entry IDs covered by Canvas's cached discussion view, not participant details or bodies. `--context group` uses the group namespace. Ratings must be explicitly enabled and post-first/visibility restrictions apply. The cached view is eventually consistent; an absent vote is only known for an entry represented in that snapshot, not a newly unmaterialized reply. Disabled ratings are reported without fetching the cached thread. Canvas may record content-access analytics for these GETs; Pocket sends no rating or read-marker writes when reading.

`entry-rate CONTEXT TOPIC ENTRY --rating 1` previews setting your like; `--rating 0` previews removing it. Execution requires `--yes --confirm DIGEST` and binds the signed-in account/site, own current rating, current topic and exact visible entry revision. Changed bodies invalidate the preview even without a timestamp change. Cached private bodies are not echoed in previews; use `entry` to inspect the target. Only one native rating POST is issued, with an empty HTTP 204 required as acknowledgement; an unexpected response is never retried. Canvas enforces grader-only and other permissions. This changes a like, not a grade, entry text or explicit read marker. Reads and writes have synthetic HTTPS coverage only. See the [official discussion API](https://developerdocs.instructure.com/services/canvas/resources/discussion_topics).

Discussion listings, topic reads, full threads, entries, replies and `post` accept `--context group` for a group ID instead of a course ID. Existing commands default to courses. The namespace is explicit in the route, thread output and write preview; course/group IDs are not interchangeable. Topic identity/publication/lock checks are shared, and entry reads or replies respect initial-post restrictions. Group access remains subject to Canvas permissions; no membership or role is assumed. Reads do not issue read-state writes, and posts still need the account-bound confirmation digest. Group routes have synthetic HTTPS coverage only.

`entry CONTEXT_ID TOPIC_ID ENTRY_ID` reads exactly one visible entry through the paginated ID lookup. `entry-edit` with `--message-file` and `entry-delete` default to previews and require a matching `--yes --confirm DIGEST`. They only change entries authored by the signed-in user, bind the current entry revision/account/context, and never delete the topic or its associated assignment. Changed content, attachments or ownership require a fresh preview. Editing/deleting a graded post can affect participation credit; Canvas still enforces course permissions.

**Canvas text edits can remove an existing attachment.** The CLI refuses that edit unless `--remove-attachment` explicitly acknowledges the loss. Use Canvas's native editor instead if the attachment must be preserved. Entry deletion requires Canvas's exact empty HTTP 204 acknowledgement, not an arbitrary empty response. Replies through `post --reply-to` now fetch and bind the visible, non-deleted target entry as well as the topic and message. These workflows have synthetic HTTPS tests only; no live discussion was modified. See the [discussion API](https://developerdocs.instructure.com/services/canvas/resources/discussion_topics) and [entry controller](https://github.com/instructure/canvas-lms/blob/master/app/controllers/discussion_entries_controller.rb).

```sh
canvas-pocket entry 123 456 789
canvas-pocket entry-edit 123 456 789 --message-file revised.txt
canvas-pocket entry-edit 123 456 789 --message-file revised.txt --yes --confirm DIGEST
canvas-pocket entry-delete 123 456 789 --context group
# Review the deletion preview before repeating with --yes --confirm DIGEST.
```

`topic-subscribe`/`topic-unsubscribe` change only your notifications for one topic. `topic-mark-read`/`topic-mark-unread` change only your read marker for the initial topic text, not all replies. `entry-mark-read`/`entry-mark-unread` change your marker for one visible entry, including another author's post, without changing its content. They all take context/topic IDs, entry commands also take an entry ID, and `--context group` selects group routes. Every change is separately previewed and digest-confirmed; ordinary reads never call these mutation endpoints. Explicit subscription changes remain possible for a closed topic, subject to Canvas access controls.

For entry markers, optional `--forced-read-state` sets Canvas's manual override and `--no-forced-read-state` clears it. Omit both to leave the override unchanged. Changing any current target/account/state invalidates confirmation. Initial-post restrictions still block entry lookups; topic-text and subscription operations do not read entries at all. The API's empty HTTP 204 acknowledges success; it does not mean content was read by a person or coursework completed. These state controls have synthetic HTTPS coverage only.

## Personal calendar

Personal calendar writes use the same account-bound preview and matching `--yes --confirm DIGEST` as other Canvas writes. `event-create` adds one event to your personal calendar; `event-edit` and `event-delete` re-read and verify the named event belongs to that calendar. They refuse course/group events, appointments, section events and deleted/locked/hidden events. Recurring-event edits and deletion explicitly use `which=one`, never a whole series. No assignment or reservation is changed, and uncertain write outcomes are never retried automatically.

Use ISO timestamps with seconds and `Z` or an explicit UTC offset for timed events. Start and end must both be provided, with end later than start. `--timezone` optionally validates both offsets against that IANA zone on their dates. For a single all-day event, use `--date YYYY-MM-DD --timezone IANA`; daylight saving is handled for that date, and skipped or ambiguous midnights are refused. `--details-file` is plain UTF-8 text escaped to HTML, with an empty file clearing details; empty `--location` or `--address` clears that field. Editing sends only specified fields. The new calendar writes have unit and synthetic HTTPS tests, not live account write coverage.

The read-only `calendar` command also accepts repeated `--group` filters. `--undated` returns only undated items; `--all` returns dated and undated items. Neither can be combined with a date window, since Canvas would ignore it. `event ID` reads one numeric calendar event ID without changing it; assignment calendar entries remain available through `calendar --type assignment`.

## Personal Canvas file organization

`my-root` returns your personal root folder ID and `my-folders` lists your paginated personal folders. `my-folder-create PARENT_ID --name NAME` creates one subfolder after an account-bound preview and matching confirmation. It refuses an existing same-named child, changed sibling inventory, inaccessible folders, other users' folders, course/group folders and submission folders. Use numeric IDs from your own inventory, not a guessed course folder.

`my-file-edit FILE_ID --name NAME --folder DESTINATION_ID` renames and/or moves a personal file. Either option can be used alone. `my-file-copy FILE_ID --folder DESTINATION_ID` copies an accessible file into your personal folder without modifying the source; a readable course file can be copied if Canvas permits it. Both use `on_duplicate=rename`, never overwrite. Canvas may append a qualifier to resolve a collision, so inspect the actual name in the result. They send no publication, visibility, sharing or lock-setting changes. Moves can affect inherited folder behavior and existing links; review the destination. Preview fingerprints bind file metadata and destination/account; they do not prove unchanged binary bytes.

`my-folder-edit FOLDER_ID --name NAME --parent PARENT_ID` renames and/or moves a personal non-root folder, including its existing contents. It verifies the destination's ancestry and rejects self/descendant moves, cycles, foreign/submission folders, and same-named destination siblings. A changed ancestry or sibling inventory requires a new preview. `my-folder-delete FOLDER_ID` requires an empty non-root folder, checking both child-folder and file lists. It never sends Canvas's recursive force flag, so the server also rejects newly added content rather than deleting it. Both are preview-first and digest-confirmed. Moving a folder can change inherited access; these controls do not send explicit sharing/lock changes.

`my-file-delete FILE_ID --permanent` previews **irreversible file removal**, not a recoverable trash action. Execution still requires `--yes --confirm DIGEST`; no deletion is sent by default. It only accepts a file in your own accessible non-submission folder, does not expose Canvas's privileged `replace` option, and cannot be combined with edits/copying. Deleting a referenced file can break links. Submitted files may be protected further by Canvas. These new commands have unit and stateful synthetic HTTPS tests only; no live file was created, moved, copied or deleted. [Canvas's file API](https://developerdocs.instructure.com/services/canvas/resources/files) documents these operations and the irreversible deletion behavior.

```sh
canvas-pocket my-root
canvas-pocket my-folders --format brief
canvas-pocket my-folder-create 123 --name 'Study notes'
canvas-pocket my-file-edit 456 --name revised.txt --folder 123
canvas-pocket my-file-copy 456 --folder 123
# Every write is a preview until repeated with --yes --confirm DIGEST.
```

## Planner checkboxes

`planner-override-create TYPE ITEM_ID` previews a completion/dismissal override for one item uniquely identified in your own paginated planner feed. Use the exact `plannable_type`/`plannable_id` from `planner`, and `--start`/`--end` if it falls outside the default window. All ten documented types are supported, including personal notes, calendar events, assignments, discussion topics, announcements, pages and quiz metadata. No question content is fetched and no assessment attempt is started. Existing overrides are not duplicated; the command directs you to edit the existing ID instead. Canvas can normalize quiz/discussion/page assignments to their linked planner object; the returned associated assignment must match before the CLI reports success.

`planner-override ID` reads one override owned by the current user. `planner-override-edit ID` changes only the requested logical checkbox state, preserving the other checkbox in the outgoing body because Canvas resets omitted checkbox parameters to false. Use `--complete`/`--no-complete` and `--dismiss`/`--no-dismiss`; dismissal controls planner opportunities, not access to the underlying work. Every write requires an account-bound preview followed by `--yes --confirm DIGEST`. Changed item/account/current state invalidates confirmation. `planner-override-delete` removes only the override, never its assignment or task, and does not claim to undo previously recorded module progress.

**A planner checkmark is not a submission or grade.** Canvas's [planner implementation](https://github.com/instructure/canvas-lms/blob/master/app/controllers/planner_overrides_controller.rb) can sync module mark-done requirements on creation or editing. Course-content operations therefore require `--allow-module-progress` in both preview and execution. Personal notes/calendar events do not need that acknowledgement. The preview states the effect even when only dismissing an item. These commands have synthetic HTTPS tests only; no live planner or module state was changed during development.

## Privacy and security

- No telemetry, hosted backend, analytics, cookie extraction, or credential export.
- Token stored outside the repo in OS keyring; config stores only the Canvas origin.
- HTTPS only. Pagination is restricted to the configured origin and API path. HTTP redirects are refused so credentials cannot follow them elsewhere.
- Known read-state guards also cover encoded conversation paths, trailing slashes/JSON suffixes and scalar/indexed query shapes; URL credentials and impersonation parameters are refused, including bracketed forms. This is not a guarantee that every undocumented Canvas GET is side-effect-free.
- All Canvas write previews bind the configured origin and signed-in numeric user ID. Switching accounts or sites requires a fresh preview, including for personal uploads. A refreshed token for the same user/site does not expose credentials in the preview.
- 401 prompts reauthentication. 403 means permission/publication restrictions, not automatically bad credentials. 429 is surfaced without aggressive retries.
- API results may contain personal data, classmates' posts, private links or grades. Do not publish your output. `exports/`, environment files, cookies and captures are ignored, but gitignore is not a privacy guarantee.
- `auth logout` removes the local keyring credential; it does not revoke the token on the server.
- No live student records are included in examples or tests. Tests use synthetic data.

## OAuth and browser login

A universal one-click Canvas login is not implemented. Canvas OAuth requires an institution-enabled developer key; do not embed a client secret in an open-source desktop client. A future institution-supported OAuth adapter needs state validation, secure token storage, refresh handling and a suitable registered redirect. The current personal-token flow is for development testing on your own account only.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

Architecture: `client.py` owns transport and pagination; `cli.py` owns command routing, credential setup and write previews; `planning.py` and `discovery.py` derive useful indexes from readable course data. No school-specific logic. Automated tests use synthetic API fixtures and local HTTPS; selected read routes, personal-token login, and read commands have also been tested against a live account. No private fixtures or output are committed. Contributions should include synthetic fixtures only.

Roadmap: richer resource selection and snapshot comparison, incremental Markdown export, institution-approved OAuth, and broader integration tests. No npm/PyPI release yet; install from this repository for development testing.

Sources: [Canvas API](https://developerdocs.instructure.com/services/canvas), [pagination](https://developerdocs.instructure.com/services/canvas/basics/file.pagination), [OAuth](https://developerdocs.instructure.com/services/canvas/oauth2/file.oauth), [discussions](https://developerdocs.instructure.com/services/canvas/resources/discussion_topics).
