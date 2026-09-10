# Technician Lighting League scoreboard

## Outcome

Add a private, multi-tenant technician game layer called **Lighting League**. Active technicians earn XP from positive attendance, completed assigned jobs, and approved on-site upsells. Their lifetime lighting level persists, while the visible competition uses the current workspace-local calendar month.

Implementation will extend `/Users/maxsherrod/the-tribunal-technician-handoff`, where the approved technician handoff work is still uncommitted. It will preserve those changes, remain uncommitted/unstaged after verification, and will not deploy either feature.

## Settled product behavior

- Every workspace member with `jobs:read` can see active technician names, monthly rank, monthly XP, and lighting level.
- Raw contribution counts and lifetime XP are private to that technician and office users with `jobs:write` (owner, admin, manager, or dispatcher). Peer-detail requests fail closed.
- Attendance is positive-only: one completed, non-void clocked day earns `25 XP`; there are no lateness, absence, approved-leave, or negative-XP rules.
- A job's first transition to `completed` earns `100 XP` for every technician assigned at that moment. Reopening revokes that award; recompleting cannot duplicate or move the original award into a newer month.
- An approved quote created through the on-site upsell flow earns `100 + min(floor(quote total / 20), 100)` XP, producing `100–200 XP`. Draft, sent, declined, expired, ordinary office, and pre-launch quotes earn nothing.
- Lifetime XP and levels never reset. Monthly standings use XP first awarded during the current workspace-local calendar month.
- Equal positive monthly XP shares a rank. Active technicians with zero monthly XP remain visible as “Not ranked,” ordered by name.
- Each source earns at most once. Correcting or reopening a source toggles the original award instead of creating negative rows or duplicate XP.
- Everyone starts at zero because the migration creates no historical award rows and marks all existing quotes as non-upsells.
- Levels provide recognition, progress, badges, and a restrained level-up celebration only. They do not create payroll, prizes, disciplinary actions, or compensation promises.
- Existing manager-only `/scorecard` reporting and configurable upsell sales tiers remain separate. The on-site upsell card will explicitly say “Upsell tier” to avoid confusing it with Lighting League levels.

## Level ladder

The backend owns the names and thresholds and returns them through the API so the UI cannot drift:

| Level | Title | Lifetime XP |
|---:|---|---:|
| 1 | Spark Starter | 0 |
| 2 | Glow Getter | 500 |
| 3 | Beam Builder | 1,250 |
| 4 | Lumen Leader | 2,250 |
| 5 | Circuit Champion | 3,500 |
| 6 | Radiance Ranger | 5,000 |
| 7 | Illumination Ace | 7,000 |
| 8 | Master of Lumens | 9,500 |
| 9 | Light Commander | 12,500 |
| 10 | Lighting Lord | 16,000 |

XP continues accumulating after Lighting Lord. The top level reports completion rather than inventing an unreachable next threshold.

## Existing foundation and gaps

- `backend/app/services/dashboard/scorecard_service.py` already provides manager-only technician activity reporting, but deliberately exposes no team ranking and counts completed time entries rather than completed jobs.
- `backend/app/services/upsell/upsell_service.py` already calculates private monthly sales stats and configurable sales tiers. It does not distinguish ordinary quotes from on-site upsell quotes in durable quote metadata.
- `backend/app/models/attendance.py` records immutable completed/void attendance states but has no expected shifts, lateness, or approved-time-off model. Therefore this feature rewards presence and cannot safely score punctuality.
- `backend/app/models/field_service.py::Job` has a mutable status but no trustworthy completion timestamp or historical assignment snapshot. Calculating a lifetime score directly from current rows would misdate completions and reassign credit.
- `backend/app/services/jobs/job_service.py::_emit_status_event`, `backend/app/services/attendance.py`, and `backend/app/services/quotes/quote_service.py::approve_quote` are the shared transaction boundaries that already see the authoritative source transitions.
- `frontend/src/components/upsell/upsell-scoreboard.tsx`, `frontend/src/components/scorecard/scorecard-page.tsx`, the shared UI primitives, and the black/yellow design tokens provide local interaction and visual patterns to reuse.
- `frontend/src/components/layout/app-nav.ts` explicitly fail-closes field users to an operational route allowlist and limits sidebar sections to six entries. Lighting League must be both an Operations item and an allowed field route.

## Persistence and migration

Add `backend/app/models/technician_xp_award.py` with a `TechnicianXpAward` table containing:

- UUID primary key plus required `workspace_id` and `technician_id` foreign keys with `ON DELETE CASCADE`;
- a checked category string: `attendance`, `job`, or `upsell`;
- a server-generated `source_key` (`attendance:YYYY-MM-DD`, `job:<uuid>`, or `upsell:<uuid>`), never accepted from an API request;
- positive integer `points`;
- `awarded_at` and nullable `revoked_at` UTC timestamps;
- a unique constraint on `(workspace_id, technician_id, category, source_key)` for idempotency;
- workspace/month and workspace/technician partial indexes for active-award aggregation;
- checks preventing non-positive points and a revocation timestamp earlier than its award.

Extend existing models additively:

- `backend/app/models/quote.py::Quote.is_onsite_upsell`, non-null and default `false`, marks only quotes created by `UpsellService.create_quote`;
- `backend/app/models/field_service.py::Technician.scoreboard_level_seen`, non-null and default `1`, persists the highest acknowledged level-up celebration without a new profile table;
- `backend/app/models/__init__.py` registers the award model for metadata and migration checks.

Create `backend/alembic/versions/20260903_add_technician_xp_scoreboard.py` after `20260903_job_handoff_images`. It creates the table/indexes/checks and adds both defaulted columns without rewriting or deleting existing business rows. It performs no XP backfill. Its downgrade exists for isolated CI and removes only newly added structures; once XP is live, production rollback must use a backup/forward fix because dropping the table would destroy earned progress.

## Scoring service and source integration

Add `backend/app/services/technician_scoreboard.py` as the single owner of rank constants, XP formulas, award upserts/revocations, aggregation, detail authorization helpers, and level acknowledgement.

Award writes stay in the same database transaction as their authoritative source transition:

- `AttendanceService.clock_out`, `create_manual_entry`, `update_manual_entry`, and `void_entry` reconcile affected workspace-local start dates. Any completed non-void entry keeps that technician/day award active; voiding the last valid entry revokes it.
- `JobService._emit_status_event` synchronizes job awards whenever status enters or leaves `completed`. It snapshots then-assigned technicians, awards all of them, revokes stale awards for that job, and leaves later assignment-only edits alone. Job deletion revokes its award first.
- `UpsellService.create_quote` passes an internal marker into `QuoteService.create_quote`; all other callers retain `false`. `QuoteService.approve_quote` awards the marked quote to its linked technician before the existing commit, after idempotent approval checks.
- PostgreSQL conflict handling makes duplicate requests and concurrent transitions idempotent. No route lets a browser submit points, categories, source keys, or technician IDs for an award.
- Reactivation clears `revoked_at` without changing `awarded_at`, preventing users from reopening work to move XP into a newer month.

Two deliberate ceilings will be documented beside the implementation:

- `simplification:` attendance days use the workspace’s current reporting timezone; preserve an immutable earned timezone/date if historical workspace-timezone changes become supported.
- `simplification:` quote totals are treated as the workspace’s operating currency; add currency normalization if multi-currency workspaces become supported.
- `simplification:` the full active technician roster is sorted in memory because home-service crews are small; add database ranking/pagination if a workspace approaches 250 active technicians.

## API and authorization

Add `backend/app/schemas/technician_scoreboard.py` and `backend/app/api/v1/technician_scoreboard.py`, then register the router in `backend/app/api/v1/router.py`.

Endpoints:

- `GET /api/v1/workspaces/{workspace_id}/technician-scoreboard` requires `jobs:read` and returns period boundaries/timezone, XP rules, level definitions, public standings, and the caller’s private detail only when their active user is linked to that technician.
- `GET /api/v1/workspaces/{workspace_id}/technician-scoreboard/technicians/{technician_id}` requires `jobs:read` plus either self ownership or `jobs:write`; every lookup includes `workspace_id`, and missing/cross-workspace/unauthorized peers all return the same not-found outcome.
- `POST /api/v1/workspaces/{workspace_id}/technician-scoreboard/me/acknowledge-level` accepts only a bounded level number, resolves the technician from the authenticated user, refuses levels above current achievement, and monotonically advances `scoreboard_level_seen`.

Public standings contain only technician name/ID, rank, monthly XP, level number/title, and whether the row belongs to the viewer. Private detail adds lifetime XP, progress to the next level, and current-month attendance-day, completed-job, approved-upsell, and category-XP counts. Source keys, customer/job/quote identifiers, hours, sale values, and peer details never appear in the list response.

Aggregation uses indexed grouped queries rather than per-technician reads. Month boundaries come from the existing workspace reporting-timezone helpers and are converted to UTC before filtering `awarded_at`.

## Frontend architecture

Add:

- `frontend/src/app/scoreboard/page.tsx` as the route entry;
- `frontend/src/lib/api/technician-scoreboard.ts` using generated OpenAPI schema types;
- scoreboard keys in `frontend/src/lib/query-keys.ts` and `POLL_30S` from `frontend/src/lib/query-options.ts`;
- `frontend/src/components/scoreboard/technician-scoreboard-page.tsx` plus focused subcomponents only where they reduce test or accessibility complexity;
- a “Lighting League” `Trophy` entry in the Operations section of `frontend/src/components/layout/app-nav.ts`, gated by `jobs:read` and added to `FIELD_ROUTE_ALLOWLIST` without exceeding six sidebar items;
- a precise “Upsell tier” label in `frontend/src/components/upsell/upsell-scoreboard.tsx`, preserving its existing sales-target behavior;
- a narrow shared fix in `frontend/src/components/ui/progress.tsx`, replacing `transition-all` with transform-only motion and a reduced-motion fallback before reuse.

The page shows:

1. A page header: “Lighting League” and “Earn XP from showing up, completing jobs, and approved upsells.”
2. A non-modal, persistent-until-dismissed level-up banner for the linked viewer when their calculated level exceeds `scoreboard_level_seen`. Dismissal acknowledges the level server-side; failure keeps the banner and offers retry.
3. The viewer’s lifetime level, exact XP progress, next title, and private current-month contribution breakdown. Office users without a technician profile skip this personal block.
4. A ten-stop level path, with completed/current/future states expressed by text, icon, shape, and semantics rather than color alone.
5. An ordered “September standings” list with monthly reset copy, stable tie handling, a clear “You” marker, and zero-XP technicians shown as “Not ranked.”
6. For `jobs:write` users, each row is a real button opening an existing accessible `Sheet` with that technician’s private breakdown. Peer rows are static for technicians.
7. A concise “How XP works” explanation that states exact values, full crew credit, monthly-versus-lifetime behavior, and recognition-only intent.

## Design read and evidence

- **Surface:** application UI led by a scan-heavy dashboard, not a marketing page or analytics report.
- **Audience:** field technicians checking a phone between jobs and office managers reviewing a crew on desktop. Names may be long; rosters may be empty or tied; touch and keyboard use both matter.
- **Single job:** understand personal progress and current team standing without exposing a coworker’s underlying performance details.
- **Task/risk:** frequent, low-decision-cost viewing with high morale and employee-privacy consequences if ranking or attribution is unclear.
- **Local evidence:** preserve the existing Inter typography, black/graphite surfaces, yellow primary accent, content rail, sidebar, `Sheet`, page-state primitives, Lucide icon family, and React Query conventions.
- **Aligned references:** the dashboard archetype’s `airtable` observation supports dense, aligned, repeatedly scanned rows; `sentry` supports clear hierarchy, state, and error recovery. These are conditional observations from only 5/74 dashboard documents, not brand templates.
- **Useful contrast:** reject `miro`-style freeform composition because standings need fixed order, comparable columns, and predictable keyboard movement.

## Design thesis

**An electrical panel, not a casino.** One graphite work surface uses the existing yellow accent as an energized circuit connecting level milestones. The first glance is the viewer’s lit current level, the second is monthly team order, and the third is the private contribution explanation. Alignment, borders, and restrained solid surfaces carry hierarchy; there are no decorative gradients, glass panels, generic bento cards, oversized podiums, emoji, flashing effects, or confetti.

The memorable device is a semantic circuit rail: completed nodes use a check and title, the current node uses the level number and “Current,” and future nodes expose exact thresholds. On mobile it becomes a vertical connected list; at desktop it becomes one horizontal rail aligned to the shared content edges. A one-time, non-looping glow may accompany the level-up banner only when reduced motion is not requested.

## Complete states, responsive behavior, and accessibility

- Reuse `PageLoadingState`, `PageErrorState`, and `PageEmptyState`; preserve stale standings while a background refresh fails, and expose an explicit retry instead of blanking the page.
- With technicians but no XP, render the ordered roster plus honest “No XP earned this month” guidance. With no active technicians, managers get a Settings/Team path and field users get a plain unavailable state.
- Keep one `max-w-7xl` content rail. The level path changes from vertical at 320/390px to horizontal at desktop; leaderboard rows recompose without horizontal page scrolling or lost names/ranks.
- Use semantic heading order, `<ol>` standings, real buttons only when detail is available, a labelled Radix `Sheet`, and Radix progress with explicit min/max/current text.
- Maintain 44px touch targets, visible `:focus-visible`, DOM-order keyboard flow, no pointer-sticky focus, and no color-only distinction. Long names wrap or visually truncate while remaining complete to assistive technology.
- Level-up acknowledgement exposes pending, success, and failure states through text and polite status announcements. It never auto-dismisses or steals focus.
- Motion names only transform/opacity properties, remains bounded and non-looping, and is removed under `prefers-reduced-motion` without losing meaning.
- Verify dark/light token contrast, forced colors, 200% text zoom, 320px reflow, no-hover/touch behavior, and an RTL/long-name stress fixture. Automated axe and accessibility-tree evidence supplement, but do not justify an ADA/WCAG conformance claim or replace unavailable manual assistive-technology proof.

Update `frontend/DESIGN.md` with this design read, the Airtable/Sentry/Miro evidence rationale, the electrical-panel thesis, token/primitives reuse, component/state map, responsive rules, screenshot evidence, final rubric score, and any explicitly unverified production-contract item.

## Tests and proof

Backend coverage will prove:

- exact XP formulas and all ten threshold boundaries;
- no migration backfill and `false` origin on existing/ordinary quotes;
- one attendance award per local day across multiple entries, edit/void reconciliation, and concurrent idempotency;
- full credit for every completion-time assignee, reopen revocation, recompletion idempotency, assignment-snapshot behavior, and job-delete cleanup;
- award only after first approval of a marked on-site upsell, value cap, and no award for ordinary/draft/declined quotes;
- current-month versus lifetime calculations across workspace timezone/month boundaries, ties, zero-XP roster rows, inactive-technician filtering, and no N+1 query path;
- anonymous denial, tenant isolation, public-list field minimization, self detail, office detail, peer-detail denial, acknowledgement validation, and no arbitrary XP-write route.

Use `backend/tests/services/dashboard/test_technician_scoreboard_service.py` for pure scoring/aggregation edges and `backend/tests/integration/test_technician_scoreboard.py` for source lifecycle, authorization, concurrency, and tenant boundaries. Extend narrower existing attendance/job/quote tests only where the shared transition itself needs a regression.

Frontend coverage will prove:

- viewer progress, exact rule copy, ten levels, ties, “Not ranked,” and honest zero/no-technician states;
- peers expose only standings while self and office details render in the correct surfaces;
- manager row keyboard activation, detail loading/error/retry, Sheet focus behavior, and technician rows without peer controls;
- level-up acknowledgement pending/success/failure and accessible status output;
- nav visibility and direct-route access for technician/lead/office tiers while preserving the six-item section limit;
- the existing upsell component says “Upsell tier” without losing current sales stats;
- loading, stale-refresh error, reduced-motion classes, long names, and responsive semantic order.

Regenerate `backend/openapi.json` and `frontend/src/lib/api/_generated.ts` together. Extend `frontend/e2e/accessibility.spec.ts` and `frontend/e2e/visual/pages.ts` with `/scoreboard`.

Runtime proof uses an isolated local workspace fixture with clearly fake technicians and real award source transitions. Use `.ezcoder/eyes/http.sh` to verify office list/detail, technician own detail, peer denial, cross-workspace denial, acknowledgement, and response-field privacy. Capture populated desktop (1440×900), mobile (390×844), and narrow reflow (320px) views; exercise manager detail and level-up states by keyboard. Run axe, forced-colors/reduced-motion checks, and one evidence-led critique/revision cycle. Completion requires at least 20/24, no quality-floor zero, no applicable production-contract failure, and honest reporting of anything unverified.

Run targeted backend/frontend tests first, migration upgrade/check/downgrade/upgrade against an isolated PostgreSQL database, then `make ci.all` as one standalone command. Because codegen drift compares against Git, temporarily stage only the two intended generated artifacts for that command and unstage them afterward. Re-read formatter/codegen-mutated files, remove temporary databases/fixtures/artifacts, run `git diff --check`, and confirm no commit or deployment occurred.

## Risks and exclusions

- Ranking employees can harm morale when details or penalties are public. This design exposes only the agreed competition fields, keeps source metrics private, awards positive events only, explains every rule, and labels the system as recognition rather than compensation or discipline.
- XP records are durable user data once released. The migration is additive, but a production downgrade would destroy earned progress; deployment therefore needs the normal backup and forward-fix process.
- The current data model cannot fairly infer lateness, missed shifts, approved leave, job difficulty, or individual effort within a crew. Those are intentionally excluded rather than guessed.
- Approved upsells earn XP before payment and use quote-denominated value without exchange-rate conversion. Payment collection, refunds, FX, and sales compensation remain outside this feature.
- No historical backfill, manual bonus/penalty controls, custom XP formulas, custom level names, prizes, payroll links, previous-month browser, public customer view, push notification, or separate worker is added.
- Existing manager activity scorecards and upsell sales-tier rewards are preserved; neither becomes the XP ledger.
- Implementation and verification do not make the handoff or scoreboard changes live. Commit, PR, merge, backup, deploy, and production smoke checks remain a separate explicitly requested release operation.

## Steps

1. Add the XP-award model, quote origin flag, technician celebration state, registration, and additive migration with constraints, indexes, defaults, and no backfill.
2. Implement the centralized scoring service with fixed rules/levels, idempotent award lifecycle, workspace-timezone month aggregation, private details, and level acknowledgement.
3. Integrate attendance create/complete/edit/void transitions with one positive daily award and reconciliation tests.
4. Integrate job completion/reopen/delete transitions with completion-time crew credit, revocation, concurrency, and reassignment tests.
5. Mark on-site upsell quotes and award capped value-based XP transactionally on first approval, preserving ordinary quote behavior.
6. Add tenant-scoped scoreboard list, authorized detail, and self-acknowledgement schemas/routes with privacy, role, and cross-workspace tests.
7. Regenerate the OpenAPI contract and generated frontend types, then add typed scoreboard API calls, query keys, and polling behavior.
8. Add the Lighting League route/navigation access, preserve the six-item sidebar bound, and disambiguate the existing Upsell tier.
9. Build the electrical-panel scoreboard UI with personal progress, level rail, standings, manager detail Sheet, level-up banner, complete states, reduced motion, and responsive accessibility.
10. Add frontend component, navigation, keyboard, privacy, error, responsive, and acknowledgement tests; extend the route accessibility and visual catalogues.
11. Update `frontend/DESIGN.md` with the design read, evidence, thesis, state/responsive contract, screenshot evidence, critique, and final rubric result.
12. Run targeted tests, generated-contract checks, and isolated migration upgrade/check/downgrade/upgrade; fix every failure without weakening checks.
13. Exercise authenticated local source transitions and authorization with HTTP probes, inspect redacted responses/logs, and prove no peer or cross-workspace detail leaks.
14. Capture desktop/mobile/narrow rendered evidence, run axe/keyboard/forced-colors/reduced-motion checks, score the rubric, remove one decorative idea, revise the weakest criterion, and recapture.
15. Run standalone `make ci.all`, re-read generated or formatter-mutated files, unstage generated artifacts, clean fixtures/databases, run `git diff --check`, and confirm all work remains uncommitted and undeployed.
