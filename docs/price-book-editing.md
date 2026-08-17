# Editing the lighting price book and pricing config

How to change fixture prices and sales-pricing settings for a lighting workspace
after the initial seed. Three surfaces, in order of how often you'll want them.

Reference workspace: `default` / **Maxteriors Lighting** /
`ba0e0e99-c7c9-45ec-9625-567d54d6e9c2` (production), updated 2026-08-17 with
22 fixture products plus two bistro services from
`backend/scripts/demo/seed_lighting_workspace.py`.

## 1. Fixture prices and names → the Price Book UI

Sidebar → **Price Book** (`/catalog`, `frontend/src/app/catalog/page.tsx`).
Edit name, kind, unit price, SKU, description, taxable, active. Requires the
`billing:write` permission. No deploy, no script — this is the day-to-day path.

Two things the dialog does _not_ show, which is fine:

- **Fixture attributes** such as `transformer`, `fixture_type`, and `unit_cost`
  plus **`components`** (the internal SKU bill-of-materials for fulfillment)
  have no form fields. Saving from the UI does **not** wipe them —
  `CatalogService.update_item` only writes fields present in the request
  (`backend/app/services/catalog/catalog_service.py`). To change those, use the
  API or the seed script.
- **Deleting an item is safe.** Copying a catalog item onto a quote or invoice
  snapshots its values, so deleting the template never alters existing
  documents.

## 2. Pricing config blocks → the API (mostly)

`workspace.settings["pricing"]` holds `tax`, `financing` (Wisetack),
`cash_discount`, `commission`, `deposit`, `tiers` (Good/Better/Best),
`care_plan`, `savings`, `bistro`, `christmas`, `permanent`.

Settings → Pricing only exposes **seasonal (Christmas)** and **permanent
roofline**. Everything else—including the landscape workflow's `deposit`
default—has **no UI**. See
[the client-deposit flow](landscape-lighting-deposit-flow.md) before enabling it,
then use the merge endpoint:

```bash
curl -X PUT "$API/api/v1/settings/workspaces/$WORKSPACE_ID/pricing" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"cash_discount":{"enabled":true,"card_reserve_rate":0.03,"label":"Cash / Check Pricing"}}'
```

`PUT .../pricing` does a **shallow merge per top-level block**: send only the
block you're changing and the others round-trip untouched. A block you _do_
send is replaced whole, so include all of its keys.

## 3. Bulk changes, BOM, transformer flags → re-run the seed

Edit `FIXTURES` / `PRICING` in
`backend/scripts/demo/seed_lighting_workspace.py`, then:

```bash
cd backend && railway run --service Postgres -- bash -c '
  export DATABASE_URL="postgresql+asyncpg://${DATABASE_PUBLIC_URL#postgresql://}"
  exec .venv/bin/python -m scripts.demo.seed_lighting_workspace --workspace default
'
```

Two gotchas in that invocation, both required:

- `railway run --service Postgres` injects `DATABASE_URL` pointing at the
  **internal** host `postgres.railway.internal:5432`, which does not resolve
  from a laptop. Use `DATABASE_PUBLIC_URL` (`*.proxy.rlwy.net`) instead.
- Railway hands out a plain `postgresql://` scheme; SQLAlchemy async needs
  `postgresql+asyncpg://`.

Catalog upsert is idempotent, matched on `sku` — a second full-seed run reports
`0 created, 24 updated`.

### Targeted specialty-fixture updates

For approved wall/underwater fixtures, use the preserving operation instead of
the wholesale seed. It dry-runs by default and changes only SKUs `59306832`,
`59407330`, and Premier's `Specialty Fixtures` section:

```bash
cd backend
uv run python -m scripts.ops.upsert_fx_specialty_fixtures --workspace default
uv run python -m scripts.ops.upsert_fx_specialty_fixtures --workspace default --apply
```

## ⚠️ The trap: the seed overwrites operator pricing edits

The script does `settings["pricing"] = validated` — a **full overwrite, not a
merge**, unlike the API endpoint above. Any seasonal or permanent-lighting
tuning an operator did in Settings → Pricing is **erased** on the next seed run.

Once real operators are editing pricing in the UI, pick one:

- Treat the seed as **catalog-only** and make all pricing changes via the API; or
- **Pull the live block down first** and fold it into `PRICING` before
  re-running:

  ```sql
  select jsonb_pretty(settings->'pricing') from workspaces where slug='default';
  ```

## Getting the SKUs to the distributor

When an **operator approves a quote on the client's behalf** through
`QuoteService.approve_quote`, the workspace gets an
**"Order parts — QUO-xxxxxx"** email listing every part number and quantity
for the accepted tier:

```
Parts to Order
QUO-000042 for Dana Homeowner was accepted. 3 SKUs to order.
  59409312      Qty 1 — Luxor 300W Transformer
  59409010      Qty 1 — Luxor WiFi Module
  BM-050-C-AB   Qty 4 — Mounting Bracket
```

Mechanics worth knowing:

- Quantities are **aggregated across fixtures**, so a lamp used by three
  different fixtures is one row with the summed count — the list is already in
  order-form shape.
- Recipients are workspace members with email notifications on. It's a plain
  `notify_workspace_event` fan-out, so it also lands as a push.
- **Deduped per quote** (`quote_fulfillment:<quote_id>`), and re-approving an
  already-approved quote is a no-op — no double orders.
- **Best-effort**: a mail outage is logged (`quote_fulfillment_notify_failed`)
  and never rolls back the approval.
- Quotes with no parts (flat, non-wizard quotes) send nothing.

Landscape projects also provide an editable Bill of Materials with supplier CSV
export. **Client approval on the public proposal currently uses
`QuoteService.approve_public`, which does not call this parts notifier.** Use the
BOM/supplier CSV as the hand-off for client-accepted quotes until those approval
paths are unified.

## Internal SKUs must never reach the client

`quote.proposal_document` mixes client presentation data with the staff-only
`fulfillment` sheet, and the public no-auth `/p/quotes/{token}` payload embeds
that snapshot. `client_safe_document()` in
`backend/app/schemas/proposal_wizard.py` filters it through
`CLIENT_SAFE_DOCUMENT_FIELDS`, a deliberate **allowlist**.

If you add a field to `ProposalDocument`, it is withheld from clients until you
add it to that allowlist —
`tests/services/quotes/test_public_proposal_document.py` fails until the new
field is explicitly classified as client-safe or internal-only. Leave it that
way; opt-in is the point.

## Verifying a change against production

```bash
cd backend && railway run --service Postgres -- .venv/bin/python - <<'EOF'
import asyncio, os, re, asyncpg
url = re.sub(r'^postgresql\+asyncpg://', 'postgresql://', os.environ["DATABASE_PUBLIC_URL"])
async def main():
    c = await asyncpg.connect(url)
    print("catalog items:", await c.fetchval(
        "select count(*) from catalog_items ci join workspaces w on w.id=ci.workspace_id"
        " where w.slug='default'"))
    print("cash_discount:", await c.fetchval(
        "select settings->'pricing'->'cash_discount'->>'enabled' from workspaces where slug='default'"))
    await c.close()
asyncio.run(main())
EOF
```
