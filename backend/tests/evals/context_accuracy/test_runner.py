"""Artifact and body-free observation-contract tests."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.evals.context_accuracy.runner import load_observations, run_harness
from tests.evals.context_accuracy.scorer import HarnessInputError


def test_artifacts_are_deterministic_and_contain_separate_metrics(tmp_path: Path) -> None:
    first_report, first_json, first_markdown = run_harness(output_dir=tmp_path / "first")
    second_report, second_json, second_markdown = run_harness(output_dir=tmp_path / "second")

    assert first_report == second_report
    assert first_json.read_text() == second_json.read_text()
    assert first_markdown.read_text() == second_markdown.read_text()
    assert first_report["gate"]["passed"] is True
    assert "overall_score" not in first_json.read_text()
    assert "Stored-fact recall" in first_markdown.read_text()
    assert "Unsupported-claim rate" in first_markdown.read_text()


def test_observation_manifest_rejects_message_bodies_and_raw_pii_fields(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.jsonl"
    path.write_text(
        json.dumps(
            {
                "scenario_id": "recall-sms-01",
                "recalled_fact_ids": [],
                "claims": [],
                "relied_on_source_ids": [],
                "tool_actions": [],
                "handoff": False,
                "message_body": "raw body must never enter the artifact",
            }
        )
        + "\n"
    )

    with pytest.raises(ValidationError, match="message_body"):
        load_observations(path)


def test_incomplete_observation_manifest_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "incomplete.jsonl"
    path.write_text(
        json.dumps(
            {
                "scenario_id": "recall-sms-01",
                "recalled_fact_ids": ["fact:preference:text"],
                "claims": [],
                "relied_on_source_ids": ["src:contact:preference-a"],
                "tool_actions": [],
                "handoff": False,
            }
        )
        + "\n"
    )

    with pytest.raises(HarnessInputError, match="coverage mismatch"):
        run_harness(observations_path=path, output_dir=tmp_path / "out")
