"""Pydantic validation tests for the Outbound Mission / Lead Miner schemas.

These tests don't touch the database — they exercise the schema contracts
that downstream API routes will rely on. The most important contract is the
``LeadProspectCreate`` validator that allows any single identifier
(phone, email, website, or owner name) but rejects payloads with none.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.lead_discovery_job import DiscoveryJobStatus, DiscoverySourceType
from app.models.lead_prospect import (
    EnrichmentProvider,
    EnrichmentResultStatus,
    ProspectIdentityKind,
    ProspectStatus,
)
from app.models.outbound_mission import MissionStatus
from app.models.outbound_sequence import (
    OutboundSequenceStatus,
    SequenceEnrollmentStatus,
    SequenceStepAttemptStatus,
    SequenceStepChannel,
)
from app.schemas.lead_discovery_job import (
    LeadDiscoveryJobCreate,
    LeadDiscoveryJobResponse,
)
from app.schemas.lead_prospect import (
    LeadEnrichmentResultCreate,
    LeadEnrichmentResultResponse,
    LeadProspectCreate,
    LeadProspectResponse,
)
from app.schemas.outbound_mission import (
    OutboundMissionCreate,
    OutboundMissionResponse,
)
from app.schemas.outbound_sequence import (
    OutboundSequenceCreate,
    OutboundSequenceEnrollmentResponse,
    OutboundSequenceResponse,
    OutboundSequenceStep,
    OutboundSequenceStepAttemptResponse,
)

# ---------------------------------------------------------------------------
# OutboundMissionCreate
# ---------------------------------------------------------------------------


class TestOutboundMissionCreate:
    def test_minimal_valid(self) -> None:
        m = OutboundMissionCreate(name="Q2 Outreach")
        assert m.name == "Q2 Outreach"
        assert m.objective == "book_call"
        assert m.timezone == "America/New_York"
        assert m.daily_prospect_cap == 100
        assert m.daily_outreach_cap == 50
        assert m.target_audience == {}
        assert m.discovery_config == {}

    def test_missing_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            OutboundMissionCreate()  # type: ignore[call-arg]

    def test_blank_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            OutboundMissionCreate(name="")

    def test_full_payload(self) -> None:
        m = OutboundMissionCreate(
            name="Demo Mission",
            description="Outbound to plumbers in Austin",
            objective="qualify",
            offer_id=uuid.uuid4(),
            default_agent_id=uuid.uuid4(),
            target_audience={"industries": ["plumbing"], "geo": "Austin, TX"},
            discovery_config={"sources": ["google_places"], "radius_km": 25},
            daily_prospect_cap=250,
            daily_outreach_cap=100,
            timezone="America/Chicago",
        )
        assert m.daily_prospect_cap == 250
        assert m.timezone == "America/Chicago"
        assert m.target_audience["geo"] == "Austin, TX"


# ---------------------------------------------------------------------------
# LeadProspectCreate — the partial-identity guardrail
# ---------------------------------------------------------------------------


class TestLeadProspectCreate:
    def test_phone_only_passes(self) -> None:
        p = LeadProspectCreate(phone_number="+15551234567")
        assert p.phone_number == "+15551234567"
        assert p.email is None
        assert p.website_url is None
        assert p.identity_kind is ProspectIdentityKind.MULTI  # default

    def test_email_only_passes(self) -> None:
        p = LeadProspectCreate(email="lead@acme.io")
        assert p.email == "lead@acme.io"

    def test_website_only_passes(self) -> None:
        p = LeadProspectCreate(website_url="https://acme.io")
        assert str(p.website_url) == "https://acme.io"

    def test_website_host_only_passes(self) -> None:
        p = LeadProspectCreate(website_host="acme.io")
        assert p.website_host == "acme.io"

    def test_owner_full_name_only_passes(self) -> None:
        p = LeadProspectCreate(full_name="Jane Doe")
        assert p.full_name == "Jane Doe"

    def test_first_last_only_passes(self) -> None:
        p = LeadProspectCreate(first_name="Jane", last_name="Doe")
        assert p.first_name == "Jane"

    def test_all_identifiers_missing_raises(self) -> None:
        with pytest.raises(ValidationError) as exc:
            LeadProspectCreate(
                title="CEO",
                company_name="Acme",
                source_type="manual",
            )
        assert "at least one identifier required" in str(exc.value)

    def test_invalid_email_raises(self) -> None:
        with pytest.raises(ValidationError):
            LeadProspectCreate(email="not-an-email")

    def test_explicit_identity_kind_respected(self) -> None:
        p = LeadProspectCreate(
            phone_number="+15551234567",
            identity_kind=ProspectIdentityKind.PHONE,
        )
        assert p.identity_kind is ProspectIdentityKind.PHONE


# ---------------------------------------------------------------------------
# LeadDiscoveryJobCreate
# ---------------------------------------------------------------------------


class TestLeadDiscoveryJobCreate:
    def test_minimal_valid(self) -> None:
        j = LeadDiscoveryJobCreate(source_type=DiscoverySourceType.GOOGLE_PLACES)
        assert j.source_type is DiscoverySourceType.GOOGLE_PLACES
        assert j.params == {}
        assert j.requested_count == 0

    def test_unknown_source_raises(self) -> None:
        with pytest.raises(ValidationError):
            LeadDiscoveryJobCreate(source_type="not_a_source")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# OutboundSequenceCreate
# ---------------------------------------------------------------------------


class TestOutboundSequenceCreate:
    def test_empty_steps_passes(self) -> None:
        s = OutboundSequenceCreate(name="Empty")
        assert s.steps == []
        assert s.max_attempts_per_step == 1
        assert s.timezone == "America/New_York"

    def test_step_entries_validated(self) -> None:
        s = OutboundSequenceCreate(
            name="3-step",
            steps=[
                OutboundSequenceStep(order=0, channel=SequenceStepChannel.EMAIL),
                OutboundSequenceStep(
                    order=1,
                    channel=SequenceStepChannel.SMS,
                    delay_hours=24,
                    template="Hey {{first_name}}",
                    stop_on_reply=True,
                ),
            ],
        )
        assert len(s.steps) == 2
        assert s.steps[1].delay_hours == 24
        assert s.steps[1].stop_on_reply is True

    def test_bad_step_channel_raises(self) -> None:
        with pytest.raises(ValidationError):
            OutboundSequenceCreate(
                name="Bad",
                steps=[{"order": 0, "channel": "carrier_pigeon"}],  # type: ignore[list-item]
            )


# ---------------------------------------------------------------------------
# Response schemas — from_attributes round-trip
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


class TestResponseSchemasFromAttributes:
    def test_outbound_mission_response_from_attributes(self) -> None:
        assert OutboundMissionResponse.model_config.get("from_attributes") is True

    def test_lead_prospect_response_from_attributes(self) -> None:
        assert LeadProspectResponse.model_config.get("from_attributes") is True

    def test_lead_discovery_job_response_from_attributes(self) -> None:
        assert LeadDiscoveryJobResponse.model_config.get("from_attributes") is True

    def test_outbound_sequence_response_from_attributes(self) -> None:
        assert OutboundSequenceResponse.model_config.get("from_attributes") is True

    def test_outbound_mission_response_round_trip(self) -> None:
        payload = {
            "id": uuid.uuid4(),
            "workspace_id": uuid.uuid4(),
            "created_by_id": None,
            "offer_id": None,
            "default_agent_id": None,
            "default_sequence_id": None,
            "name": "Test",
            "description": None,
            "objective": "book_call",
            "status": MissionStatus.ACTIVE,
            "target_audience": {},
            "discovery_config": {},
            "enrichment_config": {},
            "sequence_config": {},
            "default_from_phone_number": None,
            "default_from_email": None,
            "daily_prospect_cap": 100,
            "daily_outreach_cap": 50,
            "timezone": "America/New_York",
            "total_prospects_discovered": 0,
            "total_prospects_enriched": 0,
            "total_prospects_contacted": 0,
            "total_prospects_replied": 0,
            "total_prospects_qualified": 0,
            "total_contacts_created": 0,
            "total_appointments_booked": 0,
            "started_at": None,
            "paused_at": None,
            "completed_at": None,
            "archived_at": None,
            "last_run_at": None,
            "next_run_at": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        m = OutboundMissionResponse.model_validate(payload)
        assert m.status is MissionStatus.ACTIVE

    def test_lead_prospect_response_round_trip(self) -> None:
        payload = {
            "id": uuid.uuid4(),
            "workspace_id": uuid.uuid4(),
            "mission_id": None,
            "discovery_job_id": None,
            "contact_id": None,
            "identity_kind": ProspectIdentityKind.PHONE,
            "first_name": None,
            "last_name": None,
            "full_name": None,
            "title": None,
            "email": None,
            "phone_number": "+15551234567",
            "company_name": None,
            "website_url": None,
            "website_host": None,
            "linkedin_url": None,
            "country_code": None,
            "region": None,
            "city": None,
            "location_label": None,
            "source_type": None,
            "source_external_id": None,
            "source_query": None,
            "provenance": {},
            "evidence": [],
            "dedupe_key": None,
            "lead_score": 0,
            "qualification_score": 0,
            "status": ProspectStatus.NEW,
            "suppression_reason": None,
            "enrichment_attempts": 0,
            "last_enriched_at": None,
            "last_contacted_at": None,
            "last_replied_at": None,
            "last_failed_at": None,
            "reply_count": 0,
            "bounce_count": 0,
            "discovered_at": _now(),
            "promoted_at": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        p = LeadProspectResponse.model_validate(payload)
        assert p.identity_kind is ProspectIdentityKind.PHONE
        assert p.phone_number == "+15551234567"

    def test_lead_discovery_job_response_round_trip(self) -> None:
        payload = {
            "id": uuid.uuid4(),
            "workspace_id": uuid.uuid4(),
            "mission_id": None,
            "requested_by_id": None,
            "source_type": DiscoverySourceType.GOOGLE_PLACES,
            "source_label": "Austin plumbers",
            "query": "plumber austin tx",
            "params": {"radius_km": 25},
            "status": DiscoveryJobStatus.SUCCEEDED,
            "requested_count": 100,
            "discovered_count": 88,
            "duplicate_count": 12,
            "invalid_count": 0,
            "started_at": _now(),
            "completed_at": _now(),
            "last_error": None,
            "error_count": 0,
            "created_at": _now(),
            "updated_at": _now(),
        }
        j = LeadDiscoveryJobResponse.model_validate(payload)
        assert j.status is DiscoveryJobStatus.SUCCEEDED
        assert j.discovered_count == 88

    def test_outbound_sequence_response_round_trip(self) -> None:
        payload = {
            "id": uuid.uuid4(),
            "workspace_id": uuid.uuid4(),
            "name": "Default",
            "description": None,
            "status": OutboundSequenceStatus.DRAFT,
            "is_default": True,
            "steps": [],
            "channel_priority": None,
            "max_attempts_per_step": 1,
            "sending_hours_start": None,
            "sending_hours_end": None,
            "sending_days": None,
            "timezone": "America/New_York",
            "total_enrollments": 0,
            "total_completed": 0,
            "total_replied": 0,
            "total_converted": 0,
            "created_at": _now(),
            "updated_at": _now(),
        }
        s = OutboundSequenceResponse.model_validate(payload)
        assert s.is_default is True

    def test_enrollment_response_round_trip(self) -> None:
        payload = {
            "id": uuid.uuid4(),
            "workspace_id": uuid.uuid4(),
            "mission_id": None,
            "sequence_id": uuid.uuid4(),
            "prospect_id": uuid.uuid4(),
            "status": SequenceEnrollmentStatus.ACTIVE,
            "current_step": 0,
            "next_step_at": None,
            "last_attempt_at": None,
            "last_outcome": None,
            "cancel_reason": None,
            "attempts_made": 0,
            "successful_attempts": 0,
            "failed_attempts": 0,
            "enrolled_at": _now(),
            "completed_at": None,
            "paused_until": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        e = OutboundSequenceEnrollmentResponse.model_validate(payload)
        assert e.status is SequenceEnrollmentStatus.ACTIVE

    def test_step_attempt_response_round_trip(self) -> None:
        payload = {
            "id": uuid.uuid4(),
            "workspace_id": uuid.uuid4(),
            "enrollment_id": uuid.uuid4(),
            "prospect_id": uuid.uuid4(),
            "step_index": 0,
            "attempt_number": 1,
            "channel": SequenceStepChannel.SMS,
            "status": SequenceStepAttemptStatus.SUCCEEDED,
            "scheduled_at": _now(),
            "sent_at": _now(),
            "completed_at": _now(),
            "message_id": None,
            "conversation_id": None,
            "pending_action_id": None,
            "outcome": "delivered",
            "outcome_detail": {"telnyx_message_id": "abc"},
            "error_message": None,
            "template_snapshot": "Hello {{first_name}}",
            "rendered_body": "Hello Jane",
            "rendered_subject": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        a = OutboundSequenceStepAttemptResponse.model_validate(payload)
        assert a.channel is SequenceStepChannel.SMS

    def test_lead_enrichment_result_response_round_trip(self) -> None:
        payload = {
            "id": uuid.uuid4(),
            "workspace_id": uuid.uuid4(),
            "prospect_id": uuid.uuid4(),
            "mission_id": None,
            "provider": EnrichmentProvider.WEBSITE_SCRAPER,
            "status": EnrichmentResultStatus.SUCCESS,
            "request_payload": {"url": "https://acme.io"},
            "response_payload": {"title": "Acme"},
            "extracted": {"title": "Acme"},
            "score_delta": 5,
            "cost_cents": 1,
            "duration_ms": 1234,
            "error_message": None,
            "created_at": _now(),
        }
        r = LeadEnrichmentResultResponse.model_validate(payload)
        assert r.provider is EnrichmentProvider.WEBSITE_SCRAPER
        assert r.score_delta == 5


# ---------------------------------------------------------------------------
# LeadEnrichmentResultCreate
# ---------------------------------------------------------------------------


class TestLeadEnrichmentResultCreate:
    def test_minimal_valid(self) -> None:
        r = LeadEnrichmentResultCreate(
            prospect_id=uuid.uuid4(),
            provider=EnrichmentProvider.AI_CONTENT_ANALYZER,
            status=EnrichmentResultStatus.PARTIAL,
        )
        assert r.extracted == {}
        assert r.score_delta == 0
        assert r.provider is EnrichmentProvider.AI_CONTENT_ANALYZER
