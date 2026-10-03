# Safety and privacy

[Documentation](README.md) · [Authentication](getting-started.md)

## Confirmation

Canvas writes default to previews. Review exact account/site, audience, destination, content, selected fields, and warnings, then repeat the same command/options with both flags.

```sh
canvas-pocket post 123 456 --message-file reply.txt
canvas-pocket post 123 456 --message-file reply.txt --yes --confirm DIGEST
```

Digests bind origin, signed-in numeric user, target/content, and relevant current state. Changed identity/site/content/state requires a fresh preview. Renewing a token for the same user/site does not print credentials.

Previews are not permission proof or atomic server locks. Canvas is final authority. Writes never automatically retry ambiguous completion: verify before repeating. Native acknowledgements/independent readback are distinguished per guide.

Schema syntax, a preview, or broad automation instructions are not permission to send/post/submit. Review the operation and course rules.

## Transport boundaries

- One HTTPS API client and Link-pagination implementation.
- Pagination stays on configured origin/API paths; redirects cannot carry credentials elsewhere.
- URL credentials/impersonation/credential query parameters/path traversal are refused, including encoded/bracketed forms.
- Conversation GETs must disable automatic mark-read; submission read-status inclusion is blocked.
- Storage/binary transport has no API credential, cookies, or redirects.
- 401 requires reauth; 403 is not automatically bad auth; 429 is surfaced without aggressive retries.
- Page caps fail explicitly, including empty intermediate pages, never silent truncation.

Expert get is for guarded documented API reads, not arbitrary harmless HTTP or permission bypass.

Native GETs can log analytics. Root/path lookup may create a missing root; notification preferences may persist defaults. Those commands are labeled in help/schema. Undocumented server effects are outside the guarantee.

## Private output

No telemetry/backend/cookie extraction/credential export. Keyring is outside Git; config stores only origin. Logout does not revoke a server token.

JSON, names, posts, grades, message bodies, links, snapshots, downloads, and exports can be private/copyrighted. Metadata-first is not public-safe. Never publish live outputs/captures.

Private local writes refuse overwrite/Git destinations, including symlinked parents. Known token-shaped fields are stripped from snapshots, not every private fact. Review before sharing.

Ignore rules cover common exports/env/cookie/capture paths but are not a privacy guarantee. Only synthetic fixtures belong in public tests/issues/CI.

## Coverage and recovery

Endpoint completeness is not complete course/institution coverage. Locked/unpublished/denied content is not bypassed; unknown remains unknown. Empty feeds/missing/feedback do not prove all work complete.

Auth/network/rate-limit/malformed responses fail, not empty success. Permission/not-found fallbacks label partial coverage. Partial snapshots never invent full removals.

Own Inbox deletion is not delete-for-all; file removal is irreversible; group/invitation changes can remove access. Read command-specific caveats before confirming.

[Validation](development.md#validation) distinguishes unit, synthetic HTTPS, CI, live reads, and untested real writes.
