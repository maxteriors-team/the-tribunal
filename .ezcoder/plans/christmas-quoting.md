# Christmas Lighting Quoting — festive client proposal + reordered builder flow

## What you asked for

1. Customer-facing quote **feels like Christmas** when the quote is Christmas lights — red, green, lights, garland, wreaths.
2. Christmas **value proposition** on the proposal: maintenance included through the 23rd, all lights are company-owned, we make it easy, and why go with us.
3. Builder flow becomes **Customer info → Visual mockup → Line items → Preview → Text/Email**.

## What is already here (verified)

| Fact | Evidence |
|---|---|
| A festive theme already exists and remaps the *same* tokens the proposal view defines | `frontend/src/components/estimator/estimator.css:371-433` — `.cmp-festive` sets `--black:#0b1712`, `--gold:#ecc873`, `--holly:#cf4636`, a `::before` string-light garland, and a twinkle keyframe already gated on `prefers-reduced-motion` |
| It is applied to `/p/compare` but **never** to `/p/quotes` | `lib/estimator/services.ts:126` `clientThemeClass()`, used in `app/p/compare/[token]/page.tsx:58` only |
| The client proposal view has **zero** service branching | `components/proposal/client-proposal-view.tsx` — no christmas/landscape conditional anywhere |
| A Christmas quote renders through **care-plan** CSS with the eyebrow "Your Quote" | `client-proposal-view.tsx:493-533`, `.pcare-section`, hardcoded eyebrow at :499 |
| Its only bullet list is **price lines**, not value props | `client-proposal-view.tsx:505-517` renders `sec.lines` as `"Roofline — $1,800"` |
| ~120 lines of hardcoded generic copy show identically on a $900 Christmas quote and a $30k landscape install | `.value-bar` :243, `.wg-section` :551, `.guarantee-section` :588, `.included-section` :613, `.steps-section` :631, `.trust-section` :660 |
| `ProposalDocument.service` (`"landscape"｜"permanent"｜"christmas"｜"mixed"`) exists on the wire but is **dropped** client-side | `backend/app/schemas/proposal_wizard.py:40-57` builds it; `components/proposal/document.ts:94-157` never copies it |
| `ChristmasConfig.perks` exists and is operator-editable, but never reaches the proposal snapshot | `backend/app/schemas/pricing.py:513`; read only at `quote_service.py:2052,2527` for `/p/compare` |
| `ChristmasPackage` carries `name/experience/points/value_tag/warranty` — all **discarded** when a package becomes a section | `backend/app/services/quotes/proposal_builder.py:85-113` `_category_section()` copies money fields only |
| **The Light Designer cannot be opened on a Christmas quote** | Launch button `calculator-screen.tsx:454-462` is inside the `hasLandscape ?` block at :437, yet `sales-wizard.tsx:107-110` already handles `activeService === "christmas"` roofline feedback. That branch is unreachable from the UI. |
| Uploaded mockups live in a different step than the night render | mockups → `enhancements-step.tsx:27-108` ("Add-ons"); night render → design step |
| **No test asserts step order or labels** | No `calculator-screen.test.tsx`; `use-sales-wizard.test.tsx` and the e2e specs never reference step ids |
| Step ids are **string-matched, not derived** from the `steps` array | `calculator-screen.tsx:369,414,438,481,519,544` each hardcode `step === "<id>"`; a rename silently hides a section |

## Design read

- **Surface:** commerce, leaning premium consideration. This is the artifact that closes the sale.
- **Audience:** a homeowner, non-expert, most often opening a texted link on a phone at night.
- **Single job:** make the homeowner confident enough to tap **Approve**.
- **Risk:** high decision cost, seasonal deadline pressure. The page must answer "what do I get, what does it cost, why you" without scrolling hunting.
- **Constraint:** stay premium. The existing dark/gold sheet is the brand; Christmas must not turn it into a novelty flyer.

## Thesis — "Dusk on Christmas Eve"

The proposal keeps its premium dark sheet and shifts the base from flat black to **midnight evergreen**, with **candlelit gold** (the color of installed string lights at dusk) and **holly red** reserved for the recommended pick and the accept action. This is not invented: it is the palette `.cmp-festive` already establishes in this repo, so `/p/quotes` and `/p/compare` finally look like the same company.

Christmas identity comes from **the product being sold, drawn as real UI**, not from stickers:

- a **string-light garland** across the top of the page (already built at `estimator.css:401-417`, tiled, reduced-motion aware);
- a **pine-garland divider** replacing the plain rule between sections;
- a **wreath ornament** marking the value-proposition block;
- **holly red** on the approve CTA and the recommended package bar.

Red and green are structural — surfaces and actions — not confetti.

**Rejected** (anti-default check): emoji ornaments (skill-banned), candy-cane stripes, snowflake particle fields, script "Santa" fonts, and a generic hover lift on the package cards. Kept: the garland and wreath, because the company literally installs garland and wreaths — the decoration *is* the catalog.

**Contrast:** every new color pair gets checked against WCAG 2.2 AA (4.5:1 body, 3:1 large text and UI). Holly red `#cf4636` on evergreen `#0b1712` is a **non-text** accent only; any red *text* uses a lightened tint that measures.

## Product decisions I need you to confirm

1. **"Maintenance included up until the 23rd"** — I am reading this as **December 23** and making it operator-editable (`maintenance_through_month/day`), so the copy renders "Maintenance included through December 23" and you can change the date without a deploy. Correct?
2. **Value-prop copy.** Draft below. These are customer-facing promises, so tell me if any wording overcommits:
   - *We own every light.* Commercial-grade bulbs and custom-cut strands stay ours. You never buy them, store them, or replace them.
   - *Maintenance included through December 23.* A bulb out, a strand down, a wind storm. We come fix it at no charge.
   - *We handle all of it.* Design, install, in-season maintenance, takedown, and off-season storage.
   - *Nothing permanent on your home.* No drilling and no adhesive. Everything comes down clean.
   - *Cut to fit your roofline.* Strands are measured and cut for your house, so the lines stay straight.
3. **Scope of the festive theme.** Applies when the quote's service is `christmas`. A **mixed** quote (Christmas plus another line) — festive or neutral? My default: **neutral**, so a $30k landscape package does not get garland.

## Flow mapping

Current: `Client → Lines → Design (landscape only) → Seasonal → Add-ons → Review`, with Preview as a separate screen reached from Review.

Target: `Customer → Mockup → Line Items → Preview → Send`.

- **Customer** — today's client step, unchanged.
- **Mockup** — new step at position 2. Hosts the Light Designer launch **and** the uploaded-mockup gallery (moved out of "Add-ons"), so every visual lives in one place. **Un-gates the Light Designer for Christmas and permanent quotes**, fixing the dead branch.
- **Line Items** — today's `lines` + `design` + `seasonal` + remaining add-ons, in that order, still guarded by category.
- **Preview** — the existing `PresentationScreen`, entered as a step rather than a side door.
- **Send** — save, copy link, Email, Text. `deliver()` already auto-saves (`use-sales-wizard.ts:850`), so the buttons no longer hide behind a prior save.

Step ids get **derived from the `steps` array** instead of string-matched, so a future rename cannot silently hide a section again.

## Risks

- **Backend contract change → codegen.** `ProposalCategorySection` gains fields, so `make ci.codegen` must run and `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` commit **in the same commit** per `CLAUDE.md`.
- **Old snapshots.** Quotes saved before this ship have no `value_props`. The view must treat missing as "render nothing", never as an empty box.
- **Print path.** The proposal has a "Save as PDF" `window.print()`. Garland and twinkle must be suppressed in `@media print`.
- **No step-order tests exist**, so the reorder has no safety net today. I will add one.

## Verification

- `make ci.codegen`, `make ci.frontend`, `make ci.backend`.
- New tests: backend, that a Christmas section carries value props and the maintenance date; frontend, that the festive class applies only for a christmas quote, that value props render, and that the builder step order is Customer → Mockup → Line Items → Preview → Send.
- `.ezcoder/eyes/http.sh` against the public proposal endpoint to confirm the new fields serialize.
- Rendered check at desktop and 390px on a real Christmas quote, plus reduced-motion and print, scored against the skill rubric before I call it done.

## Steps

1. Extend `ChristmasConfig` in `backend/app/schemas/pricing.py` with `maintenance_through_month` (default 12), `maintenance_through_day` (default 23), and a `value_props` list of `{title, body}` carrying the confirmed defaults.
2. Add `value_props` to `ProposalCategorySection` in `backend/app/schemas/proposal_wizard.py`, defaulting to an empty list so pre-existing snapshots stay valid.
3. Populate `value_props` for the christmas branch in `backend/app/services/quotes/proposal_builder.py` (`_category_section` / the christmas call site), formatting the maintenance date into its body, and stop discarding the chosen `ChristmasPackage` presentation fields.
4. Add backend tests in `backend/tests/services/quotes/` asserting a Christmas section carries value props with the rendered maintenance date and that a landscape/permanent section does not.
5. Run `make codegen` and commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts`.
6. Carry `service` and `value_props` through `normalizeProposalDocument` in `frontend/src/components/proposal/document.ts` and add them to `ProposalDoc`.
7. Add the `.proposal-view.is-christmas` token remap to `frontend/src/components/proposal/proposal-theme.css`, porting the evergreen/candlelit/holly palette from `estimator.css:371-399` and verifying each pair against WCAG AA.
8. Add the festive ornament CSS — string-light garland, pine-garland section divider, wreath marker on the value-prop block — with `prefers-reduced-motion` and `@media print` suppression.
9. Detect the christmas service in `frontend/src/components/proposal/client-proposal-view.tsx` and apply `is-christmas` to the root wrapper.
10. Render the value-proposition section in the client view, and give the christmas category section a real eyebrow instead of the generic "Your Quote".
11. Swap the hardcoded generic blocks (`.value-bar`, `.wg-section`, `.included-section`, `.steps-section`, `.trust-section`) for Christmas-specific copy when the quote is festive, leaving the landscape copy untouched otherwise.
12. Add frontend tests in `client-proposal-view.test.tsx` covering the festive class applying only for christmas, value props rendering, and a legacy snapshot with no value props rendering nothing.
13. Rebuild the step list in `frontend/src/components/sales-wizard/calculator-screen.tsx` as Customer → Mockup → Line Items → Preview → Send, deriving each section's active state from the `steps` array rather than hardcoded string comparison.
14. Create the Mockup step: move the uploaded-mockup gallery out of `enhancements-step.tsx` and place it beside the Light Designer launch, removing the `hasLandscape` gate so Christmas and permanent quotes can open it.
15. Make Preview a step that renders `PresentationScreen` in place, and build the Send step with save, copy link, Email, and Text, relying on `deliver()`'s auto-save so the actions are not hidden before a save.
16. Update the stale copy that references step positions (`"Add a client email in step 1"` at `calculator-screen.tsx:721,736`, and the presentation-screen toasts naming "the review step").
17. Add a `calculator-screen.test.tsx` asserting the step order and that the Light Designer is reachable on a Christmas-only quote.
18. Run `make ci.codegen`, `make ci.frontend`, and `make ci.backend`; fix failures.
19. Capture the rendered Christmas proposal at desktop and 390px plus reduced-motion and print, score against the rubric, revise the weakest area, and re-capture.
