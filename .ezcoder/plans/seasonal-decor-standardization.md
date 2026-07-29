# Standardize seasonal decor (trees / bushes / wreaths / garland)

## Goal
Make every seasonal add‑on — trees, bushes, wreaths, **garland**, and anything
added later (bows, stakes, mini‑trees, timers) — a **data entry**, not new code.
One config shape, one pricing loop, one UI renderer. Then wire decor into the
`/estimator` rep tool, which today prices only the roofline.

## Current state (verified)
- `ChristmasConfig` (`backend/app/schemas/pricing.py`) has **three hardcoded**
  decor lists: `tree_rates`, `bush_rates`, `wreath_rates` — each `list[SizeRate]`
  (`key`/`name`/`price`), each with defaults, all priced **per item**.
- `price_christmas` (`proposal_pricing.py`) prices them through one shared helper
  `_price_size_group`, and returns hardcoded `trees_cost`/`bushes_cost`/`wreaths_cost`
  on `ChristmasPricing`. Those three fields are read **only in tests**; the
  proposal renders `ChristmasPricing.lines` (a generic `list[CategoryLine]`).
- The **sales wizard** already surfaces them (`ChristmasSection` → reusable
  `CountGroup`), sends `WizardChristmasSelection {roofline_feet, trees[], bushes[],
  wreaths[], takedown, storage}`, and `proposal_builder._counts(...)` turns each
  into a `{key: qty}` dict.
- **Garland**: exists only as a label ("Wreaths & Garland") — no rate, no line.
  It is naturally priced **per linear foot** (like roofline/bistro), not per item.
- The **`/estimator`** tool (`LinearFeetEstimateRequest`) has **no decor fields**;
  its seasonal total is roofline‑only.

## Design decision (the standard)
Collapse all decor into ONE generic list with an explicit **unit**:

```python
# schemas/pricing.py
SeasonalUnit = Literal["each", "per_ft"]

class SizeRate(BaseModel):        # unchanged — the option/variant row
    key: str; name: str; price: float

class SeasonalItem(BaseModel):    # NEW — a decor category
    key: str                      # "trees" | "bushes" | "wreaths" | "garland" | ...
    label: str                    # "Trees", "Garland"
    unit: SeasonalUnit = "each"   # "each" = per item, "per_ft" = per linear foot
    options: list[SizeRate]       # variants ("Small tree"…) or one row ("Garland")

class ChristmasConfig(BaseModel):
    ...
    items: list[SeasonalItem] = Field(default_factory=_default_seasonal_items)
```

- Defaults: trees/bushes/wreaths as `each` (same prices as today) + **garland** as
  `per_ft` (one option, placeholder ~$8/ft). Same "sane defaults, operator tunes
  in Settings" pattern as the rest of the pricing block.
- **Selection shape** everywhere becomes uniform:
  `items: Mapping[str, Mapping[str, float]]` = categoryKey → optionKey → value,
  where value is a **count** for `each` and **linear feet** for `per_ft`.
- Garland is the one genuinely new concept: `unit="per_ft"`. Takedown keeps
  applying to the net install subtotal = roofline + Σ item nets (garland included).

### Backward compatibility (key risk mitigation)
`workspace.settings["pricing"]` is JSONB read leniently, and a live workspace may
already store `tree_rates/bush_rates/wreath_rates`. Add a
`@model_validator(mode="before")` on `ChristmasConfig` that, when `items` is absent
but any legacy `*_rates` key is present, builds `items` from them (each → `each`).
So old blobs and any in‑flight wizard payloads keep pricing identically; the three
legacy fields are dropped from the model but still *upgraded* on read. No DB
migration for the config itself.

## Scope / surfaces touched
- Backend: `schemas/pricing.py`, `services/quotes/proposal_pricing.py`,
  `schemas/proposal_wizard.py`, `services/quotes/proposal_builder.py`,
  `schemas/estimate.py`, `services/quotes/quote_service.py`,
  `models/roofline_comparison.py` (+ 1 additive migration for the estimator's
  persisted decor selection), `scripts/demo/seed_lighting_workspace.py`.
- Frontend: `sales-wizard/use-sales-wizard.ts`, `sales-wizard/builder-sections.tsx`,
  `estimator/roofline-estimator.tsx`, generated client.
- Tests: `test_proposal_pricing.py`, `test_wizard_flow.py`,
  `test_linear_feet_estimate.py`, `test_public_comparison.py`, wizard hook test.

## Pricing engine changes (`proposal_pricing.py`)
- Generalize `_price_size_group` → `_price_seasonal_item(item, selection, config)`:
  - `each`: `Σ gross(qty × option.price)`, one `CategoryLine` per selected option.
  - `per_ft`: `gross(feet × option.price)`, one `CategoryLine` per option with feet.
- `price_christmas(config, *, roofline_feet, items: Mapping[str, Mapping[str, float]],
  takedown, storage)` iterates `config.christmas.items`, builds `lines` + a generic
  `items: list[SeasonalItemCost]` (`key`, `label`, `cost`). Keep `roofline_cost`,
  `takedown_cost`, `storage_cost`, `raw_total`, `total`, `min_applied`, `lines`.
- `ChristmasPricing`: drop `trees_cost/bushes_cost/wreaths_cost`, add
  `items: list[SeasonalItemCost]`. `.lines` output/display unchanged.

## Estimator wiring
- `LinearFeetEstimateRequest`: add `christmas_items: dict[str, dict[str, float]] = {}`.
- `LinearFeetEstimateResult.christmas` (`ChristmasEstimate`): add `items:
  list[SeasonalItemCost]` (priced breakdown) so the client total is explainable.
- Add a **catalog** on the result so the rep UI can render controls without a
  second request: `LinearFeetEstimateResult.christmas_catalog: list[SeasonalItem]`
  (echo of `config.christmas.items`, feet‑free, safe).
- `RooflineComparison`: add nullable `christmas_items` JSONB column (+ additive
  migration) so a shared comparison persists the rep's decor selection and the
  public page recomputes from live config. Public payload keeps only totals — no
  per‑ft rate, no linear feet — so nothing new leaks.
- `_compute_comparison` passes `christmas_items` into `price_christmas`.

## Frontend
- `use-sales-wizard.ts`: replace the fixed `ChristmasGroup`/`ChristmasDraft` decor
  fields with a dynamic `items: Record<string, Record<string, number>>` and
  `setSeasonalItem(categoryKey, optionKey, value)`; submit `items` map.
- `builder-sections.tsx`: render categories from `cfg.items` — steppers for
  `each`, a linear‑feet input for `per_ft` (garland). Removes the three hardcoded
  `CountGroup`s (the component stays, driven by data). Give garland its own section
  and fix the misleading "Wreaths & Garland" label → "Wreaths".
- `estimator/roofline-estimator.tsx`: from `estimate.christmas_catalog`, render the
  same generic controls under the seasonal side; feed selections back as
  `christmas_items` in `estimateParams` (already the query key + share payload).

## Risks & mitigations
- **Tested pricing engine**: `test_proposal_pricing.py` christmas asserts the three
  `*_cost` fields — update to assert the generic `items` breakdown; math values
  unchanged. Keep the exact gross‑up/rounding path.
- **Stored config drift**: covered by the `mode="before"` legacy upgrade validator;
  add a unit test that a legacy `{tree_rates,…}` blob yields identical prices.
- **Public leak**: garland introduces a per‑ft rate → ensure it stays server‑side;
  the public comparison exposes only `total`s. Extend the existing no‑leak
  integration test to include a garland selection and assert the $/ft is absent.
- **Contract drift**: `make codegen` + commit `openapi.json` and `_generated.ts`.

## Verification
- `make ci.backend` (ruff/mypy/pytest) + the christmas/estimator suites green.
- Migration up→check→down→up clean, no autogen drift.
- Live probes: (a) wizard christmas breakdown includes a garland line at $/ft;
  (b) `/estimator` seasonal total moves when decor is added; (c) public compare
  payload for a garland selection carries no per‑ft rate / no feet.
- `tsc` + `eslint` + `next build`; screenshot the estimator seasonal decor controls.

## Steps
1. `schemas/pricing.py`: add `SeasonalUnit`, `SeasonalItem`, `SeasonalItemCost`; add `_default_seasonal_items()` (trees/bushes/wreaths `each` + garland `per_ft`); add `ChristmasConfig.items`; add a `mode="before"` validator that upgrades legacy `tree_rates`/`bush_rates`/`wreath_rates` into `items`; remove the three legacy fields from the model; replace `ChristmasPricing.{trees,bushes,wreaths}_cost` with `items: list[SeasonalItemCost]`.
2. `proposal_pricing.py`: replace `_price_size_group` with `_price_seasonal_item` (handles `each` + `per_ft`); rewrite `price_christmas` to take a generic `items` mapping, iterate `config.christmas.items`, and emit `lines` + `items` breakdown; keep roofline/takedown/storage/minimum math identical.
3. `schemas/proposal_wizard.py`: replace `WizardChristmasSelection.{trees,bushes,wreaths}` with a generic `items: dict[str, list[WizardCategoryCount]]` (keep `roofline_feet`/`takedown`/`storage`).
4. `proposal_builder.py`: build the generic `items` mapping via `_counts(...)` and pass it to `price_christmas`.
5. `scripts/demo/seed_lighting_workspace.py`: rewrite the christmas block to the new `items` shape (trees/bushes/wreaths + garland per‑ft).
6. `schemas/estimate.py`: add `LinearFeetEstimateRequest.christmas_items`; add `ChristmasEstimate.items`; add `LinearFeetEstimateResult.christmas_catalog`.
7. `models/roofline_comparison.py`: add nullable `christmas_items` JSONB column; generate + apply an additive migration; verify up→check→down→up.
8. `quote_service._compute_comparison`: thread `christmas_items` into `price_christmas`, populate `christmas.items` + `christmas_catalog`; persist/read `christmas_items` on share/public recompute.
9. `make codegen`; commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts`.
10. `use-sales-wizard.ts`: generalize christmas decor state to a dynamic `items` map + `setSeasonalItem`; update the submit payload.
11. `builder-sections.tsx`: render seasonal categories from `cfg.items` (steppers for `each`, feet input for `per_ft`); fix the "Wreaths & Garland" label.
12. `estimator/roofline-estimator.tsx`: render decor controls from `estimate.christmas_catalog` and feed `christmas_items` into the estimate/share params.
13. Update backend tests: rewrite `test_proposal_pricing.py` christmas asserts to the `items` breakdown; add a legacy‑blob upgrade test; add garland (`per_ft`) pricing test; extend estimator unit + no‑leak integration tests to include decor/garland; fix `test_wizard_flow.py` payload shape.
14. Update the wizard hook frontend test for the generic `items` shape.
15. Verify: `make ci.backend`, migration round‑trip, `tsc`/`eslint`/`next build`; live probes for wizard garland line, estimator seasonal decor total, and a garland public‑compare no‑leak check; screenshot the estimator decor controls.
