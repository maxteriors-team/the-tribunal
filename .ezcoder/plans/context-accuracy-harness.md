# Context accuracy harness plan

## Scope

Add a local, zero-provider-call evaluation harness for SMS, voice, and CRM assistant context behavior while preserving the existing uncommitted contact-memory work.

## Steps

1. Add 48 fully synthetic/redacted scenarios under `backend/tests/evals/context_accuracy/`, exactly six for each requested failure class and 16 per channel.
2. Add structured, body-free observation manifests and deterministic scorers that report stored-fact recall, unsupported claims, stale-state errors, tool/action correctness, and handoff correctness separately.
3. Add a CLI that validates/scorers observations, writes deterministic JSON plus Markdown artifacts, and exits non-zero when CI or shadow gates fail.
4. Enforce at least 95% stored-fact recall, zero unsupported pricing/booking claims, and explicit stale/tool/handoff/routing safeguards; wire the free command into backend CI.
5. Add one structured observer that HMAC-pseudonymizes source/invocation IDs and emits only source type/ref, freshness/age, token counts, tool name/status, route metadata, and human-correction category/action.
6. Integrate observability into SMS context/model/tool execution, voice context/tool execution, CRM assistant context/tool execution, and AI-memory correction paths; remove raw tool arguments/results from touched logs.
7. Add deterministic cheap/strong SMS routing, default it to shadow mode, and score route/tier/temperature decisions across every SMS golden scenario.
8. Document exact local/CI commands, observation contracts, artifact paths/schema, thresholds, and staged shadow-rollout criteria; update the focused compliance addendum.
9. Run the targeted deterministic suite and harness command, inspect artifacts, then run focused lint/type checks for every touched backend file.
