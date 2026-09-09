"""Generate, persist, and deliver the signed agreement PDF.

The document is written **once**, at the moment of signature, from data frozen
at that moment:

* the proposal as accepted, read out of ``quote.proposal_document`` — never
  re-priced from the live catalog;
* the cancellation terms verbatim from ``quote.signed_terms_snapshot``;
* the signature block and completion certificate, from the ceremony columns on
  the quote.

Nothing here re-derives a price, a term, or a timestamp. A document regenerated
from live data would show today's catalog and today's terms text and would
quietly disagree with what the customer signed, which is precisely the failure
this table exists to prevent.

**Failure is never fatal to the approval.** Every entry point returns rather
than raises: a lost PDF is recoverable (regenerate from the frozen quote row),
a lost signature is not. Callers invoke this after the approval transaction has
committed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.contact import Contact
from app.models.quote import Quote
from app.models.signed_agreement_document import SignedAgreementDocument
from app.models.workspace import Workspace
from app.services.email import (
    EmailAttachment,
    send_event_notification_email,
)
from app.services.email_layout import Block, Brand, Callout, Details, Divider, Paragraph
from app.services.idempotency import derive_outbound_key
from app.services.notification_recipients import workspace_notification_email_users
from app.services.quotes.agreement_pdf import AgreementRenderError, render_pdf
from app.services.quotes.proposal_template import get_proposal_template
from app.utils.timezones import resolve_workspace_timezone, workspace_timezone_name

__all__ = [
    "agreement_attachment",
    "deliver_signed_agreement",
    "ensure_signed_agreement",
    "generate_signed_agreement",
]

logger = structlog.get_logger()

_TS_FORMAT = "%B %-d, %Y at %-I:%M %p %Z"


def _fmt_ts(value: datetime | None, tz: Any) -> str:
    """Render a timestamp in the workspace's own timezone.

    The workspace zone, not UTC: this document is read by the operator and the
    customer during a dispute, and "signed at 02:14" is actively misleading when
    the customer signed at 9pm local.
    """
    if value is None:
        return "—"
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.astimezone(tz).strftime(_TS_FORMAT)


def _fmt_money(amount: Decimal | float | None, currency: str) -> str:
    if amount is None:
        return "—"
    return f"{(currency or 'USD').upper()} {float(amount):,.2f}"


def _payment_method_label(quote: Quote) -> str:
    """Describe how the customer is paying, from the frozen quote columns."""
    choice = quote.proposal_payment_choice
    if choice == "fifty_percent_down":
        return "50% down, balance due at completion"
    if choice == "pay_in_full":
        return "Paid in full"
    if quote.deposit_payment_method:
        return str(quote.deposit_payment_method).replace("_", " ").title()
    return "Not specified"


def _accepted_amount(quote: Quote) -> Decimal | float | None:
    """The amount the customer committed to at signing.

    Reads the server-owned columns written during approval; never recomputes
    from the catalog.
    """
    if quote.proposal_payment_amount is not None:
        return quote.proposal_payment_amount
    if quote.deposit_amount_fixed is not None:
        return quote.deposit_amount_fixed
    if quote.deposit_percentage is not None and quote.total is not None:
        return Decimal(str(quote.total)) * Decimal(str(quote.deposit_percentage)) / Decimal(100)
    return None


def _line_item_rows(quote: Quote, currency: str) -> dict[str, str]:
    """The quote's own stored line items, for a plain (non-wizard) quote.

    A plain line-item quote has no ``proposal_document`` pricing: its lines live
    in ``quote_line_items``, already frozen at their accepted values. Reading
    them is not "re-pricing from the live catalog" — nothing is recomputed, the
    stored per-line totals are printed verbatim.

    Without this the agreement for every plain quote showed no items at all,
    which is the one thing a contract cannot omit.
    """
    rows: dict[str, str] = {}
    for index, item in enumerate(quote.line_items, start=1):
        label = item.name or f"Item {index}"
        if item.quantity and float(item.quantity) != 1:
            label = f"{label} (x{float(item.quantity):g})"
        # Disambiguate two lines that share a name; dict keys must stay unique or
        # one silently overwrites the other.
        if label in rows:
            label = f"{label} #{index}"
        rows[label] = _fmt_money(item.total, currency)
    return rows


def _accepted_line_rows(document: Mapping[str, Any] | None) -> dict[str, str]:
    """Line items exactly as they appear in the accepted proposal snapshot.

    Values come from the snapshot's own stored strings/numbers. If the snapshot
    is a shape this does not recognize, it yields nothing rather than guessing —
    an empty section is honest, an invented price is not.
    """
    if not isinstance(document, Mapping):
        return {}
    rows: dict[str, str] = {}
    selected = document.get("selected_tier")
    tiers = document.get("tiers")
    if selected and isinstance(tiers, list):
        for tier in tiers:
            if not isinstance(tier, Mapping) or tier.get("key") != selected:
                continue
            name = str(tier.get("name") or tier.get("label") or selected)
            rows["Package"] = name
            price = tier.get("price") or tier.get("total")
            if price is not None:
                rows["Package price"] = str(price)
            if tier.get("warranty"):
                rows["Warranty"] = str(tier["warranty"])
            break
    items = document.get("line_items") or document.get("lines")
    if isinstance(items, list):
        for index, item in enumerate(items, start=1):
            if not isinstance(item, Mapping):
                continue
            label = str(item.get("name") or item.get("description") or f"Item {index}")
            total = item.get("total")
            qty = item.get("quantity") or item.get("qty")
            detail = f"{total}" if total is not None else ""
            if qty is not None:
                detail = f"Qty {qty}" + (f" — {detail}" if detail else "")
            rows[label] = detail or "Included"
    return rows


def _build_blocks(
    *,
    quote: Quote,
    workspace: Workspace,
    contact: Contact | None,
    business_name: str,
    content_digest: str,
) -> list[Block]:
    """Compose the agreement's content blocks.

    Every value is read from frozen columns or the accepted snapshot. Blocks
    HTML-escape their own content, so the customer's typed name and the
    operator's terms text cannot inject markup.
    """
    tz = resolve_workspace_timezone(workspace)
    currency = quote.currency or "USD"
    customer_name = quote.signed_name or (contact.full_name if contact else "") or "—"

    blocks: list[Block] = [
        Paragraph(
            f"This document records the agreement accepted by {customer_name} "
            f"from {business_name}, and the evidence of that acceptance."
        ),
        Details(
            {
                "Agreement": quote.title or f"Proposal {quote.number}",
                "Quote number": quote.number,
                "Customer": customer_name,
                "Accepted total": _fmt_money(quote.total, currency),
            }
        ),
        Divider(),
    ]

    # 1. The proposal as accepted.
    blocks.append(Paragraph("The proposal you accepted", muted=False))
    # Wizard proposals carry their accepted pricing in the snapshot; plain quotes
    # carry it in their own line items. Both are frozen values, neither is
    # recomputed from the live catalog.
    accepted_rows = _accepted_line_rows(quote.proposal_document) or _line_item_rows(quote, currency)
    if accepted_rows:
        blocks.append(Details(accepted_rows))
    else:
        blocks.append(
            Paragraph(
                "See the itemized proposal on record for this quote number.",
                muted=True,
            )
        )
    blocks.append(Divider())

    # 2. Cancellation terms, verbatim from the snapshot taken at signing.
    blocks.append(Paragraph("Cancellation and terms"))
    blocks.append(
        Paragraph(
            quote.signed_terms_snapshot
            or "No written cancellation terms were presented with this proposal."
        )
    )
    blocks.append(Divider())

    # 3. Signature block.
    blocks.append(Paragraph("Signature"))
    blocks.append(
        Details(
            {
                "Signed by (typed name)": quote.signed_name or "—",
                "Signed at": _fmt_ts(quote.signed_at, tz),
                "Timezone": workspace_timezone_name(workspace),
                "IP address": quote.signed_ip or "—",
            }
        )
    )
    blocks.append(Divider())

    # 4. Completion certificate — the section that settles disputes.
    blocks.append(Paragraph("Completion certificate"))
    blocks.append(
        Details(
            {
                "Quote number": quote.number,
                "Proposal version": str(quote.proposal_version),
                "Terms version": str(quote.terms_version),
                "First viewed": _fmt_ts(quote.first_viewed_at, tz),
                "Last viewed": _fmt_ts(quote.last_viewed_at, tz),
                "View count": str(quote.view_count or 0),
                "E-consent accepted at": _fmt_ts(quote.econsent_accepted_at, tz),
                "Cancellation clause acknowledged at": _fmt_ts(
                    quote.cancellation_acknowledged_at, tz
                ),
                "Amount due at signing": _fmt_money(_accepted_amount(quote), currency),
                "Payment method": _payment_method_label(quote),
                "Content SHA-256": content_digest,
            }
        )
    )
    blocks.append(
        Callout(
            "The Content SHA-256 above is computed over the signed facts recorded "
            "in this certificate. A separate SHA-256 of this PDF file's exact "
            "bytes was recorded when the file was generated and is held with it "
            "on file."
        )
    )
    return blocks


def _content_digest(quote: Quote, business_name: str) -> str:
    """Hash the agreement's material facts, canonically serialized.

    **Why this is not the file hash.** A file cannot contain its own SHA-256:
    embedding the digest changes the bytes the digest was taken over. The
    printed value is therefore a hash of the *content* -- the exact frozen facts
    below -- while ``signed_agreement_documents.sha256`` is the hash of the
    stored PDF bytes. Both are recorded; only one of them can also live inside
    the page, and this is the one that can.

    It is still the useful one for a dispute: it changes if any signed fact
    changes, and it can be recomputed from the quote row years later, whereas a
    file hash only proves a particular file was not edited.

    Field order is fixed and values are NUL-separated so that two different
    field sets cannot serialize to the same string.
    """
    parts = (
        str(quote.id),
        quote.number or "",
        str(quote.proposal_version),
        str(quote.terms_version),
        business_name,
        quote.signed_name or "",
        quote.signed_at.isoformat() if quote.signed_at else "",
        quote.signed_ip or "",
        quote.econsent_accepted_at.isoformat() if quote.econsent_accepted_at else "",
        (
            quote.cancellation_acknowledged_at.isoformat()
            if quote.cancellation_acknowledged_at
            else ""
        ),
        quote.signed_terms_snapshot or "",
        str(quote.total),
        quote.currency or "",
        json.dumps(quote.proposal_document or {}, sort_keys=True, default=str),
    )
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


def _render_agreement_bytes(
    *,
    quote: Quote,
    workspace: Workspace,
    contact: Contact | None,
) -> tuple[bytes, str]:
    """Render the PDF once. Returns ``(pdf_bytes, file_sha256_hex)``.

    The returned hash is taken over exactly the bytes the caller will store, at
    generation time, so it certifies the stored file. The digest printed *inside*
    the document is the content digest -- see :func:`_content_digest` for why
    those must be two different values.
    """
    template = get_proposal_template(workspace)
    business_name = template.business_name or workspace.name
    pdf_bytes = render_pdf(
        heading=f"Signed agreement — {quote.number}",
        blocks=_build_blocks(
            quote=quote,
            workspace=workspace,
            contact=contact,
            business_name=business_name,
            content_digest=_content_digest(quote, business_name),
        ),
        brand=Brand(business_name=business_name),
    )
    return pdf_bytes, hashlib.sha256(pdf_bytes).hexdigest()


def _agreement_filename(quote: Quote) -> str:
    safe_number = "".join(c for c in (quote.number or "quote") if c.isalnum() or c in "-_")
    return f"signed-agreement-{safe_number or 'quote'}.pdf"


async def generate_signed_agreement(
    db: AsyncSession,
    quote: Quote,
    *,
    contact: Contact | None = None,
) -> SignedAgreementDocument | None:
    """Render and store the agreement for a signed quote, exactly once.

    Returns the persisted row, or ``None`` when nothing was written — because
    the quote carries no signature, because a document already exists, or
    because rendering failed. ``None`` is never an error the caller must handle:
    the approval has already committed and stands on its own.

    Regeneration is refused. The stored document is the evidence; overwriting it
    with a fresh render silently replaces what the customer was sent.
    """
    if quote.signed_at is None or not quote.signed_name:
        # Operator-side approvals and legacy rows never ran the ceremony. There
        # is no signature to certify, so there is no agreement to produce.
        return None

    existing = await db.scalar(
        select(SignedAgreementDocument).where(SignedAgreementDocument.quote_id == quote.id)
    )
    if existing is not None:
        logger.info(
            "signed_agreement_already_exists",
            quote_id=str(quote.id),
            document_id=str(existing.id),
        )
        return existing

    workspace = await db.get(Workspace, quote.workspace_id)
    if workspace is None:
        logger.warning("signed_agreement_workspace_missing", quote_id=str(quote.id))
        return None
    # Explicit: rendering reads ``quote.line_items``, and this runs after the
    # approval commit, so a lazy load here would raise MissingGreenlet in async
    # SQLAlchemy rather than quietly returning an empty item list.
    await db.refresh(quote, ["line_items"])
    if contact is None and quote.contact_id:
        contact = await db.get(Contact, quote.contact_id)

    try:
        pdf_bytes, sha256 = _render_agreement_bytes(
            quote=quote, workspace=workspace, contact=contact
        )
    except AgreementRenderError as exc:
        # Retryable: the quote row still holds every input, so a later call
        # produces the same document. Logged at error level because a signed
        # agreement with no PDF needs someone to notice.
        logger.error(
            "signed_agreement_render_failed",
            quote_id=str(quote.id),
            workspace_id=str(quote.workspace_id),
            error=str(exc),
        )
        return None

    document = SignedAgreementDocument(
        workspace_id=quote.workspace_id,
        quote_id=quote.id,
        filename=_agreement_filename(quote),
        content_type="application/pdf",
        byte_size=len(pdf_bytes),
        data=pdf_bytes,
        sha256=sha256,
        terms_version=quote.terms_version,
    )
    db.add(document)
    try:
        await db.commit()
    except IntegrityError:
        # Lost the race against a concurrent approval (a double-clicked Accept).
        # The winner's document is the original; keep it and discard this render.
        await db.rollback()
        logger.info("signed_agreement_race_lost", quote_id=str(quote.id))
        winner: SignedAgreementDocument | None = await db.scalar(
            select(SignedAgreementDocument).where(SignedAgreementDocument.quote_id == quote.id)
        )
        return winner

    await db.refresh(document)
    logger.info(
        "signed_agreement_generated",
        quote_id=str(quote.id),
        workspace_id=str(quote.workspace_id),
        document_id=str(document.id),
        byte_size=document.byte_size,
        sha256=sha256,
    )
    return document


async def _notify_workspace(
    db: AsyncSession,
    quote: Quote,
    document: SignedAgreementDocument,
    attachment: EmailAttachment,
) -> None:
    """Send the internal copy to the workspace's notification recipients."""
    users = await workspace_notification_email_users(
        db, quote.workspace_id, notification_type="quote_accepted"
    )
    download_url = (
        f"{settings.frontend_url.rstrip('/')}/quotes/{quote.id}"  # operator-facing detail page
    )
    for user in users:
        if not user.email or not user.notification_email:
            continue
        await send_event_notification_email(
            to_email=user.email,
            subject=f"Signed agreement — {quote.number}",
            heading="A proposal was signed",
            intro=(
                f"{quote.signed_name} signed {quote.title or quote.number}. "
                f"The countersigned agreement is attached and is also on the quote in the CRM: "
                f"{download_url}"
            ),
            details={
                "Quote number": quote.number,
                "Signed by": quote.signed_name or "—",
                "Document SHA-256": document.sha256,
            },
            idempotency_key=derive_outbound_key("signed_agreement_internal", document.id, user.id),
            attachments=[attachment],
        )


async def deliver_signed_agreement(
    db: AsyncSession,
    quote: Quote,
    document: SignedAgreementDocument,
) -> None:
    """Email the stored agreement to the workspace's internal recipients.

    Best-effort by contract: raises nothing. The customer's own copy rides along
    with the acceptance receipt in
    :meth:`QuoteService._send_acceptance_receipt`, which already runs
    post-commit.
    """
    attachment = EmailAttachment(
        filename=document.filename,
        content=document.data,
        content_type=document.content_type,
    )
    try:
        await _notify_workspace(db, quote, document, attachment)
    # Broad by design: delivery must not disturb the approval.
    except Exception as exc:
        logger.warning(
            "signed_agreement_internal_delivery_failed",
            quote_id=str(quote.id),
            document_id=str(document.id),
            error=str(exc),
        )


async def ensure_signed_agreement(
    db: AsyncSession,
    quote: Quote,
    *,
    contact: Contact | None = None,
) -> SignedAgreementDocument | None:
    """Generate the agreement if missing, then send the internal copy.

    The single entry point for the approval flow. Swallows every exception: this
    runs after the approval has committed, and no failure here may undo it.
    """
    try:
        document = await generate_signed_agreement(db, quote, contact=contact)
    # Broad by design: see docstring -- a lost PDF is recoverable, a lost
    # signature is not.
    except Exception as exc:
        logger.error(
            "signed_agreement_generation_error",
            quote_id=str(quote.id),
            error=str(exc),
        )
        return None
    if document is None:
        return None
    await deliver_signed_agreement(db, quote, document)
    return document


def agreement_attachment(
    document: SignedAgreementDocument | None,
) -> Sequence[EmailAttachment]:
    """Wrap a stored document for attaching to the customer's receipt.

    ``None`` yields no attachments, so a failed render degrades the receipt to
    link-only rather than breaking the send.
    """
    if document is None:
        return ()
    return (
        EmailAttachment(
            filename=document.filename,
            content=document.data,
            content_type=document.content_type,
        ),
    )
