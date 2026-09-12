# Tree Light Quoter — Staged Release Evidence

**Verified:** 2026-09-10
**Branch:** `release/tree-light-quoter-backend`
**State:** Contract and production-copy migration rehearsal passed. Nothing was deployed or enabled.

## Delivered backend contract

- Seasonal quote requests explicitly select `photo` or `tree_wrap_worksheet`.
- Workspace settings enable worksheet quoting only for exact boolean `true`.
- Worksheet quotes require phased handoff; legacy photo clients retain one-job conversion.
- Photo, worksheet, and combined snapshots freeze the selected sold scope.
- Combined technician handoff includes the frozen photo plan and price-free worksheet measurements.
- Technician responses omit worksheet prices, ATP, fulfillment quantities, inventory IDs, and private SKU mappings.
- Conversion creates atomic installation/takedown phases, one invoice, and phase-specific notifications.
- Frozen inventory mappings fail closed; unrelated untracked custom lines retain existing behavior.
- Renewals copy the frozen seasonal handoff without copying payment or conversion state.
- The migration uses five-second lock and sixty-second statement timeouts.
- `next` is pinned to `16.3.4`; the previously reported critical Next.js advisory is absent.

## Local verification

| Check | Result |
| --- | --- |
| Full backend non-integration suite | 5,533 passed, 21 skipped, 906 deselected |
| Focused quote/service-plan integration | 88 passed |
| Estimate and seasonal-renewal tests | 91 passed |
| Full frontend suite | 212 files and 1,814 tests passed |
| Frontend quality | ESLint, TypeScript, and Next.js 16.3.4 production build passed |
| Backend quality | Ruff check/format and mypy passed across 864 application files |
| Generated API contract | OpenAPI and TypeScript regenerated; `make codegen/check` passed |
| Migration parity | Restored production copy: upgrade, downgrade, and re-upgrade passed on PostgreSQL 18.6 |
| Worktree integrity | Generated files stayed stable; `git diff --check` passed |

## Production read-only and restore rehearsal

- Production was at `20260909_conv_arbiters` on PostgreSQL 18.6.
- `quotes` was approximately 29 MB/47 rows; `field_service_jobs` was approximately 1.2 MB/1,043 rows.
- Five jobs referenced quotes; the legacy uniqueness constraint existed and no duplicates existed.
- A 30 MB encrypted dump was written mode `0600` with the escrow-marked external key.
- Decryption streamed directly into temporary-memory PostgreSQL 18 with pgvector; no cleartext dump was written.
- Restore, upgrade, downgrade, and re-upgrade each completed in approximately two seconds.
- Quote/job counts stayed 47/1,043; all existing phases backfilled to `primary`.
- The temporary database and its memory-backed storage were destroyed immediately afterward.

## Security and compatibility evidence

- Feature-disabled workspaces cannot create worksheet-source quotes.
- Existing worksheet data remains stored and readable when the feature is disabled.
- Photo-source quotes reject worksheet fulfillment fields.
- Old clients omit phased handoff and still convert photo quotes without takedown scheduling.
- Worksheet rows, inventory mappings, and accepted quantities are frozen before job allocation.
- Public proposal serialization uses its existing allowlist and excludes private fulfillment data.
- `npm audit --omit=dev` reports zero critical advisories and one remaining high Tiptap advisory.

## Production gates still blocked

1. Protected pull-request checks and review have not run.
2. Vercel rollback access is unverified; no local Vercel CLI is installed.
3. The pilot workspace and internal no-delivery smoke-test records are unidentified.
4. The frontend activation branch must wait for the backend deployment health proof.

## Actions intentionally not performed

- No production row contents were read or changed; only aggregate counts and schema metadata were queried.
- No commit was merged and no production deployment was started.
- No feature setting was enabled for any workspace.
- No email, SMS, payment, approval, job, allocation, or stock-ledger action reached production.
