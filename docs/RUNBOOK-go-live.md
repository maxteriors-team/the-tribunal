# Go-Live Runbook — Jobber → The Tribunal

**Goal:** ship the completed Jobber-replacement program to production, import real
Jobber data, and run a safe parallel pilot before retiring Jobber.

This is a **checklist, not a guess**. Every command is real and verified against
this repo. Steps are ordered; do not skip. Each step has a ✅ done-check.

> **State at time of writing:** `main` is fully built and tested (`make ci.all`
> green + full integration suite green), and sits **N commits ahead of
> `origin/main`, not yet pushed**. Production has *none* of the
> invoices/quotes/catalog/jobs migrations yet. Pushing is the first
> irreversible, production-affecting action.

---

## What you (the human) must provide

These are external prerequisites — no code can supply them:

| # | Needed | For | Where it goes |
|---|--------|-----|---------------|
| A | **Prod `DATABASE_URL`** — the **public** url (Railway → Postgres → Connect → *Public Network*, host `*.proxy.rlwy.net`; **not** the internal `*.railway.internal`, which is unreachable from your laptop) | Step 1 backup | local shell only (never commit) |
| B | **Jobber data**: either a JSON export *or* a `JOBBER_ACCESS_TOKEN` | Step 4 import | `--from-file` / env var |
| C | **Stripe live keys** + **`STRIPE_WEBHOOK_SECRET`** | Step 5 payments | Railway env vars |
| D | Three cutover decisions (see end) | scope | — |

---

## Step 0 — Pre-flight (no side effects)

```bash
# You are on main, fully merged, tree clean (the roadmap doc is the only untracked file).
git -C . status -sb
git log --oneline origin/main..HEAD        # the commits about to ship

# Re-confirm everything is green before touching prod.
make ci.all
```

✅ **Done when:** `ci.all` exits 0 and you recognize the commit list.

---

## Step 1 — Back up production (MANDATORY before any migration)

Required by `CLAUDE.md` before any migration touching `contacts`/`invoices`.
This dump is **read-only** — it cannot harm prod. Uses a dockerized `pg_17`
client so no local Postgres install is needed.

```bash
# HOST must be the PUBLIC proxy host (*.proxy.rlwy.net), not *.railway.internal.
make db.backup.prod DATABASE_URL='postgresql://USER:PASS@HOST.proxy.rlwy.net:PORT/railway'
# → writes backend/backups/prod-<timestamp>.dump and refuses to continue if empty
```

✅ **Done when:** a non-empty `backend/backups/prod-*.dump` exists and its size
looks sane (not a few bytes). Keep it until the pilot succeeds.

> Rollback insurance: if a migration ever goes wrong, restore this dump into a
> fresh DB and re-point Railway, or `pg_restore` it back.

---

## Step 2 — Ship (push → auto-migrate → deploy)

Railway runs migrations automatically on deploy via
`backend/railway.toml → preDeployCommand = ["alembic upgrade head"]`. So the push
*is* the migration trigger.

```bash
git push origin main
```

Watch the Railway deploy logs for the backend service. You should see
`alembic upgrade head` apply the new revisions (field-service, invoices, quotes,
catalog, time/costing, recurring jobs) and finish clean.

✅ **Done when:** Railway shows a green deploy and the pre-deploy migration step
succeeded with no error.

---

## Step 3 — Smoke the live deployment

```bash
# Backend health + auth-gated surfaces
make smoke.backend  SMOKE_BASE_URL=https://<backend>.railway.app
# Frontend critical screens
make smoke.frontend PLAYWRIGHT_BASE_URL=https://<frontend>.vercel.app
```

Then eyeball in a browser (logged in): `/invoices`, `/jobs` (dispatch board),
`/quotes`, `/reports`, `/catalog` all render.

✅ **Done when:** both smoke targets pass and the five pages load.

---

## Step 4 — Import real Jobber data (the actual cutover of records)

The importer is **idempotent** — dry-run, eyeball counts, then run for real.
Re-running creates zero duplicates (keyed on `external_source='jobber'` + id).

**Option A — offline JSON export (safest, no token):**
```bash
cd backend
uv run jobber-sync import --workspace <slug> --from-file jobber_export.json --dry-run
# review the create/update counts, then:
uv run jobber-sync import --workspace <slug> --from-file jobber_export.json
```

**Option B — live Jobber API:**
```bash
cd backend
JOBBER_ACCESS_TOKEN=<token> uv run jobber-sync import --workspace <slug> --dry-run
JOBBER_ACCESS_TOKEN=<token> uv run jobber-sync import --workspace <slug>
```

✅ **Done when:** the dry-run counts look right, the real run succeeds, and in the
app you can see imported **clients in `/contacts`**, **jobs on `/jobs`**, and
**open invoices in `/invoices`**.

> Import maps: Jobber clients→contacts, properties→service_locations,
> jobs→field_service_jobs (technicians matched by prior sync), open
> invoices→invoices (historical/AR only — **never re-billed**).

---

## Step 5 — Turn on real payments

The Stripe webhook already exists at **`POST /api/v1/billing/webhook`** and routes
invoice payments by `invoice_id` metadata — no new route needed.

1. In Railway, set: `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`,
   `STRIPE_WEBHOOK_SECRET` (and `STRIPE_PRICE_ID` if using SaaS billing).
2. In the **Stripe Dashboard → Webhooks**, add an endpoint:
   `https://<backend>.railway.app/api/v1/billing/webhook`, subscribed to
   **`checkout.session.completed`** (and `customer.subscription.deleted` if used).
3. Test: send a real invoice, click **Pay now**, complete checkout, confirm the
   invoice flips to **`paid`** in `/invoices`.

✅ **Done when:** a test invoice auto-marks `paid` after the emailed pay link is used.

---

## Step 6 — Parallel pilot (do NOT hard-cut)

Run **one crew / one week** of real jobs through Tribunal *alongside* Jobber:
quote → approve → convert to job → schedule on the board → complete → invoice →
collect payment. Capture friction. Fix. Only then retire Jobber.

✅ **Done when:** a full real job has gone quote→cash in Tribunal and the crew is
comfortable on the dispatch board.

---

## Decisions to lock before Step 4

1. **Cutover style:** hard switch on a date, or parallel-run a few weeks?
   *(Recommended: parallel.)*
2. **History depth:** import all past jobs/invoices, or open/active only?
   *(Recommended: open/active — cleaner, faster.)*
3. **Field device:** is mobile-responsive web enough for v1, or is a native app
   required? *(Native app significantly changes scope.)*

---

## After go-live (revisit with pilot feedback, not before)

- Client self-service portal (deferred; reuses the existing `public_router` +
  signed-token `/p/...` pattern — no rework needed).
- Technician job-level ownership (tech edits only their assigned jobs) — build it
  *with* the jobs UI it gates.
- Phase 6.5 automation recipes (triggers now exist: `quote_*`, `invoice_*`,
  `job_*`) — wire concrete "quote approved → notify" style automations once the
  pilot says which ones matter.
