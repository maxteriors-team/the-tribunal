"""Create invoice-payment receipt jobs inside the payment transaction."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import structlog
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.contact import Contact
from app.models.invoice import Invoice, InvoiceLineItem
from app.models.invoice_payment_receipt_outbox import InvoicePaymentReceiptOutbox
from app.models.workspace import Workspace
from app.services.idempotency import derive_outbound_key
from app.services.quotes.proposal_template import get_proposal_template

logger = structlog.get_logger().bind(component="invoice_receipt_outbox")


def _money(value: float) -> Decimal:
    return Decimal(f"{round(float(value), 2):.2f}")


async def _service_summary(db: AsyncSession, invoice: Invoice) -> str | None:
    if "line_items" in inspect(invoice).unloaded:
        line_items = list(
            (
                await db.scalars(
                    select(InvoiceLineItem)
                    .where(
                        InvoiceLineItem.invoice_id == invoice.id,
                        InvoiceLineItem.is_selected.is_(True),
                    )
                    .order_by(InvoiceLineItem.created_at, InvoiceLineItem.id)
                )
            ).all()
        )
    else:
        line_items = [item for item in invoice.line_items if item.is_selected]

    labels: list[str] = []
    for item in line_items[:25]:
        name = item.name.strip() or "Service"
        quantity = float(item.quantity)
        labels.append(f"{name} × {quantity:g}" if quantity != 1 else name)
    if len(line_items) > 25:
        labels.append(f"{len(line_items) - 25} more services")
    summary = "; ".join(labels)
    return f"{summary[:1999]}…" if len(summary) > 2000 else summary or None


async def enqueue_invoice_payment_receipt(
    db: AsyncSession,
    invoice: Invoice,
    *,
    payment_amount: float,
    payment_event_id: str,
    balance_remaining: float = 0,
    received_at: datetime | None = None,
) -> InvoicePaymentReceiptOutbox:
    """Snapshot one receipt job without committing the caller's transaction."""
    contact = await db.get(Contact, invoice.contact_id) if invoice.contact_id is not None else None
    workspace = await db.get(Workspace, invoice.workspace_id)
    if workspace is None:
        raise RuntimeError(f"Workspace {invoice.workspace_id} disappeared during payment")

    recipient_email = invoice.last_emailed_to or (contact.email if contact else None)
    try:
        template = get_proposal_template(workspace)
        business_name = template.business_name or workspace.name
        logo_url = template.logo_url
        support_email = template.business_email
        support_phone = template.business_phone
    except ValueError as exc:
        # Optional branding corruption must not make a banked payment unreconcilable.
        logger.warning(
            "invoice_receipt_branding_invalid",
            workspace_id=str(workspace.id),
            invoice_id=str(invoice.id),
            error=str(exc),
        )
        business_name = workspace.name
        logo_url = support_email = support_phone = None

    paid_at = received_at or invoice.paid_at or datetime.now(UTC)

    job = InvoicePaymentReceiptOutbox(
        workspace_id=invoice.workspace_id,
        invoice_id=invoice.id,
        payment_event_id=payment_event_id,
        recipient_email=recipient_email,
        customer_name=contact.full_name if contact else "",
        service_summary=await _service_summary(db, invoice),
        business_name=business_name,
        invoice_number=invoice.number,
        payment_amount=_money(payment_amount),
        invoice_total=_money(float(invoice.total or 0)),
        total_paid=_money(float(invoice.amount_paid or 0)),
        balance_remaining=_money(balance_remaining),
        currency=invoice.currency,
        paid_at=paid_at,
        logo_url=logo_url,
        support_email=support_email,
        support_phone=support_phone,
        invoice_url=(
            f"{settings.frontend_url.rstrip('/')}/p/invoices/{invoice.public_token}"
            if invoice.public_token
            else None
        ),
        idempotency_key=derive_outbound_key(
            "invoice_payment_receipt",
            invoice.id,
            payment_event_id,
            recipient_email or "missing-recipient",
        ),
    )
    db.add(job)
    return job
