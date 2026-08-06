# Quote view tracking + "client opened your quote" notification

## Goal

When a customer opens their proposal link, the operator learns about it — so they can call
while the customer is still looking at it. Today `get_public_proposal()` is a pure read and
nothing is recorded.

## Why the signal will be trustworthy

The usual failure mode of read-receipts is scanner noise: Outlook Safe Links, Gmail's image
proxy, and Apple Mail Privacy Protection fetch URLs with no human involved, so "they opened
it!" fires on a robot.

That does not apply here. `frontend/src/app/p/quotes/[token]/page.tsx` is `"use client"` —
the data load only happens in a real browser executing React Query. A scanner fetching the
Next.js route gets the HTML shell and never reaches the API. **A recorded view means a human
with a JS-capable browser rendered the page.**

## Key design decision: a separate POST beacon, not a write inside the GET

`GET /api/v1/p/quotes/{token}` must stay a pure read. Writing to the database inside a GET
breaks HTTP semantics, makes the endpoint uncacheable, and means every retry/refetch that
React Query performs (including its automatic refetch-on-window-focus) amplifies into a
write on an unauthenticated path.

Instead, add `POST /api/v1/p/quotes/{token}/view` — an explicit beacon the client page fires
once on mount. This gives us:

- GET stays read-only and cacheable.
- One obvious, narrow, rate-limitable write surface.
- A trivial place to skip staff previews.

## Key problem: staff previewing inflates their own numbers

`frontend/src/components/quotes/quotes-list.tsx:122` (`openClientProposal`) opens the *exact*
customer URL from the dashboard's "Preview client proposal" action. Without handling, every
staff preview registers as a customer view and fires a false notification.

Fix: the preview action appends `?preview=1`, and the page skips the beacon when that param
is present. This is client-controlled and therefore not a security boundary — but it does not
need to be. The worst case of a forged `?preview=1` is that a real customer's view goes
*unrecorded*, which is a missed notification, not a leak or a spoofed alert.

## Notification path and its honest latency limit

`HumanNudge` (`backend/app/models/human_nudge.py`) already has `title`, `message`,
`priority`, `delivered_via` (sms/push), and a **unique** `dedup_key` — the "don't alert me 9
times because they re-read it" problem is already solved by existing infrastructure.

**However:** `NudgeWorker.POLL_INTERVAL_SECONDS = 3600`
(`backend/app/workers/nudge_worker.py:26`). SMS/push delivery is Phase 2 of an **hourly**
pass. A "call them right now" alert delivered up to 60 minutes late is materially less useful
than the pitch implies.

Resolution, and it is a genuine tradeoff worth stating plainly:

- The **nudge row is created inline** at view time, so the dashboard nudge list and its badge
  reflect it within one 60s poll (`POLL_60S` in the sidebar). That is the fast path.
- **SMS/push still ride the hourly worker.** No new delivery path, no new failure mode on an
  unauthenticated request, no SMS spend triggered directly by anonymous public traffic — that
  last point matters, since an inline send would let anyone with a link cause outbound
  messages.

If sub-minute SMS is required, that is a follow-up that shortens the nudge worker interval or
adds a dedicated fast lane — deliberately out of scope here, and called out rather than
quietly shipped as "instant".

## Scope boundaries

In scope: quotes only. The public **invoice** page (`/p/invoices/[token]`) and the
**comparison** page (`/p/compare/[token]`) are untouched.

Also in scope, and separate from tracking: the public invoice view
(`frontend/src/components/invoice/public-invoice-view.tsx`) renders `business_name` as text
and shows **no logo at all**, unlike the proposal view. Adding it is a two-line consistency
fix while we are here.

## Data model

Three columns on `quotes` (all nullable / defaulted, no backfill needed):

| Column | Type | Meaning |
|---|---|---|
| `first_viewed_at` | `timestamptz` null | First genuine client view. Never overwritten. |
| `last_viewed_at` | `timestamptz` null | Most recent view. Drives "opened 10 min ago". |
| `view_count` | `integer not null default 0` | Throttled count, not raw hits. |

`view_count` counts *throttled* views: repeat beacons within `VIEW_THROTTLE_MINUTES` (15) of
`last_viewed_at` do not increment. Without this, one customer refreshing or leaving a tab open
reads as 40 views and the number becomes noise.

## Risks

- **Migration touches `quotes`**, a live customer table. Additive nullable columns + a
  defaulted integer, so it is safe and reversible, but the release process requires a prod
  backup first.
- **Unauthenticated write path.** Throttling is per-quote (not per-IP), so the write is bounded
  regardless of caller volume: after the first, repeat beacons inside the window are a no-op
  UPDATE-free read. The token must already resolve via `_load_by_token`, so an unknown token
  404s before any write.
- **Public API contract changes** → `make ci.codegen` must run and both `backend/openapi.json`
  and `frontend/src/lib/api/_generated.ts` must be committed in the same commit.
- **Pre-existing flaky frontend test.** A full `vitest run` on clean `origin/main` fails with a
  *different* test each run (`seasonal-pricing-settings-tab` vs an attach-hook `waitFor`); both
  pass in isolation. Do not attribute this to the change, and do not "fix" it here.

## Verification

- Backend unit tests for: first view stamps all three fields; a second view inside the throttle
  window changes nothing; a view after the window bumps `last_viewed_at` and `view_count`;
  exactly one nudge is created across repeated views (dedup); an unknown token 404s.
- `.ezcoder/eyes/http.sh` against a locally-sent quote: POST the beacon twice, confirm 204 both
  times and that the second is a no-op; confirm `GET /{token}` still returns the same payload.
- Frontend: quotes-list renders the viewed indicator; preview action does not fire the beacon.

## Steps

1. Add `first_viewed_at`, `last_viewed_at`, and `view_count` columns to the `Quote` model in `backend/app/models/quote.py`, placed next to the existing `sent_at` / `approved_at` / `declined_at` timestamps.
2. Generate the migration with `make migrate.new m="add quote view tracking"`, then edit `backend/alembic/versions/<rev>_add_quote_view_tracking.py` so `upgrade()` adds the two nullable timestamptz columns plus `view_count` as `nullable=False, server_default="0"`, and `downgrade()` drops all three. Add a module docstring explaining no backfill is needed (existing quotes read as never-viewed).
3. Run `make migrate` locally and confirm it applies cleanly, then confirm reversibility with an `alembic downgrade -1` / `alembic upgrade head` cycle.
4. Add a `record_public_view(token)` method to `QuoteService` in `backend/app/services/quotes/quote_service.py` that loads via the existing `_load_by_token`, returns early when `last_viewed_at` is within `VIEW_THROTTLE_MINUTES` (15, module-level constant), otherwise sets `first_viewed_at` (only if null), `last_viewed_at`, and increments `view_count`, then commits. Document the throttle rationale in the docstring.
5. In the same method, when `first_viewed_at` was just set for the first time, create a `HumanNudge` row with `nudge_type="quote_viewed"`, `priority="high"`, `contact_id` from the quote, a title/message naming the client and quote number, `suggested_action="call"`, and `dedup_key=f"{quote.id}:quote_viewed"` so re-views never produce a second nudge. Guard the insert with the existing `dedup_exists` helper from `backend/app/services/nudges/strategies/base.py`.
6. Register `"quote_viewed"` in `ALL_NUDGE_TYPES` in `backend/app/services/nudges/nudge_generator.py` so the type is recognized by settings-driven filtering and delivery. No strategy class is needed — this nudge is created inline, not generated by a polling strategy.
7. Add `POST /{token}/view` to `public_router` in `backend/app/api/v1/quotes.py`, returning `204 No Content`, delegating to `QuoteService.record_public_view`. Place it next to the existing approve/decline public routes.
8. Expose `first_viewed_at`, `last_viewed_at`, and `view_count` as read-only fields on `QuoteResponse` in `backend/app/schemas/quote.py`, with a comment noting they are server-written and must never be accepted from a request body.
9. Add backend tests in `backend/tests/services/quotes/` covering: first view stamps all three fields and creates exactly one nudge; a repeat view inside the throttle window is a no-op; a view past the window bumps `last_viewed_at` and `view_count` but creates no second nudge; an unknown token raises `NotFoundError`.
10. Add a `recordView(token)` call to `frontend/src/lib/api/public-proposals.ts` hitting the new endpoint, swallowing errors so a failed beacon never degrades the customer's page.
11. In `frontend/src/app/p/quotes/[token]/page.tsx`, fire the beacon exactly once on mount via a `useRef` guard (mirroring the existing `reconciledRef` pattern), skipping entirely when `window.location.search` contains `preview=1`.
12. Change `openClientProposal` in `frontend/src/components/quotes/quotes-list.tsx` to append `?preview=1` to the URL it opens, leaving `copyClientLink` untouched so the customer-facing copied link never carries the flag.
13. Surface the signal in the quotes list: render a muted "Viewed <relative time>" line under the status badge when `last_viewed_at` is set, using the existing `formatDate`/relative-time helpers already imported in that file.
14. Add the logo to the public invoice view in `frontend/src/components/invoice/public-invoice-view.tsx`, mirroring the `branding.logo_url` block at `frontend/src/components/proposal/client-proposal-view.tsx:207` including its eslint-disable comment for the raw `img` element.
15. Run `make codegen` and commit `backend/openapi.json` plus `frontend/src/lib/api/_generated.ts` together with the source changes in the same commit.
16. Run `make ci.all` and confirm it exits 0, treating only the known-flaky frontend unit tests as pre-existing (verify by re-running the failing file in isolation).
17. Verify at runtime with the eyes probes: start the local backend, send a quote to get a token, then `POST` the beacon twice via `.ezcoder/eyes/http.sh` confirming 204 and no-op behavior, and check `.ezcoder/eyes/logs.sh` for tracebacks.
18. Open a PR against `main` with `gh pr create`, wait for the 4 required checks, and merge with `--rebase --delete-branch`.
19. Before deploying, take a production backup with `make db.backup.prod` since the migration touches the `quotes` table, and verify the dump is non-empty.
20. Deploy the backend from a clean `origin/main` checkout via `make deploy.backend`, then confirm `curl -s https://the-tribunal-api-production.up.railway.app/version` reports the deployed SHA and that the SHA is an ancestor of `origin/main`.
