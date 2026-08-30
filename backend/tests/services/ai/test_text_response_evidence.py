"""Deterministic evidence-gate tests for SMS generation."""

import json
import os
import subprocess
import sys
from pathlib import Path

from app.services.ai.booking_confirmation import is_booking_confirmation_turn
from app.services.ai.text_response_generator import (
    _evidence_fallback,
    _failed_required_domain,
    _first_domain_in_canonical_order,
    _safe_without_claim_evidence,
    _tool_choice_for_claims,
    _update_evidence_status,
    required_claim_evidence_domains,
    response_claim_evidence_domains,
    should_require_booking_tools,
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
    assert required_claim_evidence_domains("What slots work Monday?") == {"availability"}
    assert required_claim_evidence_domains("The Monday slot works") == set()
    assert required_claim_evidence_domains("I'll take the first available slot") == set()
    assert required_claim_evidence_domains("Is my quote still pending?") == {"quote"}
    assert required_claim_evidence_domains("Q-101") == {"quote"}
    assert required_claim_evidence_domains("How much is my invoice balance?") == {"invoice"}
    assert required_claim_evidence_domains("INV-204") == {"invoice"}
    assert required_claim_evidence_domains("Is my appointment confirmed?") == {"appointment"}
    assert required_claim_evidence_domains("What time are you coming?") == {"appointment"}
    assert required_claim_evidence_domains("STOP") == set()
    assert required_claim_evidence_domains("Stop texting me about my invoice") == set()
    assert required_claim_evidence_domains("Cancel my appointment") == {"appointment"}


def test_only_a_reply_to_the_canonical_summary_is_booking_confirmation() -> None:
    summary = (
        "Please confirm: 30-minute phone call on Thursday, January 15, 2099 at "
        "10:00 AM America/New_York, invitation to lead@example.com. Is that correct?"
    )
    assert is_booking_confirmation_turn(
        [
            {"role": "assistant", "content": summary},
            {"role": "user", "content": "Sounds good!"},
        ]
    )
    assert not is_booking_confirmation_turn(
        [
            {"role": "assistant", "content": "Would you like an estimate?"},
            {"role": "user", "content": "Sounds good!"},
        ]
    )
    assert not is_booking_confirmation_turn(
        [
            {"role": "assistant", "content": summary},
            {"role": "user", "content": "Yes, but make it video"},
        ]
    )


def test_booking_tools_are_not_forced_for_details_or_generic_agreement() -> None:
    for message in (
        "Monday at 2 works",
        "john@example.com",
        "Sounds good",
        "Yes please",
    ):
        assert should_require_booking_tools(message.casefold()) is False


def test_booking_tools_prepare_a_draft_before_calendar_mutation() -> None:
    tools = get_text_booking_tools("America/New_York")
    prepare_tool = next(tool for tool in tools if tool["function"]["name"] == "prepare_booking")

    assert prepare_tool["function"]["parameters"]["required"] == [
        "date",
        "time",
        "duration_minutes",
        "call_type",
    ]
    book_tool = next(tool for tool in tools if tool["function"]["name"] == "book_appointment")
    assert book_tool["function"]["parameters"]["required"] == ["customer_confirmed"]


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
    confirmation_choice = _tool_choice_for_claims(
        required_domains=frozenset(),
        evidence_status={},
        tools=tools,
        force_booking_tool=False,
        force_booking_confirmation=True,
    )

    assert quote_choice == {
        "type": "function",
        "function": {"name": "lookup_contact_state"},
    }
    assert availability_choice == {
        "type": "function",
        "function": {"name": "check_availability"},
    }
    assert confirmation_choice == {
        "type": "function",
        "function": {"name": "book_appointment"},
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


# A customer message that needs two independent domains proven before we may answer.
_MULTI_DOMAIN_MESSAGE = "How much is it and when can you come out?"

_HASH_SEED_PROBE = """
import json

from app.services.ai.text_response_generator import (
    _evidence_fallback,
    _failed_required_domain,
    _first_domain_in_canonical_order,
    required_claim_evidence_domains,
)

domains = required_claim_evidence_domains({message!r})
assert len(domains) > 1, sorted(domains)
failed = _failed_required_domain(domains, dict.fromkeys(domains, "absent"))
print(
    json.dumps(
        {{
            "round_limit": _first_domain_in_canonical_order(domains),
            "failed": failed,
            "text": _evidence_fallback(failed),
        }}
    )
)
"""


def test_multi_domain_fallback_is_identical_under_every_hash_seed() -> None:
    """The canned fallback must not depend on set iteration order.

    ``required_domains`` is a ``frozenset`` and CPython randomises string hashing
    per process, so picking with ``next(iter(...))`` answers the same customer
    text with a different message depending on which worker replied.
    """
    results = {
        seed: subprocess.run(
            [sys.executable, "-c", _HASH_SEED_PROBE.format(message=_MULTI_DOMAIN_MESSAGE)],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[3],
            env=os.environ | {"PYTHONHASHSEED": str(seed)},
        ).stdout.strip()
        # Seeds 0 and 1 already order {pricing, availability} differently, so a
        # regression to `next(iter(...))` cannot slip through this range.
        for seed in range(6)
    }

    assert len(set(results.values())) == 1, f"fallback varies by hash seed: {results}"


def test_fallback_domain_follows_the_same_priority_as_the_outbound_gate() -> None:
    """All three gates must name one domain, so the reply matches the warning log."""
    domains = required_claim_evidence_domains(_MULTI_DOMAIN_MESSAGE)
    assert domains == {"pricing", "availability"}

    # `_EVIDENCE_TOOL_BY_DOMAIN` ranks pricing ahead of availability, and the
    # outbound-claim gate already picks the missing domain in that order.
    assert _first_domain_in_canonical_order(domains) == "pricing"
    assert _failed_required_domain(domains, dict.fromkeys(domains, "absent")) == "pricing"
    assert _failed_required_domain(domains, {"pricing": "found", "availability": "error"}) == (
        "availability"
    )
    assert _failed_required_domain(domains, dict.fromkeys(domains, "found")) is None
    assert _first_domain_in_canonical_order(frozenset()) is None
