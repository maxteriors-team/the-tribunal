# Christmas service split + client-visible roofline cost comparison flag

Two changes requested:

1. **Client-visible feature flag** that shows the roofline cost comparison between Christmas and permanent lighting.
2. **Split the Christmas light quote into its own service path**, branched apart from all other services (landscape lighting etc.).

> **Revision note (review feedback):** the previous draft grouped services as
> `holiday = ("permanent", "christmas")`, which left Christmas fused to permanent
> and therefore did not split it at all. This revision makes the split **3-way**:
> `landscape`, `permanent`, `christmas` are each their own service path.

## What the code actually does today

Verified by reading, not assumed:

- **Pricing config is JSONB.** `workspace.settings["pricing"]` read leniently through `PricingSettings` (`backend/app/services/quotes/pricing_config.py`). **Adding config fields needs no Alembic migration and touches no contact/lead tables** — zero prod-data risk.
- `PricingSettingsUpdate` (`backend/app/schemas/pricing.py:642`) already supports partial **top-level** keys including `comparison_years`, so a new top-level flag saves through the existing `PUT /workspaces/{id}/pricing`.
- **Product lines** are `CATEGORY_ORDER = ("landscape", "permanent", "bistro", "christmas")` (`backend/app/schemas/proposal_wizard.py:24`).
- The frontend groups those four lines into **two** services today (`category-step.tsx:75`): `landscape` = {landscape, bistro}, `holiday` = {permanent, christmas}. Its own docstring says "the selections still combine into a single quote", and `toggleCategory` (`use-sales-wizard.ts:394`) freely mixes across groups. **So Christmas is currently fused to permanent AND mixable with landscape** — both fusions have to go.
- `SERVICE_ACCENTS` (`category-step.tsx:70`) has two keys, `landscape` (gold `#d4af5a`) and `holiday` (evergreen `#3fa66a`), consumed at `category-step.tsx:80,88` and `calculator-screen.tsx:365,408`.
- `calculator-screen.tsx:155` derives `hasSeasonal = hasCategory("permanent") || hasCategory("christmas")` and renders **one shared step** (`id: "seasonal"`, label `"Seasonal"`, tag hardcoded `"Christmas & Holiday Lighting"`) containing both `PermanentSection` and `ChristmasSection`. That shared step is exactly the fusion to break.
- Public comparison payload `PublicComparison` (`backend/app/schemas/estimate.py:253`) carries totals only. The module enforces a **feet-privacy contract by construction**: no `feet` / `per_ft` / `channels` field exists on any public model, deliberately.
- Both `PermanentPricing` and `ChristmasPricing` already carry `roofline_cost` (`pricing.py:582`, `:610`) — so a roofline-only cost comparison is computable **without** exposing feet.
- `frontend/src/components/ui/dropdown-menu.tsx` exists, so a service-scoped "Build a quote" menu reuses an existing primitive.
- Settings UI for seasonal lives at `frontend/src/components/settings/seasonal-pricing-settings-tab.tsx`, which already has a `packages_enabled` toggle to copy.

## Interpretation of ask #1 (stated, because it is an inference)

"Roofline cost comparison" is read as a **roofline-only, like-for-like cost comparison**. Today the seasonal total can include decor (trees/bushes/wreaths), so comparing it to permanent (roofline track) is apples-to-oranges. The new flag adds an honest roofline-vs-roofline block: permanent roofline one-time cost vs seasonal roofline per-season cost, projected over `comparison_years`.

- Flag defaults **off** → every existing workspace and every already-shared link renders exactly as it does now.
- The block stays **feet-free** (costs only), preserving the module's privacy contract.

### Why a cross-service card is still coherent under a 3-way split

The roofline comparison lives on the **estimator's** `/p/compare/[token]` page (`RooflineComparison` model), which is a standalone "which of these two should you buy" pitch — not a quote. That artifact is *intentionally* cross-service; it is the bridge between the permanent and christmas paths. A **quote** is single-service. Keeping those two rules distinct is the point: the compare page sells across paths, the quote commits to one.

## ⚠️ Product decision to confirm — how hard to enforce the split

`backend/tests/services/quotes/test_wizard_flow.py:366` is named `test_combined_multi_category_quote_prices_and_saves_all_lines` and **explicitly asserts that a quote mixing `landscape + permanent + christmas` prices every line and combines totals**. That is a currently-supported, deliberately-tested capability.

- **Option A (this plan's default): branch the rep experience, keep the API permissive.** The wizard enforces one service per quote; the backend records which service path a quote came from but still accepts mixed payloads. Existing test and any live integration keep working. Reversible.
- **Option B: also reject mixed payloads server-side (422).** Truly hard-split, but it deletes a tested capability and breaks any caller that mixes.

**Proceeding with Option A.** It delivers the branch where reps actually work, adds durable per-service metadata, and risks nothing. Say the word and B is a small follow-up (one validator + retiring that test).

## Design

### Part 1 — roofline cost comparison flag

Backend:

- `backend/app/schemas/pricing.py`
  - Add `PricingSettings.roofline_comparison_enabled: bool = False`, next to `comparison_years` (comparison config already lives top-level, not under `christmas`).
  - Add the same field to `PricingSettingsUpdate` as `bool | None = None`.
- `backend/app/schemas/estimate.py`
  - Add `roofline_cost: float` to `PermanentEstimate` and `ChristmasEstimate` (rep-side views that already expose `per_ft`).
  - Add a new public model, feet-free by construction:
    ```python
    class PublicRooflineComparison(BaseModel):
        permanent_total: float       # one-time roofline install
        seasonal_total: float        # roofline only, per season
        seasonal_multi_year: float   # seasonal_total * years
        savings: float               # seasonal_multi_year - permanent_total
    ```
  - Add `PublicComparison.roofline: PublicRooflineComparison | None = None` (None when the flag is off, or when either side is disabled).
- `backend/app/services/quotes/quote_service.py`
  - `_compute_comparison`: populate the new `roofline_cost` on both sides from the existing `perm` / `xmas` pricing objects.
  - `get_public_comparison`: when `config.roofline_comparison_enabled` **and** both sides enabled, build the `roofline` block.
    - Use the **à la carte** seasonal roofline cost, not the recommended package's, on purpose: a package with `includes_roofline=False` has `roofline_cost == 0`, which would render a misleading `$0`. The à la carte figure is the true "what the roofline alone costs each season" and is always well-defined. Comment this in code.

Frontend:

- `frontend/src/components/estimator/comparison-card.tsx`: extend `ComparisonView` with an optional `roofline` block; render a "Roofline, side by side" section when present. Reuse existing `.cmp-*` classes so it inherits the festive theme automatically.
- `frontend/src/app/p/compare/[token]/page.tsx`: map `data.roofline` into the view.
- `frontend/src/components/estimator/roofline-estimator.tsx`: map it into `clientView` too so the rep preview matches what the client sees.
- `frontend/src/components/settings/seasonal-pricing-settings-tab.tsx`: add the toggle beside the packages toggle, with copy stating clients will see it. Its mutation currently sends `{ christmas }`; extend to `{ christmas, roofline_comparison_enabled }`.

### Part 2 — three separate service paths (Option A)

Backend (metadata only, no rejection):

- `backend/app/schemas/proposal_wizard.py`
  ```python
  SERVICE_CATEGORIES: dict[str, tuple[str, ...]] = {
      "landscape": ("landscape", "bistro"),
      "permanent": ("permanent",),
      "christmas": ("christmas",),
  }
  def service_for_categories(categories: Sequence[str]) -> str | None:
      """"landscape" | "permanent" | "christmas" | "mixed" | None.

      "mixed" when the selection spans more than one service path.
      """
  ```
- Add `ProposalDocument.service: str | None = None`.
- `backend/app/services/quotes/proposal_builder.py`: set `service=service_for_categories(categories)` on the built document.

Frontend — the real branch:

- `frontend/src/components/sales-wizard/use-sales-wizard.ts`
  - Export `SERVICE_CATEGORIES` (mirroring the backend) and `ServiceKey = "landscape" | "permanent" | "christmas"`.
  - Derive `activeService` from the current `categories`.
  - Add `setService(key)`: replaces the selection with that service's lines, so switching branch can never leave a cross-service mix. For the two single-line services this selects their sole line; for `landscape` it selects `landscape` (bistro stays an opt-in line chip).
  - Make `toggleCategory` **service-scoped**: toggling a line belonging to another service switches the branch (via `setService`) instead of adding across services. Within the active service, line toggling keeps today's permissive behavior (no new "can't be empty" guard — that matches current code, which already allows an empty selection).
- `frontend/src/components/sales-wizard/category-step.tsx`
  - Three service groups, chosen exclusively: **Landscape Lighting**, **Holiday Lights — Permanent**, **Christmas & Holiday Lighting** (seasonal).
  - Selecting a service sets the branch. Only the active service's line chips render; `landscape` is the only service with more than one line (landscape + bistro), so it is the only one that still shows an inner chip list.
  - `SERVICE_ACCENTS` becomes three keys: `landscape` gold `#d4af5a` (unchanged), `christmas` evergreen `#3fa66a` (**reuses the current `holiday` value so the Christmas path keeps its existing accent**), and `permanent` a cool ice tone (`#6aa9d4`) for year-round LED track. The `holiday` key is **renamed to `christmas`**; update both consumers at `calculator-screen.tsx:365,408` and grep for any other `SERVICE_ACCENTS.holiday` reference.
- `frontend/src/components/sales-wizard/calculator-screen.tsx`
  - The shared `"seasonal"` step currently hardcodes label `"Seasonal"` and tag `"Christmas & Holiday Lighting"` for both lines. Derive the visible step **label**, heading, and `ServiceTag` (label + accent) from `activeService` — "Permanent" vs "Seasonal" — so the permanent path stops being presented as Christmas. Keep the internal step id `"seasonal"` so step ordering/machinery is untouched (limits churn; the id is not user-visible).
  - Because selection is exclusive, at most one of `PermanentSection` / `ChristmasSection` can render; the existing `hasCategory` guards already express that and stay as-is.
  - Update the product-lines copy at `:343` ("each one gets its own section, and the totals combine into one quote") to reflect one service per quote.
- `frontend/src/components/sales-wizard/night-preview-screen.tsx:419-425`: the effect pushes measured feet into `christmas.roofline_feet` and calls `toggleCategory("christmas")`. Guard it to fire **only when `activeService === "christmas"`**, so measuring on a landscape or permanent quote can never silently jump service paths. Routing measured feet into `permanent.feet` on the permanent path is **explicitly out of scope** (new behavior, not requested).
- `frontend/src/app/quotes/page.tsx:53-60`: replace the single "Build a quote" button with a `DropdownMenu` (existing primitive) offering the three service-scoped entries, so the branch starts at the hub.
- Sales-wizard route: read `?service=` and preselect that branch via `setService`.

## Risks

- **No migration, no prod-data risk** — config is JSONB, flag defaults off.
- Flag off by default means no visible change until an operator opts in; verification must explicitly enable it.
- Exclusive selection is a **behavior change for reps** mid-quote: switching service replaces the previous service's lines. Must be obvious in the UI, not silent.
- `night-preview` auto-enable is the sneaky cross-service path — explicitly guarded above.
- Renaming `SERVICE_ACCENTS.holiday` → `christmas` is a breaking rename inside the module; all consumers must be updated in the same change or the wizard steps lose their accent.
- OpenAPI contract changes → `make codegen` and commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` **in the same commit** (`codegen/check` diffs against HEAD).

## Verification

- Backend: extend `backend/tests/services/quotes/test_linear_feet_estimate.py` — flag off ⇒ `roofline is None`; flag on ⇒ correct costs; assert the serialized public payload contains no `feet` / `per_ft` / `roofline_feet` key. Extend `test_wizard_flow.py` — `service == "christmas"` for the Christmas-only quote, `"permanent"` for a permanent-only quote, `"mixed"` for the existing combined quote (that test keeps passing unchanged under Option A).
- Frontend: `comparison-card.test.tsx` — roofline block renders when `roofline` present, absent otherwise. Sales-wizard test — selecting the Christmas service clears landscape **and** permanent lines, and selecting permanent clears christmas (proving the 3-way split, not just landscape-vs-holiday).
- Runtime: enable the flag on the local test workspace, hit `.ezcoder/eyes/http.sh` on the public compare endpoint, confirm the `roofline` block appears and is feet-free; screenshot `/p/compare/[token]` at desktop + mobile.
- Gate: `make ci.all` must exit 0.

## Steps

1. Add `roofline_comparison_enabled: bool = False` to `PricingSettings` and `bool | None = None` to `PricingSettingsUpdate` in `backend/app/schemas/pricing.py`.
2. Add `roofline_cost: float` to `PermanentEstimate` and `ChristmasEstimate`, add the `PublicRooflineComparison` model, and add the optional `roofline` field to `PublicComparison` in `backend/app/schemas/estimate.py`.
3. Populate `roofline_cost` on both estimate sides in `QuoteService._compute_comparison` in `backend/app/services/quotes/quote_service.py`.
4. Build the `roofline` block in `QuoteService.get_public_comparison`, gated on `roofline_comparison_enabled` and both sides enabled, using the à la carte seasonal roofline cost (with the comment explaining why, not the package's).
5. Add the 3-way `SERVICE_CATEGORIES`, `service_for_categories()`, and `ProposalDocument.service` to `backend/app/schemas/proposal_wizard.py`.
6. Set `service=service_for_categories(categories)` on the built document in `backend/app/services/quotes/proposal_builder.py`.
7. Extend `backend/tests/services/quotes/test_linear_feet_estimate.py` with flag-off / flag-on cases and an assertion that the public payload exposes no feet or per-foot keys.
8. Extend `backend/tests/services/quotes/test_wizard_flow.py` to assert `service` is `"christmas"`, `"permanent"`, and `"mixed"` for the christmas-only, permanent-only, and combined quotes.
9. Run `make codegen` and commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` together.
10. Add the client-visible roofline-comparison toggle to `frontend/src/components/settings/seasonal-pricing-settings-tab.tsx` and include `roofline_comparison_enabled` in its save mutation.
11. Extend `ComparisonView` and render the roofline side-by-side section in `frontend/src/components/estimator/comparison-card.tsx` using existing `.cmp-*` classes.
12. Map the `roofline` block into the view in `frontend/src/app/p/compare/[token]/page.tsx` and into `clientView` in `frontend/src/components/estimator/roofline-estimator.tsx`.
13. Add `SERVICE_CATEGORIES`, `ServiceKey`, `activeService`, and `setService` to `frontend/src/components/sales-wizard/use-sales-wizard.ts`, and make `toggleCategory` switch branches instead of mixing across services.
14. Rework `frontend/src/components/sales-wizard/category-step.tsx` into a three-way exclusive service picker that renders only the active service's lines, and expand `SERVICE_ACCENTS` to `landscape` / `permanent` / `christmas` (renaming `holiday` → `christmas`).
15. Derive the shared `"seasonal"` step's label, heading, and `ServiceTag` from `activeService` in `frontend/src/components/sales-wizard/calculator-screen.tsx`, update its two `SERVICE_ACCENTS.holiday` references, and update the product-lines copy at `:343`.
16. Guard the `christmas` auto-enable effect in `frontend/src/components/sales-wizard/night-preview-screen.tsx` so it only fires when the active service is `christmas`.
17. Replace the single "Build a quote" button in `frontend/src/app/quotes/page.tsx` with a `DropdownMenu` of the three service-scoped entries, and have the sales-wizard route preselect the branch from `?service=`.
18. Add frontend tests: roofline block presence/absence in `comparison-card.test.tsx`, and 3-way service-exclusive selection in the sales-wizard tests.
19. Enable the flag on the local test workspace, verify the public compare endpoint with `.ezcoder/eyes/http.sh` (roofline block present, feet-free), and screenshot `/p/compare/[token]` at desktop and mobile.
20. Run `make ci.all` and fix any failures until it exits 0.
