"""Roofline permanent-vs-temporary comparison model.

A workspace-scoped, token-keyed snapshot of a rep's roofline estimate so a
homeowner can open a public page and see the permanent-vs-seasonal savings. Only
the *inputs* the rep measured are persisted (linear feet, optional zones, run
complexity, takedown/storage); the money is recomputed from the live workspace
pricing config on every public view, so a rate change is reflected and no stale
totals are stored.

Linear feet is stored here for internal recompute **only** — it is deliberately
never serialized onto the public :class:`app.schemas.estimate.PublicComparison`
payload. Mirrors the public-token pattern of :class:`app.models.quote.Quote`.
"""

import secrets
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.user import User
    from app.models.workspace import Workspace


def generate_comparison_token() -> str:
    """Return an unguessable URL-safe token for a public comparison page.

    192 bits of entropy so the link can be shared without auth yet stays
    non-enumerable, matching :func:`app.models.quote.generate_quote_token`.
    """
    return secrets.token_urlsafe(24)


class RooflineComparison(Base, WorkspaceScoped):
    """A shareable permanent-vs-temporary lighting comparison for one roofline."""

    __tablename__ = "roofline_comparisons"
    __table_args__ = (
        CheckConstraint(
            "permanent_complexity IN ('easy', 'standard', 'complex')",
            name="ck_roofline_comparisons_permanent_complexity",
        ),
        CheckConstraint(
            "proposal_side IN ('permanent', 'seasonal', 'comparison')",
            name="ck_roofline_comparisons_proposal_side",
        ),
        CheckConstraint(
            "discount_amount >= 0",
            name="ck_roofline_comparisons_discount_amount_nonnegative",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Public client-page token (unguessable, indexed for O(1) lookup).
    public_token: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True, default=generate_comparison_token
    )

    # Measured selection (INTERNAL — never serialized to the public payload).
    feet: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    channels: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # The scalar remains a fallback for legacy/no-map requests. Existing rows
    # migrate to Standard; new mixed-complexity designs retain their measured map.
    permanent_complexity: Mapped[Literal["easy", "standard", "complex"]] = mapped_column(
        String(20), nullable=False, default="standard", server_default="standard"
    )
    permanent_complexity_feet: Mapped[
        dict[Literal["easy", "standard", "complex"], float] | None
    ] = mapped_column(JSONB, nullable=True)
    takedown: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    storage: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Internal-only overrides of the per-linear-foot rates for this estimate
    # (permanent + seasonal). Separate from the workspace's customer-facing
    # pricing config and never serialized to the public comparison; NULL means
    # "use the standard configured rate" for that side when prices are recomputed
    # on each public view.
    per_ft_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    christmas_per_ft_override: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Seasonal decor selection (category key -> {option key -> value}). Stored so
    # a shared comparison persists the rep's trees/bushes/wreaths/garland picks;
    # prices are recomputed from live config on each public view. NULL/{} means
    # roofline-only. Only totals reach the public payload, never this selection.
    christmas_items: Mapped[dict[str, dict[str, float]] | None] = mapped_column(
        JSONB, nullable=True
    )

    # Optional seasonal package the rep selected when sharing (a
    # ``ChristmasPackage.key``). Recomputed prices use it to show the client that
    # package's total instead of the à la carte seasonal total; NULL means no
    # package was chosen. Only the total ever reaches the public payload.
    selected_package: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # Standalone lines the rep added outside the price book and outside any
    # package (a bucket-truck fee, a one-off custom install). Stored as the rep's
    # inputs — ``{label, description, quantity, unit_price, side}`` per
    # :class:`app.schemas.estimate.EstimateCustomLine` — and re-priced on every
    # public view like the rest of the estimate. NULL means none were added.
    custom_lines: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB, nullable=True)

    # Controls which customer package the shared link opens. Historical rows keep
    # the old comparison behavior; Light Designer links select one explicit side.
    proposal_side: Mapped[Literal["permanent", "seasonal", "comparison"]] = mapped_column(
        String(20), nullable=False, default="comparison", server_default="comparison"
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0"), server_default="0"
    )

    # Optional presentation context shown to the client / used internally.
    client_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Optional link to the CRM customer this estimate was saved for. Nullable so
    # anonymous "just share a link" estimates still work; SET NULL keeps the
    # comparison if the contact is later deleted. ``contacts.id`` is a BigInteger.
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # The client's "no thanks" on a shared estimate. NULL means undecided: an
    # estimate is a price to consider, so there is no pending/approved ladder
    # here, only whether they told us they are out. A timestamp rather than a
    # boolean so the rep knows *when* interest died, and it is set once -- a
    # second decline keeps the first timestamp.
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decline_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])
    contact: Mapped["Contact | None"] = relationship("Contact", foreign_keys=[contact_id])

    def __repr__(self) -> str:
        return f"<RooflineComparison(id={self.id}, token={self.public_token}, feet={self.feet})>"
