"""Deterministic, multi-metric scoring and rollout gates."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.services.ai.sms_model_router import route_sms_turn
from tests.evals.context_accuracy.schema import CandidateObservation, GoldenScenario

GateProfile = Literal["ci", "shadow"]
_HIGH_RISK_CLAIM_DOMAINS = frozenset({"pricing", "availability", "booking", "quote", "appointment"})


class HarnessInputError(ValueError):
    """Raised when corpus and candidate observations cannot be compared safely."""


@dataclass(frozen=True, slots=True)
class RatioMetric:
    numerator: int
    denominator: int

    @property
    def value(self) -> float:
        return self.numerator / self.denominator if self.denominator else 0.0

    def as_dict(self) -> dict[str, int | float]:
        return {
            "numerator": self.numerator,
            "denominator": self.denominator,
            "value": round(self.value, 6),
        }


@dataclass(frozen=True, slots=True)
class ScoredHarness:
    report: dict[str, Any]


def score_scenarios(  # noqa: PLR0912, PLR0915
    scenarios: Sequence[GoldenScenario],
    observations: Sequence[CandidateObservation],
) -> ScoredHarness:
    """Score each requested behavior independently; no aggregate is produced."""

    scenario_by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    observation_by_id = {observation.scenario_id: observation for observation in observations}
    if len(scenario_by_id) != len(scenarios):
        raise HarnessInputError("duplicate scenario IDs")
    if len(observation_by_id) != len(observations):
        raise HarnessInputError("duplicate observation IDs")

    missing_ids = sorted(set(scenario_by_id) - set(observation_by_id))
    unknown_ids = sorted(set(observation_by_id) - set(scenario_by_id))
    if missing_ids or unknown_ids:
        raise HarnessInputError(
            f"observation coverage mismatch: missing={missing_ids}, unknown={unknown_ids}"
        )

    expected_fact_total = 0
    recalled_fact_total = 0
    claim_total = 0
    unsupported_claim_total = 0
    unsupported_by_domain: Counter[str] = Counter()
    stale_scenario_total = 0
    stale_error_total = 0
    correct_tool_scenarios = 0
    correct_handoff_scenarios = 0
    handoff_required_total = 0
    handoff_required_correct = 0
    routing_total = 0
    routing_correct = 0
    cheap_routes = 0
    strong_routes = 0
    human_correction_count = 0

    missing_fact_scenarios: list[str] = []
    unsupported_claim_scenarios: list[str] = []
    stale_error_scenarios: list[str] = []
    incorrect_tool_scenarios: list[str] = []
    incorrect_handoff_scenarios: list[str] = []
    incorrect_routing_scenarios: list[str] = []

    for scenario in scenarios:
        observation = observation_by_id[scenario.scenario_id]
        expected_fact_ids = set(scenario.expected.fact_ids)
        recalled_fact_ids = set(observation.recalled_fact_ids)
        expected_fact_total += len(expected_fact_ids)
        recalled_fact_total += len(expected_fact_ids & recalled_fact_ids)
        if not expected_fact_ids.issubset(recalled_fact_ids):
            missing_fact_scenarios.append(scenario.scenario_id)

        supported_claim_ids = set(scenario.expected.supported_claim_ids)
        scenario_has_unsupported_claim = False
        for claim in observation.claims:
            claim_total += 1
            if claim.claim_id in supported_claim_ids:
                continue
            unsupported_claim_total += 1
            unsupported_by_domain[claim.domain] += 1
            scenario_has_unsupported_claim = True
        if scenario_has_unsupported_claim:
            unsupported_claim_scenarios.append(scenario.scenario_id)

        stale_source_ids = set(scenario.expected.stale_source_ids)
        if stale_source_ids:
            stale_scenario_total += 1
            if stale_source_ids.intersection(observation.relied_on_source_ids):
                stale_error_total += 1
                stale_error_scenarios.append(scenario.scenario_id)

        observed_actions = set(observation.tool_actions)
        required_actions = set(scenario.expected.required_actions)
        allowed_actions = required_actions | set(scenario.expected.allowed_actions)
        forbidden_actions = set(scenario.expected.forbidden_actions)
        tool_correct = (
            required_actions.issubset(observed_actions)
            and observed_actions.issubset(allowed_actions)
            and not forbidden_actions.intersection(observed_actions)
        )
        if tool_correct:
            correct_tool_scenarios += 1
        else:
            incorrect_tool_scenarios.append(scenario.scenario_id)

        if scenario.expected.handoff:
            handoff_required_total += 1
            if observation.handoff:
                handoff_required_correct += 1
        if observation.handoff == scenario.expected.handoff:
            correct_handoff_scenarios += 1
        else:
            incorrect_handoff_scenarios.append(scenario.scenario_id)

        if observation.human_correction:
            human_correction_count += 1

        if scenario.channel == "sms":
            routing_total += 1
            routing_input = scenario.routing_input
            if routing_input is None:  # guarded by schema; keeps type narrowing explicit
                raise HarnessInputError(f"missing SMS routing input: {scenario.scenario_id}")
            decision = route_sms_turn(
                scenario.redacted_turn,
                simple_model="configured-cheap-model",
                strong_model="configured-strong-model",
                simple_temperature=0.2,
                strong_temperature=0.0,
                has_context_conflict=routing_input.has_context_conflict,
                requires_tool_action=routing_input.requires_tool_action,
            )
            if decision.tier == "cheap":
                cheap_routes += 1
            else:
                strong_routes += 1
            route_correct = (
                decision.tier == scenario.expected.sms_route
                and scenario.expected.max_temperature is not None
                and decision.temperature <= scenario.expected.max_temperature
                and decision.model
                == (
                    "configured-cheap-model"
                    if decision.tier == "cheap"
                    else "configured-strong-model"
                )
            )
            if route_correct:
                routing_correct += 1
            else:
                incorrect_routing_scenarios.append(scenario.scenario_id)

    scenario_total = len(scenarios)
    stored_fact_recall = RatioMetric(recalled_fact_total, expected_fact_total)
    unsupported_claim_rate = RatioMetric(unsupported_claim_total, claim_total)
    stale_state_error_rate = RatioMetric(stale_error_total, stale_scenario_total)
    tool_action_correctness = RatioMetric(correct_tool_scenarios, scenario_total)
    handoff_correctness = RatioMetric(correct_handoff_scenarios, scenario_total)
    required_handoff_correctness = RatioMetric(
        handoff_required_correct,
        handoff_required_total,
    )
    routing_correctness = RatioMetric(routing_correct, routing_total)

    channel_counts = Counter(scenario.channel for scenario in scenarios)
    failure_class_counts = Counter(scenario.failure_class for scenario in scenarios)
    report: dict[str, Any] = {
        "schema_version": 1,
        "corpus": {
            "scenario_count": scenario_total,
            "channel_counts": dict(sorted(channel_counts.items())),
            "failure_class_counts": dict(sorted(failure_class_counts.items())),
            "redacted": True,
        },
        "metrics": {
            "stored_fact_recall": stored_fact_recall.as_dict(),
            "unsupported_claim_rate": unsupported_claim_rate.as_dict(),
            "unsupported_claim_counts_by_domain": dict(sorted(unsupported_by_domain.items())),
            "unsupported_pricing_booking_claim_count": sum(
                count
                for domain, count in unsupported_by_domain.items()
                if domain in _HIGH_RISK_CLAIM_DOMAINS
            ),
            "stale_state_error_rate": stale_state_error_rate.as_dict(),
            "tool_action_correctness": tool_action_correctness.as_dict(),
            "handoff_correctness": handoff_correctness.as_dict(),
            "required_handoff_correctness": required_handoff_correctness.as_dict(),
            "sms_routing_correctness": routing_correctness.as_dict(),
            "human_correction_count": human_correction_count,
        },
        "routing": {
            "cheap_count": cheap_routes,
            "strong_count": strong_routes,
            "total": routing_total,
        },
        "failures": {
            "missing_fact_scenarios": sorted(missing_fact_scenarios),
            "unsupported_claim_scenarios": sorted(unsupported_claim_scenarios),
            "stale_error_scenarios": sorted(stale_error_scenarios),
            "incorrect_tool_scenarios": sorted(incorrect_tool_scenarios),
            "incorrect_handoff_scenarios": sorted(incorrect_handoff_scenarios),
            "incorrect_routing_scenarios": sorted(incorrect_routing_scenarios),
        },
    }
    return ScoredHarness(report=report)


def apply_gate(scored: ScoredHarness, profile: GateProfile) -> dict[str, Any]:
    """Apply named CI/shadow thresholds without constructing an overall score."""

    metrics = scored.report["metrics"]
    tool_threshold = 0.95 if profile == "ci" else 0.98
    handoff_threshold = 1.0 if profile == "ci" else 0.98
    checks = {
        "stored_fact_recall_at_least_95_percent": (metrics["stored_fact_recall"]["value"] >= 0.95),
        "zero_unsupported_pricing_booking_claims": (
            metrics["unsupported_pricing_booking_claim_count"] == 0
        ),
        "zero_unsupported_claims": metrics["unsupported_claim_rate"]["numerator"] == 0,
        "zero_stale_state_errors": metrics["stale_state_error_rate"]["numerator"] == 0,
        "tool_action_correctness_threshold": (
            metrics["tool_action_correctness"]["value"] >= tool_threshold
        ),
        "handoff_correctness_threshold": (
            metrics["handoff_correctness"]["value"] >= handoff_threshold
            and metrics["required_handoff_correctness"]["value"] >= handoff_threshold
        ),
        "sms_routing_correctness_100_percent": (metrics["sms_routing_correctness"]["value"] == 1.0),
        "simple_sms_route_remains_available": scored.report["routing"]["cheap_count"] > 0,
        "high_risk_sms_route_uses_strong_tier": scored.report["routing"]["strong_count"] > 0,
    }
    return {
        "profile": profile,
        "passed": all(checks.values()),
        "thresholds": {
            "stored_fact_recall_minimum": 0.95,
            "unsupported_pricing_booking_claim_maximum": 0,
            "unsupported_claim_maximum": 0,
            "stale_state_error_maximum": 0,
            "tool_action_correctness_minimum": tool_threshold,
            "handoff_correctness_minimum": handoff_threshold,
            "sms_routing_correctness_minimum": 1.0,
        },
        "checks": checks,
    }
