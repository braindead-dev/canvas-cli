# Canvas Pocket

A privacy-conscious CLI for Canvas LMS. Read coursework, keep private local snapshots, and preview changes before making them. JSON by default, OS-keyring credentials, no telemetry.

Unofficial and not affiliated with Instructure. **Developer preview for your own account**, not a multiuser release.

## Quick start

Requires Python 3.10+, [pipx](https://pipx.pypa.io/), and a supported OS keyring.

```sh
pipx install git+https://github.com/braindead-dev/canvas-pocket.git
canvas-pocket auth login --origin https://canvas.example.edu
canvas-pocket courses --active --format brief
canvas-pocket agenda --days 14 --format brief
```

Login asks for a personal Canvas token without echoing it. No passwords or browser cookies are collected. Your institution must allow token creation; apps for other users require institution-approved OAuth. See [setup and authentication](docs/getting-started.md).

## Common workflows

```sh
canvas-pocket work --course 123
canvas-pocket feedback 123 --format brief
canvas-pocket linked-files 123
canvas-pocket sync 123
canvas-pocket help --search discussion --format brief
canvas-pocket help submit-file --format brief
```

Canvas writes default to a preview. To execute, review that preview and repeat the same command with `--yes --confirm DIGEST`. Account, target, content, or relevant state changes require a fresh preview. Writes are never retried automatically.

## Documentation

| Guide | What it covers |
| --- | --- |
| [Coursework](docs/coursework.md) | Deadlines, submissions, grades, feedback, modules, quiz metadata |
| [Content and files](docs/content.md) | Course/group content, downloads, uploads, private snapshots, exports |
| [Communication](docs/communication.md) | Inbox, discussions, peer reviews, activity |
| [Account and access](docs/account.md) | Profile, preferences, notifications, rosters, groups, invitations |
| [Planning](docs/planning.md) | Personal tasks, calendar events, planner checkboxes |
| [Safety](docs/safety.md) | Privacy, confirmation, transport boundaries, recovery |
| [Development](docs/development.md) | Architecture, tests, contribution rules, validation limits |
| [Capabilities](CAPABILITIES.md) | Coverage and remaining work |

Exact options live in `canvas-pocket help COMMAND --format brief`; scripts can inspect `canvas-pocket schema COMMAND` offline. The schema describes syntax, not permission to execute.

## Boundaries

Course access depends on Canvas permissions and publication. Empty or partial feeds do not prove all work is done. Canvas membership is not university registration. Quiz questions/attempts, grading, administrative enrollment, and external tools are not automated.

Outputs can contain private academic data or copyrighted material. Keep them out of public Git repositories. New behavior is tested with synthetic local HTTPS fixtures; [live validation is narrower](docs/development.md#validation).
