# Setup and authentication

[Documentation](README.md) · [Safety](safety.md)

## Install

Python 3.10+ and a supported OS keyring are required. Install [pipx](https://pipx.pypa.io/) separately if needed.

```sh
pipx install git+https://github.com/braindead-dev/canvas-cli.git
canvas --version
canvas auth login --origin https://canvas.example.edu
canvas auth status
canvas courses --active --format brief
```

`canvas --version` reads installed package metadata offline without authentication. This is a developer preview; no npm/PyPI release is published.

Upgrading from Canvas Pocket? Install from the new URL above, check `canvas auth status`, then remove the old pipx package with `pipx uninstall canvas-pocket`. The new command is `canvas`; saved authentication and sync storage are unchanged.

## Personal-token login

Create a token in your own Canvas **Account → Settings → Approved Integrations**, if permitted. Choose an expiration date and revoke unused tokens.

Login requires an interactive terminal and prompts without echoing the token. Credentials go into your OS keyring; configuration stores only the Canvas origin. Passwords, cookies, and browser sessions are not imported.

Supported backends are macOS Keychain, Windows Credential Locker, Secret Service, and KWallet. Unsupported/plaintext/fallback backends fail closed. Linux may require explicitly selecting a secure backend.

`auth logout` removes the local keyring entry, not the server token. Revoke it in Canvas to invalidate it. Environment credentials are not removed by logout.

## Headless use

Supply `CANVAS_ORIGIN` and `CANVAS_TOKEN` through a secret manager/process environment. They override saved authentication. Never put tokens in arguments, shell history, repository files, or bug reports.

Configuration lives at `$XDG_CONFIG_HOME/canvas-pocket/config.json`, or `~/.config/canvas-pocket/config.json` when unset. Credentials are separate. The historical storage namespace is retained after the Canvas CLI rename, so existing logins and private sync baselines still work. New installs use the same storage namespace.

## Output and discovery

JSON is complete; `--format brief` is a human summary. `--format` and `--max-pages` work before or after commands.

```sh
canvas help --search feedback --format brief
canvas help feedback --format brief
canvas schema feedback
```

Help/schema run offline without configuration, keyring, or network. The versioned schema derives flags, positionals, choices, defaults, accumulation, exclusion groups, and nested auth commands from the actual parser.

It is not a standard JSON Schema or authorization/execution contract. Runtime identity, scope, bounds, access, and confirmation checks remain mandatory.

## Shell completion

```sh
canvas completion bash --format brief
canvas completion zsh --format brief
canvas complete --cword 3 -- canvas files 123 --cont
```

Review the printed function, then source it in your **current shell** with `eval "$(canvas completion bash --format brief)"` or the Zsh equivalent. Zsh requires `compinit` first. The CLI does not edit shell startup files or install hooks automatically.

Tab completion derives current commands, nested auth commands, flags, finite choices, repeatable options and argument-exclusion groups from argparse. `--option=value` and Bash's split-equals convention are supported. The helper is offline and emits known parser candidates only; it does not inspect credentials, configuration, course IDs, Canvas data or file contents. Bash/Zsh can use their own ordinary filename fallback when no parser candidate exists.

Completion is a discovery aid, not a syntax, permission or execution validator. Free-form values/numeric IDs are not guessed. It never runs an action, previews a write, reads a secret or supplies a confirmation digest. New commands appear without regenerating a separate manual command catalog.

## Troubleshooting

| Result | Next step |
| --- | --- |
| 401 | Reauthenticate; credential missing/expired/invalid |
| 403 | Check permissions, publication, scopes, and institution settings, not just credentials |
| 404 | Endpoint/resource unavailable in this context, not necessarily nonexistent |
| 429 | Back off; no aggressive automatic retry |
| Page limit | Inventory incomplete; increase `--max-pages` deliberately |
| Uncertain write | Check Canvas first; the change may have applied |

## OAuth status

[Canvas permits personal tokens for development testing](https://developerdocs.instructure.com/services/canvas/oauth2/file.oauth). Multiuser apps require OAuth and an institution-enabled developer key.

Universal one-click login is not implemented. An adapter needs registered redirects, state validation, secure storage, and refresh handling. Never embed a client secret in an open-source desktop client or replace OAuth with cookie scraping.
