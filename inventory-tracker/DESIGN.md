# Inventory tracker design record

## Design read

- **Surface:** Data-dense application UI.
- **Audience:** Warehouse staff using desktop, tablet, or phone while counting physical stock.
- **Single job:** Record current on-hand quantities quickly and accurately.
- **Task and risk:** Repeated operational entry; a wrong SKU or quantity makes replenishment data unreliable.
- **Content:** Variable-length SKUs, names, prices, and whole-number quantities from a Google Sheet.
- **Platform:** Google Apps Script web app; keyboard, pointer, and touch; responsive through 320 CSS pixels.
- **Constraint:** Standalone from The Tribunal and deployable without a separate server or paid dependency.

## Evidence and thesis

The dashboard/data-dense archetype leads. Airtable supports strong row and column context; Sentry supports restrained status hierarchy; Miro is the contrast because a freeform canvas would slow repetitive counting.

The interface uses a warm warehouse-paper canvas, dark ink, ruled rows, monospace operational values, and one shelf-count mark. The catalog table is the primary scan path. Location and counter context remain directly above it, and the save action remains at the end of the natural form order. Decoration is limited to the product-specific stock-level mark.

## System

- Shared content rail: 1,180px maximum with 20px desktop and 12px mobile gutters.
- Type: DM Sans for interface text; DM Mono for SKU and quantities.
- Geometry: 5px controls, 8px outer surface, aligned table and form edges.
- Color: neutral canvas and surfaces; forest green only for the primary action and confirmed status; red plus text for errors; blue keyboard focus.
- Motion: 150ms named background transition and finite loading shimmer, removed under reduced motion.

## Components and states

- Catalog: loading, populated, search-empty, source-empty, and load-error states.
- Inputs: native text, search, and number controls with persistent labels and visible keyboard focus.
- Submission: disabled before catalog load, validation errors with focus, pending state, success reset, and retry after failure.
- Responsive: metadata fields stack; the semantic table scrolls horizontally rather than collapsing SKU-product relationships.

## Production checks

Scope is this single page and its load, search, validate, and save flow. Native semantics, labels, headings, table relationships, live status, target sizes, reduced motion, and narrow composition are implemented. Automated accessibility scan, screen-reader output, forced-colors rendering, 200% zoom, localization stress, Core Web Vitals, and rendered desktop/mobile captures remain unverified until the app is deployed in Google Apps Script.
