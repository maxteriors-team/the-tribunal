"""consolidate pre-existing schema drift with the ORM.

A batch of model changes (the in-progress "unified queue + actions" work plus
earlier encryption/index refactors) landed without matching migrations, so a
freshly-migrated database drifted from ``Base.metadata`` and ``alembic check``
failed. This revision brings the schema back in sync. It is intentionally
scoped to the genuine drift only:

- ``contacts`` address columns widen ``VARCHAR`` -> ``TEXT`` to back
  :class:`EncryptedString` (Fernet ciphertext is stored as TEXT). No
  re-encryption is performed: ``EncryptedString`` reads legacy plaintext back
  unchanged, and new writes are encrypted, so the change is backward
  compatible.
- Several composite/single indexes are realigned to what the ORM now declares
  (drops indexes the models no longer define, adds the ones they do).
- ``offers.public_slug`` moves from a unique *index* to a unique *constraint*.
- ``campaign_reports.campaign_id`` collapses its duplicate unique
  constraint + plain index into a single unique index.
- ``opportunity_contacts`` association columns become nullable and gain their
  per-column indexes. The ORM association table declares no primary key, so the
  legacy composite ``pk_opportunity_contacts`` (which also enforced NOT NULL) is
  dropped to match. NOTE: this removes the database-level uniqueness guarantee
  on ``(opportunity_id, contact_id)`` pairs; the downgrade restores it but will
  fail if duplicate/NULL rows were introduced while the PK was absent.

Expression (``... DESC``) indexes are NOT touched here: they already match the
database and are excluded from autogenerate comparison in ``alembic/env.py``.
The ad-library tables (``ad_advertisers`` / ``ad_creatives``) are likewise left
untouched — their schema is correct as authored in ``c5f19e53d001``.

Revision ID: d1e2f3a4b5c6
Revises: c5f19e53d001
Create Date: 2026-06-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | Sequence[str] | None = "c5f19e53d001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (column, legacy varchar length) for the contacts address PII columns.
_ADDRESS_COLUMNS: tuple[tuple[str, int], ...] = (
    ("address_line1", 255),
    ("address_line2", 255),
    ("address_city", 100),
    ("address_state", 50),
    ("address_zip", 20),
)


def upgrade() -> None:
    # contacts: widen address PII columns to TEXT for EncryptedString storage.
    for column, _length in _ADDRESS_COLUMNS:
        op.alter_column(
            "contacts",
            column,
            type_=sa.Text(),
            existing_type=sa.String(length=_length),
            existing_nullable=True,
        )

    # contacts: replace composite indexes with the single-column indexes the
    # ORM now declares via ``index=True``.
    op.drop_index("ix_contacts_workspace_last_engaged", table_name="contacts")
    op.drop_index("ix_contacts_workspace_sms_consent_status", table_name="contacts")
    op.create_index("ix_contacts_last_engaged_at", "contacts", ["last_engaged_at"])
    op.create_index("ix_contacts_sms_consent_status", "contacts", ["sms_consent_status"])

    # conversations: standalone next_followup_at index no longer declared.
    op.drop_index("ix_conversations_next_followup_at", table_name="conversations")

    # bandit_decisions / demo_requests / improvement_suggestions: drop standalone
    # created_at indexes the models no longer declare.
    op.drop_index("ix_bandit_decisions_created_at", table_name="bandit_decisions")
    op.drop_index("ix_demo_requests_created_at", table_name="demo_requests")
    op.drop_index("ix_improvement_suggestions_created_at", table_name="improvement_suggestions")

    # email_events: drop composite (workspace_id, occurred_at) index.
    op.drop_index("ix_email_events_workspace_occurred", table_name="email_events")

    # campaign_reports: ORM declares a single unique index on campaign_id. Collapse
    # the duplicate unique-constraint + plain index into one unique index, and drop
    # the standalone created_at index.
    op.drop_index("ix_campaign_reports_created_at", table_name="campaign_reports")
    op.drop_constraint("uq_campaign_reports_campaign_id", "campaign_reports", type_="unique")
    op.drop_index("ix_campaign_reports_campaign_id", table_name="campaign_reports")
    op.create_index(
        "ix_campaign_reports_campaign_id",
        "campaign_reports",
        ["campaign_id"],
        unique=True,
    )

    # offers: public_slug is a unique *constraint* in the ORM, not a unique index.
    op.drop_index("ix_offers_public_slug", table_name="offers")
    op.create_unique_constraint("uq_offers_public_slug", "offers", ["public_slug"])

    # opportunity_contacts: the ORM association table declares no primary key and
    # both columns are nullable with their own index. Drop the legacy composite
    # PK first so the NOT NULL it implies can be lifted. The PK name varies by
    # environment (databases created before the naming convention auto-named it
    # ``opportunity_contacts_pkey``), so resolve the actual name from the catalog.
    pk_name = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'opportunity_contacts'::regclass AND contype = 'p'"
            )
        )
        .scalar()
    )
    if pk_name:
        op.drop_constraint(pk_name, "opportunity_contacts", type_="primary")
    op.alter_column(
        "opportunity_contacts",
        "opportunity_id",
        existing_type=sa.UUID(),
        nullable=True,
    )
    op.alter_column(
        "opportunity_contacts",
        "contact_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.create_index("ix_opportunity_contacts_contact_id", "opportunity_contacts", ["contact_id"])
    op.create_index(
        "ix_opportunity_contacts_opportunity_id",
        "opportunity_contacts",
        ["opportunity_id"],
    )

    # phone_numbers: drop indexes the ORM no longer declares.
    op.drop_index("ix_phone_numbers_mac_relay_sender_id", table_name="phone_numbers")
    op.drop_index("ix_phone_numbers_workspace_imessage_enabled", table_name="phone_numbers")

    # prompt_versions: drop composite (agent_id, is_active, arm_status) index.
    op.drop_index("ix_prompt_versions_agent_active_arms", table_name="prompt_versions")

    # device_tokens: databases that predate the naming convention auto-named the
    # unique constraint ``device_tokens_expo_push_token_key``. Rename it to the
    # conventional name so autogenerate stops flagging drop/add drift. No-op on
    # databases that already carry the conventional name.
    legacy_uq = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM pg_constraint "
                "WHERE conname = 'device_tokens_expo_push_token_key' "
                "AND conrelid = 'device_tokens'::regclass"
            )
        )
        .scalar()
    )
    if legacy_uq:
        op.execute(
            "ALTER TABLE device_tokens RENAME CONSTRAINT "
            "device_tokens_expo_push_token_key TO uq_device_tokens_expo_push_token"
        )


def downgrade() -> None:
    # prompt_versions.
    op.create_index(
        "ix_prompt_versions_agent_active_arms",
        "prompt_versions",
        ["agent_id", "is_active", "arm_status"],
    )

    # phone_numbers.
    op.create_index(
        "ix_phone_numbers_workspace_imessage_enabled",
        "phone_numbers",
        ["workspace_id", "imessage_enabled"],
    )
    op.create_index(
        "ix_phone_numbers_mac_relay_sender_id",
        "phone_numbers",
        ["mac_relay_sender_id"],
    )

    # opportunity_contacts.
    op.drop_index("ix_opportunity_contacts_opportunity_id", table_name="opportunity_contacts")
    op.drop_index("ix_opportunity_contacts_contact_id", table_name="opportunity_contacts")
    op.alter_column(
        "opportunity_contacts",
        "contact_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.alter_column(
        "opportunity_contacts",
        "opportunity_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.create_primary_key(
        "pk_opportunity_contacts",
        "opportunity_contacts",
        ["opportunity_id", "contact_id"],
    )

    # offers.
    op.drop_constraint("uq_offers_public_slug", "offers", type_="unique")
    op.create_index("ix_offers_public_slug", "offers", ["public_slug"], unique=True)

    # campaign_reports.
    op.drop_index("ix_campaign_reports_campaign_id", table_name="campaign_reports")
    op.create_index("ix_campaign_reports_campaign_id", "campaign_reports", ["campaign_id"])
    op.create_unique_constraint(
        "uq_campaign_reports_campaign_id", "campaign_reports", ["campaign_id"]
    )
    op.create_index("ix_campaign_reports_created_at", "campaign_reports", ["created_at"])

    # email_events.
    op.create_index(
        "ix_email_events_workspace_occurred",
        "email_events",
        ["workspace_id", "occurred_at"],
    )

    # bandit_decisions / demo_requests / improvement_suggestions.
    op.create_index(
        "ix_improvement_suggestions_created_at",
        "improvement_suggestions",
        ["created_at"],
    )
    op.create_index("ix_demo_requests_created_at", "demo_requests", ["created_at"])
    op.create_index("ix_bandit_decisions_created_at", "bandit_decisions", ["created_at"])

    # conversations.
    op.create_index("ix_conversations_next_followup_at", "conversations", ["next_followup_at"])

    # contacts indexes.
    op.drop_index("ix_contacts_sms_consent_status", table_name="contacts")
    op.drop_index("ix_contacts_last_engaged_at", table_name="contacts")
    op.create_index(
        "ix_contacts_workspace_sms_consent_status",
        "contacts",
        ["workspace_id", "sms_consent_status"],
    )
    op.create_index(
        "ix_contacts_workspace_last_engaged",
        "contacts",
        ["workspace_id", "last_engaged_at"],
    )

    # contacts address columns back to VARCHAR.
    for column, length in _ADDRESS_COLUMNS:
        op.alter_column(
            "contacts",
            column,
            type_=sa.String(length=length),
            existing_type=sa.Text(),
            existing_nullable=True,
        )
