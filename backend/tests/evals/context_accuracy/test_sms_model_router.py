"""SMS cheap/strong tier and temperature policy tests."""

import pytest

from app.services.ai.sms_model_router import route_sms_turn
from tests.evals.context_accuracy.runner import load_scenarios


@pytest.mark.parametrize(
    ("turn", "kwargs", "expected_reason"),
    [
        ("What is the price for [SERVICE_A]?", {}, "pricing_or_quote"),
        ("Is the appointment for [CONTACT_A] confirmed?", {}, "booking_or_availability"),
        ("Please STOP for [CONTACT_A].", {}, "opt_out"),
        ("Get a human for [CONTACT_A].", {}, "human_handoff"),
        ("Use [CONTACT_A].", {"has_context_conflict": True}, "conflicting_state"),
        ("Use [CONTACT_A].", {"requires_tool_action": True}, "tool_action"),
    ],
)
def test_high_risk_or_action_turns_use_strong_model(
    turn: str,
    kwargs: dict[str, bool],
    expected_reason: str,
) -> None:
    decision = route_sms_turn(
        turn,
        simple_model="cheap",
        strong_model="strong",
        simple_temperature=0.2,
        strong_temperature=0.0,
        **kwargs,
    )

    assert decision.tier == "strong"
    assert decision.model == "strong"
    assert decision.temperature == 0.0
    assert expected_reason in decision.reason_codes


def test_simple_turn_stays_on_cheap_model() -> None:
    decision = route_sms_turn(
        "Acknowledge [CONTACT_A]'s service preference.",
        simple_model="cheap",
        strong_model="strong",
        simple_temperature=0.2,
        strong_temperature=0.0,
    )

    assert decision.tier == "cheap"
    assert decision.model == "cheap"
    assert decision.temperature == 0.2
    assert decision.reason_codes == ("simple_turn",)


def test_golden_sms_set_exercises_both_model_tiers() -> None:
    expected_tiers = {
        scenario.expected.sms_route for scenario in load_scenarios() if scenario.channel == "sms"
    }

    assert expected_tiers == {"cheap", "strong"}
