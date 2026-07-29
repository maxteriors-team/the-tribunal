# Roofline "measure-as-you-draw" in the sales wizard

## Goal
Close the gap vs. Holiday Home Concepts: let a rep **trace the roofline on the home photo and have it (1) render as a lit C9 strand in the night preview AND (2) set the seasonal `roofline_feet` that drives the live Christmas price** — one draw, no re-typing footage. This fuses the two photo tools we already have.

## Key finding — most of this already exists
- The **measurement math is built and unit-tested**: `frontend/src/lib/estimator/measure.ts` exports `REFERENCE_PRESETS`, `pxPerFoot`, `polylineLength`, `rooflineFeet`, `Point`. Tests: `frontend/src/lib/estimator/measure.test.ts`.
- The **polyline-trace canvas pattern** is proven in `frontend/src/components/estimator/roofline-estimator.tsx` (mark a 2-point reference of known width → trace the roofline → live feet).
- The **night-mode canvas + additive glow rendering** is in `frontend/src/components/sales-wizard/night-preview-screen.tsx` (upload photo, drop lights, composite to a JPEG the proposal shows).
- The **price already flows from feet**: the wizard payload's `christmas.roofline_feet` (`use-sales-wizard.ts`) → `wizard/preview` + `wizard` save → `QuoteService` → `price_christmas`. Proven earlier over real HTTP: `feet=100` → roofline `$600`.

So this is a **fusion job on the frontend only**. No backend, schema, migration, or codegen changes: `night_preview` is already an opaque `dict[str, Any]` in `ProposalWizardPayload`, and `roofline_feet` already exists end-to-end.

## Design decision
Add a **"Roofline (measure)" mode** to the wizard's `NightPreviewScreen`, alongside the existing tap-to-drop "Lights" mode. Reuse `measure.ts` verbatim for the math. Render the traced roofline as an evenly-spaced **C9 bulb strand** (warm glowing bulbs) using the file's existing additive-glow style, so the composite looks like Christmas lights on the eaves — not a plain line. When a calibrated trace exists, push the rounded feet into `christmas.roofline_feet` and auto-enable the `christmas` category, so the price updates live via the existing preview pipeline.

Chosen over "push from the standalone estimator into the wizard" because the user asked for a single draw-on-the-photo motion inside the proposal flow, and it keeps the estimator tool untouched.

## Data flow
1. Rep opens Night Mode (`enhancements-step.tsx` → `onOpenNight`), uploads/【re-uses】 the photo.
2. Switches to **Roofline** mode → picks a reference preset (front door / garage, from `REFERENCE_PRESETS`) → clicks 2 points on that object → clicks along the eaves.
3. `rooflineFeet(roofline, reference, referenceFeet)` computes live feet; a readout shows "≈ NN ft".
4. On change, wizard calls `setChristmas({ roofline_feet: String(feet) })` and, if not already on, `toggleCategory("christmas")`.
5. `use-sales-wizard` debounced preview re-prices; the wizard's Christmas total updates with no manual footage entry.
6. Reference + roofline points + preset persist in `night` state so re-opening the screen restores the trace; they ride into the saved snapshot's opaque `night_preview` (no schema change).
7. `compositeDataURL()` includes the C9 strand, so the client proposal image shows the lit roofline.

## Files to change (frontend only)
- `frontend/src/lib/estimator/measure.ts` — add ONE pure helper `c9BulbPositions(polyline: Point[], spacingPx: number): Point[]` (evenly spaced points along a polyline for bulb placement). Pure + unit-testable; no canvas.
- `frontend/src/lib/estimator/measure.test.ts` — add cases for `c9BulbPositions` (empty/<2 points → [], even spacing count on a known-length line, endpoints included).
- `frontend/src/components/sales-wizard/use-sales-wizard.ts` — extend `NightPreviewState` with `roofline` measurement fields:
  - `referenceKey: string`, `referencePts: Point[]`, `rooflinePts: Point[]` (import `Point` from `@/lib/estimator/measure`).
  - Initialize in the `night` default; already threaded through `setNight`, the `payload.night_preview` object, and the return value — extend those three spots to carry the new fields.
- `frontend/src/components/sales-wizard/night-preview-screen.tsx` —
  - Add a mode toggle: **Lights** (existing) vs **Roofline (measure)**.
  - In Roofline mode: reference-preset `<select>` (reuse `REFERENCE_PRESETS`), 2-click reference capture (3rd click restarts, mirroring the estimator), then multi-click roofline polyline; Undo/Clear scoped to the active sub-path.
  - Draw reference (gold line) + roofline as a **C9 bulb strand** via `c9BulbPositions` + the existing bulb-glow drawing (reuse the bistro bulb gradient style).
  - Live "≈ NN ft" + "Not calibrated yet" states from `rooflineFeet`/`pxPerFoot`.
  - On a valid calibrated trace, call `wizard.setChristmas({ roofline_feet: String(feet) })` and enable `christmas` category; seed local state from `wizard.night` on mount for continuity.
  - Include the C9 strand in `compositeDataURL()` and the live `draw()`.
- `frontend/src/components/sales-wizard/enhancements-step.tsx` — copy tweak on the night-launch button/subtext to mention "trace your roofline to auto-measure" (small, optional).
- `frontend/src/components/sales-wizard/theme.css` (or existing night styles) — styles for the mode toggle + feet readout, matching existing `night-*` classes.

## Explicitly out of scope
- No backend/schema/migration/codegen changes (feet + opaque night_preview already supported).
- No changes to the standalone `RooflineEstimator` or `/estimator` page.
- Perspective correction / auto edge-detection (HHC doesn't do true photogrammetry either; a known-reference scale is the accepted approximation — documented in `measure.ts`).

## Risks & mitigations
- **Accuracy is approximate** (single-reference 2D scale). Mitigation: it matches the existing estimator's accepted method; show "≈" and keep `roofline_feet` editable in `builder-sections.tsx` so the rep can correct.
- **Overwriting a manually-typed roofline_feet.** Mitigation: only write from the trace when a calibrated roofline exists; the manual field stays the source of truth otherwise, and the trace write is an explicit result of drawing.
- **Snapshot size.** Only points (tiny) are added to `night_preview`; the composite JPEG already exists. No meaningful size change.
- **Category side effect.** Auto-enabling `christmas` on trace is intended; guard so it only fires when feet > 0 to avoid surprise toggles.

## Verification
- **Pure math:** `npm run test` — new `c9BulbPositions` cases + existing `measure.test.ts` green.
- **Pricing wiring (real HTTP):** with a minted workspace token, POST `wizard/preview` with `christmas.roofline_feet` from a representative trace and confirm the seasonal total matches the standalone estimate (feet=100 → $600 baseline already confirmed). Use `.ezcoder/eyes/http.sh`.
- **Static:** `npx tsc --noEmit`, `npx eslint` on changed files, `npm run build`.
- **Visual (blocked):** the wizard/night canvas is behind auth; no verified visual probe + no E2E creds in this checkout. Will surface this as the one gap rather than claim a screenshot. If `E2E_USER_EMAIL/PASSWORD` are provided, add a Playwright check that opens Night Mode, traces a reference+roofline, and asserts the feet readout + Christmas total update.

## Steps
1. Add pure helper `c9BulbPositions(polyline, spacingPx)` to `frontend/src/lib/estimator/measure.ts` and unit tests in `measure.test.ts` (empty/<2 → [], endpoints included, even-spacing count on a known length).
2. Extend `NightPreviewState` in `frontend/src/components/sales-wizard/use-sales-wizard.ts` with `referenceKey`, `referencePts`, `rooflinePts` (import `Point` from `@/lib/estimator/measure`); update the `night` default, the `payload.night_preview` object, and the returned state to carry them.
3. In `night-preview-screen.tsx`, add a **Lights / Roofline** mode toggle and seed local roofline state from `wizard.night` on mount.
4. Implement Roofline mode: reference-preset select (from `REFERENCE_PRESETS`), 2-click reference capture with restart-on-3rd-click, and multi-click roofline polyline with Undo/Clear scoped to the active path.
5. Render the reference line (gold) and the roofline as a **C9 bulb strand** using `c9BulbPositions` + the existing bulb-glow drawing, in both live `draw()` and `compositeDataURL()`.
6. Show a live "≈ NN ft" / "not calibrated" readout via `rooflineFeet`/`pxPerFoot`; on a valid calibrated trace call `wizard.setChristmas({ roofline_feet: String(feet) })` and enable the `christmas` category when feet > 0.
7. Add night-mode styles for the toggle + feet readout in `theme.css` (reusing `night-*` classes) and a small copy tweak in `enhancements-step.tsx`.
8. Verify: `npm run test` (new + existing math), `npx tsc --noEmit`, `npx eslint` on changed files, `npm run build`; then drive `wizard/preview` over real HTTP with a traced `roofline_feet` and confirm the seasonal total matches the estimator baseline. Note the auth-gated visual check as the one unproven surface unless E2E creds are supplied.
