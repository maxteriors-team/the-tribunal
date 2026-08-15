# NiteLite OS UX Fidelity and Fixed Aerial Plan

## Objective

Refine the existing Maxteriors landscape-lighting studio against the authenticated NiteLite OS reference capture from 11 August 2026. Preserve the substantial feature parity already shipped, but remove the remaining visual and interaction gaps that make the editor feel denser, less predictable, or less focused than the reference.

“Exact” applies to the observable information hierarchy, compact drawing-desk geometry, workflow order, control grouping, document presentation, and interaction feedback. Keep Maxteriors branding, Tribunal data and reliability behavior, the existing Lucide icon family, and the aerial-first product rules. Do not copy NiteLite trademarks, logos, proprietary assets, source code, or emoji controls.

## Evidence and Audit

Primary evidence:

- `.ezcoder/screenshots/niteliteos-reference/01-project-desktop.png`
- `.ezcoder/screenshots/niteliteos-reference/20-project-mobile.png`
- `.ezcoder/screenshots/niteliteos-reference/tab-1-drawing-sheet.txt`
- `.ezcoder/screenshots/niteliteos-reference/tab-2-fixture-schedule.png`
- `.ezcoder/screenshots/niteliteos-reference/tab-3-bom.png`
- `.ezcoder/screenshots/niteliteos-reference/tab-4-electrical.png`
- `.ezcoder/screenshots/niteliteos-reference/tab-5-proposal.png`
- `.ezcoder/screenshots/niteliteos-reference/tab-6-pre-con.png`
- `.ezcoder/screenshots/maxteriors-studio-desktop.png`
- `.ezcoder/screenshots/maxteriors-studio-mobile.png`
- Existing source, component tests, and `frontend/e2e/landscape-lighting-studio.spec.ts`

Existing close matches to preserve:

- Six-tab workflow and exact tab order.
- Black, charcoal, white, and muted-gold drawing-desk palette.
- White drawing sheets, aerial title block, fixture legend, and dark stage.
- Real fixture schedule, BOM, electrical, proposal, and pre-construction data flows.
- Real CRM price-book, quote, delivery, conflict, browser-backup, and server-autosave behavior.
- Aerial-only upload/render semantics, scale calibration, wiring, fixtures, supplemental detail photos, undo/redo, and accessible canvas controls.
- Project list, archive/recovery behavior, loading/error/empty states, and multi-tenant API boundaries.

Remaining gaps found in the rendered and source audit:

| Area | NiteLite OS reference | Current Maxteriors implementation | Required correction |
| --- | --- | --- | --- |
| Focused shell | No resting application sidebar | Collapsed CRM icon rail remains | Hide the rail at rest; retain deliberate off-canvas CRM navigation |
| Project header | One 50px light row with back link, title, save state, send, save | Dark stacked header, rounded title field, extra metadata | Match the compact light hierarchy while preserving conflict/offline detail |
| Workflow tabs | Plain uppercase labels on one black rail | Icons plus labels | Use the reference’s simpler text rail and selected underline |
| Drawing controls | Two compact rows: brand, sheet, place drawing, marker colors, primary modes, menus, present/PDF | One long horizontal strip plus a duplicate Add aerial/Render/Quote row | Remove duplication and rebuild the reference grouping without losing real actions |
| Marker palette | Sixteen immediately visible marker colors | Color exists only in the selected-item inspector | Add an accessible shared palette for new and selected fixtures |
| Command honesty | Controls perform a visible drawing/document action | Several commands only announce “Drawing command selected” or add an uneditable object at a fixed coordinate | Implement retained commands or remove them from the visible toolbar |
| Base aerial | Registered drawing remains fixed within the sheet | Resize keeps stale viewport offsets; wheel/touch panning can make the plan appear to drift or crop, especially after desktop-to-mobile resize | Lock the base aerial and recompute a deterministic fit on every relevant resize |
| Zoom | Sheet-level right rail across document tabs | Canvas-only controls overlay the plan; supporting sheets have no matching zoom | Move zoom to a shared sheet viewport outside the document content |
| Settings | Paper, fit, opacity, legend, visibility, tab, and pre-con state persist | V2 models exist, but `createLandscapeDraft()` recreates defaults and omits several live states | Hydrate and serialize all live document settings without schema drift |
| Responsive behavior | Whole document remains a stable thumbnail on narrow screens | Toolbar overflows and the aerial is cropped after resize | Wrap logical toolbar groups and preserve the fitted sheet/image center at 390px |

## Design Read

- **Surface:** desktop-first, data-dense drawing application with document-generation tabs.
- **Audience:** landscape-lighting designers and sales operators working on laptops and tablets, often with a customer present.
- **Single job:** turn one fixed top-down aerial into an installation-ready, priced, sendable lighting project.
- **Task and risk:** high-frequency editing; accidental movement, lost settings, wrong fixture counts, or stale saves can produce installation and quote errors.
- **Platform:** Next.js/React; keyboard, mouse, trackpad, and touch; usable from 390px mobile through wide desktop; Chromium is the E2E browser while responsive CSS remains standards-based.
- **Constraints:** preserve the existing estimator data model, CRM integrations, Maxteriors brand, WCAG 2.2 AA floor, shared seasonal/property-photo designer, and unrelated quote/deposit work in the primary checkout.

## Design Thesis

**One fixed drawing desk.** The first glance shows project identity and save safety. The second glance shows the six-step workflow. The drawing, not application chrome, occupies the rest of the viewport.

- Light 50px project bar; black workflow and tool rails; charcoal stage; white paper; muted gold only for active/primary drawing actions.
- Existing typography remains authoritative. Use compact uppercase labels for workflow/tool chrome and normal sentence case for status, errors, and document content.
- Square-to-small-radius controls replace unrelated pill geometry. Borders, not floating shadows or glass, separate dense controls.
- No emoji UI, decorative gradients, card grids, hover lift, `transition: all`, invented metrics, or tint-on-tint semantic badges.
- Keep all document edges on one shared rail. The stage zoom control sits outside the paper so it never covers the aerial, legend, or title block.
- Motion is limited to 120–180ms color/opacity transitions and menu/dialog behavior, with reduced-motion equivalents.

## Interaction Design

### Focused shell and header

- In `frontend/src/components/layout/app-sidebar.tsx`, use the existing sidebar’s off-canvas mode while a focused editor is active so the resting rail consumes zero width. The existing navigation trigger may open it deliberately; closing it restores the full drawing width.
- In `frontend/src/components/landscape-lighting/lighting-project-editor.tsx`, replace the stacked dark header with the reference hierarchy: Projects back link, plain inline project name, concise save state, outlined Send proposal, and solid dark Save.
- Keep save conflict, local-backup, retry, and “save as copy” behavior intact. Concise normal states must expand into actionable error/conflict content when necessary.
- Remove the duplicate server action row from the top of `LightDesigner`. Aerial upload, AI render, quote, print, and PDF actions move to the workflow location where they are relevant.

### Workflow and toolbar

- Keep the exact tab order but remove decorative tab icons. Preserve semantic `tablist`/`tab`/`tabpanel`, arrow-key navigation, selected underline, and horizontal scrolling only when labels truly cannot fit.
- Recompose `frontend/src/components/landscape-lighting/studio/drawing-toolbar.tsx` into two logical rows matching the reference:
  - Row one: MAXTERIORS, sheet size with physical dimensions, Place/Replace aerial, marker palette, Select, Undo, Wiring state, Highlight, fixture-number state, Plan, and Add.
  - Row two: Wiring, Legend, File, Help, Present, and Download PDF.
- Move fixture-type shortcuts into Add so the primary toolbar no longer hides controls off-screen. Keep keyboard redo even though Undo is the visible reference action.
- Extract the existing marker colors from `tool-palette.tsx` into a shared estimator constant, expand to the sixteen observed swatches, and apply the selected color to both newly placed and currently selected fixtures. Existing projects without `markerColor` continue using semantic fixture defaults.
- Every visible action must mutate state, enter an explicit tool mode, open a real menu/dialog/file picker, or be disabled with a reason. Remove placeholder-only commands from the visible surface rather than pretending they worked.

### Fixed aerial and sheet viewport

- The uploaded top-down base aerial is a locked background, not a selectable sheet object. Supplemental detail-photo insets remain intentionally movable/resizable because they are explicit annotations, not the base aerial.
- Add a landscape-only locked viewport policy to `frontend/src/components/estimator/light-canvas.tsx`; do not change the shared seasonal/property-photo behavior.
- While locked:
  - ordinary pointer drag, wheel scrolling, and touch gestures cannot offset the base aerial;
  - fixtures, wire routes, highlights, measurements, and insets retain image-space coordinates and never drift relative to the aerial;
  - `ResizeObserver`, tab switches, sidebar changes, fullscreen changes, and desktop/mobile viewport changes recompute a deterministic contain/cover fit from current dimensions;
  - replacing the aerial resets the fit once without changing other sheets;
  - keyboard/pointer editing of fixtures and insets remains available.
- Add `frontend/src/components/landscape-lighting/studio/document-viewport.tsx` for sheet-level zoom. It provides Fit, plus, minus, range, and percentage controls outside the paper; the same control wraps drawing, schedule, BOM, electrical, proposal, and pre-con sheets. Preserve the sheet’s visual center while zooming and expose equivalent buttons for keyboard/touch users.
- Remove canvas overlays that duplicate toolbar actions or obscure plan content. Before/Dusk remains available through Present/preview controls, and scale state remains visible in the toolbar/title block.

### Document actions and persistence

- Add the reference’s contextual action strip on non-drawing tabs: Print on Schedule; Recount/CSV/PDF/Print on BOM; PDF/Print on Electrical, Proposal, and Pre-Con. Reuse current live calculations and existing download callbacks.
- Wire `LandscapeDocumentSettings` into `LightDesigner` initialization and draft emission: `paperSize`, `planFit`, `planOpacity`, legend visibility/position/scale, halo visibility, fixture numbers, measurements, and source voltage.
- Preserve and emit `activeWorkflowTab`, proposal selections/settings, procurement data, and `preconState` instead of rebuilding defaults in `frontend/src/lib/estimator/landscape-draft.ts`.
- Importing a Tribunal project restores all document settings, not only shots. Reset/conflict resolution rehydrates the same complete state.
- No backend/OpenAPI change is planned: the V2 document schema and per-fixture `markerColor` already support the required persisted data. If implementation proves otherwise, update backend schema, regenerate `backend/openapi.json` and `frontend/src/lib/api/_generated.ts`, and test the round trip in the same change.

## Responsive and Accessibility Contract

- Desktop: one compact project row, one workflow row, two tool rows, then the document stage. No resting CRM rail or duplicate action row.
- Tablet/mobile: project name truncates safely, status yields before actions, workflow tabs remain keyboard-scrollable, toolbar groups wrap in intact units, and the full sheet starts fitted rather than cropped.
- Keep at least 24×24px pointer targets with separation; primary mobile actions target 44px height where space permits.
- Marker colors use accessible names, `radio` semantics, a non-color selected indicator, and measured focus/selected contrast.
- Menus use existing Radix focus management. Closing a pointer-opened menu must not leave a false persistent focus treatment; keyboard focus remains visible.
- Canvas instructions remain non-sensory, fixture movement retains keyboard alternatives, status changes use polite live regions, and destructive clear actions retain confirmation.
- Verify 200% zoom/reflow, reduced motion, forced colors, long project/contact names, empty/error/offline/conflict states, and mobile touch behavior. Do not claim WCAG or ADA conformance from automated checks alone.

## Scope and Risk Controls

- Build from a clean `origin/main` worktree/feature branch. Do not stage, stash, reset, or edit the unrelated quote/deposit modifications in the primary checkout.
- Do not alter the shared seasonal/property-photo workflow; the fixed base-aerial policy is landscape-only.
- Preserve quote generation, delivery, AI aerial rendering, conflict resolution, browser backup, autosave, project archive/recovery, and backend tenancy behavior.
- Main technical risk is pointer coordinate accuracy through sheet-level zoom. Cover placement, drag, keyboard nudge, supplemental image resize, and resize/refit behavior with unit and browser tests before visual sign-off.
- Avoid a database migration unless evidence reveals a missing persisted field; none is currently expected.

## Verification

- Targeted Vitest coverage for `drawing-toolbar`, `light-canvas`, `light-designer`, `lighting-project-editor`, `landscape-document`, `landscape-draft`, and autosave payload round trips.
- Targeted Playwright flow in `frontend/e2e/landscape-lighting-studio.spec.ts`: create/open, fixed aerial, marker color, fixture placement, wiring, tab documents, save, proposal, viewport resize, keyboard navigation, and mobile fit.
- `make ci.frontend` and `make ci.codegen` if the API contract changes.
- Rendered evidence at 1440×960, 768×1024, and 390×844 for drawing plus every supporting tab. Compare against the authenticated reference and current screenshots.
- One evidence-led critique/revision cycle using the 24-point rubric. Completion requires at least 20/24, no zero in accessibility, consistency/flow, responsive behavior, state completeness, or content authenticity, and no known applicable WCAG A/AA failure.

## Steps

1. Create an isolated feature worktree from `origin/main`, inventory the exact changed-file baseline, and leave the primary checkout’s quote/deposit work untouched.
2. Convert the focused landscape editor shell and project header to the compact NiteLite-style hierarchy while preserving Tribunal save, offline, and conflict recovery behavior.
3. Simplify the six workflow tabs and remove the duplicate server action row, routing each retained action to its correct workflow context.
4. Rebuild `DrawingToolbar` into the two-row reference geometry, move fixture placement into Add, add the shared sixteen-color marker palette, and remove or replace every placeholder-only command.
5. Wire marker color through new fixture placement and selected-fixture editing while preserving legacy semantic defaults and persisted `markerColor` values.
6. Add the landscape-only fixed-base-aerial viewport policy, deterministic resize/refit behavior, and regression tests proving the aerial and drawing coordinates do not drift.
7. Add the shared sheet-level zoom viewport and contextual PDF/print/CSV/recount controls across Drawing, Schedule, BOM, Electrical, Proposal, and Pre-Con.
8. Hydrate and serialize all V2 document settings, active workflow state, proposal/procurement state, and pre-con responses through draft import, autosave, conflict reset, and export.
9. Tighten desktop, tablet, mobile, print, reduced-motion, and forced-color CSS so toolbar groups remain operable and the full sheet starts fitted at every target viewport.
10. Update component/unit tests and the landscape Playwright flow for toolbar semantics, marker colors, fixed-photo behavior, persistence, tab actions, keyboard use, and responsive resize.
11. Update `frontend/DESIGN.md` with the final evidence, design thesis, fixed-photo rule, responsive states, reused primitives, and verified/unverified accessibility checks.
12. Run targeted tests, `make ci.frontend`, any required codegen checks, capture all reference viewport screenshots, score the rendered result, revise the weakest criterion, and re-run the affected verification.
