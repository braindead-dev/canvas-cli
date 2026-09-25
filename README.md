# Canvas Pocket

A small Canvas LMS CLI for students and scripts. JSON in your terminal, credentials in your OS keyring, no telemetry. Unofficial and not affiliated with Instructure.

## Install

Requires Python 3.10+ and an available OS keyring.

```sh
pipx install git+https://github.com/braindead-dev/canvas-pocket.git
canvas-pocket auth login --origin https://canvas.example.edu
canvas-pocket auth status
canvas-pocket courses
```

Login prompts for a personal access token without echoing it. Create one in Canvas Account → Settings → Approved Integrations, if your institution permits it. Prefer an expiration date and revoke unused tokens. No passwords or browser cookies are collected. macOS Keychain, Windows Credential Locker, Secret Service and KWallet backends are supported; unsupported backends fail closed. Linux may require selecting its secure keyring backend explicitly.

For ephemeral/headless use, supply `CANVAS_ORIGIN` and `CANVAS_TOKEN` through a secret manager/environment. Do not put tokens in command arguments, shell history, source control, or bug reports.

## Commands

```sh
canvas-pocket courses
canvas-pocket assignments 123
canvas-pocket syllabus 123
canvas-pocket modules 123
canvas-pocket pages 123
canvas-pocket files 123
canvas-pocket announcements 123
canvas-pocket discussions 123
canvas-pocket entries 123 456
canvas-pocket replies 123 456 789
canvas-pocket --max-pages 200 assignments 123
```

List commands follow Canvas Link pagination, including empty pages. A page limit fails explicitly, never silently truncates. Pages/files/modules currently list metadata; they do not recursively download attachments or nested module items. `syllabus` returns the course's syllabus body, not all linked documents. `me` returns your private profile; `auth status` only reports authentication validity.

### Posting deliberately

```sh
canvas-pocket post 123 456 --message-file reply.txt
# Review the JSON preview. Nothing was posted.
canvas-pocket post 123 456 --message-file reply.txt --yes
# Add --reply-to 789 for a reply to an entry.
```

Input is plain UTF-8 text, safely escaped to HTML. This can publish real coursework under your account. Follow your course rules and review the recipient/topic and content. Writes are never retried automatically; after a timeout verify Canvas before retrying. The CLI does not take quizzes, submit assignments, change grades, or bypass initial-post restrictions.

## Privacy and security

- No telemetry, hosted backend, analytics, cookie extraction, or credential export.
- Token stored outside the repo in OS keyring; config stores only the Canvas origin.
- HTTPS only. Pagination is restricted to the configured origin and API path. HTTP redirects are refused so credentials cannot follow them elsewhere.
- 401 prompts reauthentication. 403 means permission/publication restrictions, not automatically bad credentials. 429 is surfaced without aggressive retries.
- API results may contain personal data, classmates' posts, private links or grades. Do not publish your output. `exports/`, environment files, cookies and captures are ignored, but gitignore is not a privacy guarantee.
- `auth logout` removes the local keyring credential; it does not revoke the token on the server.
- No live student records are included in examples or tests. Tests use synthetic data.

## OAuth and browser login

A universal one-click Canvas login is not implemented. Canvas OAuth requires an institution-enabled developer key; do not embed a client secret in an open-source desktop client. A future institution-supported OAuth adapter needs state validation, secure token storage, refresh handling and a suitable registered redirect. The v0.1 token flow works without a hosted service where institutional policy permits personal tokens.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

Architecture: `client.py` owns transport and pagination; `cli.py` owns command routing, credential setup and write previews. No school-specific logic. Current testing covers mocked API behavior, not a live institution's token flow. Contributions should include synthetic fixtures only.

Roadmap: richer resource selection, incremental Markdown export, due-date views, module-item pagination, optional institutional OAuth, and broader integration tests. No npm/PyPI release yet; install from this repository.

Sources: [Canvas API](https://developerdocs.instructure.com/services/canvas), [pagination](https://developerdocs.instructure.com/services/canvas/basics/file.pagination), [OAuth](https://developerdocs.instructure.com/services/canvas/oauth2/file.oauth), [discussions](https://developerdocs.instructure.com/services/canvas/resources/discussion_topics).
