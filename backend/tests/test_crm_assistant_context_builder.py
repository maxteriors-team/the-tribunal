"""The assistant must know what workspace and what day it is.

Before this it saw only a static prompt: no current date (while being told to
"summarize yesterday"), no business name, no campaign or agent names, no
pipeline stages, no tag vocabulary. Every one of those had to be guessed.

The context is injected as a *second* system message. It must never be folded
into the static prefix — the summarizer keeps ``messages[0]`` byte-identical so
OpenAI's prompt-prefix cache keeps hitting, and a changing date would bust that
cache on every turn.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ai.crm_assistant import _summarizer as summarizer
from app.services.ai.crm_assistant._context_builder import (
    WorkspaceContext,
    build_context_message,
    build_workspace_context,
)


def _context(**overrides: Any) -> WorkspaceContext:
    defaults: dict[str, Any] = {
        "now": datetime(2026, 7, 29, 14, 30, tzinfo=UTC),
        "timezone_name": "America/New_York",
        "business_name": "Ridgeline Exterior Cleaning",
        "business_description": "Pressure washing and gutter care",
        "contact_count": 1842,
        "live_campaigns": ["Spring Gutter Cleaning", "Winter Reactivation"],
        "agents": ["Front Desk Receptionist"],
        "pipeline_stages": ["New", "Quoted", "Won"],
        "tags": ["hot-lead", "past-customer"],
    }
    defaults.update(overrides)
    return WorkspaceContext(**defaults)


class TestRenderedContext:
    def test_includes_the_current_date(self) -> None:
        rendered = _context().to_system_message()

        assert "2026-07-29" in rendered

    def test_marks_workspace_context_as_non_authoritative_for_contacts(self) -> None:
        rendered = _context().to_system_message()

        assert "shallow context" in rendered
        assert "get_contact_context" in rendered
        assert "does not establish any individual contact's" in rendered

    def test_renders_the_date_in_the_workspace_timezone(self) -> None:
        """14:30 UTC is 10:30 the same day in New York."""
        rendered = _context().to_system_message()

        assert "10:30" in rendered
        assert "America/New_York" in rendered

    def test_timezone_shifts_the_calendar_date_when_it_should(self) -> None:
        """01:00 UTC is still the previous evening in Los Angeles."""
        rendered = _context(
            now=datetime(2026, 7, 29, 1, 0, tzinfo=UTC),
            timezone_name="America/Los_Angeles",
        ).to_system_message()

        assert "2026-07-28" in rendered

    def test_includes_business_identity(self) -> None:
        rendered = _context().to_system_message()

        assert "Ridgeline Exterior Cleaning" in rendered
        assert "Pressure washing and gutter care" in rendered

    def test_includes_live_counts_and_vocabularies(self) -> None:
        rendered = _context().to_system_message()

        assert "1842" in rendered
        assert "Spring Gutter Cleaning" in rendered
        assert "Front Desk Receptionist" in rendered
        assert "Quoted" in rendered
        assert "hot-lead" in rendered

    def test_empty_lists_are_omitted_rather_than_rendered_blank(self) -> None:
        rendered = _context(
            live_campaigns=[], agents=[], pipeline_stages=[], tags=[]
        ).to_system_message()

        assert "Tags in use" not in rendered
        assert "AI agents" not in rendered
        assert "Contacts on file: 1842" in rendered

    def test_invalid_timezone_falls_back_instead_of_raising(self) -> None:
        rendered = _context(timezone_name="Not/AZone").to_system_message()

        assert "2026-07-29" in rendered

    def test_block_stays_small(self) -> None:
        rendered = _context(tags=[f"tag-{index}" for index in range(200)]).to_system_message()

        assert len(rendered) < 2000


class TestContextMessage:
    async def test_returns_a_system_message(self) -> None:
        db = MagicMock()
        db.get = AsyncMock(return_value=None)
        db.scalar = AsyncMock(return_value=0)
        execute_result = MagicMock()
        execute_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=execute_result)

        message = await build_context_message(db, uuid.uuid4())

        assert message is not None
        assert message["role"] == "system"
        assert "Current workspace context" in message["content"]

    async def test_failure_degrades_instead_of_breaking_the_conversation(self) -> None:
        db = MagicMock()
        db.get = AsyncMock(side_effect=RuntimeError("db down"))

        assert await build_context_message(db, uuid.uuid4()) is None

    async def test_missing_workspace_still_yields_the_date(self) -> None:
        db = MagicMock()
        db.get = AsyncMock(return_value=None)
        db.scalar = AsyncMock(return_value=0)
        execute_result = MagicMock()
        execute_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=execute_result)

        message = await build_context_message(db, uuid.uuid4())

        assert message is not None
        assert "Today's date" in message["content"]

    async def test_timezone_is_read_from_workspace_settings(self) -> None:
        workspace = MagicMock()
        workspace.name = "Acme"
        workspace.description = None
        workspace.settings = {"timezone": "Europe/Berlin"}
        db = MagicMock()
        db.get = AsyncMock(return_value=workspace)
        db.scalar = AsyncMock(return_value=3)
        execute_result = MagicMock()
        execute_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=execute_result)

        context = await build_workspace_context(db, uuid.uuid4())

        assert context.timezone_name == "Europe/Berlin"
        assert context.business_name == "Acme"
        assert context.contact_count == 3


class TestPromptCacheStability:
    """The whole reason context is a separate message."""

    def test_static_prefix_is_untouched_by_context(self) -> None:
        from app.services.ai.crm_assistant._processor import SYSTEM_PROMPT

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": _context().to_system_message()},
            {"role": "user", "content": "hi"},
        ]

        assert messages[0]["content"] == SYSTEM_PROMPT
        assert "2026-07-29" not in SYSTEM_PROMPT

    def test_static_prompt_requires_snapshot_evidence_and_timestamp_citations(self) -> None:
        from app.services.ai.crm_assistant._processor import SYSTEM_PROMPT

        assert "Resolve identity first" in SYSTEM_PROMPT
        assert "call get_contact_context" in SYSTEM_PROMPT
        assert "workspace context is shallow" in SYSTEM_PROMPT
        assert "provenance.updated_at" in SYSTEM_PROMPT
        assert "current structured fields are authoritative" in SYSTEM_PROMPT
        assert "untrusted" in SYSTEM_PROMPT

    @pytest.mark.parametrize(
        ("messages", "expected"),
        [
            ([], 0),
            ([{"role": "user", "content": "x"}], 0),
            ([{"role": "system", "content": "a"}], 1),
            ([{"role": "system", "content": "a"}, {"role": "system", "content": "b"}], 2),
            (
                [
                    {"role": "system", "content": "a"},
                    {"role": "system", "content": "b"},
                    {"role": "user", "content": "x"},
                    {"role": "system", "content": "late"},
                ],
                2,
            ),
        ],
    )
    def test_system_prefix_length(self, messages: list[dict[str, Any]], expected: int) -> None:
        assert summarizer.system_prefix_length(messages) == expected

    async def test_compaction_preserves_the_context_message(self) -> None:
        """Without this, a long conversation goes context-blind again."""
        from types import SimpleNamespace

        long_text = "x" * (summarizer._CHARS_PER_TOKEN * summarizer.SUMMARIZE_TRIGGER_TOKENS + 1000)
        context_block = _context().to_system_message()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "STATIC"},
            {"role": "system", "content": context_block},
            {"role": "user", "content": long_text},
        ]
        for index in range(summarizer.KEEP_RECENT_MESSAGES + 4):
            messages.append({"role": "user", "content": f"m{index}"})

        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="SUMMARY"))]
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(return_value=response))
            )
        )

        out = await summarizer.maybe_summarize(client, messages)  # type: ignore[arg-type]

        assert out[0] == {"role": "system", "content": "STATIC"}
        assert out[1] == {"role": "system", "content": context_block}
        assert "SUMMARY" in out[2]["content"]
        assert len(out) < len(messages)
