# Data-layer tenancy: RLS vs. an ORM session filter

**Status:** plan only, no code written.
**Closes:** item 11 of `docs/technician-role-audit.md` — "every control this audit
found lives at the API layer, so a service-layer caller bypasses all of them."

The audit (findings 1–10) gated ~17 routers, fixed one cross-tenant existence
oracle, and added a CI ratchet. All of it sits in FastAPI dependencies. A new
service, worker, or socket that queries `Contact` directly is protected by
nothing. This plan picks the mechanism that fixes that by construction.

---

## What I verified first

Facts, read from this repo — not assumptions. Each one moves the decision.

| # | Fact | Where | Why it matters |
|---|---|---|---|
| 1 | **Alembic connects with the same role as the app** (`settings.database_url`) | `alembic/env.py:76` | That role owns every table |
| 2 | **Postgres table owners bypass RLS** unless `FORCE ROW LEVEL SECURITY` | [PG docs 5.9](https://www.postgresql.org/docs/current/ddl-rowsecurity.html) | RLS added naively here would be **silently inert** |
| 3 | RLS enabled with no matching policy = **default deny** | same | A wrong policy is an outage, not a leak |
| 4 | **Backend CI has no Postgres service**; `addopts = -m 'not integration'` | `.github/workflows/backend-ci.yml`, `pyproject.toml:206` | The required check **cannot execute an RLS policy** |
| 5 | `migrations.yml` *does* run Postgres, but is **path-filtered** to `alembic/**` + `models/**` | `.github/workflows/migrations.yml:52` | A policy regression from a service-layer change would not trigger it |
| 6 | **One `AsyncSessionLocal` for everything** — API, workers, webhooks, AI services | `app/db/session.py:55` | There is no existing "system vs. tenant" distinction to build on |
| 7 | **40 worker call sites**, 39 worker modules, all legitimately cross-workspace | `app/workers/*.py` | The escape hatch is not an edge case; it is a third of the traffic |
| 8 | **131 tables; ~90 carry `workspace_id`. ~40 do not** | `app/models/` | Both options need the same backfill to be complete |
| 9 | `messages` has only `conversation_id` — no `workspace_id` | `app/models/conversation.py:301` | The hottest table needs a subquery policy or a backfill |
| 10 | **Only 2 raw-SQL sites** in `app/`, one is `SELECT 1` | `health.py`, `qualification.py` | Nearly all access is ORM — an ORM filter has near-total reach |
| 11 | `get_db` resolves **before** `get_workspace`; the membership lookup *is* the bootstrap | `app/api/deps.py` | The query that decides the tenant cannot itself be tenant-scoped |
| 12 | `get_db` does **not** open a transaction; only `TransactionalDB` does | `app/db/session.py:98` | `SET LOCAL` has no transaction to attach to on most reads |
| 13 | No PgBouncer; direct asyncpg, pool 20 + 15 overflow, LIFO | `config.py:35`, `session.py` | Session-level `SET` would leak across pooled connections |
| 14 | `assert_workspace_owned` already exists but is **opt-in** | `app/db/scope.py:111` | Proves the team wants this; proves opt-in does not stick |
| 15 | No RLS anywhere in the repo today | grep | Greenfield either way |

---

## Option A — Postgres RLS

`SET LOCAL app.workspace_id = '<uuid>'` per transaction, plus per-table
`CREATE POLICY … USING (workspace_id = current_setting('app.workspace_id')::uuid)`.

**What it buys:** a real boundary. It holds against a missing ORM filter, a raw
`text()` query, and SQL injection alike. The database refuses to return the row.
Nothing else on this list does that.

**What it costs here, specifically:**

- **Fact 1 + 2 is the killer.** The app role owns the tables, so every policy is
  bypassed by default. You would need either `FORCE ROW LEVEL SECURITY` on ~90
  tables — which then applies to Alembic too, breaking any data migration that
  rewrites all rows — or a second, non-owner role for the app with its own
  credential, connection string, and grant management. **Shipping RLS without
  fixing this produces a system that looks protected and is not.** That is worse
  than the status quo, because the audit doc would say "closed".
- **Fact 4 means the required CI check cannot prove it.** RLS is only observable
  against a live Postgres. `make ci.backend` has no database. Proving policies
  requires a *new* required workflow with a Postgres service; until that exists
  and is marked required, a dropped policy merges green.
- **Fact 12 is a live footgun.** `SET LOCAL` outside a transaction is a no-op
  that emits a warning, and most reads run on a session that has not begun one.
  The obvious "fix" — plain `SET` — is the dangerous one: with a LIFO pool of 35
  connections (fact 13), the value survives into the next request on that
  connection and serves **another tenant's rows**. This is the single most
  likely way to turn a tenancy control into a tenancy breach.
- **Fact 7: 40 escape-hatch sites.** Every worker needs `BYPASSRLS`, a
  `SET LOCAL app.tenancy = 'system'` alternate policy branch, or a second engine.
  An escape hatch used by a third of the codebase stops being exceptional.
- **Fact 9 + 11.** `messages` needs an `EXISTS (SELECT 1 FROM conversations …)`
  policy — a per-row subquery, evaluated *before* the query's own WHERE (per PG
  docs) — on the highest-volume table. And the membership bootstrap query must
  be exempted or nobody can log in.
- **Blast radius: an outage, per table, immediately.** Fact 3: enable without a
  correct policy and every row vanishes. Reads 404/empty, writes fail
  `WITH CHECK`. Fails closed and loud — recoverable by `ALTER TABLE … DISABLE
  ROW LEVEL SECURITY` in seconds — but it is a full outage of that surface, and
  a data migration that silently matched zero rows is far worse.

## Option B — ORM session-scoped filter

A `do_orm_execute` listener adds `with_loader_criteria(Entity, Entity.workspace_id
== <session's workspace>)` to every ORM SELECT. This is SQLAlchemy's documented
recipe for exactly this ("Adding global WHERE / ON criteria").

**What it buys:**

- **Provable in the required check.** A statement can be compiled and its WHERE
  clause asserted with no database at all — so `make ci.backend`, which every PR
  already runs, catches a regression. Given fact 4, this is the difference
  between a control that is enforced and one that is aspirational.
- **Near-total reach for the actual threat.** Fact 10: two raw-SQL sites. The
  realistic failure is a developer writing `select(Contact).where(Contact.id ==
  x)` and forgetting the tenant — which this catches every time.
- **No schema change, no migration, no new role, no new credential.** Reversible
  by deleting a listener.
- Composes with the existing `assert_workspace_owned` rather than replacing it.

**What it costs:**

- **It is not a boundary.** Raw SQL bypasses it. SQL injection bypasses it. It
  is a correctness control with a security benefit, and the plan must say so
  rather than let the audit doc claim more.
- **`with_loader_criteria`'s lambda form caches per class.** SQLAlchemy's own
  issue tracker documents that a value read inside the lambda can be cached and
  not re-evaluated — reported as surprising and "scary if this is meant to be a
  security feature" (sqlalchemy#5760, #8399). A naive mixin+lambda implementation
  would **bake the first request's workspace into every later request.** The
  plan must use the non-lambda form, resolved per event fire, and prove
  non-caching with an explicit two-tenant test.
- Fact 8 still applies: ~40 tables without `workspace_id` are not covered until
  they are backfilled, same as RLS.

---

## Recommendation

**Build Option B now. Gate Option A behind one specific prerequisite.**

The deciding argument is fact 4 combined with facts 1–2: **RLS in this repo
today would be both unprovable by the required CI check and probably inert
against the owning role.** A control that cannot be tested and may not be
running is not a control — it is a claim in a document. Option B is weaker in
theory and enforceable in practice, and enforceable wins for the failure mode
that actually occurs here (a new query missing a filter).

This is not "ORM instead of RLS" forever. RLS remains the only thing that closes
the gap by construction, and it becomes the right move the moment this is true:

> **The prerequisite:** the application connects as a Postgres role that does
> **not** own the tables, with its own credential in Railway, and a
> Postgres-backed CI job is a **required** status check.

That is a discrete infra task, not a code task, and it needs a human decision
(new DB role, new secret, new required check). It is called out in Steps and
should be quoted to the user rather than assumed.

**Rejected third option:** making `assert_workspace_owned` mandatory by
convention. Fact 14 — it already exists and is already opt-in, and the sweep in
finding 7 found 50 routes that skipped it. Convention has been tried here.

---

## Design

### Tenancy is a property of the session, not a ContextVar

```
session.info["workspace_id"] = <uuid>   # tenant-scoped
session.info["tenancy"] = "system"      # explicitly unscoped
neither                                 # → violation
```

`session.info` is per-session state the listener reads via
`orm_execute_state.session.info`. A `ContextVar` was considered and rejected: it
survives across `await` boundaries into background tasks, and a missed reset
leaks one tenant's id into another's work. Binding to the session object makes
the scope exactly as long as the session.

### Fail closed, in two moves

Fail-open ("filter only when a workspace is set") is the version that silently
does nothing. But flipping straight to "raise" would take down all 40 worker
sites at once. So:

1. **Phase 1 — observe.** Unlabelled session → apply no filter, emit a
   `security_event` warning with the statement's entities and the call site.
   Run in prod; the log tells you every site still to label.
2. **Phase 2 — enforce.** Unlabelled session → raise. Only after the warning
   count is zero for a full week.

### The escape hatch

`tenancy="system"` on the session, set explicitly at each of the 40 worker call
sites. Deliberately verbose and greppable: `grep -c 'tenancy.*system'` is the
audit. Two guardrails:

- A test asserts the system-labelled set is exactly the known list, so a *new*
  system session fails CI — the same both-directions equality the route gate
  uses (`test_route_capability_coverage.py`).
- The bootstrap query (fact 11) gets `tenancy="system"` on the dependency that
  resolves membership, with a comment saying why it cannot be otherwise.

### Blast radius if Option B is wrong

| Failure | Symptom | Detection | Recovery |
|---|---|---|---|
| Filter applied to a system session | Worker silently processes 0 rows | Worker throughput → 0; **needs an alert, this is the quiet one** | Remove listener; redeploy |
| Stale workspace cached (the lambda trap) | **Tenant A served tenant B's rows** | Two-tenant test in CI; would not be visible in prod logs | Remove listener; redeploy; treat as a breach |
| Filter misses an entity | Status quo — no regression | Coverage test | — |
| Listener raises | 500s on that path | Error rate | Remove listener |

The worst case (row 2) is the same class of bug as the thing being fixed, which
is why the two-tenant non-caching test is a **blocking** step, not a nice-to-have.

Unlike RLS, every failure here is recovered by deleting a listener and
redeploying — no migration, no `ALTER TABLE`, no data rewrite.

---

## Open questions for the user

1. **The RLS prerequisite** — provisioning a non-owner Postgres role and adding a
   required Postgres CI check is infra work with a new credential. Do it now, or
   defer until Option B has run in prod for a month?
2. **The ~40 tables without `workspace_id`** (fact 8, incl. `messages`) — backfill
   a denormalised column, or leave them covered only via their parent? Backfilling
   `messages` on prod is a large migration on live CRM data and needs its own plan
   and a pre-deploy dump.

Both are recorded rather than assumed.

---

## Steps

1. Write `backend/app/db/tenancy.py`: a `WorkspaceScoped` declarative mixin
   (declaring nothing, marking the ~90 models that already have `workspace_id`),
   plus `scoped_session_info()` / `system_session_info()` helpers that set
   `session.info`. No listener yet.
2. Add the `do_orm_execute` listener in the same module, guarded on
   `is_select and not is_column_load and not is_relationship_load`, applying
   `with_loader_criteria` per matched entity using the **non-lambda** form.
   Phase-1 behaviour: unlabelled session logs a `security_event` and does not
   filter.
3. Write `backend/tests/db/test_tenancy_filter.py` proving, with no database, by
   compiling statements and asserting the emitted WHERE clause: a scoped session
   adds `workspace_id = :param`; a system session does not; an unlabelled session
   logs. Each assertion must fail with the listener removed — verify that
   explicitly before moving on.
4. Add the **blocking** two-tenant non-caching test: run the same query shape on
   a session scoped to workspace A, then one scoped to workspace B, and assert
   the second statement binds B's id. This is the sqlalchemy#5760 trap; if it
   fails, the implementation is wrong regardless of what else passes.
5. Apply the mixin to all ~90 models carrying `workspace_id`, and add a coverage
   test asserting every model with a `workspace_id` column also carries the
   mixin — a both-directions equality with an explicit justified-exclusion list,
   mirroring `test_route_capability_coverage.py`.
6. Label the request path: set `scoped_session_info()` in `get_workspace` once
   membership is resolved, and `system_session_info()` on the bootstrap
   membership lookup with a comment explaining why it cannot be scoped.
7. Label all 40 worker call sites `system`, plus the webhook and AI-service
   `AsyncSessionLocal()` sites, and add the "system sessions are exactly this
   known set" test so a new one fails CI.
8. Run `uv run pytest tests/ --ignore=tests/evals -q`, then `uv run mypy app`,
   then `uv run ruff check app tests` — each as its own command — and open a PR.
9. Deploy phase 1 and watch the `security_event` warning for one week; drive the
   unlabelled count to zero. Do not proceed until it is zero.
10. Flip to phase 2 (unlabelled raises), behind a settings flag defaulted off,
    then on. Add an alert on worker throughput dropping to zero — the quiet
    failure mode in the blast-radius table.
11. Update `docs/technician-role-audit.md` with a finding 11 that states plainly
    what this control does and does not cover: it catches a forgotten filter in
    an ORM query; it is not a boundary against raw SQL or injection.
12. **Ask the user** the two open questions above, then — only if the non-owner
    role and required Postgres CI check are approved — plan RLS as a separate
    document, starting with the three highest-value tables (`contacts`,
    `conversations`, `invoices`) rather than all 90.
