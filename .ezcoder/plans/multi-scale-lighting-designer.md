# Multi-scale lighting designer

## Outcome

Add a second photo calibration and let each linear run choose **Scale 1** or **Scale 2**. This matches the perspective case in the supplied house photo: runs on the front projection use one pixels-per-foot ratio, while runs on the recessed plane use the other.

A run that crosses a depth boundary must still be drawn as two runs. A single scalar cannot accurately measure one polyline that spans two planes.

## Research findings

- `frontend/src/lib/estimator/types.ts` currently stores one `Design.calibration`; `Run` has no scale reference.
- `frontend/src/lib/estimator/design.ts::designScale` resolves one photo-wide `ftPerPx`, and `designToEstimateInputs` applies it to every run. This is the source of the incorrect footage and quote pricing.
- `frontend/src/lib/estimator/render.ts::drawScene` also uses one `pxPerFt` for every run, so bulb spacing in previews/exports would remain visually wrong unless rendering becomes run-aware too.
- `frontend/src/components/estimator/light-designer.tsx` separately calculates bistro lengths, permanent-complexity footage, and wire-circuit lengths with the global scale; all three must use the selected run scale.
- `frontend/src/components/estimator/light-canvas.tsx` owns calibration drawing/editing and the known-feet modal. Its tool draft key currently treats every calibration tool as identical, so the target scale must be part of that key to prevent a half-drawn Scale 1 reference from leaking into Scale 2.
- `frontend/src/components/estimator/tool-palette.tsx::RunOptions` is the existing selected-strand editor and is the correct place to tag a run.
- Existing seasonal/permanent quote APIs receive flattened estimate inputs, not the drawing document. The server recomputes pricing from those inputs, so this feature needs no database migration or quote API change.
- Server-backed landscape projects persist the shared `Design` shape, but the second-scale controls are unnecessary for top-down aerial plans. The UI will expose them only in the photo designer, keeping the backend landscape document contract unchanged.

## Data design

Use the smallest backward-compatible extension rather than replacing the existing calibration model:

- Add `ScaleSlot = 1 | 2`.
- Keep `Design.calibration` as Scale 1.
- Add optional `Design.secondaryCalibration` as Scale 2.
- Add optional `Run.scaleSlot`; an omitted value means Scale 1, so every existing drawing and undo snapshot keeps its current behavior without migration.
- Add an optional scale slot to the calibration tool/action so all existing callers continue targeting Scale 1.
- Centralize lookup in `designScale(design, photoWidth, scaleSlot = 1)` and `runScale(design, run, photoWidth)`. If malformed state tags a run as Scale 2 without a secondary calibration, fall back to Scale 1 rather than producing assumed or invalid footage.

This intentionally supports exactly two scales because that is the requested workflow; it avoids an ID-based calibration collection, migration logic, and calibration-management UI that the product does not currently need.

## Interaction design

- Keep the current Scale 1 control and label it explicitly once calibrated.
- After Scale 1 exists, show **Add Scale 2** in the photo canvas controls and photo tool palette. Once created, it becomes **Scale 2: N ft** and remains clickable for remeasurement.
- Calibration hints and the feet modal name the active scale, preventing an operator from silently overwriting the wrong reference.
- When a strand is selected and Scale 2 exists, `RunOptions` shows two accessible Scale 1/Scale 2 choice chips. Changing the choice immediately updates footage, bulb count/spacing, complexity totals, circuit lengths, and pricing.
- New runs default to Scale 1. The operator draws separate strands at a depth boundary and tags only the recessed/protruding strands as Scale 2.
- The customer preview remains clean: scale controls and calibration guides stay editor-only, while exported bulb spacing uses each run’s assigned scale.

## Files and changes

- `frontend/src/lib/estimator/types.ts`
  - Add `ScaleSlot`, `Run.scaleSlot`, `Design.secondaryCalibration`, and a calibration-tool target.
- `frontend/src/lib/estimator/design.ts`
  - Make scale resolution slot-aware and use `runScale` inside `designToEstimateInputs`.
- `frontend/src/components/estimator/editor-store.ts`
  - Extend `SET_CALIBRATION` with a slot and update the correct calibration while preserving undo/redo behavior.
- `frontend/src/components/estimator/light-canvas.tsx`
  - Calibrate, drag, label, and save the selected scale; add the Scale 2 canvas chip; include the slot in interaction reset state.
- `frontend/src/components/estimator/tool-palette.tsx`
  - Add photo-only Scale 2 setup and selected-run Scale 1/Scale 2 assignment controls.
- `frontend/src/components/estimator/light-designer.tsx`
  - Enable the second-scale palette only for the photo designer and replace global-scale run calculations in schedule, complexity, and circuit summaries.
- `frontend/src/lib/estimator/render.ts`
  - Resolve `pxPerFt` per saved run so canvas and exported bulb spacing agree with measured footage.
- `frontend/src/lib/estimator/design.test.ts`, `frontend/src/components/estimator/editor-store.test.ts`, `frontend/src/components/estimator/tool-palette.test.tsx`, `frontend/src/components/estimator/light-canvas.test.tsx`, and `frontend/src/lib/estimator/render.test.ts`
  - Cover backward compatibility, Scale 2 calibration/editing, run assignment, mixed-scale totals, and run-aware visual spacing.
- `frontend/src/components/estimator/estimator.css`
  - Add only any small state styles required by the new scale chips, reusing existing palette/canvas tokens.

## Risks and controls

- **Wrong quote totals:** all footage paths must use `runScale`; verify every `polylineLength(run.points)` caller after implementation.
- **Visual/price mismatch:** rendering and estimate conversion share the same resolver and receive regression tests with different scale ratios.
- **Old drawings changing:** missing `scaleSlot` always resolves to Scale 1, matching current behavior exactly.
- **Cross-plane runs remaining inaccurate:** UI copy will state that runs crossing a corner/depth change must be split.
- **Landscape persistence drift:** do not expose or serialize Scale 2 through aerial-plan controls; no backend/OpenAPI changes are required.
- **Stale calibration drafts:** include the scale slot in `toolDraftKey` and modal state so switching scales clears unfinished points.

## Verification

- A 400 px Scale 1 run and 400 px Scale 2 run produce different expected feet from their own references, and totals sum both correctly.
- Existing runs without `scaleSlot` retain the current Scale 1 footage.
- Selecting Scale 2 in `RunOptions` dispatches the run patch and updates estimate-derived UI.
- Drawing/editing Scale 2 does not overwrite Scale 1; switching between calibration slots does not reuse a stale point.
- Canvas and JPEG export place bulbs according to each run’s scale.
- Run targeted Vitest files, then `npm run typecheck`, `npm run lint`, and `make ci.frontend` from the repository root.

## Steps

1. Extend the estimator types and reducer with a backward-compatible Scale 2 calibration and per-run scale slot.
2. Add shared slot-aware scale helpers and apply them to estimate conversion, schedules, permanent complexity, and circuit lengths.
3. Make canvas rendering and exported bulb spacing resolve the scale for each run.
4. Add photo-only Scale 2 calibration controls, scale-specific modal/hints, and safe calibration editing behavior.
5. Add Scale 1/Scale 2 assignment controls to the selected-strand panel and clarify the split-at-depth-boundary workflow.
6. Add regression tests for reducer behavior, mixed-scale footage, run tagging, calibration interaction, and rendered spacing.
7. Run the targeted estimator tests, frontend typecheck/lint, and the complete frontend CI target; fix any failures.
