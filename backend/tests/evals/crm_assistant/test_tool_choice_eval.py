"""Tool-choice accuracy eval for the CRM assistant.

Costs money and is non-deterministic, so it carries ``@pytest.mark.eval`` and
is excluded from the default pytest run (see ``addopts`` in pyproject.toml).

Run it::

    cd backend
    uv run pytest tests/evals/crm_assistant -m eval -s

Writes a markdown + JSON report to ``.ezcoder/eyes/out/`` when
``CRM_EVAL_REPORT_DIR`` is unset.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.services.ai.crm_assistant._tools import get_crm_tools
from app.services.ai.openai_credentials import create_openai_client, is_openai_configured
from tests.evals.crm_assistant.golden_set import GOLDEN_SET, GoldenCase, golden_set_stats
from tests.evals.crm_assistant.harness import (
    CRMAssistantEvalHarness,
    EvalConfig,
    score_case,
)

_DEFAULT_REPORT_DIR = Path(__file__).resolve().parents[4] / ".ezcoder" / "eyes" / "out"


def _report_dir() -> Path:
    return Path(os.environ.get("CRM_EVAL_REPORT_DIR", _DEFAULT_REPORT_DIR))


class TestGoldenSetIntegrity:
    """Cheap structural checks — these run in normal CI."""

    def test_golden_set_is_large_enough(self) -> None:
        assert golden_set_stats().total >= 40

    def test_case_ids_are_unique(self) -> None:
        ids = [case.id for case in GOLDEN_SET]
        assert len(ids) == len(set(ids))

    def test_every_case_declares_an_outcome(self) -> None:
        for case in GOLDEN_SET:
            assert case.expected_tools or case.expect_no_tool

    def test_expected_and_forbidden_tools_never_overlap(self) -> None:
        for case in GOLDEN_SET:
            overlap = set(case.expected_tools) & set(case.forbidden_tools)
            assert not overlap, f"{case.id} lists {overlap} as both expected and forbidden"

    def test_forbidden_tools_are_known_tool_names(self) -> None:
        """Catch typos without requiring the tool to exist yet.

        Planned-but-unbuilt tools are legitimately forbidden elsewhere in the
        set (a how-to question must never *create* a campaign), so the known
        vocabulary is registered tools plus every tool the set expects.
        """
        known = {tool["function"]["name"] for tool in get_crm_tools()}
        known.update(name for case in GOLDEN_SET for name in case.expected_tools)
        for case in GOLDEN_SET:
            for name in case.forbidden_tools:
                assert name in known, f"{case.id} forbids unknown tool {name}"


class TestScoring:
    """Scoring rules, verified without touching the network."""

    def test_expected_tool_passes(self) -> None:
        case = GoldenCase(id="x", category="c", utterance="u", expected_tools=("a",))
        assert score_case(case, ("a",)) == (True, None)

    def test_wrong_tool_fails(self) -> None:
        case = GoldenCase(id="x", category="c", utterance="u", expected_tools=("a",))
        passed, reason = score_case(case, ("b",))
        assert not passed
        assert reason == "no expected tool was called"

    def test_forbidden_tool_fails_even_with_expected_tool(self) -> None:
        case = GoldenCase(
            id="x",
            category="c",
            utterance="u",
            expected_tools=("a",),
            forbidden_tools=("danger",),
        )
        passed, reason = score_case(case, ("a", "danger"))
        assert not passed
        assert reason is not None
        assert "forbidden" in reason

    def test_no_tool_call_fails_when_a_tool_was_expected(self) -> None:
        case = GoldenCase(id="x", category="c", utterance="u", expected_tools=("a",))
        assert score_case(case, ()) == (False, "called no tool")

    def test_expect_no_tool_passes_on_silence(self) -> None:
        case = GoldenCase(id="x", category="c", utterance="u", expect_no_tool=True)
        assert score_case(case, ()) == (True, None)


@pytest.mark.eval
class TestToolChoiceAccuracy:
    """The real thing: live model, real schemas, stubbed handlers."""

    async def test_tool_choice_accuracy(self) -> None:
        if not is_openai_configured():
            pytest.skip("OpenAI credentials are not configured")

        harness = CRMAssistantEvalHarness(create_openai_client(), EvalConfig())
        missing = harness.missing_expected_tools()
        report = await harness.run()

        print()  # noqa: T201 — report is the point of running this
        print(report.to_markdown())  # noqa: T201
        if missing:
            print(f"\nCases whose expected tools are unregistered: {sorted(missing)}")  # noqa: T201

        directory = _report_dir()
        directory.mkdir(parents=True, exist_ok=True)
        stamp = report.started_at.strftime("%Y%m%dT%H%M%SZ")
        (directory / f"crm-eval-{stamp}.md").write_text(report.to_markdown())
        (directory / f"crm-eval-{stamp}.json").write_text(report.to_json())

        assert report.total == len(GOLDEN_SET)
