# Christmas Light Estimator — bulb size/color + permanent lighting & per-ft pricing

## Goal (from the request)
1. **Change bulb size and color** in the estimator.
2. **Add a permanent holiday lighting option** in the estimator, **with an editable per-linear-foot price**.

## What already exists (verified by reading source)
- **Bulb color — already works.** `tool-palette.tsx` → `RunOptions` renders a "Colors" `<select>` bound to `COLOR_PRESETS` (catalog.ts) and writes a per-run override via `UPDATE_RUN { colors }`. `Run.colors` + `withRunOverrides` + `drawRunLights` all honor it.
- **Bulb spacing — already works** (chip row in `RunOptions`, `Run.spacingIn`).
- **Permanent pricing — computed end-to-end already.** Backend `PermanentConfig.per_ft` (default 32, `enabled` default False) → `estimate.permanent { enabled, per_ft, total }` → `EstimatePanel` "Permanent · one-time" + `ComparisonCard`. The estimator even has a per-estimate internal `Permanent $/ft` *override* input. The **same measured roofline `feet` drives both** the permanent and seasonal sides (catalog.ts comment + `design.ts`).
- **Save path for the permanent block exists.** `salesWizardApi.updatePricing(workspaceId, { permanent })` (block-replace), `PricingSettingsUpdate.permanent`, and frontend type `PermanentConfig` are all present.
- **Permanent icon exists** — `seasonal-icons.ts` has a `permanent` spec (Cable glyph); render.ts has a `permanent` style.

## What is actually missing (the real work — all frontend)
- **Bulb size:** no size concept for linear light runs. Add a per-run bulb-size scale + a "Bulb size" control next to the existing Colors/Spacing controls, applied as a radius multiplier in the glow engine. Visual only (never touches pricing — mirrors how color/spacing already behave).
- **Permanent option in the estimator:** `buildCatalog` builds seasonal products only. Add a drawable **Permanent LED roofline** product (existing `permanent` render style, targets roofline `feet`), gated on `estimate.permanent.enabled`, so the rep can visualize/sell permanent.
- **Permanent per-ft pricing editor:** Settings → Pricing (`SeasonalPricingSettingsTab`) only edits the `christmas` block. Add a **Permanent Holiday Lighting** card (enabled + per-ft rate as the headline knob, plus controller/channel/minimum/label) that saves the `permanent` block via the existing `updatePricing`.

## Scope decisions / constraints
- **Frontend-only. No backend, no `make codegen`, no migration.** `PermanentConfig` and the estimate `permanent` fields already ship in `backend/openapi.json` + `_generated.ts`.
- **`Product.bulbScale` / `Run.bulbScale` are OPTIONAL** (`?: number`, render uses `?? 1`). Keeps existing `Product` literals (e.g. `render.test.ts` fixtures, ai-render) type-clean — no churn.
- **Bulb size is visual-only.** `design.ts` maps runs → feet by `polylineLength × ftPerPx` regardless of size/color, so pricing is unaffected. Confirmed.
- **Permanent draw product reuses the shared roofline `feet`** (like the existing warm/multicolor roofline pair) — it's another visual for the one measured roofline, not a second additive run. Gated by `estimate.permanent.enabled` so it only appears when the workspace sells permanent. No double pricing path.
- Reuse existing CSS (`.tp-chip-row`, `.tp-spacing-chip`, `.tp-opt-label`, `.est-select`) — no new stylesheet rules needed for bulb size.
- The permanent pricing card reads the **same** `queryKeys.salesWizard.pricing` query as the seasonal tab (React Query shares the cache by key — no double fetch) and preserves the `perks` field it doesn't expose (snapshot pattern, mirroring the christmas editor's `serverChristmas`).
- Follow the **evidence-led-ui** skill during implementation for the two UI surfaces (settings card + estimator palette).

## Files to change
- `frontend/src/lib/estimator/types.ts` — add optional `bulbScale?: number` to `Product` and `Run`.
- `frontend/src/lib/estimator/catalog.ts` — `BULB_SIZE_OPTIONS` map + `bulbSizeNameFor()` helper; set `bulbScale` on built products; add the gated **Permanent LED roofline** product in `buildCatalog`.
- `frontend/src/lib/estimator/render.ts` — apply `product.bulbScale ?? 1` to the bulb radius in `drawRunLights` (all linear styles); carry `bulbScale` in `withRunOverrides`.
- `frontend/src/components/estimator/editor-store.ts` — add `bulbScale` to the `UPDATE_RUN` patch `Pick`.
- `frontend/src/components/estimator/tool-palette.tsx` — add a "Bulb size" chip row in `RunOptions` (writes `bulbScale`); keep the existing Colors control.
- `frontend/src/components/settings/permanent-pricing-settings-card.tsx` — **new**: enabled + per-ft (+ controller/channel/minimum/label) editor saving the `permanent` block.
- `frontend/src/components/settings/settings-page.tsx` — render `<PermanentPricingSettingsCard />` in the existing `pricing` tab alongside the seasonal editor.

## Tests
- `frontend/src/lib/estimator/render.test.ts` — extend `withRunOverrides` to assert `bulbScale` is layered; add a `drawRunLights` call with a scaled bulb (no throw).
- `frontend/src/lib/estimator/catalog.test.ts` — **new**: permanent roofline product present only when `permanent.enabled`; `bulbSizeNameFor()` round-trips a known scale; built products carry a `bulbScale`.
- `frontend/src/components/settings/permanent-pricing-settings-card.test.tsx` — **new**: renders from mocked pricing, toggling enabled + editing per-ft and saving PUTs a full `permanent` block (mirrors `lead-sources-settings-tab.test.tsx` + `seasonal` mock patterns).

## Risks / edge cases
- **Double-counting roofline feet** if a rep traces both a C9 and a permanent roofline — same pre-existing risk as the two current roofline products; acceptable and consistent (one measured roofline, expert rep tool). Label the permanent product clearly.
- **Block-replace save** must send a complete `PermanentConfig` (preserve `perks`) or defaults would clobber operator perks — handled via the server snapshot.
- **`bulbScale` optionality** must stay optional so existing `Product` literals across the estimator/tests don't break typecheck.
- Permanent draw product price hint uses `estimate.permanent.per_ft` (display only; server stays authoritative).

## Verification
- `cd frontend && npx tsc --noEmit`, `npx eslint <changed files>`, `npx vitest run` for the touched/added specs.
- `make ci.frontend` (lint + type + unit + build) as the authoritative gate.
- evidence-led-ui screenshots: Settings → Pricing permanent card; estimator "Selected strand" bulb-size control; permanent product in the palette (behind login — capture via the skill's harness or note as manual if auth blocks it).
- No `make codegen` / migration (no backend change).

## Steps
1. In `frontend/src/lib/estimator/types.ts`, add optional `bulbScale?: number` to both the `Product` and `Run` interfaces (documented as a visual radius multiplier, default 1).
2. In `frontend/src/lib/estimator/catalog.ts`, add an exported `BULB_SIZE_OPTIONS` (named → scale, e.g. Small 0.75 / Standard 1 / Large 1.3 / Jumbo 1.6) and a `bulbSizeNameFor(scale)` helper; set `bulbScale: 1` on the roofline and decor products built in `buildCatalog`.
3. In `frontend/src/lib/estimator/catalog.ts` `buildCatalog`, when `estimate?.permanent?.enabled` is true, push a **Permanent LED roofline** product (id `roofline-permanent`, `style: "permanent"`, `target: { field: "roofline" }`, `price: estimate.permanent.per_ft`, warm-white colors, `bulbScale: 1`).
4. In `frontend/src/lib/estimator/render.ts`, multiply the computed bulb radius `r` by `product.bulbScale ?? 1` in every linear branch of `drawRunLights`, and carry `bulbScale` through `withRunOverrides` (return early only when spacing, colors, and bulbScale are all unset).
5. In `frontend/src/components/estimator/editor-store.ts`, add `bulbScale` to the `UPDATE_RUN` action's `patch` `Pick<Run, …>`.
6. In `frontend/src/components/estimator/tool-palette.tsx` `RunOptions`, add a "Bulb size" chip row (reusing `.tp-opt-label` / `.tp-chip-row` / `.tp-spacing-chip`) that reads `run.bulbScale ?? product.bulbScale ?? 1` and dispatches `UPDATE_RUN { patch: { bulbScale } }`; leave the existing Colors control in place.
7. Create `frontend/src/components/settings/permanent-pricing-settings-card.tsx`: read `queryKeys.salesWizard.pricing`, seed a draft + server snapshot from `pricing.permanent`, render an enabled `Switch` and numeric inputs (per-ft headline, controller_base, per_channel, included_channels, minimum, label), validate non-negative numbers, and save the full `permanent` block via `salesWizardApi.updatePricing`, writing the result back to the query cache with a success toast.
8. In `frontend/src/components/settings/settings-page.tsx`, render `<PermanentPricingSettingsCard />` inside the existing `pricing` `TabsContent` (above `SeasonalPricingSettingsTab`), wrapped consistently.
9. Extend `frontend/src/lib/estimator/render.test.ts` to assert `withRunOverrides` layers `bulbScale` and that `drawRunLights` renders a scaled bulb without throwing.
10. Add `frontend/src/lib/estimator/catalog.test.ts` covering the permanent product gating (present iff `permanent.enabled`), `bulbSizeNameFor()`, and that built products carry a `bulbScale`.
11. Add `frontend/src/components/settings/permanent-pricing-settings-card.test.tsx` covering render-from-config, enabling + editing per-ft, and that Save PUTs a complete `permanent` block (perks preserved).
12. Run `cd frontend && npx tsc --noEmit && npx eslint <changed files> && npx vitest run <touched specs>`, then `make ci.frontend`; capture evidence-led-ui screenshots of the settings card and estimator bulb-size/permanent controls.
