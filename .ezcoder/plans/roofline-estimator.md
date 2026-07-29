# Roofline Linear-Feet Estimator + Client-Facing Savings Comparison

## Goal

Give reps an in-CRM tool that measures a home's roofline in **linear feet** from a
photo — calibrated against a **known reference** (front door / garage door) — then
shows what we'd charge for **permanent** vs **temporary (Christmas)** lighting, and
lets the rep **share a client-facing page** so the homeowner sees the **true cost
savings and difference**.

Hard privacy rule (unchanged): **linear feet is internal-only**. It never appears in
any client-facing payload, URL, or HTML. Clients see prices and savings; reps see
the feet behind them.

Three surfaces:

- **Rep tool (`/estimator`, authenticated):** measure feet on a photo, see per-service
  totals, Permanent ↔ Temporary toggle, and a multi-year savings breakdown.
- **Rep "share" action:** persists the estimate and returns a client link.
- **Client page (`/p/compare/{token}`, no auth):** branded page showing the two
  prices, the **difference**, the **multi-year "pay once vs every season" savings**,
  and the **perks of permanent vs temporary** — with **no linear feet anywhere**.

## Why this stays contained

The pricing math already exists and is server-authoritative:
`app/services/quotes/proposal_pricing.py` has `price_permanent(config, feet=…)` and
`price_christmas(config, roofline_feet=…)`, each returning a `.total`. The public
token/share pattern already exists end-to-end for quotes (`/p/quotes/{token}`:
`generate_quote_token()`, `public_router` mounted at `/p/quotes`,
`get_public_proposal` returns a deliberately safe-fields-only payload). We copy that
proven shape for a comparison. Reused frontend: canvas engine from
`sales-wizard/night-preview-screen.tsx`, dark/gold theme from
`components/proposal/*`, public-page skeleton from `app/p/quotes/[token]/page.tsx`.

## Design decisions

- **Server computes all money; client measures only feet.** The rep tool POSTs the
  feet number; the server returns both totals + savings. Matches "client totals are
  never trusted."
- **Client-facing = a persisted, token-keyed page** (not just an in-person toggle),
  because the user wants the homeowner to see the savings themselves. It rides the
  exact `/p/quotes` rails: a random `token_urlsafe(24)` token, a `public_router`
  mounted at `/p/compare`, and a public payload that **structurally cannot** contain
  feet (no such field on the public schema).
- **Feet never serialized publicly.** Feet is stored server-side on the comparison
  row (internal) and used only to recompute prices. The public schema
  (`PublicComparison`) has price/savings/perks fields only — same discipline as
  `PublicProposal` excluding costs/margins. A test asserts the public JSON and the
  rendered HTML contain no feet value.
- **Prices recompute from live config on each public view** (not frozen), so a
  pricing change is reflected; the stored inputs (feet, channels, takedown, storage)
  are the only persisted selection.
- **"True cost savings" = multi-year projection.** Permanent is one-time; temporary
  recurs every season. The client hook is: *Temporary over N seasons = $X; Permanent
  one-time = $Y; you save $Z.* Horizon defaults to 5 seasons, configurable via a new
  `comparison_years` knob in the pricing config (editable through the existing
  `PUT .../pricing`, no new settings UI). Also show the single-season difference.
- **Perks are editable data, not hardcoded copy.** Add `perks: list[str]` to
  `PermanentConfig` and `ChristmasConfig` with sensible defaults; they round-trip
  through the existing pricing settings API. No migration for perks.
- **Measurement math is pure + unit-tested** in `frontend/src/lib/estimator/`.
- **Reference presets** (editable feet): front door ≈ 6.67 ft, single garage ≈ 8 ft,
  double garage ≈ 16 ft. feet = `sum(rooflinePx) / (referencePx / referenceFeet)`,
  rounded to the nearest foot.

## Data shapes

**Rep estimate (live preview)** — `POST /api/v1/workspaces/{id}/quotes/estimate`
(`billing:read`):

```
LinearFeetEstimateRequest { feet>=0, channels=0, takedown=false, storage=false }
LinearFeetEstimateResult {
  feet,                              # INTERNAL — rep tool only
  permanent { enabled, total, per_ft },
  christmas { enabled, total },
  difference,                        # |permanent.total - christmas.total| (one season)
  years,                             # projection horizon
  temporary_multi_year,             # christmas.total * years
  permanent_one_time,               # permanent.total
  multi_year_savings,               # temporary_multi_year - permanent_one_time
  permanent_perks: [str], christmas_perks: [str]
}
```

**Share (persist)** — `POST /api/v1/workspaces/{id}/quotes/estimate/share`
(`billing:write`): body = estimate request + optional `client_name`, `label`.
Returns `{ token, url }` (`url` = `{frontend}/p/compare/{token}`).

**Client page** — `GET /api/v1/p/compare/{token}` (no auth):

```
PublicComparison {
  business_name, brand_color, accent_color, logo_url,   # from proposal template
  client_name?,
  currency,
  permanent { enabled, total }, christmas { enabled, total },
  difference, years, temporary_multi_year, permanent_one_time, multi_year_savings,
  permanent_perks: [str], christmas_perks: [str]
  # NO feet, NO per_ft, NO channels — structurally absent
}
```

## Edge cases

- Permanent or Christmas not enabled → that side `enabled=false, total=0`; UI shows
  "not configured", and savings math skips the disabled side (no bogus $0 compare).
- feet ≤ 0 / no reference drawn → rep results disabled with a "measure the roofline"
  prompt; no request sent; share disabled.
- Unknown//expired token on the public page → same 404 "invalid or expired" state as
  the proposal page.
- Config minimums already handled inside the pricing functions.
- Hand-edited/partial config never 500s (existing lenient `get_pricing_config`).

## Files

**Backend**

- `backend/app/schemas/pricing.py` — add `perks: list[str]` (default copy) to
  `PermanentConfig` and `ChristmasConfig`; add `comparison_years: int = 5` to
  `PricingSettings` (+ `PricingSettingsUpdate`).
- `backend/app/schemas/estimate.py` (new) — `LinearFeetEstimateRequest`,
  `LinearFeetEstimateResult`, `ComparisonShareRequest`, `ComparisonShareResult`,
  `PublicComparison` (+ nested per-service models). Public model has no feet field.
- `backend/app/models/roofline_comparison.py` (new) — `RooflineComparison`
  (id, workspace_id FK, public_token unique, feet, channels, takedown, storage,
  client_name?, label?, created_by?, created_at). `generate_comparison_token()` via
  `secrets.token_urlsafe(24)`, mirroring `generate_quote_token`.
- `backend/alembic/versions/<rev>_add_roofline_comparison.py` (new) — create table
  (+ unique index on `public_token`, index on `workspace_id`). Additive only.
- `backend/app/services/quotes/quote_service.py` — add `estimate_linear_feet(ws, req)`
  (compute both + savings), `share_comparison(ws, req, created_by)` (persist + token),
  and `get_public_comparison(token)` (recompute from live config; feet never
  serialized). Mirrors `preview_from_wizard` / `get_public_proposal`.
- `backend/app/api/v1/quotes.py` — add authed `POST .../quotes/estimate` and
  `POST .../quotes/estimate/share`; add `public_router.get("/{token}")` for the
  comparison (new dedicated public router or reuse a compare-scoped one).
- `backend/app/api/v1/router.py` — mount the comparison public router at `/p/compare`.
- `backend/app/models/__init__.py` — register the new model.
- Tests (new): `backend/tests/services/quotes/test_linear_feet_estimate.py` (both
  enabled, one disabled, difference, minimum, multi-year savings, perks defaults) and
  `backend/tests/services/quotes/test_public_comparison.py` (**asserts the public
  payload has no feet/per_ft/channels keys and never equals the stored feet**, plus
  404 on bad token).

**Frontend**

- `frontend/src/lib/estimator/measure.ts` + `measure.test.ts` (new) — reference
  presets + pure `pxPerFoot()`, `rooflineFeet()`, polyline length.
- `frontend/src/lib/api/estimator.ts` (new) — `estimate`, `share`.
- `frontend/src/lib/api/public-comparisons.ts` (new) — `get(token)`.
- `frontend/src/types/estimate.ts` (new) — mirror the schemas (or use generated types).
- `frontend/src/components/estimator/roofline-estimator.tsx` (new) — canvas measure
  (upload, reference line, roofline polyline, undo/clear), internal results with
  Permanent↔Temporary toggle + multi-year savings, and a **Share with client** action
  that returns a copyable link.
- `frontend/src/components/estimator/comparison-card.tsx` (new) — the shared savings
  card (two prices, difference, multi-year savings, perks); no feet. Used by both the
  rep tool (client-view preview) and the public page.
- `frontend/src/app/estimator/page.tsx` (new) — hosts the tool in `AppSidebar`.
- `frontend/src/app/p/compare/[token]/page.tsx` (new) — public page: fetch by token,
  loading/error states like the proposal page, render `comparison-card` in the
  dark/gold theme.
- `frontend/src/components/layout/app-nav.ts` — add "Estimator" nav item near Quotes
  (`requires: "billing:read"`, `sidebar: true`, `commandPalette: true`).
- `frontend/src/lib/query-keys.ts` — add `publicComparisons.byToken(token)` key.

**Codegen**

- `make codegen`; commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts`
  in the same commit as the backend changes.

## Verification

- Backend: `pytest` the two new test modules. Then run migrations locally and use
  `.ezcoder/eyes/http.sh`:
  - authed `POST .../quotes/estimate` → confirm both totals + `difference` +
    `multi_year_savings` + perks;
  - authed `POST .../quotes/estimate/share` → get a token;
  - **no-auth `GET /api/v1/p/compare/{token}`** → confirm prices/savings/perks present
    and **grep the redacted body to prove no feet value appears**;
  - disabled-service case renders "not configured".
- Frontend: `vitest` `measure.test.ts`; run the dev server and screenshot:
  - `/estimator` in rep mode (feet visible) and client-view preview (feet absent);
  - `/p/compare/{token}` public page — assert prices, multi-year savings, and both
    perk lists render, and **linear feet is nowhere on the page**.
- `make ci.codegen` clean (no drift).

## Open questions (non-blocking — sensible defaults otherwise)

1. **Savings horizon** — default 5 seasons (editable via `comparison_years`). Prefer a
   different number?
2. **Perks copy** — I'll ship editable defaults (permanent: install once, app-
   controlled color/scenes, year-round + holiday use, no yearly install/removal,
   warrantied; temporary: lower upfront, pro install + takedown + storage, seasonal
   flexibility, nothing permanently attached). Send preferred wording anytime.

## Steps

1. Add `perks: list[str]` (default copy) to `PermanentConfig`/`ChristmasConfig` and `comparison_years: int = 5` to `PricingSettings`/`PricingSettingsUpdate` in `backend/app/schemas/pricing.py`.
2. Create `backend/app/schemas/estimate.py` with the estimate, share, and public-comparison schemas (public model has no feet field).
3. Create `backend/app/models/roofline_comparison.py` (`RooflineComparison` + `generate_comparison_token()`) and register it in `backend/app/models/__init__.py`.
4. Create the Alembic migration `add_roofline_comparison` (additive table + indexes).
5. Add `estimate_linear_feet`, `share_comparison`, and `get_public_comparison` to `QuoteService` in `backend/app/services/quotes/quote_service.py` (feet never serialized in the public result).
6. Add authed `POST .../quotes/estimate` and `.../quotes/estimate/share` endpoints and the public comparison GET in `backend/app/api/v1/quotes.py`; mount the comparison public router at `/p/compare` in `backend/app/api/v1/router.py`.
7. Write `test_linear_feet_estimate.py` and `test_public_comparison.py` (the latter asserts no feet leaks into the public payload) under `backend/tests/services/quotes/`.
8. Run `make migrate` locally, then `make codegen` and commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts`.
9. Create `frontend/src/lib/estimator/measure.ts` (+ `measure.test.ts`) with reference presets and pure scale/feet math.
10. Create `frontend/src/lib/api/estimator.ts`, `frontend/src/lib/api/public-comparisons.ts`, `frontend/src/types/estimate.ts`, and the `publicComparisons` query key.
11. Build `frontend/src/components/estimator/comparison-card.tsx` (feet-free savings card) and `roofline-estimator.tsx` (canvas measure + internal results + Share action).
12. Add `frontend/src/app/estimator/page.tsx`, `frontend/src/app/p/compare/[token]/page.tsx`, and the "Estimator" nav item in `frontend/src/components/layout/app-nav.ts`.
13. Verify: backend pytest + `http.sh` probes (including the no-auth public GET proving no feet leak), frontend vitest, `/estimator` and `/p/compare/{token}` screenshots, and a clean `make ci.codegen`.
