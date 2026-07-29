# Client‑facing lighting estimator (christmas + landscape + bistro), emailed & texted

## Goal
Turn the estimator tab away from the internal **permanent‑vs‑seasonal savings estimate** and into a **client‑facing design + quote** tool. The photo mockup must support **christmas decor, landscape‑lighting fixtures, and bistro string lights**, and the finished design must reach the homeowner as an **emailed and texted shareable link** with a clear itemized display.

## Update (sharpened 2026-07-16) — the tabs already exist; the problem is fragmentation
Verified this session by reading the sales-wizard + nav:
- **The unified Quote Builder already has all four tabs with icons.** `frontend/src/components/sales-wizard/category-step.tsx` calls itself "the first real decision in the **unified Quote Builder**"; its `CATEGORY_META` already lists **Landscape Lighting, Holiday Lights — Permanent, Bistro Lights, Holiday Lights — Temporary**, grouped into two services (Landscape[landscape,bistro] + Holiday[permanent,christmas]) with `Trees`/`TreePine` icons + gold/evergreen accents. So **ask #1 (landscape + bistro tabs/icons) is effectively already built here** — just not where the user was looking.
- **3 overlapping sidebar entries + 1 buried builder** (`frontend/src/components/layout/app-nav.ts`): `Quotes → /quotes` (list), `Estimator → /estimator` (photo designer, roofline+christmas only), `Christmas Light Estimator → /christmas-lights` (hub of links). The real Quote Builder `SalesWizard` lives at **`/sales-wizard`, NOT in the sidebar** — reachable only via the christmas-lights hub.
- **The wizard's "design" is a night-preview marker tool, not the rich photo canvas** the standalone `/estimator` has — so the two photo surfaces are parallel/duplicative.
- **Net:** ask #3 ("one fully built-out UI") = consolidate the 3 nav entries + buried builder into ONE "Quotes & Estimates" surface, fold the `/estimator` photo canvas into the Builder's design step, retire/redirect the duplicates. Ask #1 is mostly done (surface it); net-new work is making landscape/bistro **drawable on the photo** + the nav/IA consolidation. Ask #2 (AI render) is parked — empty `OPENAI_API_KEY`, so the 503 is correct-by-design.

## Executed — Phase 1: navigation/IA consolidation (2026-07-16, verified live)
Shipped the safe, high-value first phase of the converge and proved it against the running app (harness `.ezcoder/eyes/out/verify-quotes-ui.mjs` → `VERIFY_OK`; screenshots `quotes-hub.png`, `builder-lines.png`):
- **One home.** Sidebar quoting cluster is now **Quotes & Estimates** (`/quotes`) → **Quote Builder** (`/sales-wizard`) → **Photo Designer** (`/estimator`). The redundant **Christmas Light Estimator** launcher is folded out of the sidebar (`sidebar:false`, kept in the command palette + reachable by URL). Files: `frontend/src/components/layout/app-nav.ts` (+ guard test `app-nav.test.ts`).
- **`/quotes` is the unified hub** — retitled "Quotes & Estimates" with **Build a quote** (→ Quote Builder) and **Design on a photo** (→ Photo Designer) actions above the list. File: `frontend/src/app/quotes/page.tsx`.
- **Landscape + Bistro tabs are now visible, each with a distinct icon.** The four-tab Quote Builder (Landscape / Permanent / Bistro / Temporary) is surfaced; each category chip got its own tinted glyph (Landscape=Trees, Permanent=Cable, Bistro=Lightbulb, Temporary=Snowflake). File: `frontend/src/components/sales-wizard/category-step.tsx`. Satisfies ask #1 ("landscape lighting icons and tabs, including Bistro").
- **AI render (ask #2)** stays parked: empty `OPENAI_API_KEY` → 503 is correct-by-design; add a key and it works untouched.

### Remaining (Phase 2+) — the deeper canvas/pricing converge
Making landscape + bistro **drawable on the photo canvas** and minting a Quote from the estimator still needs the backend estimate to price landscape/bistro (+ `make codegen`) and canvas render styles. Landscape is package-based (Good/Better/Best), not per-fixture placeable, so it stays as Builder tiers unless a fixture-level catalog is added. Gated on codegen commit discipline, and (for AI render + SMS delivery) an OpenAI key + SMS-enabled Telnyx number.

## What exists today (verified in this checkout)
- **Two nav entries**: `Estimator → /estimator` (the real design tool) and `Christmas Light Estimator → /christmas-lights` (`frontend/src/app/christmas-lights/page.tsx` — just a **hub** of three link cards, no estimate).
- **`/estimator`** = `RooflineEstimator` (`frontend/src/components/estimator/roofline-estimator.tsx`): draw on a photo, palette from `buildCatalog` (`lib/estimator/catalog.ts`) = C9 roofline (warm/multi) + Permanent LED roofline + seasonal decor (mini/garland/trees/bushes/wreaths). Right rail = rep `EstimatePanel`; "Client preview" = `ComparisonCard`; AI night render (`ai-render.tsx` → `/quotes/estimate/render`); "Save & share"/"Email".
- **Client output today** = `ComparisonCard` (`components/estimator/comparison-card.tsx`) at **`/p/compare/[token]`**: a **"Permanent vs. Seasonal Lighting"** savings card — prices only, **no image, no line items, no landscape, no bistro**. This permanent‑vs‑seasonal readout is the "landscape lighting estimate" this task removes.
- **Delivery today** = **email only** (`quote_service.deliver_comparison` → `send_estimate_email`). The comparison model `RooflineComparison` (`backend/app/models/roofline_comparison.py`) stores only measured inputs (feet/channels/decor/package) — **no images**.
- **Estimate model** (`backend/app/schemas/estimate.py`): `feet` is the only measured input (drives both roofline sides); `christmas_items[category][option]` drives decor. **No landscape or bistro inputs.** Canvas design model (`lib/estimator/types.ts`) `DrawTarget = roofline | christmas{category,option}` — no landscape/bistro target.
- **Landscape + bistro pricing already exist**, but only in the **sales‑wizard** path: `PricingSettings.tiers` (Good/Better/Best over `catalog_items`) and `BistroConfig` (per‑ft string lighting) in `backend/app/schemas/pricing.py`.
- **A rich client‑facing proposal already exists**: sales‑wizard → **Quote** → **`/p/quotes/[token]`** (`components/proposal/client-proposal-view.tsx`) already renders **design mockups** (`doc.mockups[]`), a **night render** (`doc.night_preview.image`), **itemized Good/Better/Best tiers** spanning landscape/bistro/permanent/christmas, and **accept/decline + deposit**. **Quote delivery already supports email OR SMS** (`quote_service.deliver_quote(channel=…)` via `TelnyxSMSService`).

## Key insight
Everything the request asks for on the "how is it displayed / emailed & texted" side **already exists on the Quote/proposal pipeline** (`/p/quotes/[token]` + `deliver_quote` email/SMS + deposit). The estimator is the only piece stuck on the thin comparison page with email‑only delivery. So the cheapest, most robust path is to **converge the estimator onto the Quote pipeline** rather than grow a second client page + second SMS path.

## Recommended approach — Option A: estimator produces a Quote
Repurpose `/estimator` into a **client‑facing design front‑end** whose "Save & share" mints a **Quote** (not a `RooflineComparison`), reusing the existing proposal page, email/SMS delivery, and deposit/accept:
- **Remove** the permanent‑vs‑seasonal comparison from the estimator (drop `ComparisonCard` usage, the "Client preview" savings toggle, and the `/p/compare` output for this flow). Rep rail becomes an **itemized quote preview** (christmas + landscape + bistro), not a savings ROI.
- **Extend the mockup** so landscape fixtures (placed `each`) and bistro (linear `per_ft`) are drawable alongside christmas decor.
- **On share**, composite the drawn design (and optional night render) into the quote's `mockups[]` / `night_preview.image`, add christmas/landscape/bistro line items, and deliver the **`/p/quotes/[token]`** link by **email and/or SMS** using the existing quote delivery.

### Alternative — Option B: grow the standalone comparison
Keep `RooflineComparison`/`/p/compare`, add landscape+bistro to `estimate.py`, build a new itemized public page, persist render images on the comparison, and add an SMS path to `deliver_comparison`. This duplicates the proposal page, deposit, and SMS that already exist — **more code, more surface, not recommended.**

## Open decisions (please confirm at review — they change scope)
1. **Which tab is "the Christmas light estimator tab"?** The design tool is `/estimator`; `/christmas-lights` is only a hub. Assume **`/estimator` is the target**, and repoint/retire the `/christmas-lights` hub (or make it redirect). Confirm.
2. **"Remove the landscape lighting estimate" = remove the permanent‑vs‑seasonal savings comparison** (the ROI card) as the estimator's output. Confirm this is the thing to delete (vs. some other readout).
3. **Option A vs B.** Recommend **A** (converge on Quote/proposal). Confirm before build — A is the larger refactor but reuses the client page, deposit, and email+SMS.
4. **Landscape fixtures in the mockup**: expose individual placeable fixtures (path/spot/well lights) priced **`each`** from `catalog_items`, i.e. a new landscape "each" catalog analogous to seasonal `SeasonalItem` — **not** the whole Good/Better/Best tier packages. Confirm this fixture‑level model is what "adding landscape lighting fixtures" means.
5. **Keep permanent LED roofline?** It's currently half of the removed comparison. Assume it stays as a **drawable line item** (priced, itemized) but loses the savings‑vs‑seasonal framing. Confirm.
6. **Deposit/accept on the client link?** Assume **yes** (reuse quote deposit). Confirm.

## Target client display (the "determine exactly how" deliverable, Option A)
Client opens **`/p/quotes/[token]`** (existing page, feet‑free by construction) and sees, top → bottom:
1. **Brand header** + "Prepared for {name}".
2. **The Vision for Your Home** — the drawn design composited over their photo (`mockups[]`).
3. **Night preview** — AI render if generated (`night_preview.image`).
4. **Itemized quote**, grouped by service with feet‑free line items + subtotals:
   - *Holiday / Christmas lighting* (roofline run + decor)
   - *Landscape lighting* (placed fixtures)
   - *Bistro / string lighting* (per‑ft runs)
   - **Grand total**, optional deposit due, accept/decline CTA.
5. **Selling points/perks** per service (reuse `permanent_perks`/`christmas_perks`; add landscape/bistro copy in pricing config).
- **Email**: existing quote email → links to the page. **SMS**: existing `deliver_quote` SMS → short link. Rep gets an **email / text / both** picker + destination in the estimator's share panel (mirror the wizard's deliver UI).
- **Feet‑free discipline preserved**: the public proposal already excludes measurements; landscape/bistro line items must serialize **price only**, no linear feet or per‑ft.

## Server model changes (Option A)
- Extend the estimate request/engine so the canvas can price landscape + bistro without leaving the tool:
  - `LinearFeetEstimateRequest`: add `landscape_items: dict[str, dict[str, float]]` (category→option→count, `each`) and `bistro_feet: dict[str, float]` (tier→feet, `per_ft`).
  - `LinearFeetEstimateResult`: add `landscape` (enabled + priced `items[]` + a `landscape_catalog` of placeable fixtures) and `bistro` (enabled + priced lines) sections, reusing the seasonal `SeasonalItemCost` shape.
  - Price landscape `each` fixtures and bistro `per_ft` via the existing pricing engines (`proposal_pricing` / bistro pricing) so totals stay server‑authoritative.
- Map the drawn design → a **wizard proposal payload** (`ProposalWizardPayload`) at share time so `share`/`deliver` reuse `save_from_wizard` + quote delivery, OR add a dedicated `estimate/quote` endpoint that builds the Quote from the estimate inputs + composited images. Prefer reusing the wizard pipeline.

## Risks / constraints
- **Codegen contract**: any `backend/app/schemas/estimate.py` or quote schema change requires `make codegen` and committing `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` together (CLAUDE.md release rules).
- **Feet‑leak**: new landscape/bistro public fields must be price‑only; keep the structural feet‑free split used by `PublicComparison`/`PublicProposal`.
- **Scope**: this is multi‑phase (schema → pricing → canvas → rep UI → quote wiring → client page copy → email/SMS). Land behind the existing flows so the current `/p/compare` keeps working until the estimator is cut over.
- **SMS prerequisite**: sending texts needs a workspace SMS‑enabled Telnyx number + `telnyx_api_key` (same as `deliver_quote`); locally this may be unconfigured — verify or stub.
- **`/christmas-lights` hub**: decide retire vs. redirect to avoid two "estimator" tabs.

## Verification
- `make ci.codegen`, `make ci.backend`, `make ci.frontend` green.
- Probe the estimate endpoint with landscape+bistro payloads via `.ezcoder/eyes/http.sh` and confirm priced sections + no feet in public output.
- Re‑run the estimator drive harness (`frontend/drive-estimator.mjs`) to screenshot: estimator (no comparison) → place christmas+landscape+bistro → share → open `/p/quotes/[token]` → confirm mockup + itemized sections render.
- `mail.sh` to confirm the email send; confirm SMS path (or stub) for the text link.

## Steps
1. Confirm the Open Decisions (target tab = `/estimator`; remove permanent‑vs‑seasonal comparison; Option A converge‑on‑Quote; landscape = placeable `each` fixtures; keep permanent as a line item; deposit/accept on) — adjust the steps below if any answer differs.
2. Backend schema: extend `LinearFeetEstimateRequest` with `landscape_items` and `bistro_feet`, and `LinearFeetEstimateResult` with priced `landscape` + `bistro` sections and a `landscape_catalog`, reusing `SeasonalItemCost`/`SeasonalItem` shapes (`backend/app/schemas/estimate.py`).
3. Backend pricing: price landscape `each` fixtures and bistro `per_ft` in `quote_service.estimate_linear_feet` via the existing pricing engines; keep totals server‑authoritative.
4. Run `make codegen`; commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` together.
5. Canvas model: add `DrawTarget` variants `landscape{category,option}` and `bistro{tier}` and supporting `Product` wiring (`frontend/src/lib/estimator/types.ts`, `design.ts`).
6. Palette: extend `buildCatalog` to emit landscape fixtures (placed `each`) and bistro (linear `per_ft`) from the new result sections, with distinct icons/styles (`frontend/src/lib/estimator/catalog.ts`, `seasonal-icons`, `tool-palette.tsx`, `light-canvas.tsx`).
7. Rep rail: replace `ComparisonCard`/"Client preview" savings toggle with an **itemized quote preview** (christmas + landscape + bistro subtotals + grand total) in `estimate-panel.tsx` / `roofline-estimator.tsx`; remove the permanent‑vs‑seasonal comparison from the estimator.
8. Share wiring: on "Save & share", build a `ProposalWizardPayload` from the estimate inputs + composited design mockup(s) + optional night render, and mint a **Quote** via `save_from_wizard` (reuse `quote_service`), returning the `/p/quotes/[token]` link.
9. Delivery UI: replace the estimator's email‑only action with an **email / text / both** picker + destination, calling the existing `deliver_quote` (email + SMS).
10. Client page: ensure landscape + bistro render as feet‑free itemized sections on `components/proposal/client-proposal-view.tsx` (add section rendering + perks copy if missing); confirm deposit/accept works from the estimator‑minted quote.
11. Retire/redirect the `/christmas-lights` hub (or repoint it at the client‑facing estimator) so there is one estimator tab; update `app-nav.ts` labels.
12. Remove now‑dead comparison paths for this flow if fully cut over (`/p/compare` usage, `deliver_comparison` email‑only, `ComparisonCard` in the estimator) — leave the public compare route only if still needed elsewhere.
13. Tests: backend pricing tests for landscape/bistro estimate; frontend catalog/panel tests; update `roofline-estimator.test.tsx`.
14. Verify: `make ci.all`; probe estimate endpoint + `/p/quotes/[token]` with the drive harness; confirm email via `mail.sh` and the SMS path (or documented stub); screenshot the client link.
