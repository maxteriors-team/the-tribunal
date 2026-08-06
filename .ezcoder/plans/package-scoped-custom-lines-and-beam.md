# Package-scoped custom line items + beam control

## Two findings that change the ask

### 1. The beam control already ships
`b75d94e3` added the full beam-angle path in HEAD:
- `frontend/src/lib/estimator/types.ts` — `BEAM_STYLES`, `DEFAULT_BEAM_ANGLE_DEG`,
  `clampBeamAngle`, `beamAngleFor`, `PlacedItem.beamAngleDeg`.
- `frontend/src/lib/estimator/render.ts` — `beamGeometry`, `beamHandlePos`, `beamAngleAt`.
- `frontend/src/components/estimator/tool-palette.tsx` → `FixtureOptions`: preset chips
  from `BEAM_ANGLE_OPTIONS`.
- `frontend/src/components/estimator/light-canvas.tsx:731` — drag the gold grip on the cone.

So the *type-level* work is done. What is missing is a continuous control: today a rep
picks one of a handful of preset chips, or drags a grip on the photo. Dragging on a photo
is imprecise on a laptop trackpad in a driveway, and the chips can't express "42°".

**Do:** add a range slider to `FixtureOptions` between the chips and the readout, wired to
the same `UPDATE_ITEM` / `beamAngleDeg` action, clamped by `MIN/MAX_BEAM_ANGLE_DEG`. No new
domain concepts, no schema change — this is purely a third input onto an existing field.

### 2. Per-package custom lines reverse a deliberate decision from yesterday
`EstimateCustomLine` is documented as **independent of packages** on purpose
(`backend/app/schemas/estimate.py:33-53`), and three tests lock it in:
`test_custom_lines_stay_out_of_package_totals`, `test_custom_lines_stay_out_of_the_roofline_comparison`,
`test_convert_carries_custom_lines_onto_a_package_quote`.

The ask is not "delete that" — it is "let a line *optionally* belong to one tier", so a rep
can put the bucket-truck day inside Best without it inflating Good. Both behaviors must
coexist, and the default must stay exactly what it is today.

## Model

Add `package_key: str | None = None` to `EstimateCustomLine`.

- `None` (default) → **today's behavior, byte-for-byte**: rides on top of whichever tier the
  client picks, reported in `custom_total`, excluded from every package card.
- Set → priced **inside that package's own card total** and nowhere else. Switching tiers
  re-prices, so the line follows the tier it was sold with.
- Names no priced package → **dropped**, matching the existing precedent for a line assigned
  to a disabled service (`quote_service.py:1987-1992`). Silent fallback to global would move
  money without the rep asking.

No migration: `roofline_comparisons.custom_lines` is JSONB and the field is additive with a
default, so every already-shared link keeps working and simply carries no package key.

Double-counting is the one real hazard: a scoped line lands in `pkg.pricing.total`, so it
must stay out of `christmas.custom_total`, which the frontend `seasonalTotal()` and the
server's `get_public_comparison` both add on top of a package total.

## Files

**Backend**
- `backend/app/schemas/estimate.py` — `package_key` field + docstring covering the three rules.
- `backend/app/services/quotes/quote_service.py`
  - `_price_custom_lines(lines, side)` → take `package_key` and filter on it.
  - `_compute_comparison` — global lines into `perm`/`xmas` as today; fold each package's
    scoped lines into that `ChristmasPackagePricing.pricing` via the existing
    `_with_custom_lines`; keep `custom_total` global-only; emit scoped lines on
    `result.custom_lines` so the rep panel can show them under their tier.
  - `_price_estimate_side` — the quote gets global + selected-package lines, folded exactly once.
  - `get_public_comparison` — recommended package total already carries its scoped lines;
    `custom_lines` surfaces global + recommended-package lines to the client.
- `backend/tests/services/quotes/test_linear_feet_estimate.py` and `test_public_comparison.py`
  — existing three tests stay green unchanged (proves the default is untouched); new cases for
  scoped-into-one-card, not-in-sibling-cards, dropped-on-unknown-key, and conversion.

**Frontend**
- `frontend/src/lib/estimator/custom-lines.ts` — `packageKey` on `CustomLineDraft`,
  carried through `toEstimateCustomLines`.
- `frontend/src/components/estimator/estimate-panel.tsx` — a package `<select>` on the row
  ("All packages" default + one option per priced tier), shown only when packages exist.
- `frontend/src/components/estimator/comparison-card.tsx` — a scoped line reads under its tier.
- `frontend/src/components/estimator/tool-palette.tsx` — the beam slider.
- `frontend/src/lib/estimator/custom-lines.test.ts`, `light-designer.test.tsx` — coverage.

**Codegen**: public schema changes → `make ci.codegen`, commit `backend/openapi.json` +
`frontend/src/lib/api/_generated.ts` in the same commit.

## Verification
- `cd backend && uv run pytest tests/services/quotes -q`
- `cd frontend && npx vitest run src/lib/estimator src/components/estimator`
- `.ezcoder/eyes/http.sh` POST against `/api/v1/quotes/estimate` with a scoped line, to
  confirm the tier card's total moved and `custom_total` did not.
- `make ci.codegen`

## Steps
1. Add `package_key: str | None = None` to `EstimateCustomLine` in `backend/app/schemas/estimate.py`, documenting the three rules (None = global/today, set = inside that card only, unknown = dropped).
2. Extend `QuoteService._price_custom_lines` in `backend/app/services/quotes/quote_service.py` to filter by `package_key` alongside `side`.
3. Update `_compute_comparison` to fold each package's scoped lines into that `ChristmasPackagePricing.pricing`, keep `custom_total` global-only, and emit scoped lines on `custom_lines`.
4. Update `_price_estimate_side` so a converted quote carries global + selected-package lines exactly once.
5. Update `get_public_comparison` so the client's headline and itemized `custom_lines` include the recommended package's scoped lines without double-counting.
6. Add backend tests in `backend/tests/services/quotes/test_linear_feet_estimate.py` and `test_public_comparison.py` for scoped-into-one-card, absent-from-siblings, dropped-unknown-key, and conversion; confirm the three existing package-independence tests still pass unchanged.
7. Add `packageKey` to `CustomLineDraft` and `toEstimateCustomLines` in `frontend/src/lib/estimator/custom-lines.ts`, with tests in `custom-lines.test.ts`.
8. Add the package `<select>` to the custom-line row in `frontend/src/components/estimator/estimate-panel.tsx`, shown only when priced packages exist, and pass the priced packages in from `light-designer.tsx`.
9. Render a scoped line under its tier in `frontend/src/components/estimator/comparison-card.tsx`.
10. Add the continuous beam-angle slider to `FixtureOptions` in `frontend/src/components/estimator/tool-palette.tsx`, wired to `UPDATE_ITEM`/`beamAngleDeg` and clamped by `MIN/MAX_BEAM_ANGLE_DEG`.
11. Run `make ci.codegen` and commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts`.
12. Run backend and frontend test suites, then probe `/api/v1/quotes/estimate` with `.ezcoder/eyes/http.sh` to confirm a scoped line moves its tier total and not `custom_total`.
