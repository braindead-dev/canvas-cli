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
| [Submission](docs/coursework.md#turn-in-work-deliberately) | Previewed text/URL/multi-file submission and comments; assignment-file staging | Upload is not submission; final permission/group acceptance stays native |
| [Content](docs/content.md) | Visible course/group pages, files, folders, navigation, search, access diagnostics; RCE history and previewed shared create/edit/restore/delete/duplicate/schedule with native permissions, exact IDs and separate readback | Course RCE scheduling verifies an enabled root feature and stored draft/date, not future jobs; duplication verifies assignment lineage/differences; deletion acknowledges cascades; wiki writes are not atomic; block authoring and group/linked scheduling remain open |
| [Local snapshots](docs/content.md#private-snapshots) | Private capture, account-separated sync, offline diff/search/Markdown | No legacy automatic merge; incremental resource sync remains open |
| [Files and exports](docs/content.md) | Private downloads, bounded batch downloads, scoped uploads, own-file/folder organization, asynchronous exports | No recursive deletion/rich sharing changes; exports and uploads can be role-restricted |
| [Communication](docs/communication.md) | Inbox read/compose/reply/own organization, discussions/replies/own edits, likes/subscriptions/read markers; ungraded prompt creation/text edits/soft deletion, publication/close/open/pin controls, pinned ordering, course opening/closing dates and reply/like/default-view settings with independent readback | No bulk/group compose attachments, graded/anonymous/announcement/root-child prompt authoring, group/linked dates, podcasts/audience configuration or initial-post bypass; stripped settings fail verification; dates can publish/reopen, future jobs unverified; pinned ordering needs moderation |
| [Activity and peer reviews](docs/communication.md) | Own activity/announcement feeds and dismissal; authorized received/visible reviews | Not a complete owed-review inventory; review allocation/completion/grading excluded |
| [Planning](docs/planning.md) | Own notes/events, calendar/planner feeds, checkbox overrides, Scheduler discovery and verified individual/team reservation changes | Team changes affect all members; checkboxes do not submit/grade; appointment administration and series mutations remain open |
| [Account settings](docs/account.md) | Whitelisted profile with verified edits, favorites, aliases, colors, interface/dashboard settings, exact-key notification preferences, verified own contact creation/retirement | Defaults can have native GET effects; contacts need native confirmation; push registration needs provider/developer-key configuration |
| [Groups and enrollment](docs/account.md) | Scoped rosters/permission/group-set reads, own community joins/leaves and pending invitation responses | Not university registration; project switches/moderation/admin allocation excluded |
| [Authentication](docs/getting-started.md) | Own personal-token testing, secure OS keyring or process environment | Multiuser OAuth needs institution-enabled developer key; no cookie scraping |
| Quiz engines | Classic/New Quiz metadata | No questions, attempts, or automated exam-taking |
| External/admin systems | Links only | Zoom/LTI/publishers need separate auth; account administration/SIS not implemented |

## Design contract

One API transport/paginator, separate credential-free binary transport, metadata-first where appropriate, explicit account/scope/access checks, preview-bound writes, no automatic ambiguous-write retry, and synthetic public fixtures only.

Help/schema derive syntax from the parser; the schema is not a standard JSON Schema or authorization contract. Native GET effects are explicitly classified. See [safety](docs/safety.md) and [architecture](docs/development.md#architecture).

## Validation and next work

Unit tests, subprocess/local HTTPS, and fresh-wheel CI are the repeatable baseline. Selected historical reads were checked live; **real writes have not been live-tested**. [Validation details](docs/development.md#validation) retain that distinction.

Next work is useful student workflows, efficient incremental sync, richer offline projection, and institution-approved OAuth, not unrestricted generic writes.
