"""add outbound missions and lead miner

Creates the seven tables that back the Outbound Mission / Lead Miner feature:

1. ``outbound_sequences`` — reusable multi-channel outreach templates.
2. ``outbound_missions`` — top-level discovery + enrichment + outreach runs.
   References ``outbound_sequences`` via ``default_sequence_id``, so sequences
   must exist first.
3. ``lead_discovery_jobs`` — discovery runs that emit prospects.
4. ``lead_prospects`` — partial-identity lead candidates (phone-only,
   email-only, website-only, or owner-name-only allowed).
5. ``lead_enrichment_results`` — append-only audit of provider calls.
6. ``outbound_sequence_enrollments`` — per-prospect enrollment in a sequence.
7. ``outbound_sequence_step_attempts`` — per-attempt execution records.

Pure additive migration: no existing tables are altered. ``contacts`` keeps
``phone_number`` NOT NULL; partial-identity leads live on
``lead_prospects`` and only promote into ``contacts`` once they carry a phone.

Revision ID: 20260521_add_outbound_missions_and_lead_miner
Revises: b5c6d7e8f9a0
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "20260521_add_outbound_missions_and_lead_miner"
down_revision: str | Sequence[str] | None = "b5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# --- helpers --------------------------------------------------------------


def _uuid_pk() -> sa.Column[sa.types.TypeEngine]:  # pragma: no cover - trivial
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def _timestamps() -> list[sa.Column[sa.types.TypeEngine]]:  # pragma: no cover
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    ]


# --- upgrade --------------------------------------------------------------


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1) outbound_sequences
    # ------------------------------------------------------------------
    op.create_table(
        "outbound_sequences",
        _uuid_pk(),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "steps",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "channel_priority",
            postgresql.ARRAY(sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "max_attempts_per_step",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("sending_hours_start", sa.Time(), nullable=True),
        sa.Column("sending_hours_end", sa.Time(), nullable=True),
        sa.Column("sending_days", postgresql.ARRAY(sa.Integer()), nullable=True),
        sa.Column(
            "timezone",
            sa.String(50),
            nullable=False,
            server_default="America/New_York",
        ),
        sa.Column("total_enrollments", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_replied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_converted", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
    )
    op.create_index(
        "ix_outbound_sequences_workspace_id",
        "outbound_sequences",
        ["workspace_id"],
    )
    op.create_index(
        "ix_outbound_sequences_status",
        "outbound_sequences",
        ["status"],
    )
    op.create_index(
        "ix_outbound_sequences_workspace_status",
        "outbound_sequences",
        ["workspace_id", "status"],
    )

    # ------------------------------------------------------------------
    # 2) outbound_missions  (references outbound_sequences)
    # ------------------------------------------------------------------
    op.create_table(
        "outbound_missions",
        _uuid_pk(),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "offer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("offers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "default_agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "default_sequence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outbound_sequences.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "objective",
            sa.String(50),
            nullable=False,
            server_default="book_call",
        ),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "target_audience",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "discovery_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "enrichment_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "sequence_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("default_from_phone_number", sa.String(50), nullable=True),
        sa.Column("default_from_email", sa.String(320), nullable=True),
        sa.Column("daily_prospect_cap", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("daily_outreach_cap", sa.Integer(), nullable=False, server_default="50"),
        sa.Column(
            "timezone",
            sa.String(50),
            nullable=False,
            server_default="America/New_York",
        ),
        sa.Column(
            "total_prospects_discovered",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_prospects_enriched",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_prospects_contacted",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_prospects_replied",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_prospects_qualified",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_contacts_created",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_appointments_booked",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index(
        "ix_outbound_missions_workspace_id",
        "outbound_missions",
        ["workspace_id"],
    )
    op.create_index(
        "ix_outbound_missions_created_by_id",
        "outbound_missions",
        ["created_by_id"],
    )
    op.create_index(
        "ix_outbound_missions_offer_id",
        "outbound_missions",
        ["offer_id"],
    )
    op.create_index(
        "ix_outbound_missions_default_agent_id",
        "outbound_missions",
        ["default_agent_id"],
    )
    op.create_index(
        "ix_outbound_missions_default_sequence_id",
        "outbound_missions",
        ["default_sequence_id"],
    )
    op.create_index(
        "ix_outbound_missions_status",
        "outbound_missions",
        ["status"],
    )
    op.create_index(
        "ix_outbound_missions_workspace_status",
        "outbound_missions",
        ["workspace_id", "status"],
    )
    op.create_index(
        "ix_outbound_missions_workspace_updated_at",
        "outbound_missions",
        ["workspace_id", "updated_at"],
        postgresql_ops={"updated_at": "DESC"},
    )

    # ------------------------------------------------------------------
    # 3) lead_discovery_jobs
    # ------------------------------------------------------------------
    op.create_table(
        "lead_discovery_jobs",
        _uuid_pk(),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outbound_missions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "requested_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_label", sa.String(255), nullable=True),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("requested_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discovered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
    )
    op.create_index(
        "ix_lead_discovery_jobs_workspace_id",
        "lead_discovery_jobs",
        ["workspace_id"],
    )
    op.create_index(
        "ix_lead_discovery_jobs_mission_id",
        "lead_discovery_jobs",
        ["mission_id"],
    )
    op.create_index(
        "ix_lead_discovery_jobs_requested_by_id",
        "lead_discovery_jobs",
        ["requested_by_id"],
    )
    op.create_index(
        "ix_lead_discovery_jobs_status",
        "lead_discovery_jobs",
        ["status"],
    )
    op.create_index(
        "ix_lead_discovery_jobs_mission_status",
        "lead_discovery_jobs",
        ["mission_id", "status"],
    )
    op.create_index(
        "ix_lead_discovery_jobs_workspace_created_at",
        "lead_discovery_jobs",
        ["workspace_id", "created_at"],
        postgresql_ops={"created_at": "DESC"},
    )

    # ------------------------------------------------------------------
    # 4) lead_prospects
    # ------------------------------------------------------------------
    op.create_table(
        "lead_prospects",
        _uuid_pk(),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outbound_missions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "discovery_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lead_discovery_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "contact_id",
            sa.BigInteger(),
            sa.ForeignKey("contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "identity_kind",
            sa.String(50),
            nullable=False,
            server_default="multi",
        ),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("title", sa.String(255), nullable=True),
        # EncryptedString / LookupHash both use TEXT impl
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("email_hash", sa.Text(), nullable=True),
        sa.Column("phone_number", sa.Text(), nullable=True),
        sa.Column("phone_hash", sa.Text(), nullable=True),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("website_url", sa.String(1024), nullable=True),
        sa.Column("website_host", sa.String(255), nullable=True),
        sa.Column("website_host_hash", sa.Text(), nullable=True),
        sa.Column("linkedin_url", sa.String(500), nullable=True),
        sa.Column("owner_name_hash", sa.Text(), nullable=True),
        sa.Column("country_code", sa.String(2), nullable=True),
        sa.Column("region", sa.String(100), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("location_label", sa.String(255), nullable=True),
        sa.Column("source_type", sa.String(50), nullable=True),
        sa.Column("source_external_id", sa.String(255), nullable=True),
        sa.Column("source_query", sa.Text(), nullable=True),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("dedupe_key", sa.String(64), nullable=True),
        sa.Column("lead_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qualification_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="new",
        ),
        sa.Column("suppression_reason", sa.String(255), nullable=True),
        sa.Column("enrichment_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_enriched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_contacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reply_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bounce_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "workspace_id",
            "dedupe_key",
            name="uq_lead_prospects_workspace_dedupe_key",
        ),
    )
    op.create_index(
        "ix_lead_prospects_workspace_id",
        "lead_prospects",
        ["workspace_id"],
    )
    op.create_index(
        "ix_lead_prospects_mission_id",
        "lead_prospects",
        ["mission_id"],
    )
    op.create_index(
        "ix_lead_prospects_discovery_job_id",
        "lead_prospects",
        ["discovery_job_id"],
    )
    op.create_index(
        "ix_lead_prospects_contact_id",
        "lead_prospects",
        ["contact_id"],
    )
    op.create_index("ix_lead_prospects_email_hash", "lead_prospects", ["email_hash"])
    op.create_index("ix_lead_prospects_phone_hash", "lead_prospects", ["phone_hash"])
    op.create_index(
        "ix_lead_prospects_website_host_hash",
        "lead_prospects",
        ["website_host_hash"],
    )
    op.create_index(
        "ix_lead_prospects_owner_name_hash",
        "lead_prospects",
        ["owner_name_hash"],
    )
    op.create_index(
        "ix_lead_prospects_source_type",
        "lead_prospects",
        ["source_type"],
    )
    op.create_index("ix_lead_prospects_status", "lead_prospects", ["status"])
    op.create_index(
        "ix_lead_prospects_workspace_status",
        "lead_prospects",
        ["workspace_id", "status"],
    )
    op.create_index(
        "ix_lead_prospects_workspace_source",
        "lead_prospects",
        ["workspace_id", "source_type"],
    )
    op.create_index(
        "ix_lead_prospects_workspace_score",
        "lead_prospects",
        ["workspace_id", "lead_score"],
        postgresql_ops={"lead_score": "DESC"},
    )
    op.create_index(
        "ix_lead_prospects_mission_status",
        "lead_prospects",
        ["mission_id", "status"],
    )
    op.create_index(
        "ix_lead_prospects_source_external_id",
        "lead_prospects",
        ["source_type", "source_external_id"],
    )

    # ------------------------------------------------------------------
    # 5) lead_enrichment_results
    # ------------------------------------------------------------------
    op.create_table(
        "lead_enrichment_results",
        _uuid_pk(),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "prospect_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lead_prospects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outbound_missions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column(
            "request_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "response_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "extracted",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("score_delta", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_cents", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_lead_enrichment_results_workspace_id",
        "lead_enrichment_results",
        ["workspace_id"],
    )
    op.create_index(
        "ix_lead_enrichment_results_prospect_id",
        "lead_enrichment_results",
        ["prospect_id"],
    )
    op.create_index(
        "ix_lead_enrichment_results_mission_id",
        "lead_enrichment_results",
        ["mission_id"],
    )
    op.create_index(
        "ix_lead_enrichment_results_provider_status",
        "lead_enrichment_results",
        ["provider", "status"],
    )
    op.create_index(
        "ix_lead_enrichment_results_workspace_created_at",
        "lead_enrichment_results",
        ["workspace_id", "created_at"],
        postgresql_ops={"created_at": "DESC"},
    )

    # ------------------------------------------------------------------
    # 6) outbound_sequence_enrollments
    # ------------------------------------------------------------------
    op.create_table(
        "outbound_sequence_enrollments",
        _uuid_pk(),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outbound_missions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "sequence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outbound_sequences.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "prospect_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lead_prospects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="active",
        ),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_step_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outcome", sa.String(50), nullable=True),
        sa.Column("cancel_reason", sa.String(255), nullable=True),
        sa.Column("attempts_made", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "successful_attempts", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "enrolled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_until", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "sequence_id",
            "prospect_id",
            name="uq_outbound_sequence_enrollments_sequence_prospect",
        ),
    )
    op.create_index(
        "ix_outbound_sequence_enrollments_workspace_id",
        "outbound_sequence_enrollments",
        ["workspace_id"],
    )
    op.create_index(
        "ix_outbound_sequence_enrollments_mission_id",
        "outbound_sequence_enrollments",
        ["mission_id"],
    )
    op.create_index(
        "ix_outbound_sequence_enrollments_sequence_id",
        "outbound_sequence_enrollments",
        ["sequence_id"],
    )
    op.create_index(
        "ix_outbound_sequence_enrollments_prospect_id",
        "outbound_sequence_enrollments",
        ["prospect_id"],
    )
    op.create_index(
        "ix_outbound_sequence_enrollments_status",
        "outbound_sequence_enrollments",
        ["status"],
    )
    op.create_index(
        "ix_outbound_sequence_enrollments_next_step_at",
        "outbound_sequence_enrollments",
        ["next_step_at"],
    )
    op.create_index(
        "ix_outbound_sequence_enrollments_status_next_step",
        "outbound_sequence_enrollments",
        ["status", "next_step_at"],
    )
    op.create_index(
        "ix_outbound_sequence_enrollments_mission_status",
        "outbound_sequence_enrollments",
        ["mission_id", "status"],
    )

    # ------------------------------------------------------------------
    # 7) outbound_sequence_step_attempts
    # ------------------------------------------------------------------
    op.create_table(
        "outbound_sequence_step_attempts",
        _uuid_pk(),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "enrollment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "outbound_sequence_enrollments.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "prospect_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lead_prospects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "pending_action_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pending_actions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("outcome", sa.String(50), nullable=True),
        sa.Column(
            "outcome_detail",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("template_snapshot", sa.Text(), nullable=True),
        sa.Column("rendered_body", sa.Text(), nullable=True),
        sa.Column("rendered_subject", sa.String(255), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "enrollment_id",
            "step_index",
            "attempt_number",
            name="uq_outbound_step_attempts_enrollment_step_attempt",
        ),
    )
    op.create_index(
        "ix_outbound_sequence_step_attempts_workspace_id",
        "outbound_sequence_step_attempts",
        ["workspace_id"],
    )
    op.create_index(
        "ix_outbound_sequence_step_attempts_enrollment_id",
        "outbound_sequence_step_attempts",
        ["enrollment_id"],
    )
    op.create_index(
        "ix_outbound_sequence_step_attempts_prospect_id",
        "outbound_sequence_step_attempts",
        ["prospect_id"],
    )
    op.create_index(
        "ix_outbound_sequence_step_attempts_message_id",
        "outbound_sequence_step_attempts",
        ["message_id"],
    )
    op.create_index(
        "ix_outbound_sequence_step_attempts_conversation_id",
        "outbound_sequence_step_attempts",
        ["conversation_id"],
    )
    op.create_index(
        "ix_outbound_sequence_step_attempts_pending_action_id",
        "outbound_sequence_step_attempts",
        ["pending_action_id"],
    )
    op.create_index(
        "ix_outbound_sequence_step_attempts_status",
        "outbound_sequence_step_attempts",
        ["status"],
    )
    op.create_index(
        "ix_outbound_step_attempts_enrollment_step",
        "outbound_sequence_step_attempts",
        ["enrollment_id", "step_index"],
    )
    op.create_index(
        "ix_outbound_step_attempts_status_scheduled_at",
        "outbound_sequence_step_attempts",
        ["status", "scheduled_at"],
    )


# --- downgrade ------------------------------------------------------------


def downgrade() -> None:
    # 7) outbound_sequence_step_attempts
    op.drop_index(
        "ix_outbound_step_attempts_status_scheduled_at",
        table_name="outbound_sequence_step_attempts",
    )
    op.drop_index(
        "ix_outbound_step_attempts_enrollment_step",
        table_name="outbound_sequence_step_attempts",
    )
    op.drop_index(
        "ix_outbound_sequence_step_attempts_status",
        table_name="outbound_sequence_step_attempts",
    )
    op.drop_index(
        "ix_outbound_sequence_step_attempts_pending_action_id",
        table_name="outbound_sequence_step_attempts",
    )
    op.drop_index(
        "ix_outbound_sequence_step_attempts_conversation_id",
        table_name="outbound_sequence_step_attempts",
    )
    op.drop_index(
        "ix_outbound_sequence_step_attempts_message_id",
        table_name="outbound_sequence_step_attempts",
    )
    op.drop_index(
        "ix_outbound_sequence_step_attempts_prospect_id",
        table_name="outbound_sequence_step_attempts",
    )
    op.drop_index(
        "ix_outbound_sequence_step_attempts_enrollment_id",
        table_name="outbound_sequence_step_attempts",
    )
    op.drop_index(
        "ix_outbound_sequence_step_attempts_workspace_id",
        table_name="outbound_sequence_step_attempts",
    )
    op.drop_table("outbound_sequence_step_attempts")

    # 6) outbound_sequence_enrollments
    op.drop_index(
        "ix_outbound_sequence_enrollments_mission_status",
        table_name="outbound_sequence_enrollments",
    )
    op.drop_index(
        "ix_outbound_sequence_enrollments_status_next_step",
        table_name="outbound_sequence_enrollments",
    )
    op.drop_index(
        "ix_outbound_sequence_enrollments_next_step_at",
        table_name="outbound_sequence_enrollments",
    )
    op.drop_index(
        "ix_outbound_sequence_enrollments_status",
        table_name="outbound_sequence_enrollments",
    )
    op.drop_index(
        "ix_outbound_sequence_enrollments_prospect_id",
        table_name="outbound_sequence_enrollments",
    )
    op.drop_index(
        "ix_outbound_sequence_enrollments_sequence_id",
        table_name="outbound_sequence_enrollments",
    )
    op.drop_index(
        "ix_outbound_sequence_enrollments_mission_id",
        table_name="outbound_sequence_enrollments",
    )
    op.drop_index(
        "ix_outbound_sequence_enrollments_workspace_id",
        table_name="outbound_sequence_enrollments",
    )
    op.drop_table("outbound_sequence_enrollments")

    # 5) lead_enrichment_results
    op.drop_index(
        "ix_lead_enrichment_results_workspace_created_at",
        table_name="lead_enrichment_results",
    )
    op.drop_index(
        "ix_lead_enrichment_results_provider_status",
        table_name="lead_enrichment_results",
    )
    op.drop_index(
        "ix_lead_enrichment_results_mission_id",
        table_name="lead_enrichment_results",
    )
    op.drop_index(
        "ix_lead_enrichment_results_prospect_id",
        table_name="lead_enrichment_results",
    )
    op.drop_index(
        "ix_lead_enrichment_results_workspace_id",
        table_name="lead_enrichment_results",
    )
    op.drop_table("lead_enrichment_results")

    # 4) lead_prospects
    op.drop_index(
        "ix_lead_prospects_source_external_id", table_name="lead_prospects"
    )
    op.drop_index("ix_lead_prospects_mission_status", table_name="lead_prospects")
    op.drop_index("ix_lead_prospects_workspace_score", table_name="lead_prospects")
    op.drop_index("ix_lead_prospects_workspace_source", table_name="lead_prospects")
    op.drop_index("ix_lead_prospects_workspace_status", table_name="lead_prospects")
    op.drop_index("ix_lead_prospects_status", table_name="lead_prospects")
    op.drop_index("ix_lead_prospects_source_type", table_name="lead_prospects")
    op.drop_index("ix_lead_prospects_owner_name_hash", table_name="lead_prospects")
    op.drop_index(
        "ix_lead_prospects_website_host_hash", table_name="lead_prospects"
    )
    op.drop_index("ix_lead_prospects_phone_hash", table_name="lead_prospects")
    op.drop_index("ix_lead_prospects_email_hash", table_name="lead_prospects")
    op.drop_index("ix_lead_prospects_contact_id", table_name="lead_prospects")
    op.drop_index("ix_lead_prospects_discovery_job_id", table_name="lead_prospects")
    op.drop_index("ix_lead_prospects_mission_id", table_name="lead_prospects")
    op.drop_index("ix_lead_prospects_workspace_id", table_name="lead_prospects")
    op.drop_table("lead_prospects")

    # 3) lead_discovery_jobs
    op.drop_index(
        "ix_lead_discovery_jobs_workspace_created_at",
        table_name="lead_discovery_jobs",
    )
    op.drop_index(
        "ix_lead_discovery_jobs_mission_status", table_name="lead_discovery_jobs"
    )
    op.drop_index("ix_lead_discovery_jobs_status", table_name="lead_discovery_jobs")
    op.drop_index(
        "ix_lead_discovery_jobs_requested_by_id", table_name="lead_discovery_jobs"
    )
    op.drop_index(
        "ix_lead_discovery_jobs_mission_id", table_name="lead_discovery_jobs"
    )
    op.drop_index(
        "ix_lead_discovery_jobs_workspace_id", table_name="lead_discovery_jobs"
    )
    op.drop_table("lead_discovery_jobs")

    # 2) outbound_missions
    op.drop_index(
        "ix_outbound_missions_workspace_updated_at", table_name="outbound_missions"
    )
    op.drop_index(
        "ix_outbound_missions_workspace_status", table_name="outbound_missions"
    )
    op.drop_index("ix_outbound_missions_status", table_name="outbound_missions")
    op.drop_index(
        "ix_outbound_missions_default_sequence_id", table_name="outbound_missions"
    )
    op.drop_index(
        "ix_outbound_missions_default_agent_id", table_name="outbound_missions"
    )
    op.drop_index("ix_outbound_missions_offer_id", table_name="outbound_missions")
    op.drop_index(
        "ix_outbound_missions_created_by_id", table_name="outbound_missions"
    )
    op.drop_index(
        "ix_outbound_missions_workspace_id", table_name="outbound_missions"
    )
    op.drop_table("outbound_missions")

    # 1) outbound_sequences
    op.drop_index(
        "ix_outbound_sequences_workspace_status", table_name="outbound_sequences"
    )
    op.drop_index("ix_outbound_sequences_status", table_name="outbound_sequences")
    op.drop_index(
        "ix_outbound_sequences_workspace_id", table_name="outbound_sequences"
    )
    op.drop_table("outbound_sequences")
