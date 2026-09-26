# Capability map

This is a roadmap, not a claim that all browser actions are implemented. The [official Canvas API index](https://developerdocs.instructure.com/services/canvas) is the source of truth. Availability depends on role, token scopes, institution configuration and course publication. External LTI tools may expose entirely separate APIs.

| Area | Current interface | Next implementation / constraint |
| --- | --- | --- |
| Identity and auth | login/status/logout, me; local keyring or environment | Institutional OAuth requires enabled developer key; no cookie scraping |
| Courses | courses, courses --active, favorites, syllabus, tabs, front-page, sections, content-free doctor probe, multi-area title finder | External-tool tabs are paths only; finder only searches visible titles/names, module-page fallback is partial, and doctor reports reachability, not publication completeness |
| Assignments | assignments, assignment, assignment-groups, assignment-group, deadlines, work (own status and effective due date) | Richer planner views and local reminders |
| Modules | modules, module-items, outline with separately paginated items | Richer progress summaries |
| Pages | pages, page, `pages --best-effort` module fallback with explicit partial coverage, offline snapshot-markdown projection | Incremental snapshots; pages outside modules remain undiscoverable when Canvas denies the list |
| Files | files, `files --best-effort` explicit linked-content fallback, my-files (optional filename search), file-info, folders, folder-files, folder-folders, linked-files across course content and instructor topics (optional all published pages), download, preview-first download-linked | Course Files list may be disabled while linked files remain accessible; discovered links are not a complete inventory |
| Announcements | announcements, cross-course news | Incremental change detection; creation would be a write |
| Discussions | discussions, topic, full visible thread with paginated replies, entries, replies, post (preview + matching digest) | Topic creation/edit/delete needs preview and explicit confirmation; post-first and locked topics are not bypassed |
| Personal tasks | todo, upcoming, overview | Planner/calendar filters and reminders; overview also derives deadlines from assignments |
| Calendar and planner | calendar with date/type/context filters, advanced get | Mutations separately guarded; context limit is explicit |
| Grades and submissions | grades (own enrollment only), submission (own assignment + feedback), submit-url/submit-text/submit-file (preview + matching digest), upload-assignment-file (file stage only), advanced get where authorized | Live write validation only in a designated sandbox; multi-file submission |
| Rubrics and feedback | rubrics, rubric, submission, advanced get where authorized | Summaries and submission comments |
| Inbox | inbox, conversation (explicit no-read-state-change), recipients, inbox-reply and one-person inbox-compose (preview + matching digest required), advanced get with transport guard | Group/bulk composition; live write validation only in a designated sandbox |
| Groups, sections, enrollments | groups, group, course-groups, sections, own grades | Roster views only where authorized; no administrative privileges assumed |
| Quizzes / New Quizzes | Classic quizzes/quiz and New Quizzes new-quizzes/new-quiz metadata only | No question/attempt operations or automated exam-taking |
| Uploads | Personal and assignment-file three-step uploads, preview + file hash + matching digest; separate credential-free storage transport | Live write validation only in a designated sandbox; larger files and richer destinations |
| Local course snapshots | snapshot, one-command private sync, offline snapshot-diff, snapshot-search and snapshot-markdown; explicit incomplete state | Efficient per-resource incremental sync and richer Markdown projection |
| Canvas course exports | Not implemented | Separate asynchronous jobs and polling; role-dependent |
| Account administration / SIS | Not implemented | Separate high-risk/admin surface, not student defaults |
| Video, Zoom, publisher tools | Links only | Separate providers/auth; not covered by Canvas credentials |

## Design rules

One HTTPS API client, one pagination implementation, separate binary-download transport with no bearer header. Commands return JSON and errors go to stderr. Reads and writes must remain visibly distinct. New write verbs need an exact preview and explicit execution flag, no retry on ambiguous completion. No telemetry or private fixtures.

The generic `get` command is an expert escape hatch for documented read endpoints, not a promise of harmlessness for arbitrary third-party endpoints. It accepts only the configured Canvas origin's `/api/v1/` paths and refuses credential/impersonation query parameters. Do not use it to evade course restrictions.

## Validation ladder

1. Unit tests for routing, auth boundaries, pagination and output safety.
2. Subprocess E2E tests against a real local HTTPS fixture with synthetic records.
3. CI on supported Python versions.
4. Opt-in live read-only smoke tests after user authentication.
5. Write integration tests only against an explicitly designated sandbox course.

Current live-test gap: write actions have not been exercised against a real account. Personal-token login, calendar, own grades, folders, sections, outline, linked-file discovery, local snapshots and repeated `sync` runs, selected other read commands, one temporary file download and a URL submission preview have been tested against a live account, but synthetic E2E tests remain the repeatable regression suite. In a live course, the token received 404 for the pages list; both snapshot fallback and `pages --best-effort` recovered 27 readable module pages while reporting incomplete coverage. A live page-title search used the same partial fallback. Manual personal tokens are for testing the owner's account only; multiuser release requires institution-approved OAuth.

In one live course, assignment groups were visible, while rubric listing and New Quizzes listing returned 403 and Classic Quiz listing returned 404. Those results reflect this account/course configuration, not a claim that these resources are globally unavailable. The full-thread reader has synthetic HTTPS coverage, but the available live courses did not expose an unlocked discussion to test it against; a locked announcement was correctly refused.
