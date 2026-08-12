# Maxteriors Landscape Lighting: NiteLiteOS Workflow Parity

## Objective

Rebuild the authenticated Maxteriors landscape-lighting project as a complete, native Tribunal workflow based on the authorized NiteLiteOS reference project, including every user-visible workflow discovered by interacting with the reference. Preserve Tribunal ownership of code, Maxteriors branding, workspace isolation, CRM linkage, and the CRM price book as the only pricing source.

This is functional parity, not source-code or asset copying. The implementation may reproduce task order, control placement, interaction semantics, and document anatomy observed in the reference, but it must use Tribunal components, icons, copy, data contracts, and branding rather than NiteLiteOS proprietary assets or a pixel-identical trade dress clone.

## Reference evidence gathered

Authenticated reference project inspected at desktop 1440x1000 and mobile 390x844. Captures and text inventories are in `.ezcoder/screenshots/niteliteos-reference/`; credentials remain in the gitignored `.ezcoder/eyes/auth/niteliteos.env` and must not enter source, logs, tests, or commits.

Observed primary workspace:

- Thin project header with back navigation, editable project name, save state, `Send proposal`, and `Save`.
- Fixed workflow rail: Drawing Sheet, Fixture Schedule, BOM, Electrical, Proposal, Pre-Con.
- Dense black/brass drawing toolbar; horizontal overflow is retained on narrow screens rather than collapsing away editor capabilities.
- Sheet strip with add, duplicate, delete, and per-sheet label.
- White landscape drawing sheet on a charcoal drafting desk, right-side title block, fixture legend, plan imagery, selected markers, and fixed zoom rail.
- Printable document views for schedule, BOM, electrical, proposal, and pre-con.

Observed Drawing Sheet controls:

- Paper size: Tabloid, Super B, Letter, ARCH C, ARCH D, ANSI D.
- Drawing placement, 17 marker colors, selection, undo.
- Wiring mode, highlight mode, fixture-number toggle.
- Plan menu: set scale, measure, measurement visibility, clear plan, contain/cover fit, opacity/fade, automatic design, clear design, clear symbols.
- Add menu: note, line, tree, photo, revision.
- Wiring menu: draw wire, T-off, end run, undo point, clear wires, draw arrow, clear arrows, transformer-zone assignment, source voltage.
- Legend menu: visibility, repositioning, key size, recount fixtures, halo visibility.
- File menu: open editable project, save editable project, download all sheets, print, full screen.
- Help content, presentation mode, PDF download.
- Fixture library/legend supports fixture type selection and drag placement; selected symbols support color, size, rotation/aim, duplicate, delete.

Observed supporting workflows:

- Fixture Schedule: one row per numbered fixture with type/code, editable lamp and accessories, and copy-to-all-of-type.
- BOM: live recount, catalog/order code, manufacturer/SKU, needed/ordered/received quantities, unit cost, total, supplier, notes, lamps, wire, job total, CSV/PDF/print.
- Electrical: connected load, amperage, transformer suggestion and schedule, transformer zones, default watts for unresolved fixtures, minimum voltage, line voltage-drop calculations, design checks, PDF/print.
- Proposal: cover, client/property identity, design intent, zones/areas, fixture/investment rows, combined total visibility, fixture-detail visibility, zone photos, payment milestones, electrical responsibility, optional enhancements, commitments, signature/date, PDF/print/send.
- Pre-Con: 26 grouped readiness items, Yes/No/N/A, comments, lead installer, contract amount, completion count, notes, PDF/print.

## Existing Tribunal capability map

Keep and extend these foundations rather than replacing them:

- `frontend/src/components/landscape-lighting/lighting-project-editor.tsx`: customer-linked project shell, autosave status, conflict dialog, server project integration.
- `frontend/src/components/landscape-lighting/use-lighting-project-autosave.ts`: IndexedDB recovery, immediate placement save, queued autosave, optimistic concurrency, non-destructive conflict handling.
- `frontend/src/components/estimator/light-designer.tsx`: six-tab workflow, fixture schedule, BOM, electrical, proposal pricing and quote creation, pre-con summary, sheet actions.
- `frontend/src/components/estimator/light-canvas.tsx`: calibration, placement, drag/resize/aim, wire polylines, circuit assignment, image overlays, keyboard/touch zoom and pan.
- `frontend/src/components/estimator/tool-palette.tsx`: price-book product specs, marker color, symbol size, beam and aim, circuit, duplicate/delete.
- `frontend/src/lib/estimator/electrical.ts`: catalog watts, load, amperage, transformer utilization, route length, voltage drop and end-voltage planning estimates.
- `frontend/src/lib/estimator/supplier-csv.ts`: safe catalog-backed ordering export and formula-injection defense.
- `frontend/src/lib/estimator/landscape-proposal.ts` plus quote wizard backend: server-owned Good/Better/Best and care-plan pricing in `price_book` mode with no financing.
- `backend/app/schemas/lighting_project.py` and the lighting-project API/service: strict workspace-scoped persisted JSON document and project metadata.

## Design direction

**Surface:** dense professional drafting and sales workspace inside the CRM.

**Audience:** Maxteriors estimators and installers using desktop/laptop first and tablet/phone for review or field updates.

**Single job:** move one customer-linked property from plan placement through priced proposal and install readiness without leaving Landscape Lighting.

**Thesis:** keep the reference's efficient document-studio anatomy, but make it unmistakably Maxteriors: Tribunal's black/brass controls, existing typography, Lucide icon family, supplied Maxteriors logo, CRM customer identity, and exact catalog pricing. The drawing sheet is the dominant working object; controls stay compact and spatially stable across tabs.

**App-shell decision:** make the individual project route a focus workspace by using `AppSidebar` in hidden/off-canvas mode there, while retaining the normal CRM shell on the project list. This recovers drafting width and matches the reference's project-focused header without removing navigation; the sidebar trigger remains available.

**Responsive decision:** desktop keeps the entire workflow on one viewport. Narrow screens retain a minimum-width editor workspace with local horizontal scrolling for tabs/tools/sheets, matching the reference and preserving every control; printable document content itself reflows where practical. No control disappears solely because the viewport is narrow.

## Data model and persistence

Upgrade the landscape draft schema to version 2 with migration/normalization from all version-1 records. Add optional fields so existing projects remain readable:

- Project document: paper size, plan fit/opacity, legend visibility/position/scale, halo and number visibility, source voltage, proposal document settings, pre-con metadata/checklist, and active workflow tab when useful for recovery.
- Per shot/sheet: sheet label, drawing metadata, revision rows, annotations, measurement lines, highlight strokes, arrows, plan images, and proposal zone/area linkage.
- Per fixture: lamp/catalog selection, accessories/catalog component selections, marker color, rotation/aim, and circuit/transformer assignment.
- Per wire: supported 12/2 or 10/2 choices for new work, while reading legacy 8/14 values; route geometry remains a single polyline. T-off/branched circuit graphs remain deliberately unsupported because current electrical calculations assume one traced route and the prior product constraint excludes automatic/branched conductor routing.
- BOM procurement state: ordered quantity, received quantity, supplier note, and safe catalog references. Unit costs continue to resolve from the current workspace catalog rather than becoming editable stored prices.
- Pre-con responses: Yes/No/N/A and free-text comments, plus lead installer and notes.

Update `backend/app/schemas/lighting_project.py`, `frontend/src/lib/estimator/types.ts`, `frontend/src/lib/estimator/landscape-draft.ts`, generated OpenAPI artifacts, normalization, and tests together. No database migration is needed for nested JSON document additions, but schema/codegen drift must pass.

## Feature boundaries and adaptations

- **CRM price book wins:** fixture/lamp/accessory/wire/transformer names, SKUs, components, watts, suppliers, and prices come from active workspace catalog rows. Missing mappings stay visibly unresolved; no SKU, cost, or wattage is invented.
- **No financing:** the landscape proposal remains `pricing_source: "price_book"`; no finance gross-up, monthly figure, or cash-discount fork is added.
- **Proposal stays here:** create/save/send/email/SMS actions use the existing quote APIs inline. No redirect to Build Quote.
- **Electrical honesty:** voltage drop remains a planning estimate with source voltage, conductor gauge, route length, and assigned load visible. It is never described as field-verified.
- **Supplier safety:** incomplete lines remain in the UI/CSV with status; exports preserve spreadsheet-formula protection.
- **Plan-only geometry:** images, notes, lines, arrows, trees, highlights, measurements, and transformers do not create quote quantities.
- **T-off adaptation:** provide explicit multi-run circuits from one transformer and document why branches are represented as separate named runs. Do not implement branched graph calculations or automatic routing under a misleading T-off label.
- **Automatic design adaptation:** if implemented, it must be deterministic, previewable, undoable, and use existing selected price-book fixtures. It may suggest/place symbols only; it may not infer a safe conductor route, field conditions, or final electrical compliance.
- **External formats:** editable project export/import uses a versioned Tribunal JSON file and validates through the same strict schema before replacing a draft. PDF/print output uses Tribunal-generated documents and Maxteriors branding.
- **Accessibility:** no emoji icons from the reference; use Lucide. Every custom canvas action needs a named button/menu alternative. Tabs use proper tab semantics, dialogs manage focus, save/export statuses are announced, and keyboard operation remains intact. Manual screen-reader, complete 200% text zoom, and formal contrast audits must remain reported as unverified unless actually performed.

## Architecture

### 1. Focused project shell

Update `frontend/src/components/layout/app-sidebar.tsx` to recognize the project detail route and start in hidden/off-canvas mode. Refactor `lighting-project-editor.tsx` into the reference-derived top project header: back link, editable name, customer/project facts, one autosave state, `Send proposal`, and explicit `Save now`. Keep conflict resolution and action states.

### 2. Versioned project-domain state

Create focused modules rather than expanding `light-designer.tsx` indefinitely:

- `frontend/src/lib/estimator/landscape-document.ts`: version-2 defaults, migration, annotations, revisions, paper settings, proposal zones, BOM state, and pre-con state.
- `frontend/src/lib/estimator/landscape-sheets.ts`: add/duplicate/delete/relabel semantics and cross-sheet fixture numbering/recount.
- `frontend/src/lib/estimator/landscape-schedule.ts`: per-fixture rows, lamp/accessory resolution, copy-to-type.
- `frontend/src/lib/estimator/landscape-procurement.ts`: needed/ordered/received state merged with current catalog prices and safe export status.
- `frontend/src/lib/estimator/landscape-precon.ts`: canonical 26-item checklist and completion calculations.

Keep pure calculations independently tested.

### 3. Drawing studio

Split the landscape UI from generic seasonal estimator chrome into components under `frontend/src/components/landscape-lighting/studio/`:

- `project-workflow-tabs.tsx`
- `drawing-toolbar.tsx`
- `sheet-tabs.tsx`
- `drawing-sheet.tsx`
- `zoom-rail.tsx`
- `fixture-legend.tsx`
- `fixture-inspector.tsx`
- `annotation-inspector.tsx`

Extend `LightCanvas`/editor reducer with measurement, highlight, line, arrow, note/tree symbols, legend movement, visibility controls, fixture-number visibility, source voltage, and full-screen/present modes. Every action must participate in undo/redo and autosave where applicable.

### 4. Document tabs

Build printable Maxteriors sheets from live project data:

- Fixture Schedule: one numbered row per fixture; catalog lamp/accessory pickers; copy-to-type action.
- BOM: needed, ordered, received; current catalog SKU/manufacturer/supplier/unit cost; lamp/accessory/wire/transformer rollups; statuses; CSV/PDF/print.
- Electrical: existing calculations plus defaults/missing-spec resolution, transformer schedule, named circuits, design checks, and PDF/print.
- Proposal: retain exact Good/Better/Best and care plans, add reference-derived document presentation, zones/areas and photos, payment milestones, optional catalog-backed enhancements, commitments, signature area, inline draft quote creation and send/deliver.
- Pre-Con: persist all 26 reference categories/items with Yes/No/N/A, comments, installer, contract amount from the generated quote, completion count, notes, PDF/print.

### 5. Export, import, print, and send

Add a shared document/export module using existing dependencies first; verify installed package APIs from source before implementation. Required outcomes:

- Current sheet PDF.
- All sheets PDF.
- Print stylesheet for each active document.
- Versioned editable Tribunal project download and validated import.
- Existing supplier CSV with procurement fields added without weakening safety.
- Save/create quote, mark sent, and deliver by email/SMS through existing server APIs; surface missing contact rails and provider failures.

### 6. Verification

Automated interaction coverage must exercise every implemented button/menu item, not merely render it. Add:

- Pure unit tests for migrations and domain calculations.
- Component tests for all toolbar/menu controls and disabled/error states.
- Backend schema and workspace-isolation tests for every new document field.
- Browser automation that creates a server project, adds a plan, uses each tool and menu action, edits fixture specs, wires circuits, checks every tab, exports documents/CSV/project JSON, saves/restores, creates/sends a quote using a captured provider or non-delivery test mode, completes pre-con items, and verifies desktop/mobile geometry.
- Desktop 1440x1000, laptop 1280x800, mobile 390x844, reduced-motion, forced-colors, keyboard focus, and local overflow assertions.
- One rendered critique/revision cycle recorded in `frontend/DESIGN.md`; do not claim full WCAG conformance without manual assistive-technology and per-criterion evidence.

## Risks

- **Scope size:** exact feature parity is a multi-slice product expansion. Isolate domain modules and land in coherent checkpoints so the existing verified workflow never becomes unusable midway.
- **Schema compatibility:** strict `extra="forbid"` validation means frontend/backend version-2 changes and OpenAPI generation must land together. Version-1 migration must be fixture-tested before server payload changes.
- **Price drift:** catalog-backed selections can be renamed/deactivated. Persist stable catalog IDs/SKUs where available and render an unresolved state rather than stale prices.
- **PDF fidelity:** browser print and generated PDF can differ in pagination. Verify installed tooling before choosing implementation and test representative long schedule/BOM/checklist documents.
- **Autosave volume:** annotation/highlight pointer movement must use transient reducer updates and one commit/autosave at gesture end; fixture placement remains immediate.
- **Third-party reference:** do not copy NiteLiteOS JavaScript, CSS, assets, logos, exact marketing copy, placeholder warranties, or hidden implementation. Functional parity and workflow adaptation are permitted; visual treatment remains Tribunal/Maxteriors.
- **Reference defects:** the reference emits browser errors and exposes unsupported/placeholder states. Reproduce intended behavior, not errors, emoji UI, fabricated warranty terms, editable untrusted prices, or inaccessible controls.

## Success criteria

- Every reference control in the authenticated tool inventory has one of: a working Tribunal equivalent, a documented safe adaptation (T-off as multiple named runs), or an explicit exclusion tied to an existing user constraint.
- A Maxteriors estimator completes property plan, schedule, BOM, electrical review, Good/Better/Best proposal, quote send, and pre-con checklist without leaving the Landscape Lighting project.
- All pricing and purchasable specifications resolve from the current workspace price book; no financing or client-authored price is introduced.
- Workspace boundaries, versioned autosave, IndexedDB recovery, immediate placement save, and non-destructive conflict handling remain intact.
- All six document tabs print/export with authentic project/customer data and Maxteriors branding.
- Automated browser coverage clicks every visible button/menu action at least once and validates state or artifact outcomes; all targeted tests, codegen, frontend/backend CI, migration CI when applicable, and visual assertions pass.

## Steps

1. Add the version-2 landscape document types, migration/normalization, strict backend schema fields, generated contracts, and compatibility tests for existing version-1 projects.
2. Add pure sheet, schedule, procurement, proposal-zone, annotation, and 26-item pre-con domain modules with unit tests and CRM catalog resolution.
3. Convert the project detail route to a focused Maxteriors studio shell with the reference-derived project header, six workflow tabs, explicit save/send actions, hidden/off-canvas app sidebar, and responsive local overflow.
4. Build the full Drawing Sheet toolbar, menus, paper/title-block settings, sheet management, legend controls, selection inspector, zoom/full-screen/present modes, and accessible alternatives using Tribunal components and Lucide icons.
5. Extend the editor reducer and canvas for measurements, highlights, lines, arrows, notes, trees, revisions, plan opacity/fit, visibility toggles, fixture numbering, multi-run transformer zones, undo/redo, import/export, and deterministic undoable design suggestions.
6. Replace the Fixture Schedule with per-numbered-fixture catalog lamp/accessory editing, copy-to-type actions, fixture recounting, print behavior, and autosave tests.
7. Replace the BOM with live catalog-backed fixture/lamp/accessory/transformer/wire rollups, ordered/received procurement state, supplier/status fields, safe CSV, PDF, and print outputs.
8. Expand Electrical into the reference-equivalent live load document using catalog watts, transformer schedules/zones, 12/2 and 10/2 runs, minimum-voltage design checks, voltage-drop planning estimates, defaults for unresolved specs, PDF, and print.
9. Expand Proposal into a Maxteriors document with zones/areas, fixture detail visibility, plan photos, exact Good/Better/Best and care-plan pricing, milestones, catalog-backed enhancements, honest warranty/commitment settings, inline quote creation, send/email/SMS delivery, PDF, and print.
10. Replace Pre-Con with the persisted grouped 26-item Yes/No/N/A checklist, comments, lead installer, linked contract amount, completion summary, notes, PDF, and print.
11. Add browser automation that clicks every visible studio action and validates artifacts, autosave/restore, conflict safety, workspace scoping, provider error handling, desktop/laptop/mobile layout, keyboard operation, reduced motion, and forced colors.
12. Run focused tests and full backend/frontend/codegen CI, capture representative Maxteriors desktop/mobile states, perform one evidence-led critique and revision, and update `frontend/DESIGN.md` with verified and explicitly unverified production checks.
