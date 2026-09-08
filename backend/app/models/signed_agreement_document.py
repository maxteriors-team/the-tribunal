"""SignedAgreementDocument — the frozen PDF of a signed proposal.

**Why bytes live in Postgres.** This follows the precedent documented in
:mod:`app.models.contact_attachment`: no S3/R2 is provisioned for this
deployment and Railway disks are ephemeral, so a file written to local disk is
gone on the next deploy. An agreement PDF that vanishes is not evidence.

**Why the bytes are stored at all rather than re-rendered.** A document
regenerated from live data proves nothing — it shows what the catalog, the terms
box and the customer record say *today*, not what the customer saw and signed.
Re-rendering on demand would silently rewrite the agreement every time an
operator edits a price or the terms text. The row here is written exactly once,
at the moment of signature, and is thereafter immutable: ``sha256`` is computed
over these exact bytes at generation time, so any later mutation is detectable.
:meth:`app.services.quotes.agreement_document.generate_signed_agreement` refuses
to write a second row for a quote.

**Listing must never load ``data``.** A workspace with a few hundred signed
agreements is a few hundred megabytes of BYTEA; a list view that selects the
whole row will pull all of it into memory. Use ``load_only`` over
:data:`AGREEMENT_METADATA_COLUMNS`, matching how contact attachments avoid the
same trap.
"""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

if TYPE_CHECKING:
    from app.models.quote import Quote
    from app.models.workspace import Workspace


class SignedAgreementDocument(Base, WorkspaceScoped):
    """The immutable PDF generated when a customer signed a proposal."""

    __tablename__ = "signed_agreement_documents"
    __table_args__ = (
        # One agreement per quote, enforced in the database rather than only in
        # the service: the approval path is reachable concurrently (a customer
        # double-clicking "Accept" is the normal case), and two racing renders
        # would otherwise both insert, leaving two "originals" and no way to say
        # which one the customer was emailed.
        UniqueConstraint("quote_id", name="uq_signed_agreement_documents_quote"),
        Index(
            "ix_signed_agreement_documents_workspace_generated",
            "workspace_id",
            "generated_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # RESTRICT, not CASCADE: a signed agreement outlives the convenience of
    # deleting a quote. Dropping the quote row must not silently destroy the
    # evidence that a contract was formed.
    quote_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quotes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(127), nullable=False, default="application/pdf"
    )
    # BigInteger rather than Integer: cheap here, and it removes any chance of an
    # overflow on a pathologically large render.
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Hex SHA-256 over exactly the bytes in ``data``, computed at generation
    # time. Printed inside the document itself, so a produced copy can be checked
    # against the stored original without trusting either party's file.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Copy of ``quotes.terms_version`` as of signing, denormalized so the
    # certificate remains readable even if the quote is later revised.
    terms_version: Mapped[int] = mapped_column(Integer, nullable=False)

    workspace: Mapped["Workspace"] = relationship("Workspace")
    quote: Mapped["Quote"] = relationship("Quote")

    def __repr__(self) -> str:
        return (
            f"<SignedAgreementDocument(id={self.id}, quote_id={self.quote_id}, "
            f"byte_size={self.byte_size})>"
        )


# Every column except ``data``. Import this rather than hand-listing columns at
# each call site, so a future column addition cannot accidentally reintroduce a
# blob-loading list query.
AGREEMENT_METADATA_COLUMNS = (
    SignedAgreementDocument.id,
    SignedAgreementDocument.workspace_id,
    SignedAgreementDocument.quote_id,
    SignedAgreementDocument.generated_at,
    SignedAgreementDocument.filename,
    SignedAgreementDocument.content_type,
    SignedAgreementDocument.byte_size,
    SignedAgreementDocument.sha256,
    SignedAgreementDocument.terms_version,
)
