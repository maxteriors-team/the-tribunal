# Unified quoting tool (landscape · permanent holiday · bistro · Christmas lights)

## Goal
Replace the single-purpose **Sales Wizard** with **one unified quoting tool** that can build a
quote for any mix of four product lines, then send / approve / convert it through the existing
quote lifecycle. Combine the tools that already exist (the in-repo landscape+bistro wizard, plus
the operator's standalone Christmas / permanent-holiday tools) into a single builder.

Product lines the tool must quote:
1. **Landscape lighting** — fixtures/tiers (already modeled).
2. **Permanent holiday lights** — permanent LED roofline, priced per linear foot + controller/channels.
3. **Bistro / string lights** — festoon priced per linear foot (already modeled).
4. **Christmas lights (seasonal)** — **roofline** (linear ft), **trees** (by size/wrap), **bushes**
   (count/size), **wreaths** (count/size); optional takedown/storage.

## What already exists (reuse — do NOT delete the engine)
The prior plan's "delete the wizard" direction was wrong. The wizard is a config-driven pricing
engine we should **keep and generalize**:
- `backend/app/schemas/pricing.py` `PricingSettings` already models tax, financing (Wisetack),
  cash discount, commission, **tiers (landscape)**, care plan, savings, **bistro (per linear ft)**.
- `backend/app/services/quotes/proposal_pricing.py` (money math), `proposal_builder.py` (assembles
  the multi-tier `ProposalDocument`), `pricing_config.py` (per-workspace config read/write).
- `backend/app/api/v1/quotes.py` wizard endpoints (`/wizard/preview`, `/wizard`) + `QuoteService`
  `preview_from_wizard` / `save_from_wizard`; `quotes.proposal_document` JSONB snapshot column.
- Frontend `components/sales-wizard/*` (calculator/presentation/night-preview screens,
  `use-sales-wizard.ts`, `document.ts`), `lib/api/sales-wizard.ts`, `types/sales-wizard.ts`.
- Generic quote lifecycle to reuse unchanged: list, send, deliver (email/SMS), approve/decline,
  convert to job+invoice, public `/p/quotes/{token}` proposal page.

## What's missing (must be built / combined in)
- **Permanent holiday** and **Christmas (roofline/trees/bushes/wreaths)** are modeled **nowhere**
  in the repo. Their pricing logic must come from the operator's existing standalone tools.
- The current UI is a landscape-only 3-screen flow ("calc / present / night"); it can't select a
  product line or combine lines into one quote.

## Prerequisite (blocks category pricing accuracy — need from user)
The operator says they "have some tools made already." The in-repo tool covers landscape+bistro
only. **To port real rates/logic for permanent-holiday and Christmas, share those tools** (paste
the HTML/JS/spreadsheet or point to files). If not provided, we implement sensible per-category
pricing with editable rates in the workspace pricing config and the operator tunes them later —
call this out rather than silently guessing the numbers.

## Architecture (recommended)
Generalize the existing engine around a **product-module** concept instead of a landscape-only
tier flow:
- Extend `PricingSettings` with per-category config blocks: `permanent` (per-ft roofline +
  controller/channel pricing), `christmas` (roofline per-ft, per-tree by size, per-bush,
  per-wreath, plus takedown/storage), keeping existing `tiers` (landscape) and `bistro`.
- Extend the wizard payload/`ProposalDocument` so a quote carries **selected categories** and each
  category's line items; `proposal_builder` composes them into one priced document + canonical
  `QuoteLineItem`s. Money stays 100% server-computed (never trusted from client).
- Replace the 3-screen wizard UI with a single **Quote Builder**: pick which product lines apply →
  a section per selected line with that line's inputs → one live server-priced summary → save as a
  draft `Quote` (+ `proposal_document` snapshot) → send/deliver → client proposal page → convert.
- Keep the client proposal page; generalize `LightingProposalView` to render multiple category
  sections (or fall back to the generic line-item sheet) so existing links keep working.
- Rename the surface to the operator's label (**"LL Design"** / Quote Builder); single sidebar
  entry; drop the separate landscape-only route.

## Risks & guardrails
- **Public API contract change** (payload/schema/endpoints) → run `make codegen`, commit
  `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` in the same commit.
- **Schema/migration**: prefer NOT changing quote tables — new category config lives in the JSONB
  `workspace.settings["pricing"]` block and the `proposal_document` snapshot, so **no DB migration**
  and no prod-data risk. Confirm during implementation; if a column is truly needed, back up prod
  first per CLAUDE.md.
- Money math must stay server-authoritative and Decimal-based (mirror `proposal_pricing.py`); add
  unit tests per category so totals are provable.
- Full release requires `make ci.all` green and backend-first deploy ordering per CLAUDE.md.

## Verification
- `make ci.codegen` in sync after schema/endpoint changes; `make ci.backend` + `make ci.frontend`.
- Backend unit tests: one per category (landscape, permanent, bistro, christmas) proving priced
  totals + a combined multi-category quote.
- Eyes: `.ezcoder/eyes/http.sh` POST the builder preview for each category and a combined payload,
  inspect the returned document; `GET /p/quotes/{token}` renders; `/readyz` 200; logs clean.
- Manual: build a quote mixing ≥2 categories → save → send → preview client proposal → convert to
  job+invoice; sidebar shows one "LL Design" entry; totals match expectations.

## Execution plan (task mode)
On approval, create these tasks (in order) via the task tool:
1. **Confirm category pricing inputs** — collect the operator's Christmas/permanent tools (or the
   rate tables); define the `permanent` and `christmas` pricing config shapes.
2. **Backend pricing schema** — extend `PricingSettings` with `permanent` + `christmas` blocks
   (roofline/tree/bush/wreath rates, takedown/storage); leave landscape/bistro intact.
3. **Backend pricing math** — extend `proposal_pricing.py` with per-category calculators (Decimal),
   with unit tests per category.
4. **Backend document assembly** — extend the wizard payload + `ProposalDocument` +
   `proposal_builder.py` to accept selected categories and emit combined lines/totals + canonical
   `QuoteLineItem`s; update `preview_from_wizard`/`save_from_wizard`.
5. **Codegen** — `make codegen`; commit `openapi.json` + `_generated.ts` together.
6. **Frontend Quote Builder UI** — replace the 3-screen wizard with a single category-driven
   builder (`use-sales-wizard.ts` → generalized state; new/renamed components); live preview via
   the existing preview endpoint; save + deliver reuse.
7. **Client proposal rendering** — generalize `LightingProposalView` for multi-category sections;
   keep generic fallback so old links render.
8. **Nav + routing** — one "LL Design" sidebar entry; retire the landscape-only route/label;
   update `query-keys`, command palette, visual-suite pages list.
9. **Tests + eyes verification** — backend pytest, `make ci.all`, boot locally and run the Eyes
   checks above.
10. **Release** — follow CLAUDE.md (backup prod only if a migration appears; backend-first deploy;
    smoke; verify live).
