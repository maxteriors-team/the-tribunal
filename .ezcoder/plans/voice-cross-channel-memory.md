# Voice cross-channel CRM context

## Objective

Integrate the existing `ContactContextSnapshot` and durable `ContactAIMemory` into every production voice/realtime prompt without allowing historical summaries, notes, or prior messages to override current CRM records. Preserve campaign/offer targeting, bound prompt bytes and enrichment latency, and enforce workspace isolation.

## Existing constraints discovered

- `CallContextLoader` already loads a snapshot and durable memory, but renders large independent strings, performs optional queries inline, and fetches contact/campaign/offer rows without every workspace predicate.
- OpenAI Realtime, Grok Realtime, and the ElevenLabs/Grok hybrid each rebuild and update prompts/tools separately.
- `lookup_caller_record` provides fresh typed CRM evidence but is currently opt-in, so a prompt cannot safely require it unless the session bridge force-exposes it for a known caller.
- Legacy `CallerMemory` records are generated voice summaries. They are useful continuity hints but can become stale and must remain lower-authority than live CRM rows.
- The working tree already contains a broader, uncommitted contact-memory implementation. Changes will extend—not replace—those files.

## Steps

1. **Bounded voice context renderer**
   - Add `backend/app/services/ai/voice_prompt_builder.py` as the canonical voice-specific wrapper around the existing prompt builder.
   - Render a compact, provenance-labelled snapshot that always reserves space for contact/qualification, campaign attribution, current opportunity, quote/invoice, appointment, and selected recent SMS/human interactions.
   - Add freshness labels and an explicit authority/evidence gate: fresh tool result → current snapshot → durable memory → legacy summary/notes/history.
   - Treat all CRM/free-text content as quoted data, require a live CRM tool before volatile claims, and direct one focused clarification or human handoff for absent/conflicting evidence.
   - Cap each historical section and the complete call-context section without truncating the base agent prompt or dropping safety/tool instructions.

2. **Workspace-safe, latency-bounded call loading**
   - Refactor `call_context.py` so essential call/workspace/agent/campaign/offer context loads first with workspace predicates.
   - Load optional snapshot/durable/legacy memory after essential context under a single short timeout and fail soft, preserving campaign/offer context even when enrichment is slow.
   - Skip enrichment entirely for unknown contacts and expose only non-sensitive status/IDs in logs.

3. **Historical memory safety and cross-channel provenance**
   - Update `caller_memory_service.py` to exclude stale legacy summaries, cap per-memory text, and emit source ID, observed time, and freshness.
   - Add message authorship (`contact`, `human`, `ai`, `unknown`) to snapshot timeline records so recent human/SMS continuity is explicit.
   - Use durable memory expiry plus voice-specific age limits for old generated summaries; never use memory as proof of quote, invoice, appointment, opportunity, or qualification state.

4. **Realtime session bridges and CRM tool availability**
   - Make `VoiceAgentBase` use the voice-specific builder.
   - Update OpenAI, Grok, and ElevenLabs/Grok session updates to force-expose the read-only, caller-bound `lookup_caller_record` whenever a known caller receives volatile CRM context, while preserving configured booking/search/transfer tools.
   - Ensure rescheduling instructions require fresh appointment lookup and successful current-turn availability/booking/cancellation tool results before claiming a move.

5. **Focused proof**
   - Add unit tests for returning callers, SMS-to-voice/human continuity, rescheduling evidence rules, accepted quote overriding stale pending memory, stale summary omission, missing contacts, prompt/latency bounds, and cross-workspace isolation.
   - Run Ruff/type checks on changed modules plus the focused pytest files; fix all failures.
   - Add a short focused `COMPLIANCE.md` addendum documenting CODE/test evidence for tenant isolation, prompt-injection hierarchy, minimization, and bounded context. This is engineering guidance, not legal advice.
