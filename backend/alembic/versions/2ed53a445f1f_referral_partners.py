"""Referral partners: named roster plus per-partner attribution.

Revision ID: 2ed53a445f1f
Revises: 2d4c3339bb68
Create Date: 2026-07-30 10:17:43.540924

Referrals were collapsing into the single ``referral_partner`` lead-source
channel, so an owner could see that word of mouth closes but not which realtor,
insurance agent, trade, or BNI member sends the work — nor which one went quiet.

Adds:

- ``referral_partners`` — the named counterparty per workspace. ``email`` and
  ``phone`` are partner PII stored as :class:`app.core.encryption.EncryptedString`
  (Fernet ciphertext in ``TEXT``), matching ``service_locations`` and
  ``contacts``. Ciphertext is non-deterministic, so neither column carries an
  index; lookup keys off ``name``/``company``/``partner_type``. ``partner_type``
  is ``VARCHAR(50)`` (non-native enum), so future partner kinds need no DDL.
- ``contacts.referral_partner_id`` — which partner sent this lead.
- ``opportunities.referral_partner_id`` — the immutable snapshot that credits
  closed-won revenue, extending the existing lead-source snapshot rather than
  introducing a second attribution path.

Both FKs are nullable with ``ON DELETE SET NULL``: retiring a partner must never
delete a customer or a booked job. ``LeadSourceType.REFERRAL_PARTNER`` already
exists and is persisted as ``VARCHAR``, so no ``ALTER TYPE ... ADD VALUE`` is
needed here.

Reversible and non-destructive on upgrade: the new columns are additive and the
new table starts empty. The downgrade drops per-partner attribution that cannot
be reconstructed from the remaining channel-level data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.encryption import EncryptedString

# revision identifiers, used by Alembic.
revision: str = "2ed53a445f1f"
down_revision: str | None = "2d4c3339bb68"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PARTNER_TYPE = sa.Enum(
    "realtor",
    "insurance",
    "trade",
    "bni",
    "customer",
    "other",
    name="referralpartnertype",
    native_enum=False,
    create_constraint=False,
    length=50,
)


def upgrade() -> None:
    op.create_table(
        "referral_partners",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("company", sa.String(length=200), nullable=True),
        sa.Column("partner_type", _PARTNER_TYPE, server_default="other", nullable=False),
        # Partner contact PII — Fernet-encrypted, therefore unindexed.
        sa.Column("email", EncryptedString(), nullable=True),
        sa.Column("phone", EncryptedString(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("contact_id", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name=op.f("fk_referral_partners_contact_id_contacts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_referral_partners_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_referral_partners")),
        # Duplicate partner rows would split one partner's scoreboard in two.
        sa.UniqueConstraint("workspace_id", "name", name="uq_referral_partners_workspace_name"),
    )
    op.create_index(
        op.f("ix_referral_partners_contact_id"),
        "referral_partners",
        ["contact_id"],
        unique=False,
    )
    op.create_index(
        "ix_referral_partners_workspace_active",
        "referral_partners",
        ["workspace_id", "is_active"],
        unique=False,
    )
    op.create_index(
        op.f("ix_referral_partners_workspace_id"),
        "referral_partners",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_referral_partners_workspace_type",
        "referral_partners",
        ["workspace_id", "partner_type"],
        unique=False,
    )

    op.add_column(
        "contacts",
        sa.Column("referral_partner_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_contacts_referral_partner_id"),
        "contacts",
        ["referral_partner_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_contacts_referral_partner_id_referral_partners"),
        "contacts",
        "referral_partners",
        ["referral_partner_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "opportunities",
        sa.Column("referral_partner_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_opportunities_referral_partner_id"),
        "opportunities",
        ["referral_partner_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_opportunities_referral_partner_id_referral_partners"),
        "opportunities",
        "referral_partners",
        ["referral_partner_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_opportunities_referral_partner_id_referral_partners"),
        "opportunities",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_opportunities_referral_partner_id"), table_name="opportunities")
    op.drop_column("opportunities", "referral_partner_id")

    op.drop_constraint(
        op.f("fk_contacts_referral_partner_id_referral_partners"),
        "contacts",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_contacts_referral_partner_id"), table_name="contacts")
    op.drop_column("contacts", "referral_partner_id")

    op.drop_index("ix_referral_partners_workspace_type", table_name="referral_partners")
    op.drop_index(op.f("ix_referral_partners_workspace_id"), table_name="referral_partners")
    op.drop_index("ix_referral_partners_workspace_active", table_name="referral_partners")
    op.drop_index(op.f("ix_referral_partners_contact_id"), table_name="referral_partners")
    op.drop_table("referral_partners")
