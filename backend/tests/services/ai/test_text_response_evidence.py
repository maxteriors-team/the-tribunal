"""Deterministic evidence-gate tests for SMS generation."""

import json

from app.services.ai.text_response_generator import (
    _evidence_fallback,
    _safe_without_claim_evidence,
    _tool_choice_for_claims,
    _update_evidence_status,
    required_claim_evidence_domains,
    response_claim_evidence_domains,
)
from app.services.ai.voice_tools import (
    get_text_booking_tools,
    get_text_contact_state_tool,
    get_text_search_knowledge_tool,
)


def test_latest_inbound_intent_maps_each_mutable_claim_to_fresh_evidence() -> None:
    assert required_claim_evidence_domains("How much does a house wash cost?") == {"pricing"}
    assert required_claim_evidence_domains("What would a roof wash run?") == {"pricing"}
    assert required_claim_evidence_domains("Are you available Friday?") == {"availability"}
    assert required_claim_evidence_domains("Can you come Friday?") == {"availability"}
    assert required_claim_evidence_domains("Is my quote still pending?") == {"quote"}
    assert required_claim_evidence_domains("Q-101") == {"quote"}
    assert required_claim_evidence_domains("How much is my invoice balance?") == {"invoice"}
    assert required_claim_evidence_domains("INV-204") == {"invoice"}
    assert required_claim_evidence_domains("Is my appointment confirmed?") == {"appointment"}
    assert required_claim_evidence_domains("What time are you coming?") == {"appointment"}
    assert required_claim_evidence_domains("STOP") == set()
    assert required_claim_evidence_domains("Stop texting me about my invoice") == set()
    assert required_claim_evidence_domains("Cancel my appointment") == {"appointment"}


def test_quote_and_invoice_amounts_do_not_require_unrelated_generic_pricing_tool() -> None:
    assert required_claim_evidence_domains("How much is my quote?") == {"quote"}
    assert required_claim_evidence_domains("What is the amount due on my invoice?") == {"invoice"}
    assert response_claim_evidence_domains("Your accepted quote total is $450.") == {"quote"}
    assert response_claim_evidence_domains("A house wash starts at $199.") == {"pricing"}


def test_claim_intent_forces_the_matching_fresh_tool() -> None:
    tools = [
        get_text_contact_state_tool(),
        *get_text_booking_tools("America/New_York"),
        get_text_search_knowledge_tool(),
    ]

    quote_choice = _tool_choice_for_claims(
        required_domains=frozenset({"quote"}),
        evidence_status={},
        tools=tools,
        force_booking_tool=False,
    )
    availability_choice = _tool_choice_for_claims(
        required_domains=frozenset({"availability"}),
        evidence_status={},
        tools=tools,
        force_booking_tool=False,
    )

    assert quote_choice == {
        "type": "function",
        "function": {"name": "lookup_contact_state"},
    }
    assert availability_choice == {
        "type": "function",
        "function": {"name": "check_availability"},
    }


def test_only_this_turns_tool_result_satisfies_claim_evidence() -> None:
    evidence_status = {}
    _update_evidence_status(
        evidence_status,
        [
            {
                "content": json.dumps(
                    {
                        "evidence_domains": ["quote"],
                        "evidence_status": "found",
                    }
                )
            }
        ],
    )

    assert evidence_status == {"quote": "found"}
    assert _evidence_fallback("quote", reason="conflict") == (
        "Which quote number or service are you asking about?"
    )
    assert _safe_without_claim_evidence("Which quote number are you asking about?") is True
    assert _safe_without_claim_evidence("Your quote is approved at $450. Does that work?") is False
