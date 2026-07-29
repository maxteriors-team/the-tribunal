# Remove real-estate targeting → home-service CRM

## Goal
Audit the codebase for real-estate (realtor) functionality and remove/replace it so the product cleanly targets a **home-service** business. The migration to home-service is already ~90% done (field service, jobs, crews, technicians, quotes, invoices, catalog, CompanyCam, recurring jobs all exist; Follow Up Boss lead-sync already removed). What remains is a **realtor onboarding flow + real-estate copy + real-estate marketing/demo artifacts**.

## Audit summary — what's actually real-estate

The realtor surface is **generic onboarding infrastructure wearing real-estate clothing**. The flow itself — connect Cal.com → import a CSV of contacts → launch a reactivation SMS campaign + drip — is vertical-neutral. The real-estate-ness lives entirely in (a) **naming** (`realtor`, `Realtor*`) and (b) **copy** (home valuations, comps, sellers, "expired listings").

Critical facts that shape the plan:
- **A home-service default agent already auto-provisions on workspace creation** via `ensure_default_agent` (`backend/app/api/v1/workspaces.py:101`). So the realtor onboarding's separate `create_realtor_agent` is largely redundant — every workspace already gets a default agent before onboarding runs.
- **Name-based agent lookup is a prod-data landmine.** `drip_bootstrap.py` and `workspace_setup.get_realtor_agent` look up the agent by the exact string `"Realtor Lead Reactivation Agent"`. Existing prod workspaces may already have an agent with that name. Renaming the constant without a fallback/migration silently orphans reactivation drips for those workspaces.
- **`getRealtorStats` is dead on the frontend** — the `/workspaces/{id}/realtor/stats` endpoint + `realtor` query-keys have no `.tsx` consumer. Safe to delete outright.
- **The frontend `/onboarding` wizard IS the realtor flow** — it calls `parseCalcomUrl`/`onboard`/`createCampaignFromCsv` and its "onboard" call is what the `useSetupStatus`/`SetupGate` first-run gate relies on to create the first agent. Cannot be deleted without a replacement or it breaks first-run.

### Inventory & classification

**B1 — Rewrite real-estate copy → home-service (this is the actual "targeting")**
| File | What | Action |
|---|---|---|
| `backend/app/services/agents/realtor_template.py` | Agent system prompt + campaign defaults: "real estate agent", "free home valuation", "comps", "sellers" | Rewrite to home-service reactivation (past customers, seasonal maintenance, "we were in your neighborhood", free inspection/quote). Rename module → `reactivation_template.py`. |
| `backend/app/services/reactivation/sequence_config.py` | 6-step drip copy: "market's shifted", "home values", "sold over asking" | Rewrite steps to home-service; rename `get_realtor_drip_config`→`get_reactivation_drip_config`, `REALTOR_REACTIVATION_STEPS`→`REACTIVATION_STEPS`. |
| `backend/app/services/onboarding/workspace_setup.py` | `REALTOR_AGENT_NAME = "Realtor Lead Reactivation Agent"` | Rename to neutral (e.g. `"Lead Reactivation Agent"`) **with a migration/fallback for existing prod agents** (see Risks). |
| `frontend/src/app/onboarding/_steps/leads-step.tsx` | "Import Your Dead Leads" / "leads you want to reactivate" | Keep generic reactivation framing; ensure no RE-specific wording. (Already mostly neutral.) |

**B2 — Rename real-estate identifiers → neutral (functionality is generic)**
| File | What | Action |
|---|---|---|
| `backend/app/api/v1/onboarding/realtor_setup.py` | Routes `/realtor/onboard`, `/campaigns`, `/parse-calcom-url`, `/verify-calcom`, `/stats`; `RealtorStatsResponse`, `get_realtor_stats`, `realtor_onboard`, `create_realtor_campaign` | Rename file→`setup.py`; rename symbols; **decide on route-path rename** (see Decision 1). Delete the dead `/stats` endpoint. |
| `backend/app/schemas/realtor.py` | `RealtorOnboardRequest/Response`, `RealtorCampaignResponse` | Rename file→`onboarding.py`; rename schemas (`OnboardRequest`, `OnboardResponse`, `LaunchCampaignResponse`). |
| `backend/app/services/onboarding/workspace_setup.py` + `__init__.py` | `RealtorOnboardingInput/Result`, `RealtorCampaignInput/Result`, `complete_realtor_onboarding`, `launch_realtor_campaign_from_csv`, `create_realtor_agent`, `provision_realtor_phone_number`, `get_realtor_agent`, `get_realtor_sms_phone_number`, `import_realtor_contacts`, `create_realtor_campaign`, source `"realtor_csv_upload"` | Rename all `realtor`→ neutral (`onboarding`/`reactivation`). |
| `backend/app/services/onboarding/route_responses.py` | `realtor_onboard_response`, `realtor_campaign_response` + imports | Rename. |
| `backend/app/services/reactivation/drip_bootstrap.py` | Hardcoded agent-name lookup + `get_realtor_drip_config` import | Update to renamed constant/config with fallback. |
| `backend/app/services/email.py` (`realtor_name`), `backend/app/services/ai/text_tool_executor.py` (`realtor_email`/`realtor_name`) | Owner-notification email param is *named* realtor but is generic "notify business owner on booking" | Rename params → `owner_name`/`owner_email`. |
| `frontend/src/lib/api/realtor.ts` | `getRealtorStats`, `RealtorOnboardRequest`, etc. | Rename file→`onboarding.ts`; drop `getRealtorStats`; rename types/fns. Update importers (`onboarding/page.tsx`). |
| `frontend/src/lib/query-keys.ts` (`realtor` block) | `realtor.all/onboarding/stats/appointments` | Delete (unused) or rename → `onboarding`. |
| `frontend/src/hooks/useSetupStatus.ts` | Comment "realtor onboarding wizard" | Reword comment. |

**B3 — Remove/reframe genuine real-estate artifacts**
| File | What | Action |
|---|---|---|
| `frontend/src/components/landing/use-cases-section.tsx` | "Real Estate — Reactivate past buyers and expired listings" (1 of 6 vertical cards) | Decision 3: remove or replace with a home-service vertical. |
| `frontend/src/components/landing/results-section.tsx` | Testimonial attributed "— Real Estate Team Lead" | Reattribute to a home-service persona. |
| `backend/scripts/demo/update_demo_agents_grok.py`, `update_demo_agents_calcom.py` | Public-demo agents "Rachel (Dobi Real Estate)", "Amy (Marian Grout Real Estate)" with full RE prompts | Decision 4: rewrite personas to home-service or delete. |
| `backend/scripts/backfills/fix_contact_names.py` | One-off backfill hardcoded to workspace "Marian Grout Real Estate" | Leave (historical ops script) or delete; low priority. |
| `backend/tests/services/onboarding/test_workspace_setup.py` | Tests the realtor service end-to-end | Rename/update in lockstep with B2. |
| calcom test fixtures (`tests/**/calcom/*.json`), `test_webhooks_calcom_handlers.py`, `test_calcom_webhook_idempotency.py`, `test_email.py`, `tests/load/calcom_webhook.js` | Sample data "Jane Realtor / jane@realty.example / Acme Realty" + comments | Cosmetic; optional rename to home-service sample data. |
| `CLAUDE.md:15` | "Follow Up Boss/realtor workflows" listed as integration (FUB already removed) | Update line to reflect home-service reality. |
| `backend/openapi.json`, `frontend/src/lib/api/_generated.ts` | Generated `realtor` paths/schemas | Regenerate via `make codegen` after B2. |

## Decisions needing sign-off (product/taste + breaking change)
1. **Rename API routes `/api/v1/realtor/*` → `/api/v1/onboarding/*`?** This is a **breaking API change**. The frontend is the only consumer and both deploy from this repo, so it's feasible with codegen + a backend-first deploy. **Recommend: yes, rename** (leaves no "realtor" in the public surface). Alternative: keep route *paths*, rename only code symbols + copy (lower risk, but `realtor` stays in URLs/OpenAPI).
2. **Home-service reactivation copy** — I'll write a sensible generic home-service default (past customers, seasonal/maintenance reminder, "noticed we haven't been out in a while", free inspection/quote, soft appointment ask, breakup). Owner can tune tone later. Confirm that's acceptable vs. wanting specific trade wording (HVAC vs. roofing vs. cleaning).
3. **Landing "Real Estate" vertical** — remove entirely, or keep as one of several verticals the platform *can* serve? Recommend replace with a home-service vertical to match positioning.
4. **Demo agents** — rewrite the two public-demo real-estate personas to home-service, or delete them? Recommend rewrite (they back the public `/demo`).

## Risks & mitigations
- **Prod agent-name coupling (highest risk):** reactivation looks up `Agent.name == "Realtor Lead Reactivation Agent"`. Renaming the constant orphans existing prod drips. Mitigation: make the lookup match **both** the new and legacy names (or add a tiny data migration to rename existing agents). Must verify against prod before shipping.
- **First-run onboarding is critical path:** the `onboard` call creates/refreshes the first agent that `SetupGate` keys on. Keep the endpoint behavior identical through the rename; verify the wizard still completes and the setup gate clears.
- **Breaking API rename → release discipline:** per CLAUDE.md, run `make codegen`, commit `backend/openapi.json` + `_generated.ts` in the same commit, deploy **backend first**, then frontend.
- **Tests move in lockstep:** `test_workspace_setup.py` imports the renamed symbols; update together or the suite breaks.
- **No DB schema change** expected (naming/copy only) unless we add the optional agent-rename migration.

## Verification
- `make ci.codegen` (no drift after regenerating), `make ci.backend` (tests green incl. renamed onboarding tests + coverage floor), `make ci.frontend` (lint/type/build).
- `.ezcoder/eyes/http.sh` against the renamed onboarding endpoints (`/onboard`, `/parse-calcom-url`, `/verify-calcom`) with a real token → 2xx/expected 4xx.
- Authenticated screenshot of `/onboarding` (wizard completes, home-service copy) and the landing page (no "Real Estate" vertical).
- `grep -riE "realtor|real.?estate|realty"` across `backend/app` + `frontend/src` returns only intentional/sample-data matches.

## Steps
1. Rewrite `backend/app/services/agents/realtor_template.py` into a home-service reactivation template (rename module → `reactivation_template.py`; neutral system prompt + campaign defaults; rename `get_realtor_agent_config`/`get_realtor_campaign_defaults`).
2. Rewrite `backend/app/services/reactivation/sequence_config.py` drip copy to home-service; rename `REALTOR_REACTIVATION_STEPS`→`REACTIVATION_STEPS` and `get_realtor_drip_config`→`get_reactivation_drip_config`.
3. Rename the onboarding agent constant in `workspace_setup.py` to `"Lead Reactivation Agent"` and update `get_realtor_agent`/`drip_bootstrap.py` to match **both** the new and legacy `"Realtor Lead Reactivation Agent"` names (prod-safe fallback).
4. Rename all `Realtor*`/`realtor_*` identifiers in `backend/app/services/onboarding/workspace_setup.py` + `__init__.py` + `route_responses.py` to neutral onboarding/reactivation names; change import source string `"realtor_csv_upload"`→`"csv_upload"`.
5. Rename `backend/app/schemas/realtor.py`→`onboarding.py` and its schema classes; update imports.
6. Rename `backend/app/api/v1/onboarding/realtor_setup.py`→`setup.py`, rename symbols, delete the dead `/stats` endpoint + `RealtorStatsResponse`, and apply the route-path decision (Decision 1) in `backend/app/api/v1/router.py`.
7. Rename the owner-notification params `realtor_name`/`realtor_email`→`owner_name`/`owner_email` in `backend/app/services/email.py` and `backend/app/services/ai/text_tool_executor.py`.
8. Update `frontend/src/lib/api/realtor.ts`→`onboarding.ts`: drop `getRealtorStats`, rename types/functions/paths; update `frontend/src/app/onboarding/page.tsx` imports and any RE-flavored wizard copy.
9. Remove the `realtor` block from `frontend/src/lib/query-keys.ts` (unused) and reword the `useSetupStatus.ts` comment.
10. Replace the "Real Estate" card in `frontend/src/components/landing/use-cases-section.tsx` and the "Real Estate Team Lead" testimonial in `results-section.tsx` with home-service equivalents (Decision 3).
11. Rewrite or remove the real-estate demo personas in `backend/scripts/demo/update_demo_agents_grok.py` and `update_demo_agents_calcom.py` (Decision 4).
12. Update `backend/tests/services/onboarding/test_workspace_setup.py` to the renamed symbols; optionally rename cosmetic "Jane Realtor"/"Acme Realty" sample data in calcom fixtures + `test_email.py`.
13. Update `CLAUDE.md:15` to drop "Follow Up Boss/realtor workflows" and reflect home-service.
14. Run `make codegen` and commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` together.
15. Verify: `make ci.all`; `.ezcoder/eyes/http.sh` on the renamed onboarding endpoints; authenticated screenshots of `/onboarding` + landing; final `grep -riE "realtor|real.?estate|realty"` sweep shows only intentional matches.
