# Make the estimator look & feel like Holiday Home Concepts

## Goal

Turn the Tribunal's roofline estimator from a **flat-line, single-roofline
measurer** into a **Holiday Home Concepts–style light designer**: the rep draws
glowing C9 roofline, mini lights on bushes/trees, and places wreaths directly on
the customer's photo, sees each product glow, and gets a live itemized price —
then (phase 2) a one-click **AI photorealistic night render**.

Reference implementation (same owner, in-house): `/Users/maxsherrod/Sales-tools/light-estimator`
— a complete, tested HHC clone (React 19 + TS, ~4,600 LOC). We port its canvas
engine, not the whole app.

## Recommendation (what we should do)

**Port light-estimator's canvas UX into the Tribunal estimator, but keep the
Tribunal's server-authoritative pricing, save-to-customer, share link, email,
and permanent-vs-seasonal comparison as the output.** Add AI render via
**OpenAI server-side** (user's pick — no browser key).

Do **not** embed light-estimator wholesale (it prices client-side and has no CRM,
share, or comparison — we'd throw away everything already shipped). Do **not**
just add glow to the current single line (misses the multi-product experience,
which is the actual gap).

Ship in phases; **Phase 1 is an independently shippable visible win.**

## Why this is low-risk: the data models already line up

light-estimator product → existing Tribunal pricing (no schema change needed):

| light-estimator product | Tribunal pricing source (already exists) |
|---|---|
| C9 Roofline (linear) | `feet` @ `christmas.roofline_per_ft` (drives both comparison sides) |
| Mini Lights — bushes/trees (linear, per-ft) | a seasonal `SeasonalItem` with `unit="per_ft"` (like `garland`) |
| Lit Wreath 36/48/60 (each) | `christmas.items` `wreaths` category (`unit="each"`, size options) |
| Trees / Bushes (each) | `christmas.items` `trees` / `bushes` categories |
| Permanent Track (linear) | `permanent.per_ft` (permanent comparison side) |

The estimate endpoint already accepts `feet` + `christmas_items: {category: {option: value}}`
(count for `each`, linear feet for `per_ft`) and returns a fully priced,
grossed-up breakdown (`christmas.items`, roofline, permanent) — server-side, per
workspace. It already returns the workspace's `christmas_catalog`. So the drawn
design maps straight onto the current request with **zero backend schema change**;
the only backend touch is seeding a `mini_lights` per-ft category default.

## Key files

**Port from** `/Users/maxsherrod/Sales-tools/light-estimator/src/`
- `lib/render.ts` (470 LOC) — the glow engine: bulb sprites, `drawRunLights`
  (c9/mini/garland/stake/permanent), `drawPlacedItem` (wreath/treewrap),
  `drawScene` (additive `lighter` glow pass, night dim). Pure canvas, no React.
- `lib/geometry.ts` — `pointsAlongPath`, `dist`, `jitter`, `polylineLength`.
- `lib/catalog.ts` — `COLOR_PRESETS`, `SPACING_OPTIONS`, product shape.
- `components/CanvasEditor.tsx` (642 LOC) — pointer/keyboard interaction model
  (draw run, place item, calibrate, select/move/resize, zoom, night toggle).
- `components/EstimatePanel.tsx`, `Toolbar.tsx` — layout/styling reference.

**Change in the Tribunal**
- `frontend/src/components/estimator/roofline-estimator.tsx` — swap the flat-line
  canvas for the new editor; keep estimate/comparison/save/share/email wiring.
- `frontend/src/lib/estimator/measure.ts` — existing scale/feet math (reuse).
- `frontend/src/components/estimator/estimator.css` — dark HHC styling.
- `backend/app/schemas/pricing.py` — add a `mini_lights` per-ft default seasonal
  category to `_default_seasonal_items()` (+ workspace seed).

**Reuse as-is (already server-authoritative, already shipped)**
- Estimate/share/deliver: `POST quotes/estimate`, `estimate/share`,
  `estimate/comparison/{token}`, `estimate/comparison/{token}/send`.
- `ComparisonCard`, the public client comparison page, save-to-customer.

## Ownership / licensing

`light-estimator` is Maxteriors' own in-house tool ("Sales tools for Maxteriors
EZ"), same owner as the Tribunal. Porting its source in is fine.

## Risks & mitigations

- **Scope**: Phase 1 is ~6–8 new/rewritten frontend files (~1,200–1,500 LOC).
  Mitigate by shipping Phase 1 alone; AI render (Phase 2) and per-run
  color/tabs polish (Phase 3) are separate, independently valuable.
- **Two mental models**: current estimator = *comparison* (same roofline priced
  permanent vs seasonal); light-estimator = *free-form design*. We keep the
  comparison as the OUTPUT — the drawn roofline still drives permanent-vs-seasonal
  savings; decor adds to the seasonal side. Permanent as a *separately drawn*
  product is deferred to Phase 3 (Christmas/Permanent tabs).
- **Server pricing rule**: never compute money client-side. The canvas only
  produces feet/counts; every dollar still comes from the estimate endpoint.
- **AI render key safety**: light-estimator stores a fal key in browser
  localStorage. We do better — call OpenAI from the backend with the per-tenant
  encrypted credential (`is_openai_configured()` already exists); the browser
  never sees a key.
- **Canvas under jsdom**: keep geometry/render pure and unit-test them directly
  (like `measure.test.ts`); component tests mock the measure/render libs.

## Verification

- `frontend`: `npm run lint`, `npm run typecheck`, `vitest` (render/catalog/component), `npm run build`.
- `backend`: `make ci.backend` (mini_lights pricing test), `.ezcoder/eyes/http.sh`
  against `quotes/estimate` with a multi-product `christmas_items` payload →
  confirm the itemized breakdown.
- Visual: `screenshot` the `/estimator` page after a demo trace; compare to the
  captured light-estimator demo (`.ezcoder/eyes/out/light-estimator-demo.png`).
- `make ci.all` = 0 before shipping; deploy backend-first (mini_lights seed),
  then frontend.

## Steps

1. Port the pure glow engine into the Tribunal: copy `render.ts` and the needed
   `geometry.ts` helpers to `frontend/src/lib/estimator/render.ts` and
   `geometry.ts`, adapting them to reuse `measure.ts` (`pxPerFoot`, `Point`); add
   `"use client"`-free pure exports and unit tests (`render` sprite/scene smoke,
   `geometry` path math).
2. Add `frontend/src/lib/estimator/catalog.ts`: drawable `Product[]` (id, name,
   style, colors, spacingIn, kind, category) plus a bridge that derives the
   palette from the workspace's `christmas_catalog` (returned by the estimate
   endpoint) merged with built-in roofline C9 + mini-lights; include
   `COLOR_PRESETS`/`SPACING_OPTIONS`.
3. Add a design→request mapper `frontend/src/lib/estimator/design.ts`: tally runs
   and placed items by product, convert to `{ feet, christmas_items }` for the
   existing `LinearFeetEstimateRequest` (roofline run → `feet`; per-ft runs →
   `christmas_items[cat][opt]=feet`; each items → `christmas_items[cat][opt]=count`);
   unit-test the mapping.
4. Build `frontend/src/components/estimator/light-canvas.tsx` (`"use client"`):
   the multi-product editor adapted from `CanvasEditor.tsx` — draw run, place
   item, calibrate scale, select/move/resize, zoom, night toggle — rendering via
   the ported `drawScene`.
5. Build `frontend/src/components/estimator/tool-palette.tsx`: tools + product
   palette + per-run color/spacing controls, styled like light-estimator's
   `Toolbar`/left rail.
6. Rewrite `frontend/src/components/estimator/roofline-estimator.tsx` to host the
   new canvas + palette, hold the `Design` state, and feed the design mapper into
   the existing live estimate query; keep the comparison card, client-view
   toggle, save-to-customer, share, and email actions unchanged.
7. Replace the estimate readout with an itemized `EstimatePanel`-style breakdown
   driven by the server response (`christmas.items`, roofline, permanent totals,
   difference/multi-year savings) — no client-side money.
8. Restyle `frontend/src/components/estimator/estimator.css` to the dark HHC look
   (left tools rail, centered photo stage, right estimate/customer column).
9. Seed a `mini_lights` per-ft category in `backend/app/schemas/pricing.py`
   `_default_seasonal_items()` and the workspace seed script so mini-light runs on
   bushes/trees price; add a backend pricing test covering a multi-product
   `christmas_items` payload including `mini_lights`.
10. Update/extend tests: `roofline-estimator.test.tsx` for the new draw→estimate
    flow (mock render/measure libs), plus the new lib unit tests; run
    `make ci.frontend` and `make ci.backend`.
11. Regenerate contracts if any schema touched (`make codegen`; commit
    `backend/openapi.json` + `frontend/src/lib/api/_generated.ts`), run
    `make ci.all` to 0, screenshot `/estimator`, and **pause here for review — this
    is the Phase 1 checkpoint (shippable visible win) before Phase 2.**
12. Phase 2 (AI render, after checkpoint): add `POST quotes/estimate/render` in
    `backend/app/api/v1/quotes.py` + a service that composites → OpenAI gpt-image-2
    edit using the per-tenant OpenAI credential with a night-render prompt (mirror
    light-estimator `defaultPrompt`); return a stored/data-URL image. No browser key.
13. Phase 2 frontend: add the "✨ AI realistic render" action — composite the
    canvas to JPEG, call the endpoint, show progress, add a sketch/photo toggle,
    and save the render onto the shared comparison so the client page can show it.
14. Phase 3 (polish, separate approval): Christmas/Permanent tabs sharing one
    scale, drawn permanent-track footage feeding the permanent comparison side,
    and richer per-run color/spacing presets.
