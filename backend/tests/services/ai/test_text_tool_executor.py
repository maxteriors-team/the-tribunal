"""Regression tests for qualification gating in the SMS tool executor."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ai.text_tool_executor import TextToolExecutor
from app.services.ai.website_lead_qualification import WebsiteLeadQualificationPolicy


@pytest.fixture
def qualification_executor() -> TextToolExecutor:
    executor = TextToolExecutor.__new__(TextToolExecutor)
    executor.qualification_policy = WebsiteLeadQualificationPolicy(
        questions=("What service?", "What timeline?"),
        min_score=60,
        booking_label="Zoom consultation",
    )
    executor.conversation = SimpleNamespace(
        id=uuid.uuid4(),
        contact_id=44,
        contact_phone="+15551234567",
        workspace_id=uuid.uuid4(),
    )
    executor.agent = SimpleNamespace(
        id=uuid.uuid4(), workspace_id=executor.conversation.workspace_id
    )
    executor.db = AsyncMock()
    executor.db.flush = AsyncMock()
    executor.log = MagicMock()
    return executor


@pytest.mark.asyncio
async def test_booking_tools_are_blocked_before_persisted_qualification(
    qualification_executor: TextToolExecutor,
) -> None:
    contact = SimpleNamespace(id=44, is_qualified=False, source="lead_form")
    qualification_executor._get_contact = AsyncMock(return_value=contact)  # type: ignore[method-assign]

    availability = await qualification_executor.execute(
        "check_availability", {"start_date": "2026-08-20"}
    )
    booking = await qualification_executor.execute(
        "book_appointment",
        {"date": "2026-08-20", "time": "10:00", "email": "lead@example.com"},
    )

    assert availability["blocked"] is True
    assert booking["blocked"] is True


@pytest.mark.asyncio
async def test_mark_qualified_persists_score_signals_and_booking_state(
    qualification_executor: TextToolExecutor,
) -> None:
    contact = SimpleNamespace(
        id=44,
        is_qualified=False,
        source="lead_form",
        status="new",
        lead_score=0,
        qualified_at=None,
        qualification_signals=None,
    )
    qualification_executor._get_contact = AsyncMock(return_value=contact)  # type: ignore[method-assign]

    result = await qualification_executor.execute(
        "mark_lead_qualified",
        {
            "score": 80,
            "criteria_evidence": ["Needs gutter cleaning", "Wants it this month"],
            "summary": "Project scope and timing are confirmed.",
        },
    )

    assert result["qualified"] is True
    assert contact.is_qualified is True
    assert contact.status == "qualified"
    assert contact.lead_score == 80
    assert contact.qualified_at <= datetime.now(UTC)
    assert contact.qualification_signals["source"] == "website_lead_live_ai"
    assert len(contact.qualification_signals["criteria"]) == 2
    qualification_executor.db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_qualified_rejects_low_score_or_incomplete_evidence(
    qualification_executor: TextToolExecutor,
) -> None:
    contact = SimpleNamespace(id=44, is_qualified=False, source="lead_form")
    qualification_executor._get_contact = AsyncMock(return_value=contact)  # type: ignore[method-assign]

    low_score = await qualification_executor.execute(
        "mark_lead_qualified",
        {"score": 59, "criteria_evidence": ["A", "B"], "summary": "Summary"},
    )
    missing = await qualification_executor.execute(
        "mark_lead_qualified",
        {"score": 80, "criteria_evidence": ["A"], "summary": "Summary"},
    )

    assert low_score["success"] is False
    assert missing["success"] is False
    qualification_executor.db.flush.assert_not_awaited()
