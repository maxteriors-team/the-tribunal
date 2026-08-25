# Landscape inventory upload and fixture-type editing

## Goal

Implement and verify locally a zero-stock importer for 24 landscape-lighting SKUs plus direct fixture-type editing in the Landscape Design schedule. Stop before any PR merge, deployment, or production database connection; a human must approve the reviewed import manifest and unresolved mappings before production is changed.

## Current state

- Production workspace `default` / **Maxteriors Lighting** already has 22 sellable landscape fixture assemblies and two bistro services. The price-book assemblies carry installed selling prices and component BOM SKUs.
- The physical inventory list is `docs/google-sheets-landscape-inventory-upload.csv`: 24 unique SKUs the user confirmed Maxteriors uses. Nineteen map to existing Tribunal definitions; five remain missing, placeholder, or near-match records (`59272804`, `59213350`, `59213710`, `59304101`, `59320292`), and three exact SKUs still have role/name differences (`59213082`, `59412322`, `59413032`).
- The supplied `source_quantity` total of 49 is order/source evidence, not a verified physical count. It must not become opening stock automatically.
- `InventoryItem` creation starts at zero stock; quantities and weighted-average costs enter only through ledger receipts/opening balances.
- The canvas already has a selected-fixture type switcher, but the Fixture Schedule shows fixture type as read-only. The schedule update helper can persist item fields but its UI currently exposes only lamp and accessory overrides.
- Quote pricing, electrical load, and supplier BOM resolve installed fixtures by the visual fixture type plus selected package. Allowing an arbitrary catalog product override would make those surfaces disagree, so this change will edit the six visual types—not expose an unsafe arbitrary SKU picker.
- `frontend/src/components/estimator/light-designer.tsx` and `frontend/src/components/landscape-lighting/studio/workflow-tables.tsx` contain unrelated in-progress Bistro/pan work. Implementation must preserve those edits and make only surgical additions.

## Data import design

Create `backend/scripts/ops/upsert_landscape_inventory.py` as a dry-run-first operation that can be reviewed locally but is not run against production in this phase:

- Static, reviewed definitions for these 24 approved SKUs: `59009035`, `59009050`, `59203512`, `59205842`, `59213082`, `59213092`, `59213350`, `59213632`, `59213710`, `59214042`, `59272804`, `59303512`, `59304101`, `59306832`, `59308530`, `59311122`, `59320292`, `59400232`, `59403532`, `59407330`, `59409010`, `59409312`, `59412322`, `59413032`.
- Dry-run by default; `--apply` is required to write.
- Require a workspace slug or UUID and scope every query/write to that workspace.
- Run all writes in one transaction.
- Match existing rows by workspace + SKU. Create missing rows; preserve existing item metadata and all ledger/stock history rather than overwriting operator-managed records.
- Create each new row active, weighted-average, unit `each`, supplier SKU equal to the approved numeric SKU, and zero stock. The 40-foot strip-light package also remains `each` until its per-foot valuation is explicitly confirmed.
- Do not create opening-balance or receipt ledger entries, and do not import the unverified 49 source units.
- Do not place supplier costs in `notes`, because notes are not billing-redacted. Costs remain in the local intake evidence until a permission-controlled receipt/opening balance records real stock.
- Link direct one-to-one inventory/catalog SKUs `59306832` and `59407330` only when the matching workspace catalog row exists and no other inventory row owns that link. Other component SKUs remain unlinked because one component can serve multiple sellable assemblies.
- Print deterministic create/keep/link counts, review statuses, and would-create IDs/data in dry-run output so a human can inspect the full manifest before any production decision.

No schema migration, stock movement, OpenAPI regeneration, or dependency is required. Even though rows begin at zero stock, production execution is still a persistent data write and remains explicitly out of scope until human approval.

## Fixture-type editing design

Update the schedule table with a native, accessible `Fixture type` select containing the six existing types: Uplight, Pathlight, Downlight, In-grade, Wall light, and Underwater.

When the operator changes a type:

- Persist the canonical product ID (`fixture-<type>`) on that placed design item.
- Clear explicit fixture catalog SKU/ID and lamp/accessory overrides so the new type resolves cleanly from the currently selected package.
- Let existing recount logic update the drawing symbol, schedule counts, electrical load, BOM, procurement, and proposal payload from the new type.
- If the selected package does not sell that type, preserve the existing unresolved warning and quote-creation block rather than substituting a fixture from another package.
- Keep the installed price-book assembly—not the physical component inventory row—as the design choice. Its BOM expands to the imported component SKUs for procurement.

Exact frontend touch points:

- `frontend/src/components/landscape-lighting/studio/workflow-tables.tsx`: render the fixture-type select and expand the update callback shape.
- `frontend/src/components/estimator/light-designer.tsx`: accept/pass the expanded schedule update shape without disturbing current Bistro/pan edits.
- `frontend/src/lib/estimator/landscape-schedule.ts`: type and persist `productId`, catalog-clearing, lamp, and accessory updates.
- Add focused tests under `frontend/src/components/landscape-lighting/studio/` and `frontend/src/lib/estimator/` for accessible choices, callback payload, persistence, override clearing, recount behavior, and unresolved package handling.

## Verification

Backend:

- Unit-test all 24 definitions for uniqueness and expected identity.
- Test dry-run rollback, apply transaction behavior, idempotent rerun, workspace scoping, preservation of existing rows, safe specialty catalog linking, and absence of inventory ledger writes.
- Run the registered targeted pytest command, Ruff, MyPy, then `make ci.backend`.

Frontend:

- Test the schedule select with React Testing Library, including keyboard-accessible labeling and a type change that clears incompatible overrides.
- Test `updateFixtureScheduleSelection` across multiple sheets and verify recount/schedule output follows the new type.
- Run targeted Vitest, ESLint, TypeScript checks, then `make ci.frontend`.

Human approval gate:

- Stop after local implementation, tests, and `make ci.all`; do not open/merge a PR, deploy, connect to Railway production, or execute the importer against production.
- Produce a review manifest separating 19 mapped SKUs, five missing/placeholder/near-match SKUs, three exact-SKU name/role differences, two safe one-to-one catalog links, and all zero-stock fields.
- Require explicit human approval of the target workspace, all review records, the zero-stock policy, and the manifest before any later release/import phase.
- After approval, create a separate release/import plan that follows the protected-branch process, performs production dry-run evidence first, and requires a final apply checkpoint. None of those actions belong to this plan.

## Risks and controls

- **False stock:** importing source quantities would overstate inventory. Control: item-master rows only, no ledger writes.
- **Unresolved catalog identity:** five records are missing/placeholder/near matches and three have name/role differences. Control: label them in the local manifest, create no speculative catalog links, and require human approval before production.
- **Cost disclosure:** supplier costs in notes could bypass billing redaction. Control: no costs in notes; costs enter through protected inventory receipts later.
- **Pricing drift:** arbitrary catalog overrides could disagree with package pricing. Control: type-only selector; package resolution remains authoritative.
- **Cross-workspace writes:** direct scripts can bypass API guards. Control: required workspace argument, workspace predicates on every query, local-only execution in this phase, and a later human approval gate.
- **Duplicate/partial import:** retries can create duplicates or half a list. Control: workspace+SKU matching, one transaction, dry-run default, idempotency test.
- **User-work collision:** intended files already contain Bistro/pan edits. Control: read/diff immediately before each edit and preserve all unrelated hunks.

## Steps

1. Add the dry-run-first, workspace-scoped 24-SKU landscape inventory upsert script with zero-stock creation and safe specialty catalog linking.
2. Add backend tests for definition integrity, workspace scoping, dry-run/apply behavior, preservation, idempotency, catalog linking, and no ledger writes.
3. Add the accessible six-option fixture-type selector to the existing Landscape Fixture Schedule while preserving current Bistro/pan work.
4. Extend schedule update typing and persistence so type changes update `productId` and clear incompatible fixture, lamp, and accessory overrides.
5. Add frontend component and schedule tests proving fixture-type changes persist and package/BOM safeguards remain intact.
6. Update `docs/price-book-editing.md` with the local dry-run workflow, zero-stock policy, unresolved-record manifest, and explicit human approval gate; do not add or execute production apply instructions in this phase.
7. Run targeted backend/frontend checks followed by `make ci.all`, fixing every failure attributable to the change.
8. Produce the local 24-row review manifest and stop with no PR, merge, deployment, Railway connection, or production write.
9. Hand the manifest and verification evidence to a human for an explicit production decision; any approved release/import proceeds under a separate plan.
