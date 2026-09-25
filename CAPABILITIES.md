# Capability map

This is a roadmap, not a claim that all browser actions are implemented. The [official Canvas API index](https://developerdocs.instructure.com/services/canvas) is the source of truth. Availability depends on role, token scopes, institution configuration and course publication. External LTI tools may expose entirely separate APIs.

| Area | Current interface | Next implementation / constraint |
| --- | --- | --- |
| Identity and auth | login/status/logout, me; local keyring or environment | Institutional OAuth requires enabled developer key; no cookie scraping |
| Courses | courses, courses --active, syllabus | Favorites, name lookup |
| Assignments | assignments, assignment, deadlines | Date overrides and richer submission status |
| Modules | modules, module-items | Nested course outline with locked-state labels |
| Pages | pages, page | Markdown rendering and incremental snapshots |
| Files | files, linked-files, download | Folder traversal, selection and batch manifest; no overwrites; course Files list may be disabled while linked files remain accessible |
| Announcements | announcements | Incremental updates; creation would be a write |
| Discussions | discussions, entries, replies, post | Topic creation/edit/delete needs preview and explicit confirmation |
| Personal tasks | todo, upcoming, overview | Planner/calendar filters and reminders; overview also derives deadlines from assignments |
| Calendar and planner | advanced get with documented API path | First-class commands; mutations separately guarded |
| Grades and submissions | submission (own assignment + feedback), advanced get where authorized | Aggregate student views and upload/submit workflow with destination review |
| Rubrics and feedback | advanced get where authorized | Summaries and submission comments |
| Inbox | advanced get where authorized | Conversation commands; send/reply with previews |
| Groups, sections, enrollments | advanced get where authorized | First-class discovery, no administrative privileges assumed |
| Quizzes / New Quizzes | Not a first-class workflow | Different APIs and permissions; no automated exam-taking |
| Uploads | Not implemented | Multi-step upload handshake; separate credential-free storage transport |
| Course exports | Not implemented | Asynchronous jobs and polling; role-dependent |
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

Current live-test gap: write actions have not been exercised against a real account. Personal-token login, selected read commands and one temporary file download have been tested against a live account, but synthetic E2E tests remain the repeatable regression suite. Manual personal tokens are for testing the owner's account only; multiuser release requires institution-approved OAuth.
