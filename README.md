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

```sh
canvas-pocket courses
canvas-pocket courses --active
canvas-pocket doctor 123
canvas-pocket find 123 --query 'paper'
canvas-pocket find 123 --query 'lab' --area assignments
canvas-pocket favorites
canvas-pocket groups
canvas-pocket course-groups 123
canvas-pocket my-files --search 'paper'
canvas-pocket file-info 789
canvas-pocket inbox --scope unread --course 123
canvas-pocket conversation 456
canvas-pocket recipients --search 'Example Name' --course 123
canvas-pocket recipients --user-id 789
canvas-pocket inbox-compose --recipient 789 --subject 'Question' --message-file message.txt
canvas-pocket inbox-reply 456 --message-file reply.txt
canvas-pocket overview
canvas-pocket --format brief overview
canvas-pocket deadlines --days 30
canvas-pocket work --days 30
canvas-pocket --format brief work --course 123 --status unsubmitted
canvas-pocket --format brief news --days 30
canvas-pocket news --course 123 --course 456
canvas-pocket linked-files 123
canvas-pocket linked-files 123 --quick
canvas-pocket upcoming
canvas-pocket calendar --start 2026-09-25 --end 2026-10-09 --active --personal
canvas-pocket calendar --type assignment --course 123
canvas-pocket assignments 123
canvas-pocket assignment-groups 123
canvas-pocket rubrics 123
canvas-pocket quizzes 123
canvas-pocket quiz 123 456
canvas-pocket new-quizzes 123
canvas-pocket new-quiz 123 456  # 456 is the assignment ID for a New Quiz
canvas-pocket submission 123 456
canvas-pocket submit-url 123 456 --url-file project-url.txt
canvas-pocket submit-text 123 456 --text-file response.txt
canvas-pocket upload-personal --file ./notes.pdf
canvas-pocket upload-assignment-file 123 456 --file ./paper.pdf
canvas-pocket submit-file 123 456 789  # 789 is the resulting uploaded file ID
canvas-pocket grades 123
canvas-pocket syllabus 123
canvas-pocket tabs 123
canvas-pocket front-page 123
canvas-pocket modules 123
canvas-pocket outline 123
canvas-pocket pages 123
canvas-pocket pages 123 --best-effort
canvas-pocket files 123
canvas-pocket folders 123
canvas-pocket folder 456
canvas-pocket folder-files 456
canvas-pocket folder-folders 456
canvas-pocket sections 123
canvas-pocket announcements 123
canvas-pocket discussions 123
canvas-pocket topic 123 456
canvas-pocket entries 123 456
canvas-pocket replies 123 456 789
canvas-pocket assignment 123 456
canvas-pocket page 123 introduction
canvas-pocket module-items 123 456
canvas-pocket todo
canvas-pocket download 123 456 --output ./syllabus.pdf
canvas-pocket capabilities
canvas-pocket get '/api/v1/courses/123/tabs' --paginate
canvas-pocket --max-pages 200 assignments 123
canvas-pocket linked-files 123 --all-pages --quick
canvas-pocket download-linked 123 --directory /private/path/course-files
# Review the preview, then repeat with --yes and suitable limits.
canvas-pocket download-linked 123 --directory /private/path/course-files --max-files 100 --yes
canvas-pocket snapshot 123 --output /private/path/course-123.json
canvas-pocket sync 123  # private baseline, then field-level changes on later runs
canvas-pocket sync 123 --directory /private/path/snapshots
canvas-pocket snapshot-diff /private/path/older.json /private/path/newer.json
canvas-pocket snapshot-search /private/path/course-123.json --query 'research paper'
canvas-pocket snapshot-markdown /private/path/course-123.json --output /private/path/course-123.md
```

List commands follow Canvas Link pagination, including empty pages. A page limit fails explicitly, never silently truncates. JSON is the complete output; `--format brief` gives a compact human index. `overview` adds deadlines derived from active course assignments because Canvas's upcoming feed may be empty. `deadlines` lists due dates over a chosen window and reports courses whose assignments could not be read. `work` lists assignments with the current user's Canvas submission status and effective due date (including individual overrides). It shows all dated and undated work by default, or only upcoming dated work with `--days`; missing submission data is labeled `unknown`, never assumed unsubmitted. It reports unavailable courses without hiding other results. [Canvas documents `include[]=submission` for the current user](https://developerdocs.instructure.com/services/canvas/resources/assignments). `calendar` defaults to your personal calendar; use `--active` or repeated `--course` for course calendars, and `--personal` to include your own calendar alongside them. The [Canvas calendar API](https://developerdocs.instructure.com/services/canvas/resources/calendar_events) allows at most ten contexts, so the CLI fails instead of silently dropping extras. `grades` requests the signed-in user's numeric ID and rejects any enrollment returned for another user or course. It reports only grades Canvas makes visible. `submission` reads only your own status, grade, comments and rubric feedback; it issues no submission or read-status mutation. `outline` fetches each module's items separately because Canvas may omit them from the module listing. Use `page` for a page body and `module-items` for paginated module contents. `folders` lists a course's flat folder inventory; `folder-files` and `folder-folders` browse one folder. These may be unavailable when the course Files tab is disabled.

`pages COURSE` retains the raw Canvas list response. Some courses return 403/404 for that list even while individual module pages are readable. `pages COURSE --best-effort` returns an explicit coverage envelope: it uses the normal page list if available, otherwise fetches only readable pages linked from visible modules. A fallback result is always marked incomplete, because pages outside modules may exist. It does not return page bodies. `page COURSE SLUG` reads one known accessible page.

`tabs COURSE` lists visible course navigation labels and Canvas paths, including external-tool tabs, without launching those tools. `front-page COURSE` reads the published course home page where Canvas provides one. External tools such as Zoom or Piazza need their own authorization and are not controlled through these commands.

`linked-files` discovers links in readable syllabus, modules, module pages, and assignments, useful when a course's Files tab is hidden; it is not a complete inventory and reports when a linked file is hidden or locked for the user. `--all-pages` adds accessible published pages outside modules. `--quick` skips per-file metadata requests, so availability is unknown, but is substantially faster for courses with many files. Requests remain sequential to avoid Canvas's [parallel-request throttling penalty](https://developerdocs.instructure.com/services/canvas/basics/file.throttling). Downloads use an explicit output path, refuse overwrites, remove failed partial files, default to a 100 MiB limit and never send the API token to file storage. Signed download URLs are not logged. `syllabus` returns the course's syllabus body, not all linked documents. `me` returns your private profile; `auth status` only reports authentication validity.

`snapshot` reads the syllabus-bearing course record, assignments, module items, accessible published pages, and announcements into one local JSON file. It makes no quiz attempts or writes to Canvas. If an endpoint is unavailable, the snapshot says `complete: false` and records the missing resource. When the pages list is unavailable, it tries readable page links from modules but still marks the snapshot incomplete. It removes token-shaped JSON fields such as Canvas `secure_params` and credential-like URL query parameters before saving. The file is mode `0600`, cannot overwrite an existing file, and cannot be placed inside a Git checkout, including through a symlinked parent. It may still contain copyrighted course materials, private academic information or other expiring links; keep it local and do not post it to a public repo.

`sync COURSE` does the private capture-and-diff cycle in one read-only Canvas command. It defaults to a private snapshots directory under the app config folder, or accepts `--directory`. The first run creates a baseline; later runs compare with the latest same-origin/course snapshot and return field names and visible titles, never full bodies. Raw snapshots are immutable mode-`0600` files outside Git and accumulate until you remove ones you no longer need. A failed capture or comparison does not overwrite the previous snapshot.

`snapshot-diff` works offline and reports added/removed resources and which fields changed, without printing full assignment descriptions or page bodies. It skips full inventories for categories incomplete in either snapshot, avoiding false “removed” claims. For pages already observed in both partial snapshots, it separately reports changed fields under `observed_changes` without claiming that no other pages exist. It does not need a Canvas credential.

`snapshot-search` works offline over that same private JSON. It searches syllabus, assignment descriptions, announcements, pages and module titles, returning short plain-text snippets and ranking title matches first. It reports when the source snapshot was incomplete; no hits never proves the course contains no such material. Its output can contain private course information, so do not paste it into public issues or logs.

`snapshot-markdown` also works offline. It turns a snapshot into one readable Markdown file with syllabus, assignments, announcements, modules and pages. It converts Canvas HTML to plain text rather than embedding active HTML or external images, marks incomplete snapshots, and includes only safe same-origin Canvas assignment links. Like raw snapshots, the output is mode `0600`, never overwrites and cannot be written inside a Git checkout. Review it before sharing; course content may be copyrighted or private. This is a readable projection, not a lossless Canvas backup.

`inbox` lists your Canvas conversations; `conversation` fetches one with `auto_mark_as_read=false`. The [Canvas Conversations API](https://developerdocs.instructure.com/services/canvas/resources/conversations) otherwise marks an unread thread read by default on a GET. The transport blocks that unsafe GET even through the expert `get` command unless the query explicitly sets `auto_mark_as_read=false`. It also blocks `include[]=read_status` on GET, since the [Submissions API](https://developerdocs.instructure.com/services/canvas/resources/submissions) says including it marks submissions read. These commands do not send or intentionally alter read state; other undocumented server-side effects remain outside this guarantee. `inbox-reply` previews the current participants and exact message and also uses the safe GET. It only sends with both `--yes` and a matching `--confirm` digest from that preview, and refuses to send if the message or thread audience changes between preview and execution. This send route has synthetic TLS tests but has not been exercised against a live account. `groups` returns only your active groups; `course-groups` returns only groups visible to your Canvas role.

`recipients` searches Canvas's [messageable-user directory](https://developerdocs.instructure.com/services/canvas/resources/search) or confirms one numeric user ID. Text search can be limited to a course; Canvas ignores course context in an ID lookup, so the CLI refuses that misleading combination. `inbox-compose` addresses exactly one verified individual, previews their identity and exact subject/body, then requires `--yes` and a matching digest to send. Canvas may reuse an existing private thread with that recipient. The lookup and preview were live-tested without sending; actual sends have synthetic TLS tests only. Do not use a course or group ID as a recipient.

`news` lists recently posted announcements across active or selected courses using Canvas's dedicated [Announcements API](https://developerdocs.instructure.com/services/canvas/resources/announcements). It fetches each course separately so one inaccessible course does not hide all the others, and reports any unavailable course. JSON includes the full visible announcement body; brief output is a title/date index. The date window is based on posting time, not subsequent edits, so older edited announcements need a longer `--days` window.

`assignment-groups` shows Canvas's group weights and grading rules. `rubrics`/`rubric` read visible criteria. `quizzes`/`quiz` read metadata for Classic Quizzes, including dates, attempt limits and time limits. `new-quizzes`/`new-quiz` read metadata from Canvas's separate [New Quizzes API](https://developerdocs.instructure.com/services/canvas/resources/new_quizzes); the single-item command takes its associated assignment ID. These commands never list quiz questions or create an attempt. Availability depends on Canvas permissions and which quiz engine a course uses.

`download-linked` previews a batch of downloadable files referenced by readable content, then writes only with `--yes`. It requires an existing destination outside Git, refuses filename collisions, limits file count and total bytes, and sanitizes server filenames. Hidden or locked files are skipped. Successful earlier files remain if a later download fails, and the error reports that partial batch progress. It never sends the Canvas API token to storage URLs. It does not promise a complete course file inventory or access beyond your account's permissions.

`upload-personal` and `upload-assignment-file` follow [Canvas's three-step upload protocol](https://developerdocs.instructure.com/services/canvas/basics/file.file_uploads). They preview the source path, size, SHA-256 hash and destination, then require `--yes --confirm DIGEST`. Personal uploads request rename-on-duplicate because Canvas otherwise overwrites a same-named file. Assignment uploads check that the current assignment permits file submissions and any listed extension, but **do not submit the assignment**. The CLI sends your token only to Canvas for initiation and confirmation; its separate storage request has no token, cookies or redirects. A failed/ambiguous upload is not retried automatically. Default maximum file size is 25 MiB; use `--max-bytes` deliberately if needed. These writes have synthetic HTTPS tests but no live-upload validation. Do not assume a successful upload means your work was turned in. To turn it in, separately preview `submit-file COURSE ASSIGNMENT FILE_ID` and confirm its digest. [Canvas documents this distinct file-ID submission step](https://developerdocs.instructure.com/services/canvas/resources/submissions).

`my-files` and `file-info` use the [Files API](https://developerdocs.instructure.com/services/canvas/resources/files) to locate and verify an accessible uploaded file ID. `my-files --search` filters by partial filename and follows pagination; `file-info` requires an exact numeric ID. These are read-only and may show personal filenames in terminal output.

`doctor COURSE` makes small, sequential GET requests to a visible course's major read APIs and reports only reachability states, not course content. A 403 or 404 may reflect role, publication, or institution configuration, and a readable endpoint does not guarantee every item is visible. It stops probing on a rate limit. This is a diagnostic map, not a way around access controls.

`find COURSE --query TEXT` searches visible titles/names through the documented assignment, discussion, page, file and module filters. It returns IDs, titles and due dates, not bodies, and reports endpoints that were restricted or not found. Use `--area` to search one area faster. If Canvas denies the pages search, it searches readable pages linked from visible modules and labels page coverage incomplete; it does not claim to have searched pages outside modules. Canvas can omit module items from a module response; the result flags that incomplete coverage rather than claiming there were no matches. For body-text searches, first create a private snapshot and use `snapshot-search` offline.

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
```

Discussion-post and text-entry submission inputs are plain UTF-8 text, safely escaped to HTML. Discussion posts also re-check the topic ID, title and lock state before a separately confirmed send. Inbox replies use the plain UTF-8 body specified by the Canvas API. URL submissions read one absolute HTTP(S) URL from a file, keeping private URLs out of shell history. Assignment submission previews check the current assignment ID, publication/lock state and allowed type, then require `--yes` with a matching digest from the preview. These commands can publish real content under your account. Follow your course rules and review the destination and content. Writes are never retried automatically; after a timeout verify Canvas before retrying. The guarded send routes have synthetic TLS end-to-end tests; URL preview was tested against a live assignment, but no live submission was made. The CLI does not take quizzes, change grades, or bypass initial-post restrictions.

## Privacy and security

- No telemetry, hosted backend, analytics, cookie extraction, or credential export.
- Token stored outside the repo in OS keyring; config stores only the Canvas origin.
- HTTPS only. Pagination is restricted to the configured origin and API path. HTTP redirects are refused so credentials cannot follow them elsewhere.
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
