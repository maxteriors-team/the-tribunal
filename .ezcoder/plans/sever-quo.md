# Direct Quo code severance

Implement the safe, code-only portion immediately. Do not touch production, credentials, provider webhooks, API keys, customer records, database schema, git history, or deployment.

## Scope

- Remove Quo setup, credential-management branches, active-line APIs, webhook ingress, sync/backfill, and outbound runtime paths.
- Remove Quo-specific frontend setup and sending behavior.
- Keep historical contacts, messages, calls, summaries, provenance, send-attempt rows, models, and immutable migrations unchanged.
- Treat every imported-provider conversation as read-only so it can never fall through to Telnyx.
- Keep historical imported communication visible using provider-neutral labels.
- Delete obsolete Quo runtime tests; replace shared guarantees with provider-neutral regression coverage.
- Regenerate OpenAPI artifacts and remove obsolete operational scripts/runbooks.

## Verification

Run `make ci.backend`, `make ci.frontend`, and `make ci.codegen`. Exercise local HTTP probes proving Quo routes return 404 and imported conversations reject writes. Scan runtime code for remaining `api.quo.com` callers.

## Steps

1. Inspect the dirty worktree and preserve all unrelated edits.
2. Add regression coverage for route removal, read-only imports, and frontend removal.
3. Remove backend Quo routes, schemas, clients, sync, send, and backfill paths.
4. Generalize conversation safeguards from Quo-specific to imported-provider behavior.
5. Remove frontend Quo setup, active-line queries, sending, controls, and branding.
6. Regenerate API contracts and remove retired operational assets.
7. Run full backend, frontend, and codegen verification; fix all failures.
8. Stop before any production cleanup, credential deletion, key revocation, deployment, or other external action.