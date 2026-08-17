# SMS, voice, and CRM context accuracy harness

This harness is **local and free**: it never calls OpenAI, Telnyx, a voice provider, or a database. It scores body-free observation labels against 48 synthetic/redacted golden scenarios.

The reference fixture proves the scorer, gates, corpus, and SMS router are deterministic. It is **not evidence that a live model achieved the reference scores**. To evaluate a model or shadow run, supply a reviewed observation manifest with `--observations`.

## Exact commands

From the repository root, run the CI gate and write both artifacts:

```bash
make ci.context-evals
```

The equivalent direct command is:

```bash
cd backend && uv run python -m tests.evals.context_accuracy \
  --gate ci \
  --output-dir .eval-artifacts/context_accuracy
```

Run only the deterministic harness tests:

```bash
cd backend && uv run pytest tests/evals/context_accuracy -q
```

Evaluate body-free labels from a candidate model/shadow review:

```bash
cd backend && uv run python -m tests.evals.context_accuracy \
  --observations /absolute/path/to/redacted-observations.jsonl \
  --gate shadow \
  --output-dir .eval-artifacts/context_accuracy-shadow
```

The command exits `0` when every gate check passes and `1` when any check fails. Invalid, incomplete, duplicate, or unknown scenario IDs fail closed before artifacts are treated as a result.

## Artifact output

The default command writes:

- `backend/.eval-artifacts/context_accuracy/report.json` — machine-readable metrics, counts, failures, routing distribution, thresholds, and each gate result.
- `backend/.eval-artifacts/context_accuracy/report.md` — the same result for humans.

Artifacts contain scenario IDs and synthetic label IDs only. They contain no prompt/response body, phone, email, address, contact name, tool arguments/results, or raw production record ID. `.eval-artifacts/` is gitignored.

Top-level JSON keys are:

```text
schema_version
candidate
corpus
metrics
routing
failures
gate
```

There is deliberately **no overall score**.

## Golden corpus

`golden_scenarios.json` contains exactly 48 scenarios:

- 16 SMS, 16 voice, and 16 CRM assistant scenarios.
- Six scenarios for each failure class: stored-fact recall, cross-channel continuity, stale/conflicting state, pricing/availability grounding, quote/appointment status, tool selection, opt-out, and human handoff.
- Every turn uses explicit placeholders such as `[CONTACT_A]`, `[PRICE_A]`, and `[APPOINTMENT_A]`; schema validation rejects phone/email-shaped values.
- Context and expected behavior use synthetic IDs (`src:*`, `fact:*`, `claim:*`, and `tool:action`) so scoring never needs a message body.

## Observation manifest contract

Use one JSON object per line. Extra fields are rejected, specifically preventing callers from adding message bodies or raw PII:

```json
{"scenario_id":"pricing-sms-01","recalled_fact_ids":[],"claims":[{"claim_id":"claim:pricing:service-a","domain":"pricing"}],"relied_on_source_ids":["src:price:current-a"],"tool_actions":["lookup_pricing:service-a"],"handoff":false,"human_correction":false}
```

Fields:

- `recalled_fact_ids` — stored facts actually used correctly.
- `claims` — normalized claim IDs and domain only; no claim text/value.
- `relied_on_source_ids` — sources treated as current; do not include a stale source merely cited as historical.
- `tool_actions` — normalized `tool_name:action_id`; never arguments.
- `handoff` — whether the model selected the human-handoff path.
- `human_correction` — whether an operator had to correct this output; no correction text.

A model adapter may inspect a response in memory to create these labels, but it must discard the body before writing the manifest. Human review can produce the same IDs from a private review surface. Do not copy production messages into this directory or its artifacts.

## Separate metric definitions

1. **Stored-fact recall** — expected fact IDs recalled / total expected fact IDs.
2. **Unsupported-claim rate** — claims absent from the scenario's supported claim IDs / all emitted claims. Unsupported counts are also split by domain.
3. **Stale-state error rate** — stale/conflicting scenarios where a stale source was treated as current / scenarios containing a stale source.
4. **Tool/action correctness** — scenarios with every required action, no unallowed action, and no forbidden action / all scenarios.
5. **Handoff correctness** — exact required/not-required decisions / all scenarios; required-handoff recall is reported separately.
6. **SMS routing correctness** — route tier, configured model role, and maximum temperature match / SMS scenarios.

These metrics never collapse into an average, weighted score, or LLM-judge opinion.

## CI gate

`--gate ci` requires every item below:

- Stored-fact recall **>= 95%**.
- Unsupported pricing, availability, booking, quote, or appointment claims: **0**.
- Unsupported claims in any domain: **0**.
- Stale-state errors: **0**.
- Tool/action correctness **>= 95%**.
- Handoff correctness **100%**.
- SMS routing correctness **100%**, with at least one cheap and one strong route and every high-risk SMS scenario on the strong tier.

`make ci.backend` depends on `make ci.context-evals`, so this zero-cost gate runs in normal backend CI.

## Shadow-rollout gate

`OPENAI_SMS_ROUTING_MODE=shadow` is the default. It records the recommended tier/model/temperature but continues using the existing cheap model and agent temperature, so shadow evaluation adds no model spend.

Before setting `OPENAI_SMS_ROUTING_MODE=active`:

1. Run the locked 48-scenario corpus against the candidate configuration on three consecutive revisions; each `--gate shadow` artifact must pass.
2. Review at least 100 metadata-only high-risk SMS shadow decisions over at least seven days. Convert reviewed outcomes to body-free labels; retain no production bodies in eval artifacts.
3. Require stored-fact recall **>= 95%**, **zero unsupported pricing/booking claims**, **zero stale-state errors**, tool/action correctness **>= 98%**, handoff correctness **>= 98%**, and routing correctness **100%** in every reviewed window.
4. Require no regression in categorized `ai_human_correction_observed` events versus the pre-routing baseline. The correction event contains category/action and pseudonymous refs only.
5. Roll out `active` incrementally; return to `shadow` immediately if any zero-tolerance pricing/booking or opt-out/handoff failure appears.

The deterministic router keeps simple turns on `OPENAI_SMS_SIMPLE_MODEL` at `OPENAI_SMS_SIMPLE_TEMPERATURE`. Pricing, booking/availability, mutable status, opt-out, human handoff, cross-channel/conflicting, explicit tool-action, and complex turns recommend the stronger configured `OPENAI_ASSISTANT_MODEL` at `OPENAI_SMS_STRONG_TEMPERATURE`. The existing fail-closed SMS opt-out guard still runs before model generation.

## Privacy-safe runtime observability

`app/services/ai/context_observability.py` emits these structured events:

- `ai_context_observed` — surface, HMAC-pseudonymous invocation/source refs, source type, freshness, observed/record age, per-source token count, total context tokens, model, and temperature.
- `ai_tool_call_observed` — surface, pseudonymous invocation/tool-call refs, tool name, status, and success only.
- `ai_model_route_observed` — shadow/active mode, recommended and selected model metadata, and fixed reason codes only.
- `ai_human_correction_observed` — pseudonymous workspace/contact/operator/correction refs plus correction kind/action only.

Source refs use HMAC-SHA256 with a namespaced key derived from `SECRET_KEY`; the first 16 hex characters are logged. Raw IDs are never emitted by these events. Rotating `SECRET_KEY` intentionally breaks correlation across the rotation boundary.

Freshness is deterministic: record age <=24 hours is `current`, <=30 days is `recent`, older is `stale`, and missing timestamps are `unknown`. Tokenization runs locally with `cl100k_base`; text exists only long enough to count and is never included in the event payload.

This is an engineering control, not legal advice. Privacy notices, processor terms, retention, call-recording consent, and messaging consent still require factual/legal review for the product's actual users and jurisdictions.
