# Frontend design notes

Living notes for the operator-facing UI. Add a section when a surface's layout
rules are non-obvious from the components alone.

## Sidebar navigation (Aug 2026)

### Design read

- **Surface:** the app shell's primary navigation, present on every CRM screen.
- **Audience:** operators on laptops — measured windows run 1280x800 down to
  1440x700, well under the 39 destinations the CRM now ships.
- **Single job:** show the whole option space and get you to any destination in
  one or two clicks, without hiding anything behind an invisible scroll.

### The problem it solves

The nav rendered every section expanded: 1651px of content against 570-770px of
usable height, so 20-24 of 39 items sat off-screen. macOS overlay scrollbars
stay invisible until you scroll, so the list simply looked like it ended — the
last visible row was clipped in half at the fold. Collapsed to the icon rail it
was worse: the base component sets `overflow: hidden` there, so the icons below
the fold could not be reached by any gesture.

### Layout rules

- **One open section.** `SidebarNav` in `components/layout/app-sidebar.tsx`
  keeps exactly one section expanded. The open section is derived from the route
  (`findNavSectionIdForPath`), so deep links and command-palette jumps land with
  the right group open; a manual toggle overrides that only while you stay on
  the same path. No effect syncs it — it is computed during render.
- **Sections stay at six items or fewer** (`app-nav.ts`, asserted in
  `app-nav.test.ts`). Resting height is `(sections - 1) x 40px + the open
section`, which is what keeps the whole nav inside a 700px-tall window. Split
  a section rather than growing it.
- **Section headers are buttons** (`SidebarGroupLabel asChild`), sticky to the
  top of the scroll area, and carry only additive utility classes — `asChild`
  concatenates class strings without tailwind-merge, so restating the label's
  colour, size or weight would leave two competing classes.
- **The icon rail scrolls** and renders every section expanded: its headers are
  hidden by design, so a closed section there would be unreachable.
- **A bottom fade marks overflow.** It is the only resting cue that the list
  continues, since the scrollbar is invisible until it moves; a ResizeObserver
  keeps it in sync with section toggles, capability changes and resizes.

### Menu surfaces

`DropdownMenuSubContent` and `PopoverContent` (`components/ui/`) clamp to their
Radix `--radix-*-content-available-height` and scroll internally, matching
`DropdownMenuContent` and `SelectContent`. Any portal menu that can grow past
the viewport needs that pair; without it the overflow is unreachable rather than
scrollable.

## Contact console + contact detail (Jul 2026)

### Design read

- **Surface:** dense application UI (CRM operator console), dark-first theme.
- **Audience:** home-service owners and dispatchers triaging leads on desktop,
  checking a contact between jobs on a phone.
- **Single job:** the conversation page makes replying easy with contact context
  one glance away; the detail page answers "who is this and what has happened?".
- **Content extremes:** long mailing addresses, long agent names, message bodies
  of arbitrary length, contacts with zero activity.

### Thesis

Every pane is a bounded column. Content wraps or truncates _inside_ its rail, and
the contact record gets a full-width home where its facts and history can breathe
instead of fighting the conversation for horizontal space.

### Layout rules

- `ScrollArea` (`components/ui/scroll-area.tsx`) forces the Radix viewport's
  injected wrapper back to `display: block; width: 100%`. Radix ships it as
  `display: table`, which shrink-to-fits to the content's max-content width — in
  a fixed rail that pushes long values past the column, where `overflow-hidden`
  clips them. This is why quick actions, addresses and badges used to disappear
  off the right edge.
- The conversation console (`components/layout/conversation-layout.tsx`) renders
  three columns only at ≥1280px: `minmax(280px,320px) minmax(0,1fr) minmax(300px,340px)`.
  `minmax(0, 1fr)` is load-bearing; a bare `1fr` floors at the message column's
  max-content width and shoves the contact rail off screen.
- Below 1280px the rails become slide-overs (`Sheet`) triggered from a compact
  bar above the conversation. Sheets own their close control and carry an
  `sr-only` `SheetTitle`/`SheetDescription` for an accessible name.
- Rail values truncate with the full string in `title`; roomy layouts pass
  `wrapValues` to `ContactInfoSection` so addresses show in full.
- Breadcrumbs in the app header collapse ancestors below `sm` and truncate the
  current page, so deep routes such as `/contacts/123/details` never wrap the
  header on a phone.

### Contact detail page

Route: `/contacts/[id]/details` → `components/contacts/contact-detail/`.

- Identity card (avatar, status, engagement, last engaged) with Message, Call,
  Schedule and Edit. Message returns to the conversation; Call reuses
  `callContact` from `use-contact-sidebar-data`, so the rail and the page fail
  the same way when no voice-enabled number exists.
- Left column reuses the rail sections (`ContactInfoSection`,
  `ImportantDatesSection`, `ContactNotesMeta`, `EngagementSummary`,
  `ContactFilesMedia`) so both surfaces stay in sync.
- Right column is `ContactHistory`: messages, calls, appointments and quotes
  merged by `lib/contacts/contact-history.ts` into one reverse-chronological
  record, grouped by day, with future-dated bookings hoisted into an "Upcoming"
  section that shows the date, not just a time. Filters are `aria-pressed`
  buttons with counts, matching the contacts filter bar's segmented control.
- No new endpoints: it composes `GET /contacts/{id}/timeline`, the appointments
  list and the quotes list, all through shared hooks in `hooks/useContactRecords.ts`
  so the cache is shared with the rail.

### States covered

Loading skeletons, request error with retry, no-activity empty state,
filtered-empty state, contact-not-found (`notFound()`), and the narrow/mobile
stacked layout.

## Landscape lighting builder

### Design read

- **Surface:** a dashboard/data-dense design tool inside the authenticated CRM.
- **Audience:** landscape-lighting sales reps working at a desk, on a laptop in a
  home, or on a tablet in the field.
- **Single job:** turn a top-down satellite, drone, or site-plan image into a fixture
  and wiring plan that a homeowner can understand and a quote can price.
- **Risk and density:** placement and fixture-count errors affect margin and the
  install crew, so the aerial, fixture palette, beam controls, and server-priced
  count stay visible together. The canvas leads; pricing remains supporting data.
- **Platform:** desktop and landscape-tablet are primary. Narrow screens stack the
  aerial plan, tools, and estimate in task order without removing actions.

### Evidence and thesis

The user-provided NiteLiteOS proposal screenshots consistently use property imagery
as the drawing ground, color-coded symbols tied to a fixture legend, and a document
title block carrying project metadata. Tribunal intentionally narrows that flexible
reference to a **top-down aerial plan**; street-level and elevation photos are outside
the landscape workflow. The authenticated screenshot also shows a persistent project
rail for Drawing Sheet, Fixture Schedule, BOM, Electrical, Proposal, and Pre-Con, plus
a visible automatic-save state.

The leading direction is a **proposal sheet on a dark drafting desk**. The white
sheet and right-edge title block make the empty builder specific to lighting plans,
while the working editor preserves the CRM's existing black/brass lighting system.
The memorable device belongs because the output is literally a customer proposal
and install plan, not a generic dashboard.

### Reuse map and behavior

- Reuse `LightDesigner`, `LightCanvas`, `ToolPalette`, the workspace price book,
  server pricing, dusk preview, AI render, and multi-aerial sheet model. The landscape
  AI prompt must preserve the top-down viewpoint rather than inventing a street-level
  elevation. Proposal pricing and draft-quote creation stay inside the landscape project
  instead of routing through the separate quote builder.
- Lock the dedicated route to landscape fixtures and remove seasonal-only controls.
- Keep the existing `AppSidebar`, billing capability gate, Lucide icon system, focus
  treatment, and responsive pane order.
- Expose real project sections for Drawing Sheet, generated fixture/equipment schedule,
  BOM, connected-load calculations, composited proposal preview, and a computed pre-con
  checklist. Connected watts and current use the Tribunal FX catalog; transformer
  utilization appears only after a transformer symbol is placed. Traced circuit length,
  copper wire gauge, transformer tap, and assigned fixtures now drive a conservative
  voltage-drop estimate with explicit incomplete and review states. The BOM offers a
  supplier CSV that expands catalog components, aggregates supplier SKUs, includes
  transformer and traced wire quantities, and flags rows that still need a SKU or scale.
- Browser-only standalone sessions still autosave workspace drafts to IndexedDB and
  label them as local. The project dashboard offers those legacy records as
  **Recover browser draft**, requires a CRM customer, creates the server project,
  and deletes the legacy record only after the create request succeeds.
- Server-backed sessions use stable `/landscape-lighting/[projectId]` URLs and show
  the project name, customer, authoritative updater/time, and save state above the
  drawing workspace. The adapter disables workspace-keyed restore/save and emits
  the same complete draft after 600 ms without changing quote-hosted or seasonal
  behavior.
- Empty state includes the complete three-step path, an honest zero-count fixture
  legend, and unset project metadata rather than fabricated customer data.
- The working drawing now leads with one compact toolbar: select, scale, wire, undo, and
  NiteLite-informed placeable fixture symbols. Fixtures and transformers receive stable
  plan tags, while each dashed circuit receives a `C#` label. Details assigns fixtures
  and transformers, sets AWG and transformer tap, and keeps the fixture legend visible.
  Plan-only wire geometry never enters quote-producing footage or fixture quantities.
  Circuit details offer 12/2 and 10/2 AWG cable for new runs; older 8 and 14 AWG values
  remain readable on saved plans. Calibrated route feet are priced only when the selected
  package carries a matching wire catalog item, otherwise the proposal and supplier CSV
  identify the missing catalog price or SKU instead of inventing one.
- The Proposal tab presents the workspace's ordered Good, Better, and Best packages,
  server-owned fixture unit prices and installation totals, plus annual care-plan options.
  This dedicated flow has no financing choice: it uses each selected CRM price-book row
  directly, without client-side amounts, finance gross-up, or cash discount. Price-book
  changes therefore flow into the design on the next catalog refetch. Switching package
  re-resolves every placed fixture without changing geometry.
  The package and care-plan selection autosaves with the project, and creating the CRM
  draft quote preserves its customer, opportunity, and service-location linkage.
- Selecting one placed fixture exposes its CRM product/SKU, lamp specification, included
  accessory components, plan-marker color, symbol sizing, beam spread, aim, circuit,
  duplicate, and delete controls. Marker/size/aim edits remain visual or plan metadata and
  never change quote quantities. Adding or duplicating a fixture bypasses the normal drawing
  debounce and queues the complete project draft for immediate server persistence; slower
  drag/aim changes retain coalesced autosave and optimistic-conflict protection.
- Server-backed projects remove the duplicated inner project identity and keep only
  compact aerial, render, and quote actions. The drawing title block uses the supplied
  Maxteriors logo instead of synthesizing a text brand.
- Loading and no-workspace recovery use shared page-state primitives. Upload errors
  remain announced by the existing image-loader error path; disabled rendering
  explains that a fixture must be placed first.

### CRM project identity and persistence

- **Primary flow:** the dashboard makes creating or opening one customer-linked
  lighting plan the obvious task. Active and archived records use a compact native
  table on desktop and ordered record cards on narrow screens, with the same fields
  and action order in both compositions.
- **One shared rail:** dashboard header, recovery notice, filters, and records share
  `max-w-7xl` gutters. The editor project bar and bounded drafting workspace share a
  wider `max-w-[1600px]` rail because the aerial canvas needs the working area.
- **Save language:** `Saved to Tribunal` appears only after an accepted server
  response. `Saved on this device; sync pending` means IndexedDB holds newer work
  that is not team-visible. Saving/loading/conflict states are announced through a
  stable `aria-live` region without moving focus.
- **Concurrency:** one versioned PATCH runs at a time and later edits collapse to
  one latest queued draft. Network and 5xx failures keep the device copy and retry
  with a bounded delay. A stale version never overwrites the row.
- **Conflict recovery:** the Radix dialog has a real title and description, can be
  dismissed with Escape and reopened from the project bar, and offers only two
  non-destructive outcomes: load Tribunal after fetching it, or create a separate
  customer-linked copy from this device's complete draft. There is no force-save.
- **Responsive behavior:** project identity and save state stack before the canvas
  below the desktop breakpoint. Dashboard records recompose instead of forcing a
  page-wide horizontal scrollbar; the existing canvas remains bounded inside its
  own working region.
- **Scope boundary:** image data URLs remain in the validated document for this first
  persistence slice. Protected binary assets, revision history, branched/looped circuit
  graphs, automatic conductor routing, field-verified voltage, quote snapshots, exports,
  and delivery remain later work and are not implied by this UI.

### Production checks

Check desktop and narrow dashboard/editor layouts, keyboard focus order, visible
focus, dialog Escape/focus return, aerial canvas accessible name and instructions,
200% zoom/reflow, reduced motion, measured text/control contrast, aerial upload
failure, empty workspace, local-only recovery, offline retry, stale-record detection,
and both conflict outcomes. Automated checks cannot establish full WCAG conformance;
keyboard and assistive-technology behavior remain manual verification items.

### Persistence slice rendered critique (2026-08-11)

Evidence: `lighting-projects-desktop.png`, `lighting-projects-narrow.png`,
`lighting-editor-final.png`, and `lighting-editor-conflict-revised.png` under the
local `.ezcoder/screenshots/` verification directory.

1. **Brief specificity 2/2:** customer, project, archive, drafting sheet, and sync
   language identify a landscape-lighting CRM workflow without relying on the logo.
2. **Information hierarchy 2/2:** project identity, primary create/open action, and
   current save state lead; archive and secondary drafting controls stay subordinate.
3. **Composition 2/2:** shared rails align the dashboard while the wider editor rail
   gives the drawing sheet a content-driven exception.
4. **Consistency and flow 2/2:** existing buttons, inputs, Radix dialog, Lucide icons,
   borders, and navigation anatomy carry from list through conflict recovery.
5. **Typography 2/2:** existing product type roles stay legible across utility labels,
   record content, project identity, and the technical drawing sheet.
6. **Material and surface logic 2/2:** borders contain records and metadata; only the
   conflict overlay adds elevation because it blocks editing until a version is chosen.
7. **State completeness 2/2:** loading, empty, error/retry, active/archived, local
   pending, server saved, offline, conflict, disabled, and success paths are implemented.
8. **Responsive behavior 2/2:** desktop table becomes narrow record cards; project
   identity and sync stack; 320 px probes measured no document-level overflow.
9. **Accessibility quality floor 1/2:** native forms/tables, labels, live status,
   keyboard conflict actions, Escape, focus return, reduced motion, and forced-colors
   execution were verified. A representative screen-reader pass and full per-criterion
   WCAG audit remain unverified, so no conformance claim is made.
10. **Motion purpose 1/2:** new states are calm and reduced-motion execution works,
    but inherited shared Button/Dialog motion was not manually audited in every state.
11. **Content authenticity 2/2:** captures use a local named probe customer; save wording
    distinguishes server truth from browser-only recovery without unsupported claims.
12. **Visual distinctiveness 2/2:** the amber technical drawing sheet, fixture legend,
    sheet controls, and title block create a domain-specific signature.

**Final score: 22/24.** The first critique found contradictory placeholder identity
inside a named CRM project and repeated save badges. The revision wired project,
customer, and workspace identity into the title block and removed the duplicate inner
status, then recaptured the editor. No decorative layer was added in its place.

Production evidence: focused and full unit suites, type checking, production build,
versioned API probes, 320 px reflow, reduced-motion/forced-colors execution, dialog
Escape, and focus return passed. Manual assistive-technology output, a complete 200%
text-zoom audit, and formal contrast sampling remain specifically unverified.

### Simplified aerial workflow critique (2026-08-11)

Evidence: `tribunal-simplified-fixture-workflow.png`,
`tribunal-electrical-load.png`, and
`tribunal-simplified-fixture-workflow-mobile.png` under
`.ezcoder/screenshots/`.

1. **Brief specificity 2/2:** the aerial drawing, FX fixture symbols, fixture legend,
   transformer placement, and connected-load panel are specific to landscape lighting.
2. **Information hierarchy 2/2:** fixture placement leads on the drawing; detail and
   document actions remain one obvious control away.
3. **Composition 2/2:** the single compact tool row aligns with the sheet and leaves the
   aerial plan as the dominant surface.
4. **Consistency and flow 2/2:** existing brass/black controls, Lucide icons, tabs,
   autosave, schedule, and sheet actions retain their established behavior.
5. **Typography 2/2:** compact technical labels stay subordinate to fixture and load data.
6. **Material and surface logic 2/2:** the dark drafting desk separates controls from the
   white field document without decorative cards or hover lift.
7. **State completeness 2/2:** empty load, missing transformer, unassigned fixtures,
   missing scale/wattage, limited headroom, over-capacity, voltage-drop review, and
   calculated states are represented.
8. **Responsive behavior 1/2:** the 390 px capture keeps every action reachable and the
   drawing inside its own horizontal working region; complete 200% text reflow remains
   unverified.
9. **Accessibility quality floor 1/2:** direct fixture buttons expose pressed state and
   product names, menus remain semantic, load tables include headers/captions, and status
   is announced. A representative screen-reader pass remains unverified.
10. **Motion purpose 2/2:** feedback uses restrained color/border transitions and inherits
    the reduced-motion override.
11. **Content authenticity 2/2:** electrical values come from catalog attributes or the
    known Tribunal fixture map; voltage drop discloses its route, gauge, tap, assigned
    load, and planning-estimate status instead of presenting a field measurement.
12. **Visual distinctiveness 2/2:** the fixture icon dock, retained legend, branded title
    block, and technical load sheet form one recognizable field-planning system.

**Final score: 22/24.** The first narrow capture showed repeated project identity and
three large action rows before the canvas. The revision removed the duplicate server
identity, shortened the server action bar, and made utility buttons icon-only on narrow
screens while preserving accessible names. No decorative replacement was added.

### In-project pricing and fixture-options critique (2026-08-11)

Evidence: `tribunal-landscape-proposal-pricing.png`,
`tribunal-landscape-proposal-pricing-mobile.png`, and
`tribunal-fixture-options.png` under `.ezcoder/screenshots/`.

1. **Brief specificity 2/2:** package, fixture, care, cable, and CRM catalog language names
   the exact landscape-lighting sales task without relying on branding.
2. **Information hierarchy 2/2:** package choice leads, fixture/wire prices explain it,
   care stays separate, and draft-quote creation closes the flow.
3. **Composition 2/2:** package controls, price table, route pricing, care, and total share
   the field-document rail and consistent section dividers.
4. **Consistency and flow 2/2:** existing tabs, buttons, table anatomy, dark/brass controls,
   autosave, and CRM quote behavior continue through the new panels.
5. **Typography 2/2:** technical utility labels, package totals, specification terms, and
   explanatory copy retain clear roles at desktop and narrow widths.
6. **Material and surface logic 2/2:** the proposal remains one printable sheet; only the
   selected package, selected marker color, and final total receive stronger containment.
7. **State completeness 2/2:** loading, empty, retry, unpriced wire, unresolved SKU, disabled,
   pending, selected, and successful draft-quote states are implemented and tested.
8. **Responsive behavior 1/2:** the 390px browser probe asserts package controls remain
   inside the proposal sheet; 320px and complete 200% text reflow remain unverified.
9. **Accessibility quality floor 1/2:** fieldsets, legends, table captions, pressed states,
   accessible control names, focus-visible styles, and drag alternatives are present;
   manual screen-reader and full WCAG criterion audits remain unverified.
10. **Motion purpose 2/2:** only named border/shadow transitions explain selection, and the
    reduced-motion rule shortens those transitions without removing state meaning.
11. **Content authenticity 2/2:** the backend reads CRM catalog prices exactly, removes the
    finance/cash fork, and labels missing wire SKUs rather than inventing prices.
12. **Visual distinctiveness 2/2:** the technical fixture specification rail and proposal
    sheet make the feature recognizable as a landscape-lighting field sales tool.

**Final score: 22/24.** The first mobile proposal capture exposed grid min-content overflow;
the revision constrained the proposal grid and sheet box model, then recaptured and measured
controls inside the 390px sheet. Finance copy and monthly pricing were also removed rather
than adding another pricing treatment.

### NiteLiteOS workflow-parity studio critique (2026-08-11)

**Design read:** this is a dense professional drafting and sales workspace for Maxteriors
estimators and installers. Its single job is to move a CRM customer-linked property from plan
placement through exact price-book proposal and installation readiness without leaving the
project. Desktop/laptop use leads; narrow screens preserve the entire editor through local
horizontal overflow rather than hiding actions.

**Thesis and reuse:** the white drawing sheet remains the dominant object on a charcoal drafting
desk. Black/brass Tribunal controls, existing type roles, Lucide icons, Maxteriors identity,
CRM customer facts, and native button/menu/table primitives provide continuity. Workflow tabs,
toolbar groups, sheet strip, canvas, document sheets, and save/send actions share one 1800px
working rail. No reference assets, emoji, fabricated pricing, financing, or branched electrical
claims are used.

Evidence available for this cycle: prior authorized reference captures listed above; new
desktop 1440x1000 and mobile 390x844 rendered captures at
`.ezcoder/screenshots/maxteriors-studio-{desktop,mobile}.png`; structural and interaction
evidence from `drawing-toolbar.test.tsx`, `lighting-project-editor.test.tsx`,
`light-designer.test.tsx`, and the route-intercepted authenticated
`e2e/landscape-lighting-studio.spec.ts`.

1. **Brief specificity 2/2:** sheet size, fixture schedule, procurement, transformer runs,
   voltage-drop checks, proposal delivery, and pre-con language identify the exact workflow.
2. **Information hierarchy 2/2:** project identity/save/send leads, six fixed workflow tabs set
   sequence, the drawing sheet dominates, and document actions remain one menu away.
3. **Composition 2/2:** project header, tabs, toolbar, sheets, and document panels share the
   1800px studio rail; print sheets remain bounded working objects.
4. **Consistency and flow 2/2:** Lucide icons, Tribunal buttons/Radix menus, black/brass controls,
   stable tab order, and repeated Print/PDF behavior carry through all six tabs.
5. **Typography 2/2:** inherited product type roles distinguish compact drafting utilities,
   technical tables, document headings, totals, and checklist content.
6. **Material and surface logic 2/2:** dark controls belong to the drafting desk, white content
   belongs to printable output, and overlays are reserved for menus/conflicts.
7. **State completeness 2/2:** autosave, queued/offline/conflict recovery, unresolved catalog
   rows, disabled quote/send actions, delivery failures, destructive confirmation, and pre-con
   completion are implemented with status feedback.
8. **Responsive behavior 2/2:** rendered 390px evidence proves local horizontal overflow retains
   workflow, toolbar, and sheet controls while the drawing remains the dominant object.
9. **Accessibility quality floor 1/2:** tab semantics/arrow keys, labeled menu alternatives,
   native tables/forms, live status, focus-visible treatment, reduced motion, and forced-colors
   automation exist. Screen-reader output and a complete per-criterion WCAG audit are unverified,
   so no conformance claim is made.
10. **Motion purpose 2/2:** feedback uses named color/border/background transitions, no hover
    lift or ambient motion, and reduced motion preserves state meaning.
11. **Content authenticity 2/2:** purchasable names/SKUs/prices/watts resolve from the active CRM
    catalog; missing mappings stay unresolved; electrical output says it is not field-verified.
12. **Visual distinctiveness 2/2:** stable workflow rail, dense brass drafting toolbar, sheet
    strip, drawing title block, fixture legend, and printable install documents make the studio
    recognizable without copying reference trade dress.

**Final score: 23/24.** The first fresh capture exposed a duplicated workflow rail between the
project shell and editor, which wasted drafting height and weakened mobile hierarchy. The revision
removed that redundant rail for server-backed projects and recaptured both viewports. It also
removed the separate Help dropdown, an unnecessary duplicate beside direct Present/PDF/Help
controls, and forwarded menu-trigger props/ref so expanded and keyboard states work correctly.
Full assistive-technology testing, formal measured contrast sampling, and complete 200% text zoom
remain explicitly unverified.

### Fixed drawing desk refinement (2026-08-14)

#### Design read and evidence

- **Surface:** desktop-first, data-dense landscape-lighting drafting and document workspace.
- **Audience:** estimators and sales operators using keyboard, mouse, trackpad, or touch while
  building an installation-ready, customer-sendable plan.
- **Single job:** keep one registered top-down aerial fixed while fixtures, wiring, pricing,
  procurement, and pre-construction records move through six predictable workflow steps.
- **Risk:** accidental image movement, stale settings, missing fixture counts, or unclear save
  state can create installation and quote errors.
- **Primary local evidence:** authenticated NiteLite OS captures under
  `.ezcoder/screenshots/niteliteos-reference/`, the prior Maxteriors captures, 18 final renders
  under `.ezcoder/screenshots/niteliteos-final/{desktop,tablet,mobile}/`, component tests, and the
  route-intercepted authenticated Playwright flow in `e2e/landscape-lighting-studio.spec.ts`. The
  reference supplies hierarchy and workflow evidence only; no NiteLite marks, assets, source, or
  emoji controls are reused.

#### Thesis and craft system

**One fixed drawing desk.** Project identity and save safety lead in one light 50px row. The six
plain-text workflow steps form the second read. Two compact black tool rows and a charcoal stage
frame the white document, while muted gold is reserved for selected modes and primary drawing
actions. The aerial and generated documents, not CRM chrome, occupy the viewport.

- The focused project route uses the existing `Sidebar` off-canvas mode; the deliberate
  `SidebarTrigger` restores CRM navigation without a resting icon rail.
- Existing typography, Lucide icons, Radix menus/dialogs, `Button`, autosave status, conflict
  recovery, price-book calculations, quote delivery, and `LightCanvas` editing remain the reuse
  foundation.
- `DrawingToolbar` owns the two-row command geometry. Fixture shortcuts live under Add, all
  sixteen named marker colors remain immediately visible, and every exposed command changes a
  setting/tool/document, opens a real picker/menu/dialog, or reports a disabled reason.
- `DocumentViewport` is shared by Drawing, Schedule, BOM, Electrical, Proposal, and Pre-Con.
  Fit, plus, minus, range, and percentage controls sit outside the paper and preserve the visual
  center during manual zoom.
- Borders and material changes separate header, drafting controls, stage, and paper. There is no
  decorative gradient, glass layer, generic hover lift, `transition: all`, or ambient motion.

#### Fixed-aerial contract

- The top-down base aerial is a locked landscape-only background. Wheel, middle-button/space
  drag, and two-finger gestures cannot change its internal view transform.
- `ResizeObserver` recomputes one deterministic contain or cover fit after container, sidebar,
  fullscreen, tab, or viewport changes. Replacing the aerial recomputes that fit; fixtures, wire
  routes, highlights, measurements, and movable supplemental insets remain in image-space
  coordinates.
- The shared seasonal/property-photo workflow retains its free pan, wheel zoom, and pinch zoom.
- Sheet-level zoom scales the complete document around the registered drawing. It does not alter
  image coordinates or cover the canvas with controls.

#### State and document behavior

The emitted V2 draft includes `paperSize`, `planFit`, `planOpacity`, legend visibility/position/
scale, halo/fixture-number/measurement visibility, source voltage, active workflow tab, complete
proposal settings and selections, procurement, and pre-con responses. Browser restore, Tribunal
autosave, editable JSON import/export, and conflict reset hydrate the same complete state. Legacy
fixtures without `markerColor` keep their semantic fixture colors; selecting a named swatch writes
a stable per-fixture color, and new fixtures receive the current toolbar color.

Non-drawing tabs share contextual document actions: Print on Schedule; Recount, CSV, PDF, and
Print on BOM; PDF and Print on Electrical, Proposal, and Pre-Con. PDF actions honestly open the
browser print dialog for Save as PDF.

#### Responsive states

- **Wide desktop:** one project row, one workflow row, two tool rows, one sheet strip, and the
  fitted paper plus external zoom rail. The CRM sidebar consumes zero resting width.
- **Tablet / 768px:** toolbar groups wrap as intact units, workflow labels scroll only when they
  cannot fit, and the entire paper starts fitted.
- **Mobile / 390px:** project name truncates before Send proposal and Save, normal saved status
  becomes screen-reader-only, tool and sheet groups wrap, and the desktop document anatomy remains
  a stable fitted thumbnail instead of cropping or recomposing.
- **Print:** project/workflow/tool chrome and the zoom rail are removed; the active paper resets
  to an untransformed landscape print layout.
- **Reduced motion and forced colors:** named transitions collapse under reduced motion; document
  controls use system colors in forced-colors mode while marker swatches retain color plus a
  non-color check and selection ring.

#### Verification boundaries

Verified automatically: TypeScript, targeted Vitest state/geometry/menu tests, six-tab keyboard
navigation, native marker radio semantics, fixed-aerial resize and gesture regression, visual-center
zoom math, complete V2 serialization, autosave/conflict component behavior, Playwright mouse and
keyboard editing, mobile fit, toolbar reflow, reduced-motion execution, forced-colors execution,
quote creation, proposal delivery, and screenshot capture.

Still unverified manually: representative screen-reader output, voice-control naming, browser
text-only zoom at 200%, physical touch-device behavior, print output on multiple printer drivers,
and a criterion-by-criterion WCAG 2.2 audit. Automated checks do not establish WCAG or ADA
conformance.

#### Evidence-led critique and revision

The first 18-view capture exposed two concrete fit defects: the tall Pre-Con document reached the
20% zoom floor and cropped on narrow screens, while nested sheet shadows produced inconsistent
paper edges across workflow tabs. The revision lowered the safe document floor to 10%, moved paper
material and shadow to the shared viewport, removed nested sheet shadows, and renamed the ambiguous
sheet-strip action from “Add aerial” to “Add sheet.” All six documents were then recaptured at
1440×960, 768×1024, and 390×844.

Rubric (0–2 each): brief specificity 2; information hierarchy 2; composition 2; consistency and
flow 2; typography 2; material and surface logic 2; state completeness 2; responsive behavior 2;
accessibility quality floor 1; motion purpose 2; content authenticity 2; visual distinctiveness 2.

**Final score: 23/24.** Accessibility remains 1/2 because automated keyboard, semantics, reduced-
motion, and forced-colors evidence cannot substitute for the manual assistive-technology, 200%
text-only zoom, physical touch, printer, and complete WCAG checks listed above. No required
criterion scores zero.

### Editable schedule and purchasing workflow (2026-08-17)

**Design read:** this remains a desktop-led professional operations workspace for landscape-lighting
estimators, purchasing staff, and installers. The single job is to turn placed fixtures into an
accurate, order-ready material list without breaking the drawing as source of truth. Quantity and
supplier mistakes have direct margin and installation-delay costs, so calculated values must remain
traceable, editable, recoverable, and saved with the CRM project.

**Behavioral evidence:** the user-supplied NiteLiteOS project URL redirected the unauthenticated
browser to sign-in. Two existing authorized repository captures were used only to understand flow:
`.ezcoder/screenshots/niteliteos-fixture-schedule.png` showed per-fixture lamp/accessory assignments,
and `.ezcoder/screenshots/niteliteos-bom.png` showed plan recount, order tracking, cost, supplier,
notes, export, and print. `.ezcoder/screenshots/maxteriors-studio-desktop.png` was the contrast and
local source: Tribunal's black/brass drafting chrome, paper-sheet work surface, Lucide icons, and CRM
save model remain the visual language. No competitor code, assets, wording, dimensions, or trade
dress were copied.

**Thesis and reuse:** the drawing owns base quantities; the schedule owns per-fixture specification;
the BOM owns purchasing overrides. Recount removes only manually overridden Needed quantities, so
ordered/received progress, cost, supplier, and notes are never destroyed. Existing workflow tabs,
autosave, document normalization, catalog data, table surfaces, button hierarchy, focus treatment,
CSV safeguards, and print behavior are reused. The memorable device is this visible calculated-to-
override contract rather than a decorative motif.

**Components and states:**

- Fixture Schedule has one row per placed fixture, sheet/number context, an editable lamp selector,
  removable accessories, and an explicit Apply to matching fixtures action.
- Bill of Materials aggregates fixtures, selected lamps/accessories, catalog components,
  transformers, and measured wire. Material, SKU, manufacturer, Needed, Ordered, Received, unit
  cost, supplier, and notes are editable; totals and ordering status recalculate from saved state.
- Recount plan restores live drawing quantities only. Supplier CSV and print consume the edited BOM,
  not a parallel unedited list.
- Missing SKU, missing catalog mapping, and unscaled wire remain plainly labeled. Empty tables point
  back to fixture placement. Number fields accept temporary blank input, clamp negatives on commit,
  and preserve Escape/Enter keyboard recovery.
- Fixture symbol size is a separate 60% to 180% plan-marker scale. It does not alter beam throw,
  fixture quantity, or price. The beam-direction control and canvas aim grip are removed; legacy
  saved orientations still render so opening an older customer plan does not change its appearance.

**Responsive and production contract:** wide technical tables use local horizontal scrolling while
project chrome and headings reflow independently. Selects reserve inline-end arrow space; inputs and
remove controls have visible keyboard focus; captions and labels expose table purpose and field
identity; no emoji, hover lift, tint-on-tint status chips, `transition: all`, or ambient motion were
introduced. Desktop and narrow rendered critique, measured contrast, 200% text zoom, and manual
assistive-technology results are recorded after implementation rather than claimed in advance.

## CRM accessibility semantics (Aug 2026)

### Design read and thesis

- **Surface:** authenticated, data-dense CRM routes plus proposal and embed customer surfaces.
- **Audience:** operators and customers using pointer, touch, keyboard, zoom, or assistive technology.
- **Single job:** preserve every existing workflow while making each control's purpose, state, and
  focus location available without visual labels or color.
- **Risk:** an unnamed action can trigger outreach, pricing, or payment changes; a mouse-only scroll
  region can hide reports; low-contrast financial values can hide decision-critical outcomes.
- **Thesis:** accessibility state belongs at the semantic control, not in a tooltip or test-only
  workaround. Existing Radix, shadcn, Lucide, Tailwind, and proposal presentation styles remain the
  visual system.

### Reuse and interaction rules

- Icon buttons, mobile tabs, switches, progress bars, quantity controls, proposal package choices,
  and setup steps carry task-specific names. Decorative icons are excluded from the accessibility
  tree, and current/pressed/checked state uses native ARIA patterns.
- Visible form labels use stable `htmlFor`/`id` pairs. Controls that share one visual heading, such
  as color picker plus hex input, receive distinct labels.
- Filter choices that do not control tab panels are pressed-button groups rather than ARIA tabs.
  Real Settings tabs retain arrow-key navigation and expose their full label at narrow widths.
- Scroll-only report, chat history, and embed-code regions are named, keyboard-focusable, and use
  the existing focus-visible ring. Proposal package choices use one roving tab stop and arrow keys.
- Normal-size positive and negative financial text uses darker light-theme colors and lighter
  dark-theme colors; semantic meaning is also present in text, not color alone.

### Responsive states and proof boundary

The semantic contract is identical at 1440 x 900 and 390 x 844. Text can hide visually in a mobile
stepper or Settings tab only when an equivalent accessible name remains. Disabled decrement buttons
keep their item-specific name; current steps expose `aria-current="step"`; pending actions keep a
stable action name.

`e2e/accessibility.spec.ts` runs axe with WCAG 2.2 A/AA tags over representative desktop and mobile
CRM routes and automates keyboard checks for tabs, steppers, and report scrolling. Focused Vitest
coverage pins proposal package and quantity-control keyboard behavior. The human checks in
`e2e/accessibility-keyboard-checklist.md` cover visible focus, complete tab order, reflow, dialog
focus return, and assistive-technology output. These scoped checks are regression evidence, not a
product-wide WCAG or legal conformance claim.

---

## 390px responsive application shell (2026-08-19)

### Design read

- **Surface:** data-dense CRM application UI spanning dashboards, queues, builders, and settings.
- **Audience:** home-service operators working quickly on desktop or a 390px touch device; keyboard users
  must be able to reach the same navigation and actions.
- **Single job:** keep each route's primary action visible while making wider navigation reachable without
  introducing page-level horizontal scrolling.
- **Risk:** clipped actions can block campaign, offer, opportunity, agent, document, and pricing work;
  wrapped navigation can also hide sequence and selection context.
- **Constraints:** preserve the existing dark theme, typography, cards, buttons, Radix tab semantics,
  Lucide icons, real workspace data, and desktop composition. This is a reflow correction, not a redesign.

### Thesis and reuse map

Use one 16px mobile content rail, then restore the established 24px rail at `sm`. Header action groups
stack or wrap within that rail and make their primary buttons full-width only when the narrow layout needs
it. Navigation remains a single horizontal sequence inside `HorizontalScroll`: native touch scrolling, a
focusable keyboard region, stable scrollbar space, active-item reveal, and directional edge cues make
off-screen destinations explicit. The application `main` no longer clips horizontal content as a fallback;
every audited route still measures exactly 390px because intentional overflow is contained locally.

Reused primitives remain `Button`, `Tabs`, `Card`, `ResourceListHeader`, `WizardContainer`, and the
existing focus-ring/color tokens. `HorizontalScroll` is the only new primitive. It owns neither tab state nor
wizard state, so Radix and route-specific controls preserve their established semantics and behavior.

### Responsive behavior

- **Wrapped actions:** Dashboard, Assistant, Opportunities, Agents, Knowledge Base, Service Plans, Offers,
  offer AI generation, and pricing save controls place actions below or wrap them at 390px.
- **Contained navigation:** AI Suggestions, Reviews, Service Plans, Settings, opportunity stages, shared
  campaign/pre-booking steps, and offer steps scroll locally with left/right edge cues.
- **Pricing forms:** financing service rows use two flexible fields plus a delete target; upsell rank rows
  become labeled stacked groups; seasonal option rows wrap name and price fields; save actions remain
  fully visible.
- **Content extremes:** assistant starter prompts use normal wrapping; offer/document names use min-width
  and word-breaking rules; populated opportunity and offer cards retain local containment.
- **Desktop:** the existing sidebar, content widths, multi-column layouts, and wrapped Settings tab set are
  preserved at 1440px.

### States and interaction

The scroll primitive exposes start, middle, and end states: a right cue appears when more content follows,
a left cue appears after movement, and the active tab or step is scrolled into view without animation.
The region is touch-scrollable and focusable; native arrow-key scrolling remains available, while nested
tabs and step buttons keep their own names, selection/current state, and focus rings. Reduced-motion
screenshots disable the existing route transitions. No new loading, error, empty, success, or destructive
business states were introduced.

### Evidence and critique

Rendered evidence is generated by `e2e/responsive-mobile.spec.ts`, which attaches one 390x844 screenshot
for Dashboard, Assistant, Opportunities, Agents, Knowledge Base, AI Suggestions, Reviews, Service Plans,
SMS campaign steps, pre-booking steps, Offers, offer steps, and Settings Pricing. Local review artifacts live
under `.ezcoder/screenshots/responsive-390/`; representative 1440px captures live under
`.ezcoder/screenshots/responsive-desktop/` (both gitignored).

The first narrow capture showed that native overlay scrollbars were not visually persistent. The revision
added stateful directional edge cues, then re-captured all routes. A proposed sticky/boxed mobile header
treatment was rejected as unnecessary decoration; wrapping the existing controls preserved hierarchy with
less visual weight.

Quality-rubric score from the revised 390px and 1440px captures: **22/24**.

| Criterion                   | Score | Rendered evidence                                                                         |
| --------------------------- | ----: | ----------------------------------------------------------------------------------------- |
| Brief specificity           |     2 | Route-specific actions and navigation retain CRM labels and behavior.                     |
| Information hierarchy       |     2 | Page title, context, primary action, then work surface remain ordered.                    |
| Composition                 |     2 | Shared 16px mobile and 24px desktop rails align all changed routes.                       |
| Consistency and flow        |     2 | One wrapping rule and one scrolling primitive cover equivalent patterns.                  |
| Typography                  |     2 | Existing type scale is preserved; long prompts and descriptions reflow.                   |
| Material and surface logic  |     2 | Existing cards, borders, and selected controls remain unchanged.                          |
| State completeness          |     2 | Scroll start/middle/end, active reveal, focus, touch, and keyboard states are covered.    |
| Responsive behavior         |     2 | Thirteen 390px captures report no document, body, main, or primary-action overflow.       |
| Accessibility quality floor |     1 | Touch and keyboard paths pass; screen-reader and forced-colors review remain unverified.  |
| Motion purpose              |     2 | Edge changes are immediate; reduced-motion capture introduces no new motion.              |
| Content authenticity        |     2 | Captures use actual local workspace records and honest empty states.                      |
| Visual distinctiveness      |     1 | The task intentionally preserves the established product system rather than restyling it. |

### Verification contract

- `npm run typecheck` passed.
- `npm run lint` passed with no errors (36 existing repository warnings); targeted ESLint also passed for the
  changed responsive files and Playwright spec.
- `npm run build` passed, including production compilation, TypeScript, and all 67 static page renders.
- `E2E_STORAGE_STATE=… npx playwright test e2e/responsive-mobile.spec.ts --project=chromium --workers=1`
  passed **4/4** tests, including a synthesized touch swipe, keyboard scrolling, touch/Enter activation,
  prompt reflow, 13 route screenshots, and viewport-bound assertions.
- The runtime route audit measured `document`, `body`, and application `main` widths at **390px on 13/13
  routes**, found **0 clipped non-navigation interactives**, and found no page errors after the Settings
  hydration stabilization.
- Representative 1440px captures measured no document overflow on Dashboard, Opportunities, offer steps,
  or Settings Pricing.
- Assistive-technology speech output, forced-colors rendering, browser zoom, and legal conformance remain
  unverified; this section makes no product-wide WCAG or legal compliance claim.
