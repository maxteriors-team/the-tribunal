"""Phone number daily statistics model."""

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.phone_number import PhoneNumber


class PhoneNumberDailyStats(Base):
    """Daily statistics for phone number sending and reputation tracking."""

    __tablename__ = "phone_number_daily_stats"
    __table_args__ = (UniqueConstraint("phone_number_id", "date", name="uq_phone_daily_stats"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone_number_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("phone_numbers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Send counts
    messages_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    messages_delivered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    messages_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Bounce tracking
    hard_bounces: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    soft_bounces: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Compliance
    spam_complaints: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    opt_outs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    phone_number: Mapped["PhoneNumber"] = relationship("PhoneNumber")

    def __repr__(self) -> str:
        return (
            f"<PhoneNumberDailyStats(phone_number_id={self.phone_number_id}, "
            f"date={self.date}, sent={self.messages_sent})>"
        )
