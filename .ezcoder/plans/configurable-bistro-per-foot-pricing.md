# Configurable Bistro per-foot pricing

## Goal

Price temporary and permanent Bistro runs from measured linear feet, with separate configurable per-foot allowances for lights and poles/supports, while leaving the existing permanent-holiday kit calculator unchanged.

## Existing behavior

- `frontend/src/components/estimator/light-designer.tsx` already measures Bistro runs per sheet and distinguishes `temporary` from `permanent`, but deliberately blocks CRM quote creation whenever any Bistro run exists.
- `backend/app/services/quotes/proposal_pricing.py::price_bistro` supports the legacy sales-wizard model (`color`/`classic`, one footage total, complexity tier, fixed hardware), but it cannot represent temporary/permanent Bistro runs or pole/support pricing.
- `backend/app/schemas/pricing.py::BistroConfig` is stored inside `workspace.settings["pricing"]`, so new Bistro rate fields need no database migration.
- Settings → Pricing currently exposes permanent-holiday and Christmas editors, but not Bistro. Landscape fixture selling prices remain configurable in Price Book.
- The permanent-holiday calculator in `price_permanent` is kit/COGS based and currently accurate; this work will not change its schema, code, settings card, payload, or tests.

## Design

### Config model

Add backward-compatible `temporary` and `permanent` installation-rate blocks under `BistroConfig`. Each block contains:

- an operator-visible label;
- `lights_per_ft`, the Bistro light/service base price per measured linear foot;
- `poles_each`, the price for each explicitly marked pole/support (`poles_per_ft` remains a read alias for existing workspace JSON).

Both numeric rates default to `0` so existing workspaces load without invented pricing. A requested Bistro installation with either rate unconfigured fails closed instead of silently producing a free or partial quote. Existing `tiers`, `color`, `classic`, `hardware`, and minimum fields remain for legacy wizard payloads and saved proposals.

### Quote input and calculation

Extend `WizardBistroSelection` with a bounded list of grouped run measurements containing `installation` (`temporary` or `permanent`), `feet`, and `pole_count`. Keep the legacy `product`, `tier`, and aggregate `feet` fields for compatibility.

The Light Designer will group calibrated Bistro footage across every sheet by installation and send those groups in the existing `bistro` payload while adding `bistro` to `categories`. The backend, not the browser, will calculate:

- temporary light amount = temporary feet × configured temporary light rate;
- temporary pole/support amount = marked temporary poles × configured temporary per-pole rate;
- permanent Bistro light amount = permanent feet × configured permanent Bistro light rate;
- permanent Bistro pole/support amount = marked permanent poles × configured permanent per-pole rate;
- one configured Bistro job minimum after all Bistro lines are summed.

Each component is grossed up through the existing fee/commission pricing chokepoint, and the result records separate lights and poles totals plus per-installation breakdowns. Legacy payloads without grouped runs continue through the current color/classic algorithm unchanged.

### Fail-closed behavior

Introduce a Bistro pricing-configuration domain error. Wizard preview/save/update/revise endpoints map it to a clear non-500 conflict response. The Light Designer also disables quote creation when any Bistro run is uncalibrated; configured-rate errors from preview remain visible through the existing pricing error surface. No Bistro footage may disappear from a quote merely because settings are missing.

### CRM settings

Add `frontend/src/components/settings/bistro-pricing-settings-card.tsx` to Settings → Pricing. It will:

- edit enabled state, job minimum, two per-foot light rates, and two per-pole support rates;
- explain that the entries are base prices and existing financing/commission adjustments still apply;
- reject non-numeric or non-positive active rates in the UI;
- round-trip all unexposed legacy Bistro fields when saving the whole config block;
- state that permanent-holiday pricing is separate and unchanged.

This gives every lighting service an operator path: landscape fixtures in Price Book, Bistro and permanent-holiday under Settings → Pricing, and Christmas in Seasonal Pricing.

## Files

### Backend

- `backend/app/schemas/pricing.py` — installation config and Bistro result breakdown types.
- `backend/app/schemas/proposal_wizard.py` — grouped Bistro run input.
- `backend/app/services/quotes/proposal_pricing.py` — server-authoritative per-foot light/pole calculation and configuration error.
- `backend/app/services/quotes/proposal_builder.py` — choose grouped-run pricing without changing legacy behavior.
- `backend/app/api/v1/quotes.py` — return a clear conflict for missing active Bistro rates.
- `backend/tests/services/quotes/test_proposal_pricing.py` — temporary, permanent, mixed, minimum, missing-rate, and permanent regression tests.
- `backend/tests/services/quotes/test_wizard_flow.py` and focused route tests if needed — grouped Bistro proposal behavior and fail-closed API behavior.

### Frontend

- `frontend/src/types/sales-wizard.ts` — generated-schema aliases for Bistro settings/input/result types.
- `frontend/src/lib/estimator/landscape-proposal.ts` — group Bistro measurements and add the Bistro category/input.
- `frontend/src/lib/estimator/landscape-proposal.test.ts` — multi-sheet temporary/permanent aggregation and uncalibrated-run exclusion/guard evidence.
- `frontend/src/components/estimator/light-designer.tsx` — feed measured Bistro rows into preview/save and remove the old blanket block while retaining calibration/configuration guards.
- `frontend/src/components/estimator/light-designer.test.tsx` — quote-enable/disable behavior around Bistro measurements and pricing errors.
- `frontend/src/components/settings/bistro-pricing-settings-card.tsx` and `.test.tsx` — accessible CRM editor and exact save payload.
- `frontend/src/components/settings/settings-page.tsx` — mount the Bistro card beside existing lighting pricing controls.
- `frontend/src/components/proposal/client-proposal-view.tsx` and its test — render configured temporary/permanent Bistro wording without mislabeling it as legacy Classic/Color.

### Contracts and docs

- `backend/openapi.json` and `frontend/src/lib/api/_generated.ts` — regenerate together after schema changes.
- `docs/price-book-editing.md` — document the Bistro CRM editor, per-foot light/pole policy, and unchanged permanent-holiday path.

## Risks and controls

- **Undercharging:** zero/missing light or pole rates fail closed for requested Bistro work; tests assert no partial/free quote.
- **Mixed plans:** footage is aggregated by installation across all sheets server-side; tests cover temporary plus permanent in one proposal.
- **Legacy quotes:** old color/classic requests and saved snapshots retain their existing fields and calculation path.
- **Customer-facing money:** all totals remain server-derived and use the existing gross-up/minimum logic; the browser submits only measurements and selections.
- **Permanent regressions:** no permanent-holiday production code is edited; a pricing regression assertion remains in the focused backend suite.
- **API drift:** OpenAPI and generated frontend types are regenerated in the same change; unrelated existing working-tree hunks are preserved.
- **No schema/data migration:** configuration remains JSON-backed and additive.

## Verification

- Focused backend pricing, proposal-builder, and quote-route tests.
- Backend Ruff and MyPy for touched modules, then `make ci.backend`.
- Focused frontend settings, proposal-builder, Light Designer, and public-proposal tests.
- Frontend ESLint, TypeScript, and production build via `make ci.frontend`.
- `make ci.codegen` after regenerated artifacts are included; if the repository's known unrelated uncommitted OpenAPI drift still prevents the HEAD-diff gate, record that separately while proving generated contracts match the current backend.
- `make ci.all` last; fix every failure attributable to this change.

## Steps

1. Add backward-compatible Bistro installation-rate and grouped-run/result schemas with zero defaults and no permanent-holiday schema changes.
2. Implement server-side temporary/permanent light-and-pole per-foot pricing, one Bistro minimum, legacy calculation compatibility, and fail-closed configuration errors.
3. Wire grouped Bistro runs through proposal preview/save/update/revise and add focused backend pricing, flow, and API error tests.
4. Add the CRM Bistro Pricing settings card for all four rates plus enabled/minimum controls, preserving legacy config fields, and mount it in Settings → Pricing.
5. Aggregate calibrated temporary/permanent Bistro footage across Light Designer sheets, send it in the landscape proposal payload, replace the blanket Bistro block with calibration/configuration guards, and test mixed plans.
6. Update the customer proposal Bistro presentation for configured temporary/permanent work and test that it does not use legacy Classic/Color labels.
7. Regenerate `backend/openapi.json` and `frontend/src/lib/api/_generated.ts`, then update `docs/price-book-editing.md` with the CRM configuration and pricing rules.
8. Run focused backend/frontend checks, `make ci.backend`, `make ci.frontend`, codegen verification, and `make ci.all`; resolve all attributable failures and report unrelated dirty-tree gates separately.
