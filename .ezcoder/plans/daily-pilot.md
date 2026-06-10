# Daily Pilot — the CRM tells you what to do each morning

## Objective

Raise the floor on existing systems so the daily loop becomes: **open the app (or read the SMS) → see today's ordered mission queue → approve → done.** No new product surface areas — compose the organs that already exist:

| Organ | Where it lives today | Gap |
|---|---|---|
| Nudges (generate + SMS/push deliver) | `backend/app/services/nudges/` + `backend/app/workers/nudge_worker.py` | All 11 strategies are contact-lifecycle; nothing about the outbound machine; `HumanNudge.contact_id` is NOT NULL |
| Approvals (HITL queue + executor) | `backend/app/models/pending_action.py`, `backend/app/services/approval/approval_gate_service.py`, `frontend/src/app/pending-actions/` | No handler that launches a drafted outbound campaign |
| Ad-library machine (monitor → discover → enrich → promote) | `backend/app/workers/ad_monitor_worker.py`, `ad_library_discovery_worker.py`, `prospect_enrichment_worker.py`, `prospect_promotion_worker.py`, `backend/app/services/outbound/promotion.py` | Stops at "contact tagged `ad-library`/`stale-creative`" — a human must notice and walk pages to build a campaign |
| Guided campaign wizard | `backend/app/services/outbound/growth_workflow.py` (`plan()` with `_collect_missing_inputs`, draft creation, previews, responder) | Only reachable via assistant tool `plan_outbound_growth_workflow`; never triggered automatically |
| Assistant with real tools | `backend/app/services/ai/crm_assistant/` (`_tools.py`, `_processor.py`), `frontend/src/app/assistant/` | Waits passively; has no view of "today's state" |
| Dashboard | `backend/app/services/dashboard/dashboard_service.py`, `frontend/src/components/dashboard/dashboard-page.tsx` | Stats wall, not a mission queue; root redirects to `/contacts` |

## Design

### A. Today Queue (backend)

New `backend/app/services/dashboard/today_queue_service.py` producing an **ordered** list of mission items:

1. `approvals` — `PendingAction` status=`pending` (count + top 3 descriptions) → `/pending-actions`
2. `hot_nudges` — pending `HumanNudge` due today, priority desc → `/nudges`
3. `prospect_batch` — contacts with `source="ad_library"` created in last 24h (count, top companies, signal tags) → `/find-leads/ad-library`
4. `draft_campaigns` — `Campaign` status=`draft` (name, enrolled count) → `/campaigns/{id}`
5. `setup_gaps` — cold-start guidance: no active ad monitor (`monitors.is_active_monitor`), no active offer, no sms-enabled `PhoneNumber` → deep link to the relevant wizard

Item shape: `{id, kind, priority, title, body, count, cta_label, href, payload}` (new Pydantic schemas in `backend/app/schemas/`). Route: `GET /workspaces/{workspace_id}/dashboard/today-queue` added to `backend/app/api/v1/dashboard.py` (router already mounted with that prefix in `backend/app/api/v1/router.py:189`).

### B. Operator-level nudges (the CRM texts *you* the plan)

- Alembic migration: make `human_nudges.contact_id` nullable (additive; production-safe; test locally per CLAUDE.md).
- New strategies in `backend/app/services/nudges/strategies/` following `base.py` `NudgeStrategy` + registered in `_STRATEGY_REGISTRY` (`nudge_generator.py`) and `ALL_NUDGE_TYPES`:
  - `outbound_batch_ready` — N ad-library contacts never enrolled in any campaign ("212 fresh advertisers ready — review batch")
  - `approvals_waiting` — pending `PendingAction`s older than 2h ("7 approvals waiting")
  - `monitor_idle` — no active ad monitors in workspace ("the scraper is off — set a monitor")
  - Dedup keys per workspace per day (`{workspace_id}:{type}:{date}`); `contact_id=None`.
- Update `backend/app/api/v1/nudges.py` serializer, `nudge_delivery.py`, and `frontend/src/components/nudges/nudges-page.tsx` + dashboard `NudgesCard` to tolerate null contact (title/message already carry full text).

### C. Autopilot draft (overnight scrape → morning approval)

- New `backend/app/workers/outbound_auto_draft_worker.py` (daily tick per workspace, gated by workspace setting `outbound_autopilot.enabled`, default **off**; registered in `start_all_workers()`):
  1. Find un-campaigned `ad-library` contacts (reuse tag filtering from `backend/app/services/contacts/contact_filters.py`).
  2. Ensure a managed Segment "Ad library — fresh" exists (tag rule).
  3. Resolve default offer from `outbound_autopilot.offer_id`; if missing, emit a `monitor_idle`-style nudge instead of guessing.
  4. Call `GrowthWorkflowService.plan(create_draft=True)` — reusing copy, previews, responder resolution.
  5. Create a `PendingAction` `action_type="outbound.launch_campaign"`, payload `{campaign_id}`, description embedding preview messages — lands in the existing approval pipe (web + SMS/push via approval delivery).
- New `LaunchCampaignHandler` in `approval_gate_service.py` (mirrors existing `outbound_improvement.follow_up_campaign` handler pattern) that starts the draft campaign on approval.
- Idempotency: skip if an unexpired `outbound.launch_campaign` PendingAction or today's draft already exists.

### D. Assistant morning briefing

- New tool `get_today_queue` in `_tools.py` + executor module (calls TodayQueueService); add briefing guidance to `SYSTEM_PROMPT` in `_processor.py` (~line 103): when asked for a briefing, fetch the queue, summarize yesterday via `get_dashboard_stats`/`summarize_campaign`, then walk items in order, offering to execute each with existing tools.
- Frontend: `/assistant?briefing=1` auto-sends "Give me my morning briefing" as the first message in `frontend/src/components/assistant/assistant-chat.tsx`.

### E. Today page (one front door)

- New route `frontend/src/app/today/page.tsx` + `frontend/src/components/today/today-page.tsx`: ordered mission cards from the today-queue endpoint; each card's CTA deep-links (approve → `/pending-actions`, batch → `/find-leads/ad-library`, draft → `/campaigns/{id}`, gaps → wizard); hero button "Start my day" → `/assistant?briefing=1`.
- Use `frontend/src/lib/query-keys.ts`, `query-options.ts`, `page-state.tsx` per repo conventions; nav entry in `frontend/src/components/layout/app-sidebar.tsx`.
- Change root redirect in `frontend/src/app/page.tsx` from `/contacts` → `/today`.

## Out of scope (explicitly)

- Email campaign channel (campaigns are `sms`/`voice_sms_fallback` only — `CampaignType` in `backend/app/models/campaign.py:37`; email exists only for notifications). Worth a separate plan.
- New scraping providers, billing tiers, multi-workspace autopilot policy.

## Risks

- `contact_id` nullable migration touches a production table — additive and nullable (safe shape), but run `make ci.migrations` and a local backup first per CLAUDE.md.
- Auto-draft sends nothing by itself — every send still passes the human approval gate (TCPA posture preserved). Keep autopilot setting default-off.
- Workers run in-process; one more daily worker is negligible, but don't lower its poll interval below daily.
- Frontend codegen: backend schema changes require `make ci.codegen` and committing `backend/openapi.json` + `frontend/src/lib/api/_generated.ts`.

## Verification

- Backend: pytest for today_queue_service, the 3 new nudge strategies (dedup + null-contact), auto-draft worker (idempotency, missing-offer path), `LaunchCampaignHandler`; `make ci.backend`, `make ci.migrations`.
- Probe: `.ezcoder/eyes/http.sh http://localhost:8000/api/v1/workspaces/<ws>/dashboard/today-queue` (shape + 200); `.ezcoder/eyes/logs.sh --grep "outbound_auto_draft|nudge_worker|ERROR"` after a forced tick.
- Frontend: `make ci.frontend`; `/today` renders queue, empty, and error states; root redirect lands on `/today`.
- Codegen: `make ci.codegen` clean.

## Steps

1. Create Alembic migration making `human_nudges.contact_id` nullable; update `backend/app/models/human_nudge.py`; run `make ci.migrations`.
2. Build `backend/app/services/dashboard/today_queue_service.py` with ordered mission items (approvals, hot nudges, prospect batch, draft campaigns, setup gaps) + Pydantic schemas; expose `GET .../dashboard/today-queue` in `backend/app/api/v1/dashboard.py`; add pytest coverage.
3. Add operator-level nudge strategies (`outbound_batch_ready`, `approvals_waiting`, `monitor_idle`) under `backend/app/services/nudges/strategies/`, register them in `nudge_generator.py`, and make `backend/app/api/v1/nudges.py` + `nudge_delivery.py` tolerate null contact; add pytest coverage.
4. Add `LaunchCampaignHandler` for `action_type="outbound.launch_campaign"` in `backend/app/services/approval/approval_gate_service.py` with tests.
5. Build `backend/app/workers/outbound_auto_draft_worker.py` (daily, default-off via `outbound_autopilot` workspace setting) that segments fresh ad-library contacts, calls `GrowthWorkflowService.plan(create_draft=True)`, and parks an `outbound.launch_campaign` PendingAction; register in `start_all_workers()`; add idempotency tests.
6. Add `get_today_queue` assistant tool (definition in `_tools.py`, executor, metadata) and extend `SYSTEM_PROMPT` in `_processor.py` with morning-briefing behavior.
7. Run `make ci.codegen` and commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts`.
8. Build `/today` frontend route + `today-page.tsx` mission-queue UI with query keys/options and page-state conventions; add "Start my day" → `/assistant?briefing=1`; add sidebar nav entry.
9. Implement `?briefing=1` auto-message in `frontend/src/components/assistant/assistant-chat.tsx`; update nudges UI (`nudges-page.tsx`, dashboard `NudgesCard`) for workspace-level nudges.
10. Flip root redirect in `frontend/src/app/page.tsx` to `/today`.
11. Run full verification: `make ci.backend`, `make ci.frontend`, `make ci.all` parity, then probe `today-queue` endpoint and worker logs via `.ezcoder/eyes/http.sh` and `.ezcoder/eyes/logs.sh`.
