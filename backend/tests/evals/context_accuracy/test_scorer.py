"""Independent metric and gate regression tests."""

from tests.evals.context_accuracy.runner import (
    build_reference_observations,
    load_scenarios,
)
from tests.evals.context_accuracy.schema import CandidateClaim, CandidateObservation
from tests.evals.context_accuracy.scorer import apply_gate, score_scenarios


def _replace(
    observations: list[CandidateObservation],
    scenario_id: str,
    **updates: object,
) -> list[CandidateObservation]:
    return [
        observation.model_copy(update=updates)
        if observation.scenario_id == scenario_id
        else observation
        for observation in observations
    ]


def test_reference_fixture_passes_each_metric_without_overall_score() -> None:
    scenarios = load_scenarios()
    scored = score_scenarios(scenarios, build_reference_observations(scenarios))
    metrics = scored.report["metrics"]

    assert "overall" not in scored.report
    assert "overall_score" not in metrics
    assert metrics["stored_fact_recall"]["value"] == 1.0
    assert metrics["unsupported_claim_rate"]["value"] == 0.0
    assert metrics["stale_state_error_rate"]["value"] == 0.0
    assert metrics["tool_action_correctness"]["value"] == 1.0
    assert metrics["handoff_correctness"]["value"] == 1.0
    assert metrics["sms_routing_correctness"]["value"] == 1.0
    assert apply_gate(scored, "ci")["passed"] is True
    assert apply_gate(scored, "shadow")["passed"] is True


def test_recall_gate_fails_below_ninety_five_percent_only() -> None:
    scenarios = load_scenarios()
    observations = build_reference_observations(scenarios)
    observations = _replace(observations, "recall-sms-01", recalled_fact_ids=())
    observations = _replace(observations, "recall-sms-02", recalled_fact_ids=())

    scored = score_scenarios(scenarios, observations)

    assert scored.report["metrics"]["stored_fact_recall"]["value"] < 0.95
    assert scored.report["metrics"]["unsupported_claim_rate"]["value"] == 0.0
    assert apply_gate(scored, "ci")["checks"]["stored_fact_recall_at_least_95_percent"] is False


def test_unsupported_pricing_claim_has_its_own_zero_tolerance_gate() -> None:
    scenarios = load_scenarios()
    observations = build_reference_observations(scenarios)
    observations = _replace(
        observations,
        "recall-sms-01",
        claims=(CandidateClaim(claim_id="claim:pricing:invented", domain="pricing"),),
    )

    scored = score_scenarios(scenarios, observations)
    gate = apply_gate(scored, "ci")

    assert scored.report["metrics"]["stored_fact_recall"]["value"] == 1.0
    assert scored.report["metrics"]["unsupported_pricing_booking_claim_count"] == 1
    assert gate["checks"]["zero_unsupported_pricing_booking_claims"] is False


def test_stale_state_tool_and_handoff_failures_are_scored_separately() -> None:
    scenarios = load_scenarios()
    observations = build_reference_observations(scenarios)
    observations = _replace(
        observations,
        "stale-sms-01",
        relied_on_source_ids=("src:memory:old-appointment-a",),
    )
    observations = _replace(
        observations,
        "tools-sms-01",
        tool_actions=("update_contact:overwrite",),
    )
    observations = _replace(observations, "handoff-sms-01", handoff=False)

    scored = score_scenarios(scenarios, observations)
    metrics = scored.report["metrics"]

    assert metrics["stored_fact_recall"]["value"] == 1.0
    assert metrics["unsupported_claim_rate"]["value"] == 0.0
    assert metrics["stale_state_error_rate"]["numerator"] == 1
    assert metrics["tool_action_correctness"]["numerator"] == 47
    assert metrics["handoff_correctness"]["numerator"] == 47
