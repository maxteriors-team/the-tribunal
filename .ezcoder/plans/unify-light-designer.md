# Unify the photo tools into one Light Designer

## Problem
Two overlapping tools ask the rep to design lights on a photo of the home:

1. **Photo Designer** (`components/estimator/roofline-estimator.tsx`) — catalog-driven
   canvas, photo calibration, server-priced permanent-vs-seasonal comparison, packages,
   AI render, share link, "create quote". Seasonal + permanent only.
2. **Night Preview** (`components/sales-wizard/night-preview-screen.tsx`) — a second,
   weaker canvas inside the Quote Builder: freehand landscape glows (uplight / spot /
   path / wash / bistro), a dusk slider, hold-to-compare, a roofline measure trace, and
   "Save to Proposal" (composite JPEG → `proposal_document.night_preview`).

Work done in one is invisible to the other, and landscape lighting — the core product —
can only be drawn in the weaker tool, where it is decoration that maps to no catalog item.

## Design read
- **Surface:** dashboard / data-dense creative tool.
- **Audience:** a rep standing in a customer's driveway on a laptop or tablet, in front
  of the buyer, under time pressure. Errors are expensive (a wrong count is a wrong price).
- **Single job:** photograph the home → draw the lights being sold → show the customer
  what it looks like lit → get it priced by the server.
- **Constraint:** money is server-authoritative everywhere in this repo. The canvas
  produces feet and counts only.

## Thesis
**One canvas, one palette, one saved design.** The Photo Designer survives; the Night
Preview's unique capabilities move into it:

- **Landscape fixtures become drawable products** sourced from the workspace price book
  (`catalog_items`), so an uplight on the photo *is* the "ZD Uplight" catalog item with
  its SKU and bill-of-materials — not a decorative glow. This is the foundation the
  inventory/technician SKU work needs.
- **Dusk is a continuous control**, not a boolean night toggle, plus hold-to-compare.
- **The Quote Builder hosts the same component** instead of owning a rival canvas.
  Saving composites the canvas into `night_preview` *and* pushes measured feet and
  fixture counts back into the wizard, where the server prices them.

One memorable device: the dusk slider is the tool's signature — the rep drags the sun
down while the customer watches their own house light up.

## Boundaries
- Frontend-only. No API contract change: `night_preview` is already `dict[str, Any]`,
  and the fixture palette reads the existing `catalog-items` endpoint.
- No money computed on the client. Landscape counts feed the wizard's server preview.
- The standalone Designer tab keeps its server-priced seasonal/permanent comparison and
  reports landscape fixture counts, pointing at the Quote Builder to price them.

## Follow-up (needs the operator's SKU list)
Real SKUs replace the seeded placeholders in
`backend/scripts/demo/seed_lighting_workspace.py`, and the aggregated fulfillment sheet
(`ProposalDocument.fulfillment`, already computed server-side but rendered nowhere)
surfaces on the quote and job detail for the technician and inventory side.
