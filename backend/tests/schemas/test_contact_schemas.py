"""Tests for contact Pydantic schemas.

Validates ContactCreate, ContactUpdate, and ContactResponse schemas
including field constraints, optional fields, and ORM model coercion.
"""

import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models.contact import Contact
from app.models.tag import ContactTag, Tag
from app.schemas.contact import (
    BulkDeleteRequest,
    BulkDeleteResponse,
    BulkStatusUpdateRequest,
    BulkStatusUpdateResponse,
    ContactCreate,
    ContactListResponse,
    ContactResponse,
    ContactUpdate,
    ContactWithConversationResponse,
    QualificationSignalDetail,
    QualificationSignals,
)


class TestContactCreate:
    """Tests for ContactCreate schema validation."""

    def test_valid_minimal(self) -> None:
        """Minimal required fields pass validation."""
        contact = ContactCreate.model_validate(
            {"first_name": "Alice", "phone_number": "1234567890"}
        )
        assert contact.first_name == "Alice"
        assert contact.phone_number == "1234567890"
        assert contact.status == "new"

    def test_valid_full(self) -> None:
        """All fields pass validation."""
        contact = ContactCreate(
            first_name="Alice",
            last_name="Smith",
            email="alice@example.com",
            phone_number="+15551234567",
            company_name="Acme Corp",
            status="qualified",
            tags=["vip", "warm"],
            notes="Interested in premium plan",
            source="web",
        )
        assert contact.email == "alice@example.com"
        assert contact.tags == ["vip", "warm"]

    def test_missing_first_name_raises(self) -> None:
        """Missing first_name raises ValidationError."""
        with pytest.raises(ValidationError):
            ContactCreate.model_validate({"phone_number": "1234567890"})

    def test_missing_phone_raises(self) -> None:
        """Missing phone_number raises ValidationError."""
        with pytest.raises(ValidationError):
            ContactCreate.model_validate({"first_name": "Alice"})

    def test_first_name_too_short_raises(self) -> None:
        """Empty first_name raises ValidationError."""
        with pytest.raises(ValidationError):
            ContactCreate.model_validate({"first_name": "", "phone_number": "1234567890"})

    def test_first_name_too_long_raises(self) -> None:
        """first_name over 100 chars raises ValidationError."""
        with pytest.raises(ValidationError):
            ContactCreate.model_validate({"first_name": "A" * 101, "phone_number": "1234567890"})

    def test_phone_too_short_raises(self) -> None:
        """phone_number under 10 chars raises ValidationError."""
        with pytest.raises(ValidationError):
            ContactCreate.model_validate({"first_name": "Alice", "phone_number": "123"})

    def test_phone_too_long_raises(self) -> None:
        """phone_number over 20 chars raises ValidationError."""
        with pytest.raises(ValidationError):
            ContactCreate.model_validate(
                {"first_name": "Alice", "phone_number": "1" * 21}
            )

    def test_invalid_email_raises(self) -> None:
        """Invalid email format raises ValidationError."""
        with pytest.raises(ValidationError):
            ContactCreate.model_validate(
                {
                    "first_name": "Alice",
                    "phone_number": "1234567890",
                    "email": "not-an-email",
                }
            )

    def test_optional_fields_default_none(self) -> None:
        """Optional fields default to None."""
        contact = ContactCreate.model_validate(
            {"first_name": "Alice", "phone_number": "1234567890"}
        )
        assert contact.last_name is None
        assert contact.email is None
        assert contact.company_name is None
        assert contact.tags is None
        assert contact.notes is None
        assert contact.source is None


class TestContactUpdate:
    """Tests for ContactUpdate schema validation."""

    def test_empty_update_valid(self) -> None:
        """Empty update (all None) is valid."""
        update = ContactUpdate.model_validate({})
        assert update.first_name is None
        assert update.status is None

    def test_partial_update_valid(self) -> None:
        """Partial update passes validation."""
        update = ContactUpdate.model_validate({"first_name": "Bob", "lead_score": 75})
        assert update.first_name == "Bob"
        assert update.lead_score == 75

    def test_first_name_empty_string_raises(self) -> None:
        """Empty string for first_name raises ValidationError."""
        with pytest.raises(ValidationError):
            ContactUpdate.model_validate({"first_name": ""})

    def test_phone_too_short_raises(self) -> None:
        """phone_number too short raises ValidationError."""
        with pytest.raises(ValidationError):
            ContactUpdate.model_validate({"phone_number": "123"})

    def test_invalid_email_raises(self) -> None:
        """Invalid email raises ValidationError."""
        with pytest.raises(ValidationError):
            ContactUpdate.model_validate({"email": "bad-email"})


class TestContactResponse:
    """Tests for ContactResponse schema."""

    def _make_response(self, **overrides: object) -> ContactResponse:
        """Build a valid ContactResponse dict."""
        now = datetime.now()
        data: dict[str, object] = {
            "id": 1,
            "workspace_id": uuid.uuid4(),
            "first_name": "Alice",
            "last_name": "Smith",
            "email": "alice@example.com",
            "phone_number": "+15551234567",
            "company_name": "Acme",
            "status": "new",
            "lead_score": 0,
            "is_qualified": False,
            "qualification_signals": None,
            "qualified_at": None,
            "tags": None,
            "notes": None,
            "source": None,
            "source_campaign_id": None,
            "noshow_count": 0,
            "last_appointment_status": None,
            "tag_objects": [],
            "created_at": now,
            "updated_at": now,
        }
        data.update(overrides)
        return ContactResponse.model_validate(data)

    def test_valid_response(self) -> None:
        """Valid data creates ContactResponse."""
        response = self._make_response()
        assert response.first_name == "Alice"
        assert response.lead_score == 0

    def test_from_attributes_config(self) -> None:
        """model_config has from_attributes=True."""
        assert ContactResponse.model_config.get("from_attributes") is True

    def test_workspace_id_is_uuid(self) -> None:
        """workspace_id is a UUID."""
        response = self._make_response()
        assert isinstance(response.workspace_id, uuid.UUID)

    def test_response_derives_tags_from_normalized_relationships(self) -> None:
        """ORM responses expose tag names from loaded ContactTag relationships."""
        workspace_id = uuid.uuid4()
        now = datetime.now()
        vip = Tag(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            name="vip",
            color="#6366f1",
            created_at=now,
            updated_at=now,
        )
        warm = Tag(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            name="warm",
            color="#6366f1",
            created_at=now,
            updated_at=now,
        )
        contact = Contact(
            id=1,
            workspace_id=workspace_id,
            first_name="Alice",
            phone_number="+15551234567",
            company_name=None,
            status="new",
            lead_score=0,
            is_qualified=False,
            qualification_signals=None,
            qualified_at=None,
            notes=None,
            important_dates=None,
            source=None,
            source_campaign_id=None,
            noshow_count=0,
            last_appointment_status=None,
            last_engaged_at=None,
            engagement_score=0,
            created_at=now,
            updated_at=now,
            contact_tags=[
                ContactTag(contact_id=1, tag_id=vip.id, tag=vip),
                ContactTag(contact_id=1, tag_id=warm.id, tag=warm),
            ],
        )

        response = ContactResponse.model_validate(contact)

        assert response.tags == ["vip", "warm"]
        assert [tag.name for tag in response.tag_objects] == ["vip", "warm"]


class TestQualificationSignals:
    """Tests for QualificationSignals and QualificationSignalDetail."""

    def test_defaults(self) -> None:
        """Default QualificationSignals has empty/unknown values."""
        signals = QualificationSignals()
        assert signals.interest_level == "unknown"
        assert signals.pain_points == []
        assert signals.objections == []
        assert signals.conversation_count == 0

    def test_signal_detail_defaults(self) -> None:
        """QualificationSignalDetail defaults are false/zero."""
        detail = QualificationSignalDetail()
        assert detail.detected is False
        assert detail.value is None
        assert detail.confidence == 0.0

    def test_signal_detail_set(self) -> None:
        """QualificationSignalDetail accepts values."""
        detail = QualificationSignalDetail(
            detected=True, value="100k budget", confidence=0.85
        )
        assert detail.detected is True
        assert detail.confidence == 0.85


class TestBulkSchemas:
    """Tests for bulk operation schemas."""

    def test_bulk_status_update_request(self) -> None:
        """BulkStatusUpdateRequest validates literal status values."""
        req = BulkStatusUpdateRequest(ids=[1, 2, 3], status="qualified")
        assert req.ids == [1, 2, 3]
        assert req.status == "qualified"

    def test_bulk_status_invalid_status_raises(self) -> None:
        """Invalid status value raises ValidationError."""
        with pytest.raises(ValidationError):
            BulkStatusUpdateRequest.model_validate(
                {"ids": [1], "status": "invalid_status"}
            )

    def test_bulk_status_update_response(self) -> None:
        """BulkStatusUpdateResponse parses correctly."""
        resp = BulkStatusUpdateResponse(updated=5, failed=1, errors=["row 3: bad data"])
        assert resp.updated == 5
        assert len(resp.errors) == 1

    def test_bulk_delete_request(self) -> None:
        """BulkDeleteRequest validates correctly."""
        req = BulkDeleteRequest(ids=[10, 20, 30])
        assert len(req.ids) == 3

    def test_bulk_delete_response(self) -> None:
        """BulkDeleteResponse parses correctly."""
        resp = BulkDeleteResponse(deleted=3, failed=0, errors=[])
        assert resp.deleted == 3

    def test_contact_list_response(self) -> None:
        """ContactListResponse validates correctly."""
        resp = ContactListResponse(items=[], total=0, page=1, page_size=50, pages=0)
        assert resp.total == 0
        assert resp.items == []

    def test_contact_with_conversation_response(self) -> None:
        """ContactWithConversationResponse has unread_count default."""
        now = datetime.now()
        data = {
            "id": 1,
            "workspace_id": uuid.uuid4(),
            "first_name": "Bob",
            "last_name": None,
            "email": None,
            "phone_number": "+15559999999",
            "company_name": None,
            "status": "new",
            "lead_score": 0,
            "is_qualified": False,
            "qualification_signals": None,
            "qualified_at": None,
            "tags": None,
            "notes": None,
            "source": None,
            "source_campaign_id": None,
            "noshow_count": 0,
            "last_appointment_status": None,
            "tag_objects": [],
            "created_at": now,
            "updated_at": now,
        }
        resp = ContactWithConversationResponse.model_validate(data)
        assert resp.unread_count == 0
        assert resp.last_message_at is None
