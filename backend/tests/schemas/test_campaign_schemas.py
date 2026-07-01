"""Tests for campaign Pydantic schemas.

Validates CampaignCreate, CampaignUpdate, and CampaignResponse schemas.
"""

import uuid
from datetime import datetime, time

import pytest
from pydantic import ValidationError

from app.schemas.campaign import CampaignCreate, CampaignResponse, CampaignUpdate


class TestCampaignCreate:
    """Tests for CampaignCreate schema."""

    def test_valid_minimal(self) -> None:
        """Minimal required fields pass validation."""
        campaign = CampaignCreate(
            name="Test Campaign",
            from_phone_number="+15551234567",
            initial_message="Hello!",
        )
        assert campaign.name == "Test Campaign"
        assert campaign.ai_enabled is True
        assert campaign.timezone == "America/New_York"

    def test_valid_full(self) -> None:
        """Full campaign with all fields passes validation."""
        campaign = CampaignCreate(
            name="Full Campaign",
            agent_id=uuid.uuid4(),
            offer_id=uuid.uuid4(),
            from_phone_number="+15551234567",
            initial_message="Hello from Acme!",
            ai_enabled=False,
            qualification_criteria="Budget > 10k",
            sending_hours_start="09:00",
            sending_hours_end="17:00",
            sending_days=[0, 1, 2, 3, 4],
            timezone="America/Chicago",
            messages_per_minute=5,
            follow_up_enabled=True,
            follow_up_delay_hours=48,
            follow_up_message="Following up!",
            max_follow_ups=3,
        )
        assert campaign.ai_enabled is False
        assert campaign.timezone == "America/Chicago"
        assert campaign.sending_days == [0, 1, 2, 3, 4]

    def test_missing_name_raises(self) -> None:
        """Missing name raises ValidationError."""
        with pytest.raises(ValidationError):
            CampaignCreate(  # type: ignore[call-arg]
                from_phone_number="+15551234567",
                initial_message="Hello!",
            )

    def test_from_phone_optional_at_schema_layer(self) -> None:
        """from_phone_number is optional in the schema.

        Email campaigns have no phone sender, so the sender requirement for
        SMS/voice campaigns is enforced at the API layer
        (see tests/api/test_campaigns_validation.py), not by the schema.
        """
        campaign = CampaignCreate(
            name="Test",
            initial_message="Hello!",
        )
        assert campaign.from_phone_number is None
        assert campaign.campaign_type == "sms"

    def test_email_campaign_fields(self) -> None:
        """Email campaigns accept a type, subject, and body without a phone."""
        campaign = CampaignCreate(
            name="Newsletter",
            campaign_type="email",
            email_subject="Hi {first_name}",
            initial_message="Welcome!",
        )
        assert campaign.campaign_type == "email"
        assert campaign.email_subject == "Hi {first_name}"
        assert campaign.from_phone_number is None

    def test_default_messages_per_minute(self) -> None:
        """messages_per_minute defaults to 10."""
        campaign = CampaignCreate(
            name="Test",
            from_phone_number="+15551234567",
            initial_message="Hi",
        )
        assert campaign.messages_per_minute == 10

    def test_default_follow_up_disabled(self) -> None:
        """Follow-up is disabled by default."""
        campaign = CampaignCreate(
            name="Test",
            from_phone_number="+15551234567",
            initial_message="Hi",
        )
        assert campaign.follow_up_enabled is False
        assert campaign.max_follow_ups == 2


class TestCampaignUpdate:
    """Tests for CampaignUpdate schema."""

    def test_empty_update_valid(self) -> None:
        """All-None update is valid."""
        update = CampaignUpdate()
        assert update.name is None
        assert update.ai_enabled is None

    def test_partial_update_valid(self) -> None:
        """Partial updates pass validation."""
        update = CampaignUpdate(name="New Name", messages_per_minute=20)
        assert update.name == "New Name"
        assert update.messages_per_minute == 20


class TestCampaignResponse:
    """Tests for CampaignResponse schema."""

    def _make_response(self, **overrides: object) -> CampaignResponse:
        """Build a valid CampaignResponse."""
        now = datetime.now()
        data: dict[str, object] = {
            "id": uuid.uuid4(),
            "workspace_id": uuid.uuid4(),
            "campaign_type": "sms",
            "agent_id": None,
            "offer_id": None,
            "name": "Test Campaign",
            "status": "draft",
            "from_phone_number": "+15551234567",
            "initial_message": "Hello!",
            "ai_enabled": True,
            "qualification_criteria": None,
            "scheduled_start": None,
            "sending_hours_start": None,
            "sending_hours_end": None,
            "sending_days": None,
            "timezone": "America/New_York",
            "messages_per_minute": 10,
            "follow_up_enabled": False,
            "follow_up_delay_hours": 24,
            "follow_up_message": None,
            "max_follow_ups": 2,
            "total_contacts": 0,
            "messages_sent": 0,
            "messages_delivered": 0,
            "messages_failed": 0,
            "replies_received": 0,
            "contacts_qualified": 0,
            "contacts_opted_out": 0,
            "appointments_booked": 0,
            "guarantee_target": None,
            "guarantee_window_days": None,
            "guarantee_status": None,
            "created_at": now,
            "updated_at": now,
        }
        data.update(overrides)
        return CampaignResponse.model_validate(data)

    def test_valid_response(self) -> None:
        """Valid data creates CampaignResponse."""
        response = self._make_response()
        assert response.name == "Test Campaign"
        assert response.messages_sent == 0

    def test_from_attributes_config(self) -> None:
        """model_config has from_attributes=True."""
        assert CampaignResponse.model_config.get("from_attributes") is True

    def test_sending_hours_from_time_object(self) -> None:
        """time objects are coerced to HH:MM strings via validator."""
        response = self._make_response(
            sending_hours_start=time(9, 0),
            sending_hours_end=time(17, 30),
        )
        assert response.sending_hours_start == "09:00"
        assert response.sending_hours_end == "17:30"

    def test_sending_hours_from_string(self) -> None:
        """String HH:MM values pass through unchanged."""
        response = self._make_response(
            sending_hours_start="08:00",
            sending_hours_end="18:00",
        )
        assert response.sending_hours_start == "08:00"
        assert response.sending_hours_end == "18:00"

    def test_id_is_uuid(self) -> None:
        """id field is a UUID."""
        response = self._make_response()
        assert isinstance(response.id, uuid.UUID)
