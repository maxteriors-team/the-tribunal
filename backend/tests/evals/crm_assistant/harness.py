"""Tool-choice eval harness for the CRM assistant.

Runs the *real* model against the *real* tool schemas with *stubbed* handlers,
then scores which tool the model picked against ``golden_set.GOLDEN_SET``.

Why stubbed handlers: the thing under test is tool selection, not SQL. Stubs
keep the eval hermetic (no DB, no workspace fixtures, no Telnyx) and make the
model's reply plausible enough that multi-step chains still unfold.

Pattern follows ``app/services/ai/testing/ivr_test_harness.py``: a config
dataclass, an async runner with bounded concurrency, and a report object that
renders markdown.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from openai import AsyncOpenAI

from app.services.ai.crm_assistant import _processor
from app.services.ai.crm_assistant._tools import get_crm_tools
from tests.evals.crm_assistant.golden_set import GOLDEN_SET, GoldenCase
from tests.evals.crm_assistant.stub_handlers import stub_tool_result


@dataclass(frozen=True, slots=True)
class EvalConfig:
    """Knobs for one eval run."""

    model: str = _processor.MODEL
    temperature: float = _processor.TEMPERATURE
    max_completion_tokens: int = _processor.MAX_COMPLETION_TOKENS
    max_tool_turns: int = 3
    timeout_seconds: float = 90.0
    concurrency: int = 6
    context_message: str | None = None


@dataclass(frozen=True, slots=True)
class EvalCaseResult:
    """Outcome of scoring one golden case."""

    case: GoldenCase
    called_tools: tuple[str, ...]
    passed: bool
    failure_reason: str | None
    duration_seconds: float
    reply_text: str = ""

    @property
    def first_tool(self) -> str | None:
        return self.called_tools[0] if self.called_tools else None


@dataclass(frozen=True, slots=True)
class CategoryScore:
    """Aggregate accuracy for one golden-set category."""

    category: str
    passed: int
    total: int

    @property
    def accuracy(self) -> float:
        return self.passed / self.total if self.total else 0.0


@dataclass(slots=True)
class EvalReport:
    """Aggregated results of a full eval run."""

    model: str
    results: list[EvalCaseResult] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for result in self.results if result.passed)

    @property
    def accuracy(self) -> float:
        return self.passed / self.total if self.total else 0.0

    def by_category(self) -> list[CategoryScore]:
        buckets: dict[str, list[EvalCaseResult]] = {}
        for result in self.results:
            buckets.setdefault(result.case.category, []).append(result)
        return [
            CategoryScore(
                category=category,
                passed=sum(1 for item in items if item.passed),
                total=len(items),
            )
            for category, items in sorted(buckets.items())
        ]

    def failures(self) -> list[EvalCaseResult]:
        return [result for result in self.results if not result.passed]

    def to_markdown(self) -> str:
        """Render a per-category breakdown plus every failure."""

        lines = [
            "# CRM assistant tool-choice eval",
            "",
            f"- Model: `{self.model}`",
            f"- Started: {self.started_at.isoformat(timespec='seconds')}",
            f"- **Accuracy: {self.accuracy:.1%} ({self.passed}/{self.total})**",
            "",
            "## Per category",
            "",
            "| Category | Accuracy | Passed |",
            "| --- | --- | --- |",
        ]
        for score in self.by_category():
            lines.append(
                f"| {score.category} | {score.accuracy:.0%} | {score.passed}/{score.total} |"
            )

        failures = self.failures()
        lines.extend(["", f"## Failures ({len(failures)})", ""])
        if not failures:
            lines.append("None.")
        for failure in failures:
            called = ", ".join(failure.called_tools) or "(no tool called)"
            expected = ", ".join(failure.case.expected_tools) or "(no tool)"
            lines.append(
                f"- `{failure.case.id}` [{failure.case.category}] — "
                f"expected {expected}; got {called}. {failure.failure_reason or ''}".rstrip()
            )
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(
            {
                "model": self.model,
                "started_at": self.started_at.isoformat(),
                "completed_at": self.completed_at.isoformat() if self.completed_at else None,
                "accuracy": round(self.accuracy, 4),
                "passed": self.passed,
                "total": self.total,
                "categories": [
                    {
                        "category": score.category,
                        "accuracy": round(score.accuracy, 4),
                        "passed": score.passed,
                        "total": score.total,
                    }
                    for score in self.by_category()
                ],
                "cases": [
                    {
                        "id": result.case.id,
                        "category": result.case.category,
                        "passed": result.passed,
                        "called_tools": list(result.called_tools),
                        "expected_tools": list(result.case.expected_tools),
                        "failure_reason": result.failure_reason,
                        "duration_seconds": round(result.duration_seconds, 2),
                    }
                    for result in self.results
                ],
            },
            indent=2,
        )


def score_case(case: GoldenCase, called_tools: tuple[str, ...]) -> tuple[bool, str | None]:
    """Score one case against the tools the model actually called."""

    forbidden = [name for name in called_tools if name in case.forbidden_tools]
    if forbidden:
        return False, f"called forbidden tool(s): {', '.join(sorted(set(forbidden)))}"

    if case.expect_no_tool:
        if called_tools:
            return False, "answered with a tool call when none was needed"
        return True, None

    if not called_tools:
        return False, "called no tool"

    if any(name in case.expected_tools for name in called_tools):
        return True, None
    return False, "no expected tool was called"


def build_messages(case: GoldenCase, config: EvalConfig) -> list[dict[str, Any]]:
    """Build the same message shape the processor sends for a first user turn."""

    messages: list[dict[str, Any]] = [{"role": "system", "content": _processor.SYSTEM_PROMPT}]
    if config.context_message:
        messages.append({"role": "system", "content": config.context_message})
    messages.append({"role": "user", "content": case.utterance})
    return messages


class CRMAssistantEvalHarness:
    """Run golden-set cases against a live model and score tool choice."""

    def __init__(self, client: AsyncOpenAI, config: EvalConfig | None = None) -> None:
        self.client = client
        self.config = config or EvalConfig()
        self.tools = get_crm_tools()
        self.tool_names = {tool["function"]["name"] for tool in self.tools}

    async def run_case(self, case: GoldenCase) -> EvalCaseResult:
        """Run one utterance through a bounded tool loop with stubbed handlers."""

        started = time.perf_counter()
        messages = build_messages(case, self.config)
        called_tools: list[str] = []
        reply_text = ""

        try:
            for _turn in range(self.config.max_tool_turns):
                response = await asyncio.wait_for(
                    self.client.chat.completions.create(
                        model=self.config.model,
                        messages=messages,
                        tools=self.tools,
                        tool_choice="auto",
                        temperature=self.config.temperature,
                        max_completion_tokens=self.config.max_completion_tokens,
                    ),
                    timeout=self.config.timeout_seconds,
                )
                message = response.choices[0].message
                reply_text = message.content or reply_text
                if not message.tool_calls:
                    break

                messages.append(
                    {
                        "role": "assistant",
                        "content": message.content,
                        "tool_calls": [
                            {
                                "id": call.id,
                                "type": "function",
                                "function": {
                                    "name": call.function.name,
                                    "arguments": call.function.arguments,
                                },
                            }
                            for call in message.tool_calls
                        ],
                    }
                )
                for call in message.tool_calls:
                    called_tools.append(call.function.name)
                    try:
                        arguments = json.loads(call.function.arguments or "{}")
                    except json.JSONDecodeError:
                        arguments = {}
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": json.dumps(stub_tool_result(call.function.name, arguments)),
                        }
                    )
        except TimeoutError:
            return EvalCaseResult(
                case=case,
                called_tools=tuple(called_tools),
                passed=False,
                failure_reason="model call timed out",
                duration_seconds=time.perf_counter() - started,
            )

        passed, failure_reason = score_case(case, tuple(called_tools))
        return EvalCaseResult(
            case=case,
            called_tools=tuple(called_tools),
            passed=passed,
            failure_reason=failure_reason,
            duration_seconds=time.perf_counter() - started,
            reply_text=reply_text,
        )

    async def run(self, cases: tuple[GoldenCase, ...] = GOLDEN_SET) -> EvalReport:
        """Run every case with bounded concurrency and aggregate a report."""

        report = EvalReport(model=self.config.model)
        semaphore = asyncio.Semaphore(self.config.concurrency)

        async def guarded(case: GoldenCase) -> EvalCaseResult:
            async with semaphore:
                return await self.run_case(case)

        results = await asyncio.gather(*(guarded(case) for case in cases))
        report.results = list(results)
        report.completed_at = datetime.now(UTC)
        return report

    def missing_expected_tools(
        self, cases: tuple[GoldenCase, ...] = GOLDEN_SET
    ) -> dict[str, tuple[str, ...]]:
        """Return golden-case ids whose expected tools are not registered yet.

        Used to explain a zero-scoring category without re-reading the plan.
        """

        missing: dict[str, tuple[str, ...]] = {}
        for case in cases:
            absent = tuple(name for name in case.expected_tools if name not in self.tool_names)
            if absent and len(absent) == len(case.expected_tools):
                missing[case.id] = absent
        return missing
