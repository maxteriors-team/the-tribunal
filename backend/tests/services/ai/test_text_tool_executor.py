"""Regression tests for qualification gating and booking results in the SMS tool executor."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.text_tool_executor import TextToolExecutor
from app.services.ai.website_lead_qualification import WebsiteLeadQualificationPolicy


def test_booking_success_tells_model_exactly_what_was_queued() -> None:
    """The model may only claim an invite went out when the result says so.

    Without ``invitation_sent`` the model invented "I emailed you the invite",
    and the customer waited on an email that was never attempted.
    """
    executor = TextToolExecutor.__new__(TextToolExecutor)
    executor._appointment_datetime = datetime.fromisoformat("2026-08-12T13:30:00-04:00")

    result = executor.format_booking_success(
        SimpleNamespace(booking_uid="book-123"),
        contact_name="Scott McKenzie",
        date_str="2026-08-12",
        time_str="13:30",
        email="scott@example.com",
        duration_minutes=30,
    )

    assert result["invitation_sent"] is True
    assert result["booking_email"] == "scott@example.com"
    assert "Calendar invitation queued" in result["message"]
    assert "no separate reminder" in result["message"]


@pytest.mark.asyncio
async def test_live_sms_booking_suppresses_generic_confirmation() -> None:
    """The assistant confirms in-turn, so the lifecycle SMS would double-text."""
    executor = TextToolExecutor.__new__(TextToolExecutor)
    executor.db = MagicMock()
    executor.conversation = SimpleNamespace(workspace_id="workspace", campaign_id=None)
    executor.agent = SimpleNamespace(calcom_event_type_id=123)
    executor._appointment_datetime = datetime.fromisoformat("2026-08-12T13:30:00-04:00")
    executor._contact = SimpleNamespace(id=44)
    executor.assigned_staff = None
    executor.assigned_staff_id = MagicMock(return_value=None)
    executor.log = MagicMock()

    with patch(
        "app.services.ai.text_tool_executor.finalize_booking",
        AsyncMock(return_value=SimpleNamespace(id=99)),
    ) as finalize:
        await executor.post_booking_success(
            SimpleNamespace(booking_uid="book-123", booking_id=456),
            date_str="2026-08-12",
            time_str="13:30",
            email="scott@example.com",
            duration_minutes=30,
            notes=None,
        )

    assert finalize.await_args.kwargs["send_customer_sms"] is False


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
