"""Regression tests for SMS booking result behavior."""

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.text_tool_executor import TextToolExecutor
from app.services.ai.website_lead_qualification import WebsiteLeadQualificationPolicy


def test_booking_success_tells_model_exactly_what_was_queued() -> None:
    executor = TextToolExecutor.__new__(TextToolExecutor)
    executor._appointment_datetime = datetime.fromisoformat("2026-08-12T13:30:00-04:00")
    executor._booked_appointment = SimpleNamespace(
        sync_status="synced",
        meeting_url=None,
    )

    result = executor.format_booking_success(
        SimpleNamespace(booking_uid="book-123"),
        contact_name="Scott McKenzie",
        date_str="2026-08-12",
        time_str="13:30",
        email="Scottpmckenzie@aol.com",
        duration_minutes=30,
    )

    assert result["invitation_sent"] is True
    assert result["booking_email"] == "Scottpmckenzie@aol.com"
    assert "Phone Call booked" in result["message"]
    assert "calendar invitation was sent" in result["message"]


def test_video_booking_success_returns_provider_meeting_link() -> None:
    executor = TextToolExecutor.__new__(TextToolExecutor)
    executor._appointment_datetime = datetime.fromisoformat("2026-08-12T13:30:00-04:00")
    executor._pending_call_type = "video_call"
    executor._booked_appointment = SimpleNamespace(
        sync_status="synced",
        meeting_url="https://zoom.us/j/123456789",
    )

    result = executor.format_booking_success(
        SimpleNamespace(booking_uid="book-123"),
        contact_name="Scott McKenzie",
        date_str="2026-08-12",
        time_str="13:30",
        email="Scottpmckenzie@aol.com",
        duration_minutes=30,
    )

    assert result["invitation_sent"] is True
    assert result["meeting_url"] == "https://zoom.us/j/123456789"
    assert "The Zoom link is https://zoom.us/j/123456789" in result["message"]


@pytest.mark.asyncio
async def test_live_sms_booking_suppresses_generic_confirmation() -> None:
    executor = TextToolExecutor.__new__(TextToolExecutor)
    executor.db = MagicMock()
    executor.conversation = SimpleNamespace(workspace_id="workspace", campaign_id=None)
    executor.agent = SimpleNamespace(id="agent")
    executor._appointment_datetime = datetime.fromisoformat("2026-08-12T13:30:00-04:00")
    executor._pending_call_type = "video_call"
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
            email="Scottpmckenzie@aol.com",
            duration_minutes=30,
            notes=None,
        )

    assert finalize.await_args.kwargs["send_customer_sms"] is False
    assert finalize.await_args.kwargs["service_type"] == "video_call"
    assert finalize.await_args.kwargs["sync_external_events_before_return"] is True


@pytest.mark.asyncio
async def test_ai_staff_routing_requires_connected_google_calendar() -> None:
    class SessionContext:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *_args):
            return None

    executor = TextToolExecutor.__new__(TextToolExecutor)
    executor.agent = SimpleNamespace(id="agent")
    executor.log = MagicMock()
    resolver = AsyncMock(return_value=None)

    with (
        patch("app.db.session.AsyncSessionLocal", return_value=SessionContext()),
        patch(
            "app.services.calendar.staff_assignment.resolve_staff_for_booking",
            resolver,
        ),
    ):
        await executor._resolve_assigned_staff(None, record=False)

    assert resolver.await_args.kwargs["record"] is False
    assert resolver.await_args.kwargs["require_calendar_connection"] is True


@pytest.mark.asyncio
async def test_sms_executor_passes_explicit_confirmation_to_booking_guard() -> None:
    workspace_id = uuid.uuid4()
    executor = TextToolExecutor(
        agent=SimpleNamespace(id=uuid.uuid4(), workspace_id=workspace_id),
        conversation=SimpleNamespace(id=uuid.uuid4(), workspace_id=workspace_id),
        db=AsyncMock(),
    )
    executor._execute_book_with_contact_lookup = AsyncMock(  # type: ignore[method-assign]
        return_value={"success": False, "error": "test stop"}
    )

    await executor.execute(
        "book_appointment",
        {
            "date": "2099-01-15",
            "time": "10:00",
            "email": "lead@example.com",
            "customer_confirmed": True,
            "call_type": "phone_call",
        },
    )

    assert (
        executor._execute_book_with_contact_lookup.await_args.kwargs["customer_confirmed"] is True
    )


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
        {
            "date": "2026-08-20",
            "time": "10:00",
            "email": "lead@example.com",
            "call_type": "phone_call",
        },
    )

    assert availability["blocked"] is True
    assert booking["blocked"] is True


@pytest.mark.asyncio
async def test_booking_requires_explicit_phone_or_video_choice(
    qualification_executor: TextToolExecutor,
) -> None:
    contact = SimpleNamespace(
        id=44,
        is_qualified=True,
        source="lead_form",
        status="qualified",
        email="lead@example.com",
        full_name="Lead Person",
    )
    qualification_executor._get_contact = AsyncMock(return_value=contact)  # type: ignore[method-assign]

    result = await qualification_executor.execute(
        "book_appointment",
        {"date": "2026-08-20", "time": "10:00", "email": "lead@example.com"},
    )

    assert result["success"] is False
    assert "phone call or video call" in result["message"]


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
    opportunity = SimpleNamespace(id=uuid.uuid4())

    with patch(
        "app.services.ai.text_tool_executor.mark_contact_qualified",
        AsyncMock(return_value=opportunity),
    ) as transition:
        result = await qualification_executor.execute(
            "mark_lead_qualified",
            {
                "score": 80,
                "criteria_evidence": ["Needs gutter cleaning", "Wants it this month"],
                "summary": "Project scope and timing are confirmed.",
            },
        )

    assert result["qualified"] is True
    assert result["opportunity_id"] == str(opportunity.id)
    assert contact.lead_score == 80
    assert contact.qualification_signals["source"] == "website_lead_live_ai"
    assert len(contact.qualification_signals["criteria"]) == 2
    transition.assert_awaited_once_with(qualification_executor.db, contact)


@pytest.mark.asyncio
async def test_mark_qualified_refuses_terminal_contact(
    qualification_executor: TextToolExecutor,
) -> None:
    contact = SimpleNamespace(
        id=44,
        is_qualified=False,
        source="lead_form",
        status="lost",
        lead_score=0,
        qualification_signals=None,
    )
    qualification_executor._get_contact = AsyncMock(return_value=contact)  # type: ignore[method-assign]

    result = await qualification_executor.execute(
        "mark_lead_qualified",
        {"score": 80, "criteria_evidence": ["A", "B"], "summary": "Summary"},
    )

    assert result["blocked"] is True
    assert contact.lead_score == 0


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


@pytest.mark.asyncio
async def test_claim_tools_return_this_turn_evidence_metadata(
    qualification_executor: TextToolExecutor,
) -> None:
    qualification_executor._execute_search_knowledge = AsyncMock(  # type: ignore[method-assign]
        return_value={"success": True, "results": [{"text": "House wash starts at $199"}]}
    )

    result = await qualification_executor.execute(
        "search_knowledge",
        {"query": "house wash price"},
    )

    assert result["evidence_source"] == "live_tool"
    assert result["evidence_domains"] == ["pricing"]
    assert result["evidence_status"] == "found"
    assert result["observed_at"]


@pytest.mark.asyncio
async def test_contact_lookup_absence_never_falls_back_to_notes(
    qualification_executor: TextToolExecutor,
) -> None:
    snapshot_service = MagicMock()
    snapshot_service.get_snapshot = AsyncMock(return_value=None)

    with patch(
        "app.services.ai.text_tool_executor.ContactContextSnapshotService",
        return_value=snapshot_service,
    ) as service_class:
        result = await qualification_executor.execute(
            "lookup_contact_state",
            {"subject": "quote"},
        )

    assert result["evidence_status"] == "absent"
    assert "Do not use notes or prior messages as proof" in result["message"]
    service_class.return_value.get_snapshot.assert_awaited_once_with(
        workspace_id=qualification_executor.conversation.workspace_id,
        contact_id=qualification_executor.conversation.contact_id,
    )


@pytest.mark.asyncio
async def test_tool_executor_rejects_cross_workspace_agent_before_query() -> None:
    executor = TextToolExecutor.__new__(TextToolExecutor)
    executor.agent = SimpleNamespace(id=uuid.uuid4(), workspace_id=uuid.uuid4())
    executor.conversation = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        contact_id=44,
    )
    executor.db = AsyncMock()
    executor.log = MagicMock()

    with patch("app.services.ai.text_tool_executor.ContactContextSnapshotService") as service:
        result = await executor.execute(
            "lookup_contact_state",
            {"subject": "appointment"},
        )

    assert result["blocked"] is True
    assert result["evidence_status"] == "error"
    service.assert_not_called()


def test_customer_reference_disambiguates_accepted_and_pending_quotes() -> None:
    evidence = {
        "message": "Live CRM evidence.",
        "evidence_status": "conflict",
        "domain_status": {"quote": "conflict"},
        "active_quotes": [
            {
                "number": "Q-100",
                "title": "House wash",
                "status": "sent",
                "decision_state": "pending",
            },
            {
                "number": "Q-101",
                "title": "Roof wash",
                "status": "approved",
                "decision_state": "accepted",
            },
        ],
    }

    narrowed = TextToolExecutor._narrow_contact_state_evidence(
        evidence,
        domain="quote",
        reference="the accepted roof wash quote",
    )

    assert narrowed["evidence_status"] == "found"
    assert [quote["number"] for quote in narrowed["active_quotes"]] == ["Q-101"]
