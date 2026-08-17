"""Golden corpus shape, coverage, and redaction invariants."""

from collections import Counter

from tests.evals.context_accuracy.runner import load_scenarios


def test_golden_corpus_has_balanced_requested_coverage() -> None:
    scenarios = load_scenarios()

    assert len(scenarios) == 48
    assert Counter(scenario.channel for scenario in scenarios) == {
        "sms": 16,
        "voice": 16,
        "crm_assistant": 16,
    }
    assert set(Counter(scenario.failure_class for scenario in scenarios).values()) == {6}
    assert {scenario.failure_class for scenario in scenarios} == {
        "stored_fact_recall",
        "cross_channel_continuity",
        "stale_conflicting_state",
        "pricing_availability_grounding",
        "quote_appointment_status",
        "tool_selection",
        "opt_out",
        "human_handoff",
    }


def test_golden_corpus_uses_only_synthetic_redacted_turns() -> None:
    scenarios = load_scenarios()

    assert all(
        "[" in scenario.redacted_turn and "]" in scenario.redacted_turn for scenario in scenarios
    )
    assert all(
        source.source_id.startswith("src:")
        for scenario in scenarios
        for source in scenario.context_sources
    )
    assert all("@" not in scenario.redacted_turn for scenario in scenarios)
