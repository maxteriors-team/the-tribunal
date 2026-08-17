"""Verify the eval harness itself, without spending money on a live model.

The harness is the instrument every later phase is measured with, so its loop,
scoring, and reporting are tested against a scripted fake OpenAI client that
mimics the SDK's chat-completions response shape.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from tests.evals.crm_assistant.golden_set import GoldenCase, cases_for_category
from tests.evals.crm_assistant.harness import CRMAssistantEvalHarness, EvalConfig
from tests.evals.crm_assistant.stub_handlers import stub_tool_result


@dataclass
class _FakeFunction:
    name: str
    arguments: str


@dataclass
class _FakeToolCall:
    id: str
    function: _FakeFunction


@dataclass
class _FakeMessage:
    content: str | None
    tool_calls: list[_FakeToolCall] | None


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeResponse:
    choices: list[_FakeChoice]


class _FakeCompletions:
    """Replays a script of turns and records the requests it received.

    Requests are deep-copied on capture: the harness mutates one message list
    across turns, so storing the reference would make every recorded request
    show the final state.
    """

    def __init__(self, script: list[_FakeMessage]) -> None:
        self._script = list(script)
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _FakeResponse:
        self.requests.append(deepcopy(kwargs))
        message = self._script.pop(0) if self._script else _FakeMessage("done", None)
        return _FakeResponse(choices=[_FakeChoice(message=message)])


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self, script: list[_FakeMessage]) -> None:
        self.completions = _FakeCompletions(script)
        self.chat = _FakeChat(self.completions)


def _tool_turn(*names: str) -> _FakeMessage:
    return _FakeMessage(
        content=None,
        tool_calls=[
            _FakeToolCall(id=f"call_{index}", function=_FakeFunction(name=name, arguments="{}"))
            for index, name in enumerate(names)
        ],
    )


_CASE = GoldenCase(
    id="probe",
    category="probe",
    utterance="Look up Bob.",
    expected_tools=("search_contacts",),
    forbidden_tools=("send_sms",),
)


class TestHarnessLoop:
    async def test_records_the_tool_the_model_picked(self) -> None:
        client = _FakeClient([_tool_turn("search_contacts"), _FakeMessage("Found Bob.", None)])
        harness = CRMAssistantEvalHarness(client, EvalConfig())  # type: ignore[arg-type]

        result = await harness.run_case(_CASE)

        assert result.called_tools == ("search_contacts",)
        assert result.passed
        assert result.reply_text == "Found Bob."

    async def test_feeds_stub_results_back_so_chains_continue(self) -> None:
        client = _FakeClient(
            [
                _tool_turn("search_contacts"),
                _tool_turn("get_conversation"),
                _FakeMessage("ok", None),
            ]
        )
        harness = CRMAssistantEvalHarness(client, EvalConfig())  # type: ignore[arg-type]

        result = await harness.run_case(_CASE)

        assert result.called_tools == ("search_contacts", "get_conversation")
        second_request = client.completions.requests[1]
        tool_messages = [
            message for message in second_request["messages"] if message["role"] == "tool"
        ]
        assert len(tool_messages) == 1
        assert "Marchetti" in tool_messages[0]["content"]

    async def test_forbidden_tool_fails_the_case(self) -> None:
        client = _FakeClient([_tool_turn("search_contacts", "send_sms"), _FakeMessage("x", None)])
        harness = CRMAssistantEvalHarness(client, EvalConfig())  # type: ignore[arg-type]

        result = await harness.run_case(_CASE)

        assert not result.passed
        assert result.failure_reason is not None
        assert "forbidden" in result.failure_reason

    async def test_loop_is_bounded(self) -> None:
        client = _FakeClient([_tool_turn("search_contacts") for _ in range(10)])
        harness = CRMAssistantEvalHarness(client, EvalConfig(max_tool_turns=2))  # type: ignore[arg-type]

        result = await harness.run_case(_CASE)

        assert len(result.called_tools) == 2

    async def test_real_tool_schemas_are_sent_to_the_model(self) -> None:
        client = _FakeClient([_FakeMessage("hi", None)])
        harness = CRMAssistantEvalHarness(client, EvalConfig())  # type: ignore[arg-type]

        await harness.run_case(_CASE)

        sent = {tool["function"]["name"] for tool in client.completions.requests[0]["tools"]}
        assert "search_contacts" in sent
        assert sent == harness.tool_names

    async def test_context_message_is_appended_after_the_static_prefix(self) -> None:
        client = _FakeClient([_FakeMessage("hi", None)])
        config = EvalConfig(context_message="Today is 2026-07-29.")
        harness = CRMAssistantEvalHarness(client, config)  # type: ignore[arg-type]

        await harness.run_case(_CASE)

        messages = client.completions.requests[0]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[1] == {"role": "system", "content": "Today is 2026-07-29."}
        assert messages[2]["role"] == "user"


class TestHarnessReport:
    async def test_report_scores_and_renders_per_category(self) -> None:
        cases = (
            _CASE,
            GoldenCase(
                id="miss",
                category="other",
                utterance="Do a thing.",
                expected_tools=("list_campaigns",),
            ),
        )
        client = _FakeClient(
            [
                _tool_turn("search_contacts"),
                _FakeMessage("ok", None),
                _tool_turn("list_agents"),
                _FakeMessage("ok", None),
            ]
        )
        harness = CRMAssistantEvalHarness(client, EvalConfig(concurrency=1))  # type: ignore[arg-type]

        report = await harness.run(cases)

        assert report.total == 2
        assert report.passed == 1
        assert report.accuracy == 0.5
        categories = {score.category: score for score in report.by_category()}
        assert categories["probe"].accuracy == 1.0
        assert categories["other"].accuracy == 0.0

        markdown = report.to_markdown()
        assert "Accuracy: 50.0% (1/2)" in markdown
        assert "| probe | 100% | 1/1 |" in markdown
        assert "`miss`" in markdown

        assert '"accuracy": 0.5' in report.to_json()

    def test_missing_expected_tools_flags_unbuilt_tools(self) -> None:
        client = _FakeClient([])
        harness = CRMAssistantEvalHarness(client, EvalConfig())  # type: ignore[arg-type]

        missing = harness.missing_expected_tools(
            (
                GoldenCase(
                    id="future",
                    category="c",
                    utterance="u",
                    expected_tools=("not_a_tool_yet",),
                ),
                _CASE,
            )
        )

        assert missing == {"future": ("not_a_tool_yet",)}


class TestStubHandlers:
    def test_known_tool_returns_list_shape(self) -> None:
        result = stub_tool_result("search_contacts", {})
        assert result["success"] is True
        assert result["total"] == result["returned"]

    def test_ambiguous_identity_stops_before_snapshot_lookup(self) -> None:
        result = stub_tool_result("search_contacts", {"query": "Alex Kim"})

        assert result["identity_resolution"]["status"] == "ambiguous"
        assert result["returned"] == 2

    def test_contact_context_stub_supports_timeline_pagination(self) -> None:
        result = stub_tool_result(
            "get_contact_context",
            {"contact_id": 512, "timeline_limit": 2, "timeline_offset": 0},
        )

        page = result["data"]["timeline_page"]
        assert page == {
            "offset": 0,
            "limit": 2,
            "returned": 2,
            "has_more": True,
            "next_offset": 2,
        }
        assert len(cases_for_category("contact_context")) == 5

    def test_contact_context_stub_denies_foreign_workspace_contact_generically(self) -> None:
        result = stub_tool_result("get_contact_context", {"contact_id": 9001})

        assert result["success"] is False
        assert result["code"] == "not_found"
        assert "workspace" not in result["message"].lower()

    def test_unknown_tool_still_returns_parseable_success(self) -> None:
        result = stub_tool_result("some_future_tool", {"a": 1})
        assert result["success"] is True
        assert result["data"]["tool"] == "some_future_tool"
