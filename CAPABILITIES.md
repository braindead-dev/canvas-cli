# Capabilities

Developer preview for the owner's account. Coverage follows the [native Canvas APIs](https://developerdocs.instructure.com/services/canvas), not every browser action. Role, scopes, publication, and institution settings determine access.

Exact commands/options and safety classifications are available offline:

```sh
canvas-cli help --format brief
canvas-cli capabilities
canvas-cli schema --search upload
```

## Coverage

| Area | Implemented | Boundary / next work |
| --- | --- | --- |
| [Coursework](docs/coursework.md) | Assignment/deadline/own-status views, missing work, grades, feedback/rubrics, module progress | Feeds are not complete coursework/owed-review inventories; unknown stays unknown |
| [Submission](docs/coursework.md#turn-in-work-deliberately) | Previewed text/URL/multi-file submission and comments; assignment-file staging | Upload is not submission; final permission/group acceptance stays native |
| [Content](docs/content.md) | Visible course/group pages, files, folders, navigation, search, access diagnostics | Permission-denied module/linked-file fallbacks remain explicitly partial |
| [Local snapshots](docs/content.md#private-snapshots) | Private capture, account-separated sync, offline diff/search/Markdown | No legacy automatic merge; incremental resource sync remains open |
| [Files and exports](docs/content.md) | Private downloads, bounded batch downloads, scoped uploads, own-file/folder organization, asynchronous exports | No recursive deletion/rich sharing changes; exports and uploads can be role-restricted |
| [Communication](docs/communication.md) | Inbox read/compose/reply/own organization, discussions/replies/own edits, likes/subscriptions/read markers | No bulk/group compose attachments, topic administration, or initial-post bypass |
| [Activity and peer reviews](docs/communication.md) | Own activity/announcement feeds and dismissal; authorized received/visible reviews | Not a complete owed-review inventory; review allocation/completion/grading excluded |
| [Planning](docs/planning.md) | Own notes/events, calendar/planner feeds, previewed checkbox overrides | Checkboxes can affect module progress but do not submit/grade; no appointments/series mutations |
| [Account settings](docs/account.md) | Whitelisted profile with verified edits, favorites, aliases, colors, interface/dashboard settings, exact-key notification preferences | Defaults can have native GET effects; shared profile text needs acknowledgement |
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
