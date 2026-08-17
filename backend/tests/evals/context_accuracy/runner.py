"""CLI runner and deterministic artifact rendering for context accuracy."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from tests.evals.context_accuracy.schema import (
    CandidateClaim,
    CandidateObservation,
    GoldenScenario,
)
from tests.evals.context_accuracy.scorer import (
    GateProfile,
    HarnessInputError,
    apply_gate,
    score_scenarios,
)

_MODULE_DIR = Path(__file__).resolve().parent
_DEFAULT_CORPUS_PATH = _MODULE_DIR / "golden_scenarios.json"
_DEFAULT_OUTPUT_DIR = Path(".eval-artifacts/context_accuracy")
_SCENARIO_ADAPTER = TypeAdapter(list[GoldenScenario])
_OBSERVATION_ADAPTER = TypeAdapter(list[CandidateObservation])


def load_scenarios(path: Path = _DEFAULT_CORPUS_PATH) -> list[GoldenScenario]:
    return _SCENARIO_ADAPTER.validate_json(path.read_text())


def load_observations(path: Path) -> list[CandidateObservation]:
    """Load JSON array or JSONL body-free candidate labels."""

    raw = path.read_text().strip()
    if not raw:
        raise HarnessInputError(f"observation file is empty: {path}")
    if raw.startswith("["):
        return _OBSERVATION_ADAPTER.validate_json(raw)
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    return _OBSERVATION_ADAPTER.validate_python(rows)


def _claim_domain(claim_id: str) -> str:
    for domain in ("pricing", "availability", "booking", "quote", "appointment", "contact"):
        if f":{domain}:" in claim_id:
            return domain
    return "other"


def build_reference_observations(
    scenarios: Sequence[GoldenScenario],
) -> list[CandidateObservation]:
    """Build a known-good mechanics fixture; this is not a model-quality result."""

    observations: list[CandidateObservation] = []
    for scenario in scenarios:
        expected_facts = set(scenario.expected.fact_ids)
        expected_claims = set(scenario.expected.supported_claim_ids)
        relied_on_sources = tuple(
            source.source_id
            for source in scenario.context_sources
            if source.freshness == "fresh"
            and (
                expected_facts.intersection(source.fact_ids)
                or expected_claims.intersection(source.claim_ids)
            )
        )
        observations.append(
            CandidateObservation(
                scenario_id=scenario.scenario_id,
                recalled_fact_ids=scenario.expected.fact_ids,
                claims=tuple(
                    CandidateClaim(claim_id=claim_id, domain=_claim_domain(claim_id))
                    for claim_id in scenario.expected.supported_claim_ids
                ),
                relied_on_source_ids=relied_on_sources,
                tool_actions=scenario.expected.required_actions,
                handoff=scenario.expected.handoff,
                human_correction=False,
            )
        )
    return observations


def render_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    gate = report["gate"]

    def percent(metric_name: str) -> str:
        metric = metrics[metric_name]
        return f"{metric['value'] * 100:.2f}% ({metric['numerator']}/{metric['denominator']})"

    check_rows = "\n".join(
        f"| `{name}` | {'PASS' if passed else 'FAIL'} |" for name, passed in gate["checks"].items()
    )
    return "\n".join(
        [
            "# Context accuracy evaluation",
            "",
            f"**Gate:** `{gate['profile']}` — **{'PASS' if gate['passed'] else 'FAIL'}**",
            "",
            "> Metrics are intentionally separate. There is no aggregate or subjective score.",
            "",
            "## Corpus",
            "",
            f"- Scenarios: **{report['corpus']['scenario_count']}**",
            f"- Channels: `{json.dumps(report['corpus']['channel_counts'], sort_keys=True)}`",
            f"- Redacted/synthetic: **{str(report['corpus']['redacted']).lower()}**",
            "",
            "## Metrics",
            "",
            f"- Stored-fact recall: **{percent('stored_fact_recall')}**",
            f"- Unsupported-claim rate: **{percent('unsupported_claim_rate')}**",
            "- Unsupported pricing/booking claims: "
            f"**{metrics['unsupported_pricing_booking_claim_count']}**",
            f"- Stale-state error rate: **{percent('stale_state_error_rate')}**",
            f"- Tool/action correctness: **{percent('tool_action_correctness')}**",
            f"- Handoff correctness: **{percent('handoff_correctness')}**",
            f"- Required-handoff correctness: **{percent('required_handoff_correctness')}**",
            f"- SMS routing correctness: **{percent('sms_routing_correctness')}**",
            f"- Human corrections: **{metrics['human_correction_count']}**",
            "",
            "## SMS route distribution",
            "",
            f"- Cheap: **{report['routing']['cheap_count']}**",
            f"- Strong: **{report['routing']['strong_count']}**",
            "",
            "## Gate checks",
            "",
            "| Check | Result |",
            "|---|---|",
            check_rows,
            "",
            "## Failure scenario IDs",
            "",
            "```json",
            json.dumps(report["failures"], indent=2, sort_keys=True),
            "```",
            "",
        ]
    )


def run_harness(
    *,
    corpus_path: Path = _DEFAULT_CORPUS_PATH,
    observations_path: Path | None = None,
    output_dir: Path = _DEFAULT_OUTPUT_DIR,
    gate_profile: GateProfile = "ci",
) -> tuple[dict[str, Any], Path, Path]:
    scenarios = load_scenarios(corpus_path)
    observations = (
        load_observations(observations_path)
        if observations_path is not None
        else build_reference_observations(scenarios)
    )
    scored = score_scenarios(scenarios, observations)
    report = {
        **scored.report,
        "candidate": {
            "kind": "observation_manifest" if observations_path else "reference_mechanics_fixture",
            "path": str(observations_path) if observations_path else None,
        },
        "gate": apply_gate(scored, gate_profile),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    markdown_path = output_dir / "report.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    markdown_path.write_text(render_markdown(report))
    return report, json_path, markdown_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the local/free SMS, voice, and CRM context accuracy harness."
    )
    parser.add_argument("--corpus", type=Path, default=_DEFAULT_CORPUS_PATH)
    parser.add_argument(
        "--observations",
        type=Path,
        help="JSON/JSONL body-free candidate labels; omit for the mechanics fixture.",
    )
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIR)
    parser.add_argument("--gate", choices=("ci", "shadow"), default="ci")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report, json_path, markdown_path = run_harness(
        corpus_path=args.corpus,
        observations_path=args.observations,
        output_dir=args.output_dir,
        gate_profile=args.gate,
    )
    print(f"context accuracy gate: {'PASS' if report['gate']['passed'] else 'FAIL'}")
    print(f"json artifact: {json_path}")
    print(f"markdown artifact: {markdown_path}")
    return 0 if report["gate"]["passed"] else 1
