# CRM Assistant — Accuracy & Usefulness Overhaul

**Branch:** `assistant`
**Goal:** make the operator assistant accurate enough to trust, and useful for campaigns, automations, contact data entry, and general CRM/client questions.

---

## Verdict

The assistant is not inaccurate because of prompt wording. It is inaccurate for **four structural reasons**, then unhelpful for a **fifth**:

| # | Root cause | Evidence |
|---|---|---|
| 1 | **Cheapest model tier, 28 tools** | `_processor.py:42` → `MODEL = "gpt-5.4-nano"`. Repo convention is nano = "lightweight tasks", mini = "heavier tasks needing more intelligence" (`.ezcoder/plans/update-ai-models-march-2026.md`). A 28-tool agent loop is not lightweight. Also 2 generations stale. |
| 2 | **Context-blind** | `_build_api_messages()` injects a **static** `SYSTEM_PROMPT` constant, nothing else. No current date, no workspace/business name, no campaign or agent names, no tag vocabulary. Yet the prompt tells it to "summarize yesterday". `_context_builder.py` was designed in `crm-assistant-agent.md` and **never built**. |
| 3 | **Two core tools silently broken** | Proven empirically, see below. |
| 4 | **Confidently wrong counts** | Every list tool returns `"count": len(returned)` after `limit = min(arg, 50)`. No `total`, no `has_more`. "How many Smiths?" with 300 matches answers **"10"**. Repeated in 9 tools. |
| 5 | **The things you asked for have no tools** | No `update_contact`, `add_note`, `add_tag`, `get_contact`. No `create_campaign`/`update_campaign`. No `update_automation`. No product-knowledge retrieval. |

### Root cause 3, proven

`Contact.email` and `Contact.phone_number` are `EncryptedString` (Fernet, non-deterministic). I compiled the real predicates and ran the actual bind processors:

```
phone_number ILIKE : 'gAAAAABqalDdZPTEqUm3zbxsuTNWuoCVfIUw-JQ2...'
  raw digits survive?  False          ← pattern is encrypted before it reaches Postgres
first_name   ILIKE : '%Bob%'          ← plain column, works
encrypt() twice equal?  False         ← non-deterministic
```

**Bug A — `search_contacts` cannot match phone or email.** Its own description claims *"Search contacts by name, phone, email, or company"*. Searching a phone number returns `count: 0`, and the assistant reports the customer doesn't exist. Only `first_name`/`last_name`/`company_name` work.

**Bug B — `create_contact`'s duplicate guard is dead.** It does `Contact.phone_number == phone` on that same non-deterministic column, so it **never** matches → duplicate contacts created silently, reported as `success: true`.

Both have a correct path already used in ~20 other files: the deterministic, indexed `phone_hash` / `email_hash` (`LookupHash`) columns.

### Security issue found along the way

`confirmed` is a **model-settable approval bypass**. The gate is `if metadata.requires_approval and not args.get("confirmed")`, `confirmed` is in the tool schema the model writes, and it is never in `required`. The model can emit `confirmed: true` itself and skip the human approval gate on `send_sms`, `start_campaign`, `create_automation`, `create_agent`. Only a prose description discourages it. (`user_confirmed` is also honoured and appears in no schema.) The growth-tools plan explicitly warned: *"Prompt confirmation is not safety."* Must be fixed **before** Phase 2 widens write access.

---

## Phase 0 — Make accuracy measurable *(do first)*

Today **nothing** tests whether the model picks the right tool. Every test hardcodes the tool name into a scripted fake response; the user message is decorative. `SYSTEM_PROMPT` can be rewritten and 100% of tests still pass. So "not super accurate" is currently unfalsifiable and every fix below is unverifiable.

- Build `backend/tests/evals/crm_assistant/` with a golden set of ~40 real operator utterances → expected tool (or tool sequence), covering campaigns, automations, contact edits, lookups, and how-to questions.
- Harness runs the real model against real tool *schemas* with stubbed *handlers*, scores tool-choice accuracy, and prints a per-category breakdown.
- Mark `@pytest.mark.eval`, excluded from `make ci.backend` (costs money, non-deterministic); run on demand.
- **Record the baseline before changing anything.** That number is how we prove the rest worked.

Reuse: `backend/app/services/ai/testing/` already has an LLM test-harness pattern (`ivr_test_harness.py`) built for IVR and never applied here.

### Baseline record — ⚠️ BLOCKED on credentials (2026-07-29)

Built: `backend/tests/evals/crm_assistant/` — **48 cases across 9 categories**
(contact_lookup 6, contact_write 8, campaigns 9, automations 6, conversations 4,
agents 3, operations 5, offers 2, how_to 5).

| Artifact | Status |
|---|---|
| `golden_set.py` — 48 scored utterances | ✅ built |
| `harness.py` — live-model loop, scoring, per-category markdown/JSON report | ✅ built |
| `stub_handlers.py` — canned tool results so chains unfold | ✅ built |
| `test_harness_mechanics.py` — 20 tests proving the instrument works | ✅ passing |
| **Live baseline number** | ❌ **not recorded** |

**Why blocked:** this checkout has no OpenAI credential. `OPENAI_API_KEY` and all
`OPENAI_OAUTH_*` values in `backend/.env` are empty, no `OPENAI_*` env var is
exported, and there is no `~/.codex/auth.json`. `is_openai_configured()` →
`False`, so the eval self-skips.

**To record it**, set a key and run:

```bash
cd backend
OPENAI_API_KEY=sk-... uv run pytest tests/evals/crm_assistant -m eval -s
```

Reports land in `.ezcoder/eyes/out/crm-eval-<stamp>.{md,json}`.

**Known-zero categories at baseline** (their expected tools are not registered yet,
so they *cannot* score above zero until Phases 2–3 land — this is the measurement
that justifies building them): `how_to` (needs `search_help`), plus the
`update_contact` / `add_contact_note` / `add_contact_tags` / `get_contact` /
`find_contacts` / `create_campaign` / `update_campaign` / `list_campaign_contacts` /
`get_automation` / `update_automation` / `delete_automation` / `get_agent` cases.
`CRMAssistantEvalHarness.missing_expected_tools()` prints this list on every run.

---

## Phase 1 — Correctness foundation

**1.1 Fix Bug A** — `search_contacts` matches `phone_hash == hash_phone(q)` / `email_hash == hash_value(q)` for exact contact-detail lookups, keeps ILIKE for name/company, ORs the results. Fix the tool description to match reality.

**1.2 Fix Bug B** — dedupe on `phone_hash == hash_phone(phone)`. Return the existing contact's id on collision so the model can update instead of duplicating.

**1.3 Stop lying about counts** — every list tool returns `{items, returned, total, has_more}` via a `COUNT(*)`. Cheap, and it kills a whole class of confidently-wrong answers.

**1.4 Structured tool errors** — replace the blanket `except Exception: return {"error": f"Failed to execute {name}"}` with `{code, message, hint}`. Right now a malformed argument, a DB outage and a real bug are indistinguishable, so the model can never self-correct. Keep stack traces in structlog only.

**1.5 Enums + strict schemas** — 28 tools currently contain **one** enum. Add real enums for `campaign.status`, `channel_mode`, `discount_type`, `automation action.type`, etc., and `"additionalProperties": false`. Worst offender: an invalid `list_campaigns.status` (e.g. the natural guess `"active"`, not a real value) returns `success: true, count: 0` → "you have no active campaigns."

**1.6 Close the `confirmed` bypass** — drop `confirmed` from all model-facing schemas. Approval state belongs to the executor and the `/pending-actions` flow, never to a model-written argument.

**1.7 Model upgrade** — ✅ **done, with a caveat.** The live `/v1/models` check
could **not** be run (no OpenAI credential in this checkout — same blocker as
Phase 0). Model IDs were instead confirmed against OpenAI's own GPT-5.6 pages
plus three independent sources: `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`.

Because that live check is still outstanding, the IDs are **settings-backed**
(`OPENAI_ASSISTANT_MODEL` / `OPENAI_ASSISTANT_SUMMARY_MODEL`) rather than
hard-coded — a wrong ID is an env change, not a deploy. Tool loop → Terra;
summarisation and prompt-enhance → Luna. `MAX_COMPLETION_TOKENS` 800 → 2000.

**Still verify** `/v1/models` before this reaches production.

Original note: move the reasoning loop off `gpt-5.4-nano`. Current lineup is the GPT-5.6 family: <cite index="6-5">Sol for complex reasoning, Terra to balance intelligence and cost, Luna for cost-sensitive high-volume workloads</cite>. **Recommend Terra** for the tool loop; leave summarisation/enhance on a cheap tier.
⚠️ **Confirm exact API model IDs against the live `/v1/models` endpoint before hard-coding** — do not trust model names from memory. Also raise `MAX_COMPLETION_TOKENS` (currently 800, truncates multi-record answers).

**1.8 Build `_context_builder.py`** — the missing piece from the original design. Inject current date/time + workspace timezone, business name/industry, live counts, active campaign names, agent names, pipeline stages, tag vocabulary.
⚠️ **Must preserve prompt-cache prefix stability** — `_summarizer.py` deliberately keeps the system prefix byte-identical (there's a test asserting it). Append dynamic context as a **second** system message after the static prefix, never inside it.

> Expect Phase 1 alone to move the Phase 0 number the most — 1.7 and 1.8 are the two biggest single levers.

### Post-Phase-1 eval check (2026-07-29)

The live A/B number is still blocked on the missing credential (see Phase 0).
What *is* verifiable without one — the harness now runs against the upgraded
configuration and a shrinking set of structurally-impossible cases:

| | Baseline | After Phase 1 |
|---|---|---|
| Harness model | `gpt-5.4-nano` | `gpt-5.6-terra` |
| `max_completion_tokens` | 800 | 2000 |
| Tools exposed | 28 | 28 |
| Enums in schemas | 1 | 12 |
| Cases that *cannot* score | 9/48 | 9/48 |
| Live accuracy | ❌ blocked | ❌ blocked |

The 9 unscoreable cases are blocked on 4 unbuilt tools — `update_contact`,
`add_contact_note`, `add_contact_tags` (Phase 2) and `search_help` (Phase 3):
`contact_write` 4, `how_to` 5. Phase 2 closes the first group.

---

## Phase 2 — The time-savers you named

Good news: **the services already exist and are simply unwired.** `contact_repository.update_contact`, `bulk_update_status`, `get_contact_timeline`, `TagService.add_tags_to_contact`, `apply_contact_filters`, `AutomationUpdate`. This is wiring, not building.

**Contacts** — today contacts are *append-only* to the assistant: `create_contact` is the only write.
- `get_contact(contact_id)` — **fixes three broken chains**: `list_appointments`, `list_opportunities` and `list_recent_conversations` all emit contact IDs the model currently has no way to turn into a person. ("Who are my appointments with tomorrow?" is unanswerable today.)
- `update_contact` — the literal "adding contact information" ask.
- `add_contact_note` — `notes` is currently write-once-at-create, never readable.
- `add_contact_tags` — note the irony: `create_automation` can build a machine that applies tags, but the assistant cannot tag one contact.
- `find_contacts(filters)` — expose `apply_contact_filters` for "everyone tagged hot-lead", "not contacted in 30 days", "created this week".
- Return `contact_id` from `list_recent_conversations` (it returns a conversation UUID and phone, but `get_conversation` requires `contact_id` — chain is structurally broken).

**Campaigns** — currently lifecycle-only (start/pause/resume).
- `create_campaign`, `update_campaign` (incl. editing `initial_message` before launch), `list_campaign_contacts`.
- Widen `list_campaigns` beyond `{id, name, status, type}` — no schedule, no message body, no contact count today.

**Automations**
- `get_automation`, `update_automation` (wire up existing `AutomationUpdate`), `delete_automation`.
- Today "change the wait from 2h to 24h" forces the model to create a duplicate and disable the original; disabled junk accumulates forever.
- Give `trigger_config` and `actions[].config` real per-type schemas — `config` is currently a shapeless `{"type": "object"}`.

**Also worth fixing:** `list_agents` returns no `system_prompt` and there is no `get_agent`, yet `update_agent` can overwrite that prompt — the model can blind-write a field it cannot read.

### Post-Phase-2 eval check (2026-07-29)

All Phase 2 tool families are now registered. **43/48 cases are structurally
scoreable**; the remaining 5 all require Phase 3's `search_help` tool. The live
accuracy run still self-skips because OpenAI credentials are not configured.

---

## Phase 3 — "General questions and facts about the CRM"

A full hybrid RAG stack already exists (`knowledge/retrieval_service.py`: pgvector KNN + tsvector keyword, weighted fusion, MMR rerank). **The assistant cannot reach it, and wiring it up alone would not fix this** — two blockers:

1. Not registered as an assistant tool.
2. **Wrong corpus.** `KnowledgeDocument.agent_id` is `nullable=False` → every document must belong to a customer-facing agent, and the content is per-tenant *business* material (faq/pricing/policy/persona) for answering *contacts*. There is no product/how-to corpus and no ingestion path for one.

So "how do I set up an automation?" is answered purely from model priors — while the system prompt orders it to *"Ground every factual claim in tool results"* and *"Never invent"*. It must either wrongly refuse or confabulate. **This is the mechanical explanation for the how-to inaccuracy.**

Plan: allow workspace-scoped documents with `agent_id NULL`, seed a product-knowledge corpus from `docs/`, expose `search_help`. Largest phase — defer until 1–2 land.

---

## Phase 4 — Trust & UX

- **Approvals are invisible in chat.** A gated tool returns `pending_approval` in a `role:"tool"` row that the UI filters out. The user only learns of it if the model happens to narrate it, then must navigate to `/pending-actions`. `OutboundWorkflowCard` **already has** approve/reject buttons — chat just renders it without the `action`/`onApprove` props. Add a `pending_approval` stream event and wire the existing card.
- **Failed tools render as green checks** — `tool_end.success` is captured then dropped.
- **Partial text vanishes on error** — `streamingText` isn't cleared and no message is appended. Add a retry button.
- **SSE bypasses the axios 401-refresh interceptor** → raw "status 401" in chat.
- Dead protocol: `reasoning` and `retry` events are declared on both sides with **zero** backend emitters.
- Starter prompts are 3 hardcoded strings, not workspace-aware; clicking sends immediately with no chance to edit.
- Show tool arguments/results, not just a name chip. `actions_taken` already arrives in `done` and is discarded.

---

## Sequencing & verification

```
Phase 0  →  baseline number
Phase 1  →  re-run eval, expect the large jump      ← ship here first
Phase 2  →  re-run eval + new write-tool categories
Phase 4  →  UX (can run parallel to 2)
Phase 3  →  knowledge corpus (largest, defer)
```

Per phase: `make ci.backend`, `make ci.frontend`, `make ci.codegen` (assistant routes are public API → commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` in the same commit). Exercise changed endpoints with `.ezcoder/eyes/http.sh` against local backend. Phase 0 eval run before/after each phase.

**Migrations:** Phase 3 needs one (`agent_id` nullable). Phases 0–2 and 4 need none.

## What I would cut

- The 15-tool `growth_*` contract from `crm-assistant-growth-tools.md` (30KB spec, collapsed into one tool in practice). Not worth reviving now.
- `send_initial_message` — it just looks up `campaign.initial_message` and delegates to `send_sms`. It's a redundant tool competing for model attention in an already-crowded 28-tool namespace.

## Steps

1. Create `backend/tests/evals/crm_assistant/` with a golden set of ~40 operator utterances mapped to expected tool calls, covering campaigns, automations, contact edits, lookups, and how-to questions.
2. Build the eval harness in that directory: run the real model against real tool schemas with stubbed handlers, score tool-choice accuracy, print a per-category breakdown, mark `@pytest.mark.eval` and exclude it from `make ci.backend`. Reuse the pattern in `backend/app/services/ai/testing/ivr_test_harness.py`.
3. Run the harness and record the baseline accuracy number in the plan file before changing any behaviour.
4. Fix `search_contacts` in `backend/app/services/ai/crm_assistant/_contact_tools.py` to match `phone_hash == hash_phone(query)` and `email_hash == hash_value(query)` for contact-detail lookups, keep ILIKE for name/company, and correct the tool description in `_tools.py`.
5. Fix the `create_contact` duplicate guard in `_contact_tools.py` to compare `phone_hash == hash_phone(phone)`, and return the existing contact id on collision.
6. Change every list tool across the `_*_tools.py` modules to return `{items, returned, total, has_more}` using a `COUNT(*)`, replacing the current `"count": len(returned)`.
7. Replace the blanket `except Exception` handler in `_tool_executor.py` with structured `{code, message, hint}` errors, keeping stack traces in structlog only.
8. Add real enums and `"additionalProperties": false` to the tool schemas in `_tools.py` for `campaign.status`, `channel_mode`, `discount_type`, `automation action.type`, and the other closed value sets currently described in prose.
9. Remove `confirmed` (and honour-but-undocumented `user_confirmed`) from all model-facing schemas in `_tools.py` and from the gate in `_tool_executor.py`, so approval state lives only in the executor and `/pending-actions` flow.
10. Query the live OpenAI `/v1/models` endpoint to confirm exact current model IDs, then update `MODEL` in `_processor.py` to the balanced GPT-5.6 tier, leave `_summarizer.py` on a cheap tier, and raise `MAX_COMPLETION_TOKENS` above 800.
11. Create `backend/app/services/ai/crm_assistant/_context_builder.py` producing current date/time, workspace timezone, business name/industry, live counts, active campaign names, agent names, pipeline stages and tag vocabulary; inject it from `_build_api_messages()` as a second system message after the static prefix so prompt-cache stability and the summarizer test still hold.
12. Re-run the eval harness and compare against the Phase 0 baseline.
13. Add `get_contact`, `update_contact`, `add_contact_note`, `add_contact_tags` and `find_contacts` tools wired to the existing `contact_repository`, `TagService` and `apply_contact_filters`; register them in `_tools.py`, `_contact_tools.py` and `_tool_metadata.py`.
14. Add `contact_id` to the `list_recent_conversations` payload so the `list_recent_conversations` → `get_conversation` chain works.
15. Add `create_campaign`, `update_campaign` and `list_campaign_contacts` to `_campaign_tools.py`, and widen the `list_campaigns` payload beyond `{id, name, status, type}` to include schedule, message body and contact count.
16. Add `get_automation`, `update_automation` and `delete_automation` to `_automation_tools.py` wired to the existing `AutomationUpdate` schema, and give `trigger_config` and `actions[].config` real per-trigger-type schemas in `_tools.py`.
17. Add a `get_agent` tool and include `system_prompt` in the `list_agents`/`get_agent` payloads so `update_agent` can no longer blind-write an unreadable field.
18. Remove the redundant `send_initial_message` tool, which only looks up `campaign.initial_message` and delegates to `send_sms`.
19. Run `make ci.codegen` and commit `backend/openapi.json` plus `frontend/src/lib/api/_generated.ts` alongside the route/schema changes, then re-run the eval harness.
20. Emit a `pending_approval` stream event from `_processor.py`, add it to the backend and frontend event schemas, and render the existing `OutboundWorkflowCard` in chat with `action`/`onApprove`/`onReject` wired so approvals can be actioned without leaving the conversation.
21. Fix the frontend stream handling in `frontend/src/components/assistant/assistant-chat.tsx` and `frontend/src/hooks/useAssistantChat.ts`: render `tool_end.success` as a failure state instead of a green check, preserve partial `streamingText` on error, add a retry button, and surface `actions_taken` tool arguments/results instead of a bare name chip.
22. Route the SSE fetch through the axios 401-refresh path (or replicate the refresh) so expired sessions no longer surface as raw "status 401" in chat.
23. Remove the dead `reasoning` and `retry` event types from both schemas, or emit them from the backend; make the three hardcoded starter prompts workspace-aware and prefill the composer instead of sending immediately.
24. Make `KnowledgeDocument.agent_id` nullable via an Alembic migration to allow workspace-scoped product documents, and update `retrieve_passages` to accept a null `agent_id`.
25. Seed a product-knowledge corpus from `docs/` and expose a `search_help` tool to the assistant, then re-run the eval harness against the how-to question category.

## Open questions

1. **Budget for 1.7?** Terra costs meaningfully more per call than nano. Alternative: Terra for the tool loop, Luna for summarisation. I'd take the accuracy.
2. **Phase 3 corpus source** — generate from `docs/`, or hand-write help content? Changes the size a lot.
3. **Scope check:** this branch currently carries your in-progress quotes/estimator work. Want me to keep assistant commits separate from that, or is the WIP intentional here?
