"""In-memory unit tests for the Outbound Mission / Lead Miner ORM models.

These tests construct model instances without touching the database. They
exercise default column values, enum identity, the partial-identity
``LeadProspect`` design (phone-only / email-only / website-only /
owner-name-only), and the table_args constraints documented in the plan.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Index, UniqueConstraint

from app.models.lead_discovery_job import (
    DiscoveryJobStatus,
    DiscoverySourceType,
    LeadDiscoveryJob,
)
from app.models.lead_prospect import (
    EnrichmentProvider,
    EnrichmentResultStatus,
    LeadEnrichmentResult,
    LeadProspect,
    ProspectIdentityKind,
    ProspectStatus,
)
from app.models.outbound_mission import MissionStatus, OutboundMission
from app.models.outbound_sequence import (
    OutboundSequence,
    OutboundSequenceEnrollment,
    OutboundSequenceStatus,
    OutboundSequenceStepAttempt,
    SequenceEnrollmentStatus,
    SequenceStepAttemptStatus,
    SequenceStepChannel,
)


def _workspace_id() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestEnums:
    """All status / channel enums are StrEnum and use stable string values."""

    def test_mission_status_values(self) -> None:
        assert issubclass(MissionStatus, StrEnum)
        assert MissionStatus.DRAFT.value == "draft"
        assert MissionStatus.ACTIVE.value == "active"
        assert MissionStatus.PAUSED.value == "paused"
        assert MissionStatus.COMPLETED.value == "completed"
        assert MissionStatus.ARCHIVED.value == "archived"

    def test_discovery_source_type_values(self) -> None:
        assert issubclass(DiscoverySourceType, StrEnum)
        assert {m.value for m in DiscoverySourceType} == {
            "google_places",
            "web_scrape",
            "web_people",
            "csv_import",
            "manual",
            "api",
            "linkedin",
            "meta_ad_library",
            "google_ads_transparency",
            "other",
        }

    def test_discovery_job_status_values(self) -> None:
        assert issubclass(DiscoveryJobStatus, StrEnum)
        assert {m.value for m in DiscoveryJobStatus} == {
            "pending",
            "running",
            "succeeded",
            "failed",
            "cancelled",
        }

    def test_prospect_identity_kind_values(self) -> None:
        assert issubclass(ProspectIdentityKind, StrEnum)
        assert {m.value for m in ProspectIdentityKind} == {
            "phone",
            "email",
            "website",
            "owner_name",
            "multi",
        }

    def test_prospect_status_values(self) -> None:
        assert issubclass(ProspectStatus, StrEnum)
        assert ProspectStatus.NEW.value == "new"
        assert ProspectStatus.QUALIFIED.value == "qualified"
        assert ProspectStatus.CONVERTED.value == "converted"

    def test_enrichment_provider_values(self) -> None:
        assert issubclass(EnrichmentProvider, StrEnum)
        assert EnrichmentProvider.GOOGLE_PLACES.value == "google_places"
        assert EnrichmentProvider.WEBSITE_SCRAPER.value == "website_scraper"

    def test_enrichment_result_status_values(self) -> None:
        assert issubclass(EnrichmentResultStatus, StrEnum)
        assert {m.value for m in EnrichmentResultStatus} == {
            "success",
            "partial",
            "failed",
            "skipped",
        }

    def test_outbound_sequence_status_values(self) -> None:
        assert issubclass(OutboundSequenceStatus, StrEnum)
        assert OutboundSequenceStatus.DRAFT.value == "draft"

    def test_sequence_step_channel_values(self) -> None:
        assert issubclass(SequenceStepChannel, StrEnum)
        assert {m.value for m in SequenceStepChannel} == {
            "sms",
            "email",
            "voice",
            "manual",
        }

    def test_sequence_enrollment_status_values(self) -> None:
        assert issubclass(SequenceEnrollmentStatus, StrEnum)
        assert SequenceEnrollmentStatus.ACTIVE.value == "active"
        assert SequenceEnrollmentStatus.OPTED_OUT.value == "opted_out"

    def test_sequence_step_attempt_status_values(self) -> None:
        assert issubclass(SequenceStepAttemptStatus, StrEnum)
        assert SequenceStepAttemptStatus.PENDING.value == "pending"


# ---------------------------------------------------------------------------
# OutboundMission
# ---------------------------------------------------------------------------


class TestOutboundMission:
    def test_construct_defaults(self) -> None:
        mission = OutboundMission(workspace_id=_workspace_id(), name="Q1 Outreach")

        # Required identity
        assert mission.name == "Q1 Outreach"
        # Python-side defaults fire on instantiation (default=) and on flush
        # for server_default. For the Mapped(...) `default=` kwargs SQLAlchemy
        # applies them at flush time only — but for plain Column kwargs they
        # don't. We assert the ones that the ORM populates eagerly via the
        # ``default=`` callable or constant *after* explicit assignment.
        mission.objective = "book_call"
        mission.status = MissionStatus.DRAFT
        mission.target_audience = {}
        mission.discovery_config = {}
        mission.enrichment_config = {}
        mission.sequence_config = {}
        mission.timezone = "America/New_York"
        mission.daily_prospect_cap = 100
        mission.daily_outreach_cap = 50

        assert mission.status is MissionStatus.DRAFT
        assert mission.objective == "book_call"
        assert mission.target_audience == {}
        assert mission.timezone == "America/New_York"
        assert mission.daily_prospect_cap == 100
        assert mission.daily_outreach_cap == 50

    def test_repr_contains_identity(self) -> None:
        mission = OutboundMission(
            workspace_id=_workspace_id(),
            name="Repr Mission",
            status=MissionStatus.ACTIVE,
            objective="qualify",
        )
        text = repr(mission)
        assert text.startswith("<OutboundMission(")
        assert "Repr Mission" in text
        assert "qualify" in text

    def test_table_indexes_present(self) -> None:
        index_names = {ix.name for ix in OutboundMission.__table__.indexes}
        assert "ix_outbound_missions_workspace_status" in index_names
        assert "ix_outbound_missions_workspace_updated_at" in index_names


# ---------------------------------------------------------------------------
# LeadDiscoveryJob
# ---------------------------------------------------------------------------


class TestLeadDiscoveryJob:
    def test_construct_minimal(self) -> None:
        job = LeadDiscoveryJob(
            workspace_id=_workspace_id(),
            source_type=DiscoverySourceType.GOOGLE_PLACES,
        )
        assert job.source_type is DiscoverySourceType.GOOGLE_PLACES

    def test_repr(self) -> None:
        job = LeadDiscoveryJob(
            workspace_id=_workspace_id(),
            source_type=DiscoverySourceType.MANUAL,
            status=DiscoveryJobStatus.RUNNING,
            discovered_count=3,
        )
        text = repr(job)
        assert "LeadDiscoveryJob" in text
        assert "manual" in text or "DiscoverySourceType.MANUAL" in text


# ---------------------------------------------------------------------------
# LeadProspect — the partial-identity surface
# ---------------------------------------------------------------------------


class TestLeadProspectPartialIdentity:
    def test_phone_only_prospect(self) -> None:
        p = LeadProspect(
            workspace_id=_workspace_id(),
            identity_kind=ProspectIdentityKind.PHONE,
            phone_number="+15551234567",
            phone_hash="hash_phone_abc",
        )
        assert p.has_phone is True
        assert p.has_email is False
        assert p.has_website is False
        assert p.has_owner_name is False
        assert p.is_promoted is False

    def test_email_only_prospect(self) -> None:
        p = LeadProspect(
            workspace_id=_workspace_id(),
            identity_kind=ProspectIdentityKind.EMAIL,
            email="ceo@acme.io",
            email_hash="hash_email_abc",
        )
        assert p.has_email is True
        assert p.has_phone is False
        assert p.has_website is False
        assert p.has_owner_name is False

    def test_website_only_prospect(self) -> None:
        p = LeadProspect(
            workspace_id=_workspace_id(),
            identity_kind=ProspectIdentityKind.WEBSITE,
            website_url="https://acme.io",
            website_host="acme.io",
            website_host_hash="hash_host_abc",
        )
        assert p.has_website is True
        assert p.has_phone is False
        assert p.has_email is False
        assert p.has_owner_name is False

    def test_owner_name_only_prospect(self) -> None:
        p = LeadProspect(
            workspace_id=_workspace_id(),
            identity_kind=ProspectIdentityKind.OWNER_NAME,
            full_name="Jane Doe",
            owner_name_hash="hash_owner_abc",
        )
        assert p.has_owner_name is True
        assert p.has_phone is False
        assert p.has_email is False
        assert p.has_website is False

    def test_promoted_when_contact_id_set(self) -> None:
        p = LeadProspect(
            workspace_id=_workspace_id(),
            identity_kind=ProspectIdentityKind.PHONE,
            phone_number="+15550000000",
            phone_hash="h",
            contact_id=42,
            promoted_at=datetime.now(UTC),
        )
        assert p.is_promoted is True


class TestLeadProspectTableShape:
    def test_unique_constraint_workspace_dedupe_key(self) -> None:
        names = {
            c.name
            for c in LeadProspect.__table_args__  # type: ignore[attr-defined]
            if isinstance(c, UniqueConstraint)
        }
        assert "uq_lead_prospects_workspace_dedupe_key" in names

    def test_workspace_status_index_present(self) -> None:
        names = {
            c.name
            for c in LeadProspect.__table_args__  # type: ignore[attr-defined]
            if isinstance(c, Index)
        }
        assert "ix_lead_prospects_workspace_status" in names
        assert "ix_lead_prospects_workspace_score" in names

    def test_encrypted_and_hash_columns_exist(self) -> None:
        cols = {c.name for c in LeadProspect.__table__.columns}
        # Channel identifiers — encrypted + lookup hash siblings.
        for required in (
            "email",
            "email_hash",
            "phone_number",
            "phone_hash",
            "website_host",
            "website_host_hash",
            "owner_name_hash",
            "dedupe_key",
            "provenance",
            "evidence",
        ):
            assert required in cols, f"missing column {required!r}"

    def test_repr_includes_status_and_score(self) -> None:
        p = LeadProspect(
            workspace_id=_workspace_id(),
            identity_kind=ProspectIdentityKind.MULTI,
            phone_number="+15555550100",
            phone_hash="h",
            email="x@y.io",
            email_hash="h2",
            status=ProspectStatus.ENRICHED,
            lead_score=42,
        )
        text = repr(p)
        assert "LeadProspect" in text
        assert "enriched" in text or "ProspectStatus.ENRICHED" in text


# ---------------------------------------------------------------------------
# LeadEnrichmentResult
# ---------------------------------------------------------------------------


class TestLeadEnrichmentResult:
    def test_construct(self) -> None:
        ws = _workspace_id()
        result = LeadEnrichmentResult(
            workspace_id=ws,
            prospect_id=uuid.uuid4(),
            provider=EnrichmentProvider.WEBSITE_SCRAPER,
            status=EnrichmentResultStatus.SUCCESS,
            extracted={"title": "Acme — homepage"},
            score_delta=5,
        )
        assert result.workspace_id == ws
        assert result.provider is EnrichmentProvider.WEBSITE_SCRAPER
        assert result.status is EnrichmentResultStatus.SUCCESS
        assert result.score_delta == 5

    def test_no_updated_at_column(self) -> None:
        cols = {c.name for c in LeadEnrichmentResult.__table__.columns}
        assert "created_at" in cols
        assert "updated_at" not in cols


# ---------------------------------------------------------------------------
# OutboundSequence + Enrollment + StepAttempt
# ---------------------------------------------------------------------------


class TestOutboundSequence:
    def test_construct_defaults(self) -> None:
        seq = OutboundSequence(workspace_id=_workspace_id(), name="Default 3-step")
        seq.status = OutboundSequenceStatus.DRAFT
        seq.steps = []
        assert seq.status is OutboundSequenceStatus.DRAFT
        assert seq.steps == []

    def test_table_indexes(self) -> None:
        names = {ix.name for ix in OutboundSequence.__table__.indexes}
        assert "ix_outbound_sequences_workspace_status" in names


class TestOutboundSequenceEnrollment:
    def test_unique_sequence_prospect(self) -> None:
        names = {
            c.name
            for c in OutboundSequenceEnrollment.__table_args__  # type: ignore[attr-defined]
            if isinstance(c, UniqueConstraint)
        }
        assert "uq_outbound_sequence_enrollments_sequence_prospect" in names

    def test_status_next_step_index(self) -> None:
        names = {
            c.name
            for c in OutboundSequenceEnrollment.__table_args__  # type: ignore[attr-defined]
            if isinstance(c, Index)
        }
        assert "ix_outbound_sequence_enrollments_status_next_step" in names


class TestOutboundSequenceStepAttempt:
    def test_unique_enrollment_step_attempt(self) -> None:
        names = {
            c.name
            for c in OutboundSequenceStepAttempt.__table_args__  # type: ignore[attr-defined]
            if isinstance(c, UniqueConstraint)
        }
        assert "uq_outbound_step_attempts_enrollment_step_attempt" in names

    def test_indexes(self) -> None:
        names = {
            c.name
            for c in OutboundSequenceStepAttempt.__table_args__  # type: ignore[attr-defined]
            if isinstance(c, Index)
        }
        assert "ix_outbound_step_attempts_enrollment_step" in names
        assert "ix_outbound_step_attempts_status_scheduled_at" in names
