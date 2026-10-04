# Development

[Documentation](README.md) · [Capabilities](../CAPABILITIES.md) · [Safety](safety.md)

## Local workflow

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check src tests
.venv/bin/python -m unittest discover -s tests -v
```

Tests use standard unittest. Subprocess integration requires openssl and synthetic local HTTPS, not a real account.

## Architecture

Keep domain behavior outside the entry point. No school-specific rules, plugin framework, generic CRUD engine, or speculative backend layers.

```text
src/canvas_cli/
  cli.py          entry point; offline/online orchestration
  arguments.py    argparse definitions; shared confirmation flags
  auth.py         origin config, keyring, login/logout/client setup
  dispatch.py     parsed arguments → domain operations
  formatting.py   human summaries; no credentials/network
  client.py       HTTPS transport, guarded paths, pagination
  strict_json.py  unambiguous API/snapshot decoding
  writes.py       identity and confirmation digests
  text.py         bounded explicit UTF-8 file inputs
  wiki_content.py shared native page metadata and private content fingerprints
  download.py     credential-free binary transport
  <domain>.py     resource-specific validation/projection/behavior
tests/
  test_<domain>.py  focused unit tests
  e2e/
    fixture.py       shared synthetic Canvas/storage HTTPS server
    appointments.py  focused synthetic Scheduler routes and state
    team_appointments.py  shared-team Scheduler routes and state
    channels.py      focused synthetic contact routes and state
    page_authoring.py  shared RCE wiki routes and state
    page_history.py   native history and exact-revision restore routes
    page_deletion.py  native soft-delete evidence and assignment cascades
    page_duplication.py  native course copies and assignment lineage
    page_scheduling.py  native publication callbacks reusing the RCE fixture
    module_items.py  own progression events, pagination and Horizon read-side effects
    module_paths.py  native mastery choices, switching effects and asynchronous readback
    topic_management.py  native prompt authoring/state/configuration/deletion, full pinned ordering and permissions
    test_<area>.py   subprocess lifecycle regressions by workflow
```

Argparse is the sole syntax source; navigation derives help/schema and capabilities supplies safety labels. Do not hand-maintain an exhaustive duplicate Markdown option catalog.

Reuse actual shared behavior: transport/pagination, identity/confirmation, context verification, private saves, storage transfer. Keep ownership/publication/audience/acknowledgement/side-effect differences explicit; similar-looking APIs can have different semantics.

Prefer small functions/domain modules and direct calls. Abstract only concrete repetition. Refactor with behavior-preserving tests, not an unrelated directory shuffle.

## Contribution checks

1. Use documented native routes/primary Instructure sources.
2. Separate reads, local writes, and preview-first mutations.
3. Test pagination, malformed/foreign data, stale previews, side effects, uncertain outcomes, and output privacy.
4. Synthetic records only, including HTTPS fixtures.
5. Run Ruff/full suite/freshly installed wheel suite.
6. Review credentials/live records/paths/undocumented behavior.
7. Update the relevant guide/capability row, not every doc.

Fresh-wheel tests catch source-checkout dependency. CI runs Python 3.10 and 3.13 with lint/unit/HTTPS/wheel checks.

## Validation

Unit → subprocess/local HTTPS → supported-version CI → opt-in live reads → writes only in a designated sandbox.

New behavior is synthetic-tested unless a live read is explicitly recorded. **No real write action has been exercised against a live account.** Synthetic success is not a production permission/write-validation claim.

Historical live checks covered personal-token login, calendar, own grades, folders/sections, outline, linked files, snapshots/repeated sync, selected other reads, one temporary download, and URL-submission preview, not coursework submission.

A denied live Pages list (404) recovered 27 readable module pages while remaining partial, also supporting title search. Assignment groups were readable; rubrics/New Quizzes returned 403 and Classic Quizzes 404. These are account/course observations, not global availability claims.

Recipient/compose preview were checked without sending. No unlocked live thread was available; a locked announcement was correctly refused. New group/profile/preferences/invitation/feedback features rely on synthetic fixtures, not live mutations.

## Remaining work

Prioritize useful student workflows with documented/testable boundaries. Incremental sync, richer offline projection, and institution-approved OAuth remain open. Admin controls/external-tool authorization/project switches/quiz attempts are distinct surfaces, not generic-write shortcuts.

See the capability map for domain limits. No npm/PyPI release or universal browser-login promise.

## Primary references

[Canvas API](https://developerdocs.instructure.com/services/canvas), [Pagination](https://developerdocs.instructure.com/services/canvas/basics/file.pagination), [OAuth](https://developerdocs.instructure.com/services/canvas/oauth2/file.oauth), [Native implementation](https://github.com/instructure/canvas-lms), [JSON interoperability](https://docs.python.org/3/library/json.html#standard-compliance-and-interoperability).
