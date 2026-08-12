# NiteLiteOS landscape-lighting workflow review

**Reviewed:** August 11, 2026
**Scope:** Authenticated project dashboard and editor at `niteliteos.com`, using the existing `Johnsons` project.
**Purpose:** Record the real workflow and identify product behavior worth adapting to The Tribunal without copying NiteLiteOS branding or its implementation.

## What was exercised

The public marketing, sign-up, sign-in, project dashboard, drawing editor, fixture library, fixture editor, fixture schedule, bill of materials, electrical calculations, proposal, pre-construction checklist, and narrow/mobile editor were inspected in a real browser.

A safe working sheet was created by duplicating the existing drawing instead of overwriting it:

- **Project:** `Johnsons`
- **Working sheet:** `L-1 Copy`
- **Placed plan symbols:** 3 uplights, 2 path lights, 1 downlight, 1 well/in-grade light, and 1 transformer
- **Electrical edit:** a wire route was drawn, the transformer was selected as a zone, and the seven light fixtures were assigned to it
- **Plan display:** fixture code/number tags and the wiring layer were enabled
- **Persistence:** the project was saved through the product's Save action

The original `L-1` sheet remains present. The generated schedule correctly reports seven light-emitting fixtures; the transformer is tracked separately as electrical equipment.

## Created diagram

Local screenshot artifact: `.ezcoder/screenshots/niteliteos-created-diagram.png` (gitignored evidence, captured at 1600 × 1200).

## Observed end-to-end workflow

```text
Projects
  -> Open project
  -> Duplicate or add drawing sheet
  -> Place/crop site drawing
  -> Set drawing scale
  -> Build fixture key from library
  -> Drag fixture-key symbols onto plan
  -> Edit each placed fixture
       color | size | aim | lamp | accessories | duplicate | delete
  -> Draw wire as a point-to-point run
  -> Place/select transformer
  -> Assign fixtures to transformer/run
  -> Review generated outputs
       Fixture Schedule -> BOM -> Electrical -> Proposal -> Pre-Con
  -> Save, present, print, or download PDF
```

The important product model is not merely “icons on an image.” It is a connected document graph:

```text
Fixture library product
  -> fixture-key row
  -> placed, numbered fixture instance
  -> lamp + accessories + wattage
  -> wire run + transformer zone
  -> voltage/load checks
  -> orderable BOM
  -> proposal zone and fixture count
  -> installation checklist
```

## Detailed interaction notes

### 1. Project dashboard

- The dashboard is intentionally minimal: project list, trial state, New Project, Proposals, Billing, Settings, and account controls.
- Opening a project is one click on a full-width project row.
- Project metadata is much lighter than The Tribunal's CRM-linked contact/location/opportunity model.

**Keep from The Tribunal:** CRM-linked records, search/filter/archive, recovery, tenant scoping, and explicit server save state are materially stronger.

### 2. Drawing sheet

- A project can have multiple numbered sheets.
- Add, duplicate, and delete sheet controls are adjacent and persistent.
- The sheet uses a formal title block and fixture legend, making the editor feel like a construction document rather than only a visualization canvas.
- The toolbar includes Select, Undo, wiring visibility, conceptual highlighting, fixture numbers, plan tools, annotations, wiring, legend, file, help, presentation, PDF, and zoom.
- Plan tools include scale calibration, measurement, measurement visibility, AI fixture placement, clearing design marks, and clearing symbols.
- Annotation tools include notes, lines, trees, supplemental photos, arrows, revisions, and a translucent hierarchy-of-light highlighter.

### 3. Fixture placement and editing

- A fixture type is first added to the fixture key/legend, either manually or from a searchable library.
- A fixture is placed by **dragging its legend symbol onto the drawing**.
- Placed fixture instances are automatically counted and numbered by fixture code.
- Clicking a fixture opens a compact anchored popover with:
  - fixture code and instance number;
  - lamp and accessory state;
  - color choices;
  - size controls;
  - an aim/rotation dial;
  - duplicate and delete actions.
- Lamp and accessory choices can be edited per fixture and copied to every fixture with the same code.
- The fixture library supports code, display name, manufacturer/SKU, symbol, search, favorites, and custom entries.

Evidence:

- `.ezcoder/screenshots/niteliteos-fixture-popup.png`
- `.ezcoder/screenshots/niteliteos-fixture-library.png`

### 4. Electrical workflow

- Wiring is a separate display layer, so a clean design view and an electrical view share one plan.
- Draw Wire starts a point-by-point polyline workflow with Undo Point, End Run, and Done controls.
- A T-off workflow snaps a lateral run to an existing main wire.
- Runs carry wire gauge and calculated length after the drawing scale is set.
- Transformer Zones switches to an assignment mode:
  1. click a transformer or run;
  2. click fixtures to assign/unassign them;
  3. finish the assignment mode.
- The electrical document derives:
  - connected watts and amps;
  - suggested transformer size;
  - transformer and circuit fixture counts;
  - wire length and gauge;
  - voltage drop and end voltage;
  - missing wattage, unassigned fixture, and low-voltage warnings.
- Fixtures with no lamp specification can temporarily use a per-type default wattage, but the UI pushes the user back to the fixture schedule to resolve missing data.

### 5. Generated documents

#### Fixture Schedule

- One row per placed fixture instance, not only per fixture type.
- Columns include numbered tag, type, code, lamp, accessories, and “apply to all of this type.”

#### Bill of Materials

- Live tally from all plan sheets.
- Includes fixtures, lamps, accessories, wire, transformers, and additional materials.
- Tracks manufacturer/SKU, needed, ordered, received, unit cost, total, supplier, and notes.
- Supports recount from plan, CSV export, print, and PDF.

#### Electrical

- Live transformer, circuit, load, current, wire, and voltage-drop output.
- Includes explicit design checks instead of silently presenting incomplete calculations.

#### Proposal

- Client/property cover data and design-intent narrative.
- Investment can be split into independently selectable zones.
- Each zone carries fixture count, investment, and an optional photo.
- Milestones, optional enhancements, electrical responsibility, commitments, signature, and client-facing PDF are integrated.

#### Pre-Con

- A 26-item, sectioned installation-readiness checklist.
- Each row has Yes/No/N/A and a comment.
- Covers documentation, utilities, electrical, transformers/zones, wire/mounting, tools/access, and site risks.

### 6. Save and recovery behavior

- The authenticated shell presents an explicit Save button and “Unsaved changes” state.
- The editor does not visibly provide the autosave queue, browser recovery, optimistic version conflict resolution, or safe-copy conflict handling already implemented in The Tribunal.

**Keep from The Tribunal:** server autosave, IndexedDB pending backup, retries, version conflicts, “load Tribunal version,” and “save as a copy.” Those behaviors are safer than the observed manual-save model.

### 7. Narrow/mobile behavior

- The page avoids body-level horizontal overflow at 390 px.
- The dense tab row clips horizontally, the project heading is truncated, and the formal drawing sheet becomes too small for practical editing.
- Controls wrap into many rows and consume much of the viewport before the drawing.
- This is usable for review, but not a strong touch editing experience.

Evidence: `.ezcoder/screenshots/niteliteos-mobile-project.png`

### 8. Follow-up annotation and image-overlay test

A second saved pass on `L-1 Copy` exercised the non-fixture plan layer:

- calibrated a 40 ft reference and added a separate measurement;
- added and edited a plan note;
- added a scalable tree canopy;
- drew a conceptual highlight region;
- added a plain line and directional arrow;
- uploaded a supplemental image onto the plan.

The supplemental image is a genuine sheet object rather than another project photo. It can be moved, resized from a corner, and removed independently of the base drawing and priced fixture layer. That separation is the right model for detail photos, equipment callouts, inspiration images, and site-condition evidence.

Evidence:

- `.ezcoder/screenshots/niteliteos-annotations-measurements.png`
- `.ezcoder/screenshots/niteliteos-plan-image-overlay.png`

## Features to add to The Tribunal

### P0: complete the connected field-document workflow

1. **Electrical plan graph**
   - Place transformers as typed equipment.
   - Draw editable wire runs and T-offs.
   - Assign fixtures to a transformer and circuit.
   - Store wire gauge, run length, lamp wattage, and source voltage.
   - Calculate connected load, current, voltage drop, end voltage, and transformer recommendation.
   - Block misleading output with explicit incomplete-data warnings.
   - **Applied circuit slice:** The Tribunal now traces editable, plan-only `C#` wire routes; assigns each route to a placed transformer and fixtures; stores AWG and 12-15 V tap; calculates route length from scale plus connected watts, current, voltage drop, drop percent, and estimated end voltage; and persists the graph through IndexedDB/server autosave. Missing fixture, transformer, scale, and wattage inputs remain explicit rather than producing a false complete state. T-offs, branching graphs, and automatic transformer recommendations remain later work.
   - Rendered proof: `.ezcoder/screenshots/tribunal-simplified-fixture-workflow.png`; electrical proof: `.ezcoder/screenshots/tribunal-electrical-load.png`; 390 px proof: `.ezcoder/screenshots/tribunal-simplified-fixture-workflow-mobile.png`.

2. **Per-instance fixture schedule**
   - Give every placed fixture a stable code and sequence number, such as `U/B (3)`.
   - **Applied plan-tag slice:** every fixture and transformer now receives a compact type-plus-sequence tag (`UP1`, `PL1`, `T1`) on the editable plan while the customer dusk export stays clean.
   - Store lamp, wattage, accessories, aim, and notes per instance.
   - Support “apply lamp/accessories to all fixtures of this type.”
   - Keep the current explicit icon buttons for changing type; they are clearer than silently cycling the symbol.

3. **Complete BOM**
   - Expand the current fixture-only table to transformers, cable, connectors, controls, lamps, accessories, and manual materials.
   - Add needed/ordered/received quantities, supplier, manufacturer/SKU, unit cost, total, and notes.
   - Add safe CSV/PDF export.
   - **Applied supplier-export slice:** the BOM now downloads a spreadsheet-safe CSV that expands catalog components, multiplies and aggregates physical SKUs from placed fixture/transformer quantities, includes traced wire by AWG, carries supplier/manufacturer attributes when present, and flags missing SKU or scale data instead of silently omitting incomplete order lines. Procurement state, cost totals, manual materials, field allowance, and PDF export remain later work.

Remaining local gaps:

- Wire routes are single editable polylines; T-offs, branch topology, loop validation, and automatic conductor routing are not implemented.
- The BOM still needs calculated cable allowance, connectors, controls, lamps/accessories, procurement state, and manual materials.
- The current schedule aggregates fixture types instead of producing one editable row per placed fixture.

### P1: make the design usable through installation

4. **Designer-focused fixture library**
   - Search price-book products by code, name, manufacturer, and SKU.
   - Store a drafting symbol, lamp compatibility, default wattage, accessories, and favorite placement shortcuts.
   - Reuse the existing workspace catalog as the source of truth instead of creating a parallel catalog.

5. **Plan measurement and annotation layer**
   - Retain current calibration.
   - Add arbitrary measurements, measured wire routes, notes, arrows, lines, trees, supplemental photos, and revision rows.
   - Keep annotations structurally separate from quote-producing fixture data.
   - **Applied first slice:** The Tribunal now accepts PNG/JPEG/GIF/WebP/AVIF files through direct canvas drop or an accessible file picker, persists them as plan-only images, and supports pointer or keyboard movement, proportional pointer or keyboard resize, undo, delete, IndexedDB recovery, and server autosave.
   - Rendered proof: `.ezcoder/screenshots/tribunal-plan-image-moved-resized.png`; 390 px proof: `.ezcoder/screenshots/tribunal-plan-image-mobile.png`.

6. **Operational pre-con checklist**
   - Replace the current four computed readiness signals with an editable, sectioned checklist.
   - Track Yes/No/N/A, comments, assignee, timestamp, and completion status.
   - Keep computed gates, but distinguish them from human field confirmation.

7. **Proposal zones**
   - Map one or more drawing sheets to independently priced proposal zones.
   - Pull fixture counts from the approved plan.
   - Support milestones, enhancements, responsibility language, warranties, and signature without duplicating quote math.

### P2: productivity and presentation

8. **Fixture numbering toggle and legend reconciliation**
   - Show/hide code plus sequence tags on the plan.
   - Recount from plan with a preview and non-destructive confirmation.

9. **AI fixture placement as a draft**
   - Keep the existing AI dusk rendering separate.
   - If automatic fixture placement is added, write suggestions into a reviewable draft layer and require operator acceptance before quote/BOM impact.

10. **Construction-document exports**
    - Tabloid/letter title blocks, revision metadata, per-document print/PDF, combined plan package, and presentation mode.

## What not to copy

- **Emoji-labeled controls:** use The Tribunal's existing Lucide icon system and accessible names.
- **Manual Save as the only safety mechanism:** preserve The Tribunal autosave and recovery model.
- **A single dense toolbar:** keep progressive disclosure and move electrical/annotation tools into task-specific modes.
- **Tap-to-cycle fixture type:** retain explicit labeled type choices.
- **Tiny mobile sheet:** use a focused mobile canvas with bottom-sheet tools and a separate read-only document preview.
- **Editable document text without domain structure:** keep typed fields and validation instead of relying on unrestricted `contenteditable` regions.
- **Iframe-style editor isolation:** keep The Tribunal's typed React integration, API contracts, query keys, and project-level concurrency.

## Recommended implementation order

```text
1. Electrical domain types + persistence
2. Transformer and wire-run canvas interactions
3. Per-instance lamp/accessory fixture schedule
4. Electrical calculations + validation tests
5. Complete BOM and exports
6. Proposal-zone adapter
7. Editable pre-con checklist
8. Annotations, favorites, AI placement draft
```

This order makes each later document derive from one validated design graph instead of rebuilding the same fixture, load, and zone logic in multiple tabs.

## Evidence inventory

- Public landing page: `.ezcoder/screenshots/niteliteos-home.png`
- Sign-up: `.ezcoder/screenshots/niteliteos-signup.png`
- Sign-in: `.ezcoder/screenshots/niteliteos-login.png`
- Authenticated dashboard: `.ezcoder/screenshots/niteliteos-dashboard.png`
- Original project editor: `.ezcoder/screenshots/niteliteos-project.png`
- Created plan: `.ezcoder/screenshots/niteliteos-created-diagram.png`
- Fixture popup: `.ezcoder/screenshots/niteliteos-fixture-popup.png`
- Fixture library: `.ezcoder/screenshots/niteliteos-fixture-library.png`
- Fixture schedule: `.ezcoder/screenshots/niteliteos-fixture-schedule.png`
- BOM: `.ezcoder/screenshots/niteliteos-bom.png`
- Electrical: `.ezcoder/screenshots/niteliteos-electrical.png`
- Proposal: `.ezcoder/screenshots/niteliteos-proposal.png`
- Pre-con: `.ezcoder/screenshots/niteliteos-precon.png`
- Narrow/mobile project: `.ezcoder/screenshots/niteliteos-mobile-project.png`
- Scale, measurement, and annotation pass: `.ezcoder/screenshots/niteliteos-annotations-measurements.png`
- Supplemental plan image: `.ezcoder/screenshots/niteliteos-plan-image-overlay.png`
