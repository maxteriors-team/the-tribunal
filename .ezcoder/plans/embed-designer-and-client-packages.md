# Embed Photo Designer into Quotes + surface seasonal packages client-side

Two coupled UI changes to declutter the quoting area and move Good/Better/Best
seasonal packages in front of the client.

## Design read

- **Surface:** application UI (dashboard-dense) for the rep; a separate branded
  client-facing share page for the homeowner.
- **Single job:** give the rep *one* quoting home, and let the homeowner see the
  seasonal options as packages instead of a single pre-picked price.
- **Reuse:** `frontend/src/components/ui/tabs.tsx` (existing primitive), the
  estimator `RooflineEstimator` component (embed as-is), the estimator client
  card styling (`.cmp-cards/.cmp-card` in `estimator.css`), and the existing
  `ComparisonCard`. No new design system, no new icon set.
- **Constraint (privacy):** `backend/app/schemas/estimate.py` intentionally
  keeps linear feet / per-foot rate out of every public (`/p/compare`) payload.
  `ChristmasPackagePricing.pricing` is a `ChristmasPricing`, which **includes
  `roofline_feet` and `roofline_cost`**. So the client package payload must be a
  new feet-free shape carrying only presentation + total, never the raw pricing.

## Current state (verified)

- Nav (`frontend/src/components/layout/app-nav.ts`) has three sidebar items:
  `Quotes & Estimates` (`/quotes`), `Quote Builder` (`/sales-wizard`), and
  `Photo Designer` (`/estimator`). A comment already notes the intent of "one
  obvious quoting/estimates home instead of competing estimator tabs."
- `/quotes` (`frontend/src/app/quotes/page.tsx`) renders a header with two
  buttons ("Build a quote" -> `/sales-wizard`, "Design on a photo" ->
  `/estimator`) and `<QuotesList />`.
- `/estimator` (`frontend/src/app/estimator/page.tsx`) just wraps
  `<RooflineEstimator workspaceId=... />` in `<AppSidebar>`.
- The Photo Designer's 3 seasonal packages render **rep-side** in
  `frontend/src/components/estimator/estimate-panel.tsx` (`.ep-packages`); the
  rep picks one (`onSelectPackage`) and only that package's folded total reaches
  the client via `/p/compare`.
- Backend `get_public_comparison` (`backend/app/services/quotes/quote_service.py`)
  already computes `computed.christmas_packages` (all 3, priced) but returns only
  a single `christmas.total` in `PublicComparison`.
- `PublicComparison` schema + `ComparisonCard`
  (`frontend/src/components/estimator/comparison-card.tsx`) render one seasonal
  total, not packages.

## Request 1 — embed the Photo Designer into the Quotes tab

Make `/quotes` a tabbed hub and host the estimator inside it; remove the
separate sidebar entry so there is one quoting home.

- Convert `frontend/src/app/quotes/page.tsx` to a client page with a `Tabs`
  header driven by a `?tab=` search param (so the tab is deep-linkable and the
  command palette can point at it): **Quotes** (default, `<QuotesList />`) and
  **Photo Designer** (`<RooflineEstimator>`), with the panel given full height
  (`flex-1 min-h-0`) so the 3-pane tool fills the area.
- Keep the "Build a quote" -> `/sales-wizard` button (out of scope to embed the
  full wizard). Replace the "Design on a photo" button with the new tab.
- `frontend/src/app/estimator/page.tsx`: redirect to `/quotes?tab=designer`
  (keep the route working for existing deep links / command palette / bookmarks
  rather than 404).
- `frontend/src/components/layout/app-nav.ts`: set the `Photo Designer` item
  `sidebar: false` (mirrors the `christmas-lights` treatment) and point its
  `url` at `/quotes?tab=designer` so the command palette deep-links to the tab;
  leave the breadcrumb map intact.
- Verify the estimator renders correctly embedded (it owns its own topbar and
  full-height 3-pane layout; the tab panel must not clip it).

## Request 2 — present the 3 seasonal packages to the client

Interpretation (the genuine product decision): the homeowner should **see all
three Good/Better/Best seasonal packages as cards** on the existing client share
(`/p/compare/[token]`), instead of the rep pre-selecting one and the client
seeing a single seasonal total. The rep's pick becomes an optional
"Recommended" highlight, not a gate.

**Recommended scope (A) — presentational, low-risk, reuse-heavy:**
- Backend `backend/app/schemas/estimate.py`: add a feet-free
  `PublicComparisonPackage` (`key`, `label`, `name`, `marker`, `experience`,
  `points`, `value_tag`, `popular`, `includes_roofline`, `total`, `recommended`)
  and add `christmas_packages: list[PublicComparisonPackage] = []` to
  `PublicComparison`. **Only `total` crosses over from each
  `ChristmasPackagePricing.pricing` — never `roofline_feet`/`roofline_cost`.**
- Backend `get_public_comparison`: when `christmas.enabled` and packages exist,
  map `computed.christmas_packages` -> `PublicComparisonPackage[]`, flag
  `recommended` from `comparison.selected_package` (fallback: the most-inclusive,
  matching `resolveSelectedPackage`). Keep `christmas.total` as a sensible
  fallback (recommended/most-inclusive) for the à la carte / no-packages case so
  existing behavior is preserved when the list is empty.
- Regen contract: `make codegen` (commit `backend/openapi.json` +
  `frontend/src/lib/api/_generated.ts`).
- Frontend `comparison-card.tsx`: when `christmas_packages` is non-empty, render
  a package grid (reuse `.cmp-cards/.cmp-card`, `recommended` tag, price, perks)
  in place of the single seasonal card; keep the existing single-total seasonal
  card when the list is empty (à la carte). No client selection/commit in scope
  A (the comparison page is informational today; approve/pay lives on
  `/p/quotes`).
- Frontend `estimate-panel.tsx`: reframe the rep picker as "Mark recommended"
  (still drives which package is flagged on the client share); the three cards
  now surface to the client regardless of pick. No behavior removed the rep
  relies on — the seasonal headline keeps reflecting the recommended package.

**Alternative (B) — larger, NOT in this plan unless you redirect:** make
`create_quote_from_estimate` emit a 3-tier `proposal_document` so `/p/quotes`
shows the packages as **selectable tiers with approve/deposit** (reusing the
existing `pkg-grid` in `client-proposal-view.tsx`). This is a materially bigger
backend change (tier/financing mapping) on top of the just-shipped conversion.
Flagging it; default is A.

## Files to change

Backend:
- `backend/app/schemas/estimate.py` — new `PublicComparisonPackage`; extend
  `PublicComparison`.
- `backend/app/services/quotes/quote_service.py` — map packages in
  `get_public_comparison` (feet-free).
- `backend/openapi.json` — regenerated.
- `backend/tests/services/quotes/test_linear_feet_estimate.py` (or a public
  comparison test) — assert packages surface, are feet-free, and `recommended`
  is set correctly.

Frontend:
- `frontend/src/app/quotes/page.tsx` — tabbed hub (Quotes | Photo Designer).
- `frontend/src/app/estimator/page.tsx` — redirect to `/quotes?tab=designer`.
- `frontend/src/components/layout/app-nav.ts` — Photo Designer `sidebar:false`,
  url -> `/quotes?tab=designer`.
- `frontend/src/components/estimator/comparison-card.tsx` — render package grid.
- `frontend/src/components/estimator/estimate-panel.tsx` — "Recommended" reframe.
- `frontend/src/lib/api/_generated.ts` — regenerated.
- `frontend/src/components/estimator/estimator.css` — only if a client package
  grid needs minor layout tweaks (reuse existing `.cmp-*` first).
- Tests: `comparison-card` (renders 3 packages + recommended), quotes tab
  (renders designer tab), and update any nav/command-palette test touching the
  Photo Designer entry.

## Risks / edge cases

- **Feet privacy:** the new public schema must not carry feet/per-ft/roofline
  cost. Enforce by mapping only `total` + presentation fields; add a test that
  the serialized payload has no feet fields.
- **À la carte (packages disabled):** `christmas_packages` empty -> client card
  unchanged (single seasonal total). Must be preserved.
- **Embedded estimator height/scroll:** the 3-pane tool must fill the tab
  without clipping; verify at desktop + narrow widths.
- **Deep links / command palette / breadcrumb** for `/estimator` must keep
  working (redirect + nav url update).
- Reduced-motion / focus-visible on the new tab control (reuse `tabs.tsx`, which
  already handles this).

## Verification

- `make ci.codegen` (zero drift after committing regenerated artifacts).
- Backend: `uv run pytest tests/services/quotes/ -q` incl. new public-comparison
  package test (feet-free + recommended); `ruff` + `mypy` on changed files.
- Frontend: `npm run lint`, `npm run typecheck`, `npm test -- --run` (incl. new
  comparison-card + quotes-tab tests), `npm run build`.
- Probe: `.ezcoder/eyes/http.sh` GET a `/api/v1/.../comparisons/{token}` (or the
  public comparison route) and confirm the JSON carries `christmas_packages`
  with totals and **no** feet fields.
- Visual: screenshot `/quotes` (Photo Designer tab) and a `/p/compare/[token]`
  with packages at desktop + mobile widths; confirm 3 cards, recommended tag,
  readable contrast, no clipping.

## Steps

1. Backend: add `PublicComparisonPackage` (feet-free) and
   `christmas_packages: list[PublicComparisonPackage] = []` to `PublicComparison`
   in `backend/app/schemas/estimate.py`.
2. Backend: in `get_public_comparison`
   (`backend/app/services/quotes/quote_service.py`), map
   `computed.christmas_packages` to the feet-free shape (only `total` + copy),
   set `recommended` from `selected_package` (fallback most-inclusive), keep the
   single `christmas.total` fallback for the à la carte case.
3. Add/extend a backend test asserting the public comparison surfaces all 3
   packages, marks `recommended`, and exposes no feet/per-ft/roofline-cost field.
4. Run `make codegen`; commit regenerated `backend/openapi.json` +
   `frontend/src/lib/api/_generated.ts`.
5. Frontend: render a package grid in
   `frontend/src/components/estimator/comparison-card.tsx` when
   `christmas_packages` is non-empty (reuse `.cmp-cards/.cmp-card`, recommended
   tag, price, perks), preserving the single-total card when empty.
6. Frontend: reframe the rep picker in
   `frontend/src/components/estimator/estimate-panel.tsx` as "Mark recommended"
   (keeps flagging the client-highlighted package; all 3 now go to the client).
7. Frontend: convert `frontend/src/app/quotes/page.tsx` into a `Tabs` hub
   (Quotes | Photo Designer) driven by `?tab=`, hosting `<RooflineEstimator>`
   full-height; replace the "Design on a photo" button with the tab.
8. Frontend: redirect `frontend/src/app/estimator/page.tsx` to
   `/quotes?tab=designer`.
9. Frontend: in `frontend/src/components/layout/app-nav.ts` set the Photo
   Designer item `sidebar:false` and its `url` to `/quotes?tab=designer`; keep
   command-palette + breadcrumb working. Update any nav/command-palette test.
10. Add frontend tests: `comparison-card` renders 3 packages with the
    recommended highlight; the quotes page shows the Photo Designer tab and
    mounts the estimator.
11. Verify: `make ci.codegen`, backend pytest + ruff + mypy, frontend
    lint/typecheck/test/build; probe the public comparison JSON for
    `christmas_packages` (and no feet); screenshot `/quotes` designer tab and a
    `/p/compare` with packages at desktop + mobile.
