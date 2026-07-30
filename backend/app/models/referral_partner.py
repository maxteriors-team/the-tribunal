"""Referral partner model: the individual people/companies who send work.

A home-service business's most weather-proof and market-proof lead source is a
network of referral partners — realtors, insurance agents, adjacent trades
(HVAC/plumbing/landscaping), BNI/networking-group members, and delighted past
customers. Without per-partner records every referral collapses into the single
:attr:`~app.models.lead_source.LeadSourceType.REFERRAL_PARTNER` channel, so the
owner can see *that* referrals close but never *who* sends them or who stopped.

:class:`ReferralPartner` is the named counterparty. Attribution itself is not
duplicated here: a referred lead carries
:attr:`app.models.contact.Contact.referral_partner_id` and its deals carry the
immutable snapshot :attr:`app.models.opportunity.Opportunity.referral_partner_id`,
which is the same first-touch/snapshot path lead sources already use. The
scoreboard in :mod:`app.services.lead_sources.referral_partner_service` reads
those two columns; nothing else needs a parallel attribution path.

``email`` and ``phone`` are partner contact PII and are Fernet-encrypted at rest
via :class:`app.core.encryption.EncryptedString`, matching
:class:`app.models.field_service.ServiceLocation` and
:class:`app.models.contact.Contact`. Encrypted columns are not SQL-queryable, so
partner lookup keys off ``name``/``company``/``partner_type`` — never the email
or phone.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedString
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.workspace import Workspace


class ReferralPartnerType(StrEnum):
    """What kind of relationship the partner is, for grouping the scoreboard.

    Persisted as ``VARCHAR(50)`` (``native_enum=False``, ``create_constraint=False``
    on :attr:`ReferralPartner.partner_type`), **not** a Postgres ``ENUM`` type, so
    adding a member here needs no DDL migration — the same treatment as
    :class:`app.models.lead_source.LeadSourceType`. Keep values under 50 chars.
    """

    REALTOR = "realtor"
    INSURANCE = "insurance"
    TRADE = "trade"
    BNI = "bni"
    CUSTOMER = "customer"
    OTHER = "other"


class ReferralPartner(Base):
    """A named person or company that sends referral work to the workspace."""

    __tablename__ = "referral_partners"
    __table_args__ = (
        # Two rows for the same partner would split their scoreboard in half and
        # defeat the whole point of tracking partners individually.
        UniqueConstraint("workspace_id", "name", name="uq_referral_partners_workspace_name"),
        Index("ix_referral_partners_workspace_active", "workspace_id", "is_active"),
        Index("ix_referral_partners_workspace_type", "workspace_id", "partner_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Identity. ``name`` is the person ("Dana Ruiz"); ``company`` is where they
    # work ("Keller Williams"), which is how an owner recognizes a partner whose
    # name they half-remember.
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    partner_type: Mapped[ReferralPartnerType] = mapped_column(
        SAEnum(
            ReferralPartnerType,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ReferralPartnerType.OTHER,
        server_default=ReferralPartnerType.OTHER.value,
    )

    # Partner contact details — PII, Fernet-encrypted at rest and therefore not
    # SQL-queryable. Never filter or sort on these columns.
    email: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    phone: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)

    # Operator notes about the relationship ("meets Thursdays, prefers text").
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # A partner is very often already a customer/contact in the CRM (the classic
    # "happy customer who keeps sending neighbors"). Optional so a partner who
    # has never been a customer — a realtor, an insurance adjuster — needs no
    # placeholder contact row. ``SET NULL`` keeps the partner and their whole
    # historical scoreboard intact if that contact is later deleted.
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Deactivating retires a partner from pickers without deleting the history
    # that their past referrals still need.
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships are one-directional (cf. ``ServiceLocation.contact``) so
    # neither the workspace nor the encrypted Contact model has to widen.
    # ``contacts`` also points back here (a referred lead names its partner), so
    # the join has to name its side explicitly or SQLAlchemy sees two FK paths.
    workspace: Mapped["Workspace"] = relationship("Workspace")
    contact: Mapped["Contact | None"] = relationship("Contact", foreign_keys=[contact_id])

    def __repr__(self) -> str:
        return (
            f"<ReferralPartner(id={self.id}, name={self.name}, partner_type={self.partner_type})>"
        )
