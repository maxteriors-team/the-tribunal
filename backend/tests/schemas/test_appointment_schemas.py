"""Tests for appointment Pydantic schemas.

Validates AppointmentCreate, AppointmentUpdate, AppointmentResponse,
and stats schemas.
"""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.appointment import (
    AppointmentAgentStat,
    AppointmentCampaignStat,
    AppointmentCreate,
    AppointmentOverallStats,
    AppointmentResponse,
    AppointmentStatsResponse,
    AppointmentUpdate,
    ContactSummary,
    PaginatedAppointments,
)


class TestAppointmentCreate:
    """Tests for AppointmentCreate schema."""

    def test_valid_minimal(self) -> None:
        """Minimal required fields pass validation."""
        appt = AppointmentCreate(
            contact_id=1,
            scheduled_at=datetime.now(UTC),
        )
        assert appt.contact_id == 1
        assert appt.duration_minutes == 30
        assert appt.anytime is False

    def test_valid_full(self) -> None:
        """All fields pass validation."""
        appt = AppointmentCreate(
            contact_id=42,
            agent_id=str(uuid.uuid4()),
            scheduled_at=datetime.now(UTC),
            duration_minutes=60,
            anytime=True,
            service_type="Consultation",
            notes="First meeting",
        )
        assert appt.duration_minutes == 60
        assert appt.anytime is True
        assert appt.service_type == "Consultation"

    def test_missing_contact_id_raises(self) -> None:
        """Missing contact_id raises ValidationError."""
        with pytest.raises(ValidationError):
            AppointmentCreate(scheduled_at=datetime.now(UTC))  # type: ignore[call-arg]

    def test_missing_scheduled_at_raises(self) -> None:
        """Missing scheduled_at raises ValidationError."""
        with pytest.raises(ValidationError):
            AppointmentCreate(contact_id=1)  # type: ignore[call-arg]

    def test_duration_too_short_raises(self) -> None:
        """duration_minutes < 15 raises ValidationError."""
        with pytest.raises(ValidationError):
            AppointmentCreate(
                contact_id=1,
                scheduled_at=datetime.now(UTC),
                duration_minutes=5,
            )

    def test_duration_too_long_raises(self) -> None:
        """duration_minutes > 480 raises ValidationError."""
        with pytest.raises(ValidationError):
            AppointmentCreate(
                contact_id=1,
                scheduled_at=datetime.now(UTC),
                duration_minutes=500,
            )

    def test_duration_boundary_values(self) -> None:
        """Boundary duration values (15 and 480) are accepted."""
        now = datetime.now(UTC)
        appt_min = AppointmentCreate(contact_id=1, scheduled_at=now, duration_minutes=15)
        appt_max = AppointmentCreate(contact_id=1, scheduled_at=now, duration_minutes=480)
        assert appt_min.duration_minutes == 15
        assert appt_max.duration_minutes == 480

    def test_optional_agent_id(self) -> None:
        """agent_id defaults to None."""
        appt = AppointmentCreate(contact_id=1, scheduled_at=datetime.now(UTC))
        assert appt.agent_id is None


class TestAppointmentUpdate:
    """Tests for AppointmentUpdate schema."""

    def test_empty_update_valid(self) -> None:
        """All-None update is valid."""
        update = AppointmentUpdate()
        assert update.status is None
        assert update.duration_minutes is None

    def test_valid_status(self) -> None:
        """Valid status values are accepted."""
        for status in ("scheduled", "completed", "cancelled", "no_show"):
            update = AppointmentUpdate(status=status)
            assert update.status == status

    def test_invalid_status_raises(self) -> None:
        """Invalid status raises ValidationError."""
        with pytest.raises(ValidationError):
            AppointmentUpdate(status="rescheduled")

    def test_valid_duration(self) -> None:
        """Valid duration_minutes passes validation."""
        update = AppointmentUpdate(duration_minutes=45)
        assert update.duration_minutes == 45

    def test_duration_too_short_raises(self) -> None:
        """duration_minutes below minimum raises ValidationError."""
        with pytest.raises(ValidationError):
            AppointmentUpdate(duration_minutes=10)


class TestContactSummary:
    """Tests for ContactSummary schema."""

    def test_valid_contact_summary(self) -> None:
        """Valid contact summary parses correctly."""
        data = {
            "id": 1,
            "first_name": "Alice",
            "last_name": "Smith",
            "email": "alice@example.com",
            "phone_number": "+15551234567",
        }
        summary = ContactSummary.model_validate(data)
        assert summary.first_name == "Alice"
        assert summary.email == "alice@example.com"

    def test_from_attributes_config(self) -> None:
        """model_config has from_attributes=True."""
        assert ContactSummary.model_config.get("from_attributes") is True

    def test_optional_fields_none(self) -> None:
        """last_name and email are optional."""
        data = {
            "id": 1,
            "first_name": "Bob",
            "last_name": None,
            "email": None,
            "phone_number": "+15559999999",
        }
        summary = ContactSummary.model_validate(data)
        assert summary.last_name is None
        assert summary.email is None


class TestAppointmentResponse:
    """Tests for AppointmentResponse schema."""

    def _make_response(self, **overrides: object) -> AppointmentResponse:
        """Build a valid AppointmentResponse."""
        now = datetime.now(UTC)
        data: dict[str, object] = {
            "id": 1,
            "workspace_id": uuid.uuid4(),
            "contact_id": 1,
            "contact": None,
            "agent_id": None,
            "message_id": None,
            "campaign_id": None,
            "scheduled_at": now,
            "duration_minutes": 30,
            "service_type": None,
            "notes": None,
            "status": "scheduled",
            "google_calendar_event_id": None,
            "google_calendar_event_url": None,
            "meeting_url": None,
            "sync_status": "pending",
            "last_synced_at": None,
            "sync_error": None,
            "reminder_sent_at": None,
            "reminders_sent": [],
            "created_at": now,
            "updated_at": now,
        }
        data.update(overrides)
        return AppointmentResponse.model_validate(data)

    def test_valid_response(self) -> None:
        """Valid data creates AppointmentResponse."""
        response = self._make_response(
            service_type="video_call",
            meeting_url="https://meet.google.com/abc-defg-hij",
        )
        assert response.status == "scheduled"
        assert response.duration_minutes == 30
        assert response.meeting_url == "https://meet.google.com/abc-defg-hij"

    def test_from_attributes_config(self) -> None:
        """model_config has from_attributes=True."""
        assert AppointmentResponse.model_config.get("from_attributes") is True

    def test_with_contact(self) -> None:
        """AppointmentResponse with embedded contact parses correctly."""
        contact_data = {
            "id": 1,
            "first_name": "Alice",
            "last_name": None,
            "email": None,
            "phone_number": "+15551234567",
        }
        response = self._make_response(contact=contact_data)
        assert response.contact is not None
        assert response.contact.first_name == "Alice"


class TestAppointmentStats:
    """Tests for appointment statistics schemas."""

    def test_overall_stats(self) -> None:
        """AppointmentOverallStats validates correctly."""
        stats = AppointmentOverallStats(
            total=100,
            scheduled=30,
            completed=50,
            no_show=15,
            cancelled=5,
            show_up_rate=0.77,
        )
        assert stats.total == 100
        assert stats.show_up_rate == 0.77

    def test_agent_stat(self) -> None:
        """AppointmentAgentStat validates correctly."""
        stat = AppointmentAgentStat(
            agent_id=str(uuid.uuid4()),
            agent_name="Sales Bot",
            total=20,
            completed=15,
            no_show=5,
            show_up_rate=0.75,
        )
        assert stat.agent_name == "Sales Bot"

    def test_campaign_stat(self) -> None:
        """AppointmentCampaignStat validates correctly."""
        stat = AppointmentCampaignStat(
            campaign_id=str(uuid.uuid4()),
            campaign_name="Q1 Outreach",
            total=50,
            completed=40,
            no_show=10,
            show_up_rate=0.80,
        )
        assert stat.campaign_name == "Q1 Outreach"

    def test_stats_response(self) -> None:
        """AppointmentStatsResponse validates nested schemas."""
        overall = AppointmentOverallStats(
            total=10, scheduled=3, completed=5, no_show=2, cancelled=0, show_up_rate=0.5
        )
        response = AppointmentStatsResponse(overall=overall, by_agent=[], by_campaign=[])
        assert response.overall.total == 10
        assert response.by_agent == []

    def test_paginated_appointments(self) -> None:
        """PaginatedAppointments validates correctly."""
        paginated = PaginatedAppointments(items=[], total=0, page=1, page_size=25, pages=0)
        assert paginated.total == 0
        assert paginated.page_size == 25
