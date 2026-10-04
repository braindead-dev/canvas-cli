# Capabilities

Developer preview for the owner's account. Coverage follows the [native Canvas APIs](https://developerdocs.instructure.com/services/canvas), not every browser action. Role, scopes, publication, and institution settings determine access.

Exact commands/options and safety classifications are available offline:

```sh
canvas help --format brief
canvas capabilities
canvas schema --search upload
```

## Coverage

| Area | Implemented | Boundary / next work |
| --- | --- | --- |
| [Coursework](docs/coursework.md) | Assignment/deadline/own-status views, missing work, grades, feedback/rubrics, module progress, scoped item inspection and native previous/next sequences; preview-first own done/not-done/read events and mastery selection/switching with separate choice readback | Sequence is capped at ten occurrences; mastery effects can be asynchronous, availability/dates remain unverified; feeds are not complete coursework/owed-review inventories; reads do not simulate submissions/scores; planner/downstream effects stay unverified |
| [Submission](docs/coursework.md#turn-in-work-deliberately) | Previewed text/URL/multi-file submission and comments; assignment-file staging; separate [native own draft](docs/submission-drafts.md) read/save across six types and all-attempt deletion; [own comment drafts](docs/submission-comments.md) with per-attempt pagination, create/edit/publish/delete and own readback | Draft/upload is not submission; next-attempt getter is not historical inventory; raw storage, hidden group copies, notifications and historical draft deletion remain unverified; published student comments need separate grading rights |
| [Feedback attention](docs/submission-attention.md) | Exact own aggregate indicator and optional annotation/rubric-feedback preferences; paginated visible published comment metadata and one-comment acknowledgement; preview-first mutations with independent effective-state/preference readback | Overall marking targets the native default grade item, not every unread item; aggregate read can mask viewed-comment storage; participation-item storage and collateral viewed effects remain unverified; indicators do not prove viewing or coursework completion |
| [What-If scores](docs/what-if.md) | Exact own hypothetical point-score inspection; preview-first save/clear with native recalculation and separate saved-score readback; optional whitelisted native forecast totals | Not official grades or promised future results; calculation can fail after saving; no course-wide reset or automatic scenario polling |
| [Content](docs/content.md) | Visible course/group pages, files, folders, navigation, search, access diagnostics; RCE history and previewed shared create/edit/restore/delete/duplicate/schedule with native permissions, exact IDs and separate readback | Course RCE scheduling verifies an enabled root feature and stored draft/date, not future jobs; duplication verifies assignment lineage/differences; deletion acknowledges cascades; wiki writes are not atomic; block authoring and group/linked scheduling remain open |
| [Local snapshots](docs/content.md#private-snapshots) | Private capture, account-separated sync, offline diff/search/Markdown | No legacy automatic merge; incremental resource sync remains open |
| [Files and exports](docs/content.md) | Private downloads, bounded batch downloads, scoped uploads, own-file/folder organization, asynchronous exports | No recursive deletion/rich sharing changes; exports and uploads can be role-restricted |
| [Communication](docs/communication.md) | Inbox workflows; discussion replies/own edits, likes/subscriptions/markers; shared ungraded prompt authoring/copy/state/settings, pinned ordering, course availability/section filtering and course/group student to-do dates | Copies are not full backups. Graded/anonymous/announcement/root-child authoring, group/linked availability, podcasts, modern participant overrides and bulk attachments remain open. Section filtering is not all-participant visibility proof. Readback does not prove future jobs, planner effects or completion |
| [Activity and peer reviews](docs/communication.md) | Own activity/announcement feeds and dismissal; authorized received/visible reviews | Not a complete owed-review inventory; review allocation/completion/grading excluded |
| [Personal discussion views](docs/discussion-view.md) | Native own sort/expansion/pinned-entry/language/summary settings and separately acknowledged pinned-unread indicator; runtime language catalog, expansion inheritance and language clearing; account/context/state-bound preview and independent readback | Queries may initialize own participant/default state. Hidden sort/expansion and cleared-language storage stay unverified. No content-read proof, invalid null resets, translation/summary generation or service-access guarantee; no peer content or assessment requests |
| [Planning](docs/planning.md) | Own notes/events, calendar/planner feeds, checkbox overrides, Scheduler discovery and verified individual/team reservation changes | Team changes affect all members; checkboxes do not submit/grade; appointment administration and series mutations remain open |
| [Account settings](docs/account.md) | Whitelisted profile with verified edits, favorites, aliases, colors, interface/dashboard settings, exact-key notification preferences, verified own contact creation/retirement | Defaults can have native GET effects; contacts need native confirmation; push registration needs provider/developer-key configuration |
| [Groups and enrollment](docs/account.md) | Scoped rosters/permission/group-set reads, own community joins/leaves and pending invitation responses | Not university registration; project switches/moderation/admin allocation excluded |
| [Authentication](docs/getting-started.md) | Own personal-token testing, secure OS keyring or process environment | Multiuser OAuth needs institution-enabled developer key; no cookie scraping |
| Quiz engines | Classic/New Quiz metadata | No questions, attempts, or automated exam-taking |
| External/admin systems | Links only | Zoom/LTI/publishers need separate auth; account administration/SIS not implemented |

## Design contract

One API transport/paginator, separate credential-free binary transport, metadata-first where appropriate, explicit account/scope/access checks, preview-bound writes, no automatic ambiguous-write retry, and synthetic public fixtures only.

Help/schema derive syntax from the parser; the schema is not a standard JSON Schema or authorization contract. Native GET/GraphQL query effects are explicitly classified. See [safety](docs/safety.md) and [architecture](docs/development.md#architecture).

## Validation and next work

Unit tests, subprocess/local HTTPS, and fresh-wheel CI are the repeatable baseline. Selected historical reads were checked live; **real writes have not been live-tested**. [Validation details](docs/development.md#validation) retain that distinction.

Next work is useful student workflows, efficient incremental sync, richer offline projection, and institution-approved OAuth, not unrestricted generic writes.
