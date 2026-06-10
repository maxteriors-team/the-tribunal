# "Today" — the daily money plan front door

## Goal

Stop being a tool you learn; become a system that runs for you. Open the app → one ranked queue answers "what makes money today?" → every item is one click: **Approve** (existing approval gate), **Do it** (opens the CRM Assistant pre-prompted to execute with its existing ~30 tools), or **Done/Dismiss**. Collapse the 31-item nav so this is the front door. No new features — converge what exists.

## What already exists (reused, not rebuilt)

| Capability | Where |
|---|---|
| Agent with ~30 tools + risk/approval policy | `backend/app/services/ai/crm_assistant/` (`_processor.py`, `_tool_metadata.py`) |
| Guided outbound setup (`plan_outbound_growth_workflow`) | `backend/app/services/outbound/growth_workflow.py` |
| Money nudges (hot lead, deal stall, unresponsive, referral…) | `backend/app/services/nudges/`, API `backend/app/api/v1/nudges.py` |
| Human-in-the-loop approvals | `backend/app/api/v1/pending_actions.py`, `approval_gate_service` |
| Deal risk scoring (`assess_risk`, amount_at_risk) | `DashboardService.get_deal_coach_stats` in `backend/app/services/dashboard/dashboard_service.py:763` |
| AI prompt suggestions pending count | `backend/app/api/v1/improvement_suggestions.py` (`/pending-count`) |
| Assistant chat UI + streaming runtime | `frontend/src/components/assistant/`, `frontend/src/hooks/useAssistantChat.ts` |
| Nav config | `frontend/src/components/layout/app-nav.ts` |

## Part 1 — Backend: Today Plan aggregator

### 1a. Schema: `backend/app/schemas/today_plan.py` (new)

```python
TodayPlanItemKind = Literal["approval", "nudge", "deal_risk", "suggestion", "outbound_idle", "speed_to_lead"]
TodayPlanCta = Literal["approve", "assistant", "open"]

class TodayPlanItem(BaseModel):
    id: str                    # stable key, e.g. "nudge:<uuid>", "approval:<uuid>"
    kind: TodayPlanItemKind
    title: str
    why: str                   # the money rationale ("$12,400 deal stalled 14 days")
    estimated_value: float | None
    currency: str
    priority: int              # computed score, descending sort
    cta: TodayPlanCta
    assistant_prompt: str | None   # set when cta == "assistant"
    href: str | None               # deep link for cta == "open" / secondary nav
    source_id: str | None          # nudge/action/opportunity uuid for inline mutations

class TodayPlanResponse(BaseModel):
    generated_at: datetime
    items: list[TodayPlanItem]
    summary: TodayPlanSummary    # counts per kind + total estimated_value
```

### 1b. Service: `backend/app/services/dashboard/today_plan_service.py` (new)

`TodayPlanService(db).get_plan(workspace) -> TodayPlanResponse`. Six read-only collectors, each producing items, merged + sorted by `priority`:

1. **Approvals** — `PendingAction` where `status="pending"`, not expired. CTA `approve`. Priority: highest band (work is blocked on the human). Use `description` + `urgency`.
2. **Nudges** — `HumanNudge` where status in `("pending","sent")`, ordered hot_lead > deal_milestone > noshow_recovery > follow_up > unresponsive > cooling > referral_ask > dates. CTA `assistant`; prompt built from `suggested_action` + contact name/phone (e.g. *"Draft and send an SMS to {name} ({phone}): {suggested_action}. Search the contact first, show me the message before sending."* — send still gates through the approval queue per `_tool_metadata.py`).
3. **Deal risk** — reuse the same query/heuristic as `get_deal_coach_stats` (extract shared helper or call `assess_risk` directly) for top N watch/at_risk/critical deals. `estimated_value = amount_at_risk`. CTA `assistant` with a re-engagement prompt; `href=/opportunities`.
4. **Speed to lead** — contacts created in the last 48h with no outbound conversation/message. CTA `assistant` ("reach out to these new leads now").
5. **Suggestions** — pending improvement-suggestion count > 0 → one rollup item, CTA `open` → `/suggestions`.
6. **Outbound idle** — zero campaigns in `active` status → one item, CTA `assistant` with prompt *"Plan an outbound campaign to promote one of my offers"* (routes to the existing `plan_outbound_growth_workflow` tool, which asks for offer/segment/number and drafts everything).

Deterministic priority: `band * 1000 + min(int(estimated_value or 0) // 100, 999)` with bands approval=9, hot-lead nudge=8, deal critical=7, speed_to_lead=6, deal at_risk/watch=5, other nudges=4, outbound_idle=3, suggestion=2. Cap list at ~20 items. No Redis caching (queries are cheap; the dashboard's 5-min cache caused stale-feeling data — call this out in the docstring).

Export from `backend/app/services/dashboard/__init__.py`.

### 1c. Router: `backend/app/api/v1/today.py` (new)

`GET ""` → `TodayPlanResponse`, deps `DB, CurrentUser, WorkspaceAccess` matching `dashboard.py`. Register in `backend/app/api/v1/router.py` with prefix `/workspaces/{workspace_id}/today`, tag `Today`.

### 1d. Tests: `backend/tests/api/test_today_plan.py` (new)

- Empty workspace → only `outbound_idle` item.
- Seed one pending action + one hot-lead nudge + one at-risk opportunity → ordering approval > nudge > deal, prompts/`source_id` populated, workspace-scoped (other workspace's rows excluded).
- Nudge prompt contains `suggested_action`.

## Part 2 — Frontend: Today page + one-click execution

### 2a. Assistant deep-link (the "help me prompt the agent" piece)

- `frontend/src/hooks/useAssistantChat.ts`: accept optional `initialPrompt?: string`; on mount with a workspaceId, start a fresh draft conversation and auto-call `sendMessage(initialPrompt)` exactly once (ref guard).
- `frontend/src/components/assistant/assistant-chat.tsx`: pass `initialPrompt` prop through.
- `frontend/src/app/assistant/page.tsx`: read `?prompt=` via `useSearchParams` (needs a client wrapper + Suspense boundary), pass down. Navigating to `/assistant?prompt=...` = "agent, go do this."

### 2b. API client + keys

- `frontend/src/lib/api/today.ts` (new): `todayApi.getPlan(workspaceId)` typed from regenerated `_generated.ts`.
- `frontend/src/lib/query-keys.ts`: add `todayPlan: { plan: (workspaceId) => ... }` builder (ESLint forbids literals).

### 2c. Today page: `frontend/src/app/today/page.tsx` + `frontend/src/components/today/` (new)

- `today-page.tsx`: header ("Here's how we make money today" + total estimated value + generated-at), then the ranked item list. Use `PageState` components for loading/error/empty; empty state = "Nothing queued — plan outbound" button → assistant.
- `today-item-card.tsx`: icon per kind, title, **why** line, value badge, and the single primary button:
  - `approve` → inline Approve/Reject via `pendingActionsApi` mutations, invalidate `queryKeys.pendingActions.all` + `todayPlan`.
  - `assistant` → `router.push("/assistant?prompt=" + encodeURIComponent(item.assistant_prompt))`.
  - `open` → `Link` to `item.href`.
  - Secondary overflow for nudge items: Done (`nudgesApi.act`) / Dismiss (`nudgesApi.dismiss`), invalidate `nudges` + `todayPlan`.
- Match existing card/motion styling from `frontend/src/components/dashboard/`.

### 2d. Make it the front door

- `frontend/src/app/page.tsx`: `redirect("/today")` (was `/contacts`).
- `frontend/src/components/layout/app-nav.ts`:
  - New top section **Operate**: Today (new, `Sun` or `Target` icon, first), Assistant, Pending Actions (badge), Nudges (badge), Opportunities, Contacts, Campaigns.
  - Demote everything else (Dashboard, Deal Coach, Segments, Calls, Scorecard, Lead Discovery items, all Tools items) into collapsible sections with `defaultOpen: false`. Keep `commandPalette: true` on all so nothing is lost.
  - Add `today: "Today"` to `breadcrumbLabels`.
- No routes deleted — pure re-ranking. (Risk: muscle memory; mitigated by command palette and collapsed-but-present sections.)

## Part 3 — Codegen + verification

- `make ci.codegen` → commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts`.
- `make ci.backend`, `make ci.frontend`.
- Eyes: `.ezcoder/eyes/http.sh http://localhost:8000/api/v1/workspaces/<id>/today` (auth header) → 200 + ranked items; verify ordering and prompt text in saved body.

## Risks / non-goals

- **Not** auto-executing anything new: every risky action still flows through the existing approval gate. The Today page only *launches* the assistant.
- Assistant auto-send on deep-link fires one LLM call on page load — guard against double-send (React strict mode) with a ref.
- `speed_to_lead` collector adds a new query against contacts/conversations — keep it indexed-column-only (`created_at`, workspace scope); production has live data.
- Estimated values are heuristics (amount_at_risk), not promises — label as "at stake."
- Nav demotion may annoy existing users; all items stay reachable via command palette.

## Steps

1. Create `backend/app/schemas/today_plan.py` with `TodayPlanItem`, `TodayPlanSummary`, `TodayPlanResponse`.
2. Create `backend/app/services/dashboard/today_plan_service.py` with the six collectors, deterministic priority scoring, and prompt builders; export from `backend/app/services/dashboard/__init__.py`.
3. Create `backend/app/api/v1/today.py` router and register it in `backend/app/api/v1/router.py` under `/workspaces/{workspace_id}/today`.
4. Add `backend/tests/api/test_today_plan.py` covering empty workspace, ranking order, prompt content, and workspace scoping.
5. Run `make ci.codegen` and commit regenerated `backend/openapi.json` + `frontend/src/lib/api/_generated.ts`.
6. Add `initialPrompt` auto-send support to `frontend/src/hooks/useAssistantChat.ts` and `frontend/src/components/assistant/assistant-chat.tsx`, and `?prompt=` handling (Suspense-wrapped) in `frontend/src/app/assistant/page.tsx`.
7. Create `frontend/src/lib/api/today.ts` client and add the `todayPlan` builder to `frontend/src/lib/query-keys.ts`.
8. Build `frontend/src/components/today/today-page.tsx` and `today-item-card.tsx` with approve/assistant/open CTAs and nudge done/dismiss actions wired to existing APIs.
9. Create `frontend/src/app/today/page.tsx` route and switch `frontend/src/app/page.tsx` redirect to `/today`.
10. Restructure `frontend/src/components/layout/app-nav.ts` into the Operate section + collapsed sections, add Today nav item and breadcrumb label.
11. Run `make ci.backend` and `make ci.frontend`; fix any failures.
12. Start the local stack and verify with `.ezcoder/eyes/http.sh` on the new `/today` endpoint, confirming ranked items and prompt text.
