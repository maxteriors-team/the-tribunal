"""Regression tests for customer-facing SMS prompt behavior."""

from app.services.ai.text_prompt_builder import (
    MAX_CONTACT_CONTEXT_CHARS,
    build_booking_instructions,
    build_text_instructions,
)


def test_text_prompt_requires_human_concise_truthful_replies() -> None:
    prompt = build_text_instructions("You help customers book estimates.")

    assert "helpful person texting" in prompt
    assert "one short message" in prompt
    assert "Never repeat a confirmation" in prompt
    assert "appears mistyped, ask a brief clarifying question" in prompt
    assert "tool result in THIS response proves it" in prompt
    assert "genuine STOP/unsubscribe request outranks" in prompt


def test_claim_evidence_gate_names_fresh_tools_and_live_crm_authority() -> None:
    prompt = build_text_instructions("Help the customer.")

    assert "Before stating a price or pricing policy, call search_knowledge" in prompt
    assert "Before stating that a time is available, call check_availability" in prompt
    assert "call lookup_contact_state in THIS response" in prompt
    assert "fresh live-CRM/tool result, current structured snapshot, durable memory" in prompt
    assert "Never merge conflicting values or choose the likely one" in prompt
    assert "Ask exactly one focused question" in prompt


def test_contact_context_bound_preserves_live_fields_over_stale_notes() -> None:
    contact_context = (
        "LIVE_QUOTE_STATUS=approved\n"
        + ("current-field\n" * MAX_CONTACT_CONTEXT_CHARS)
        + "STALE_NOTE_QUOTE_STATUS=pending"
    )

    prompt = build_text_instructions(
        "Help the customer.",
        lead_context=contact_context,
    )

    assert "LIVE_QUOTE_STATUS=approved" in prompt
    assert "STALE_NOTE_QUOTE_STATUS=pending" not in prompt
    assert "[contact context truncated]" in prompt


def test_booking_prompt_prevents_scott_conversation_failures() -> None:
    prompt = build_booking_instructions("America/New_York")

    assert "send exactly ONE concise confirmation" in prompt
    assert "invitation_sent is true" in prompt
    assert "did the invite email not arrive" in prompt
    assert "never claim you changed them" in prompt
    assert "Selecting or proposing a time starts a SEPARATE confirmation turn" in prompt
    assert "exact weekday and calendar date" in prompt
    assert "appointment duration, and invite email" in prompt
    assert "customer_confirmed=true" in prompt
    assert "ambiguous reply is not confirmation" in prompt
