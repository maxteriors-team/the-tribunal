"""Global opt-out model."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, event
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedString, LookupHash, hash_phone
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.workspace import Workspace


class GlobalOptOut(Base):
    """Global opt-out list for phone numbers across all campaigns in a workspace."""

    __tablename__ = "global_opt_outs"
    __table_args__ = (
        # Uniqueness must live on the deterministic hash: ``phone_number`` is
        # Fernet-encrypted and therefore ciphertext-unique on every insert, so a
        # constraint on it would never actually suppress a duplicate opt-out.
        UniqueConstraint("workspace_id", "phone_hash", name="uq_workspace_opt_out"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # PII at rest — ``phone_number`` is Fernet-encrypted via :class:`EncryptedString`.
    # ``phone_hash`` holds the BLAKE2b-keyed deterministic hash and carries the
    # index + unique constraint used for suppression-list lookups. Both are kept
    # in sync by the ``before_insert``/``before_update`` hook below, so no write
    # path can persist a number without its lookup hash.
    phone_number: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    phone_hash: Mapped[str] = mapped_column(LookupHash(), nullable=False, index=True)

    # Opt-out details
    opted_out_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    opt_out_keyword: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # STOP, UNSUBSCRIBE, etc.
    source_campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_channel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_actor_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_actor_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")

    def __repr__(self) -> str:
        # Never interpolate ``phone_number`` — reprs land in logs/error reports and
        # would defeat encrypting it at rest. ``phone_hash`` is only populated by
        # the hook below at flush time, so guard against the transient state.
        phone_hash = self.phone_hash
        fragment = f"{phone_hash[:8]}..." if phone_hash else None
        return f"<GlobalOptOut(workspace_id={self.workspace_id}, phone_hash={fragment})>"


def _sync_opt_out_lookup_hashes(_mapper: object, _connection: object, target: GlobalOptOut) -> None:
    """Keep the encrypted opt-out lookup hash in sync for all write paths."""
    if target.phone_number:
        target.phone_hash = hash_phone(target.phone_number)


event.listen(GlobalOptOut, "before_insert", _sync_opt_out_lookup_hashes)
event.listen(GlobalOptOut, "before_update", _sync_opt_out_lookup_hashes)
