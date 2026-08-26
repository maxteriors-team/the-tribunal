"""Deliver transactionally queued paid-invoice customer receipts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select

from app.db.session import AsyncSessionLocal
from app.models.invoice_payment_receipt_outbox import (
    RECEIPT_PENDING,
    RECEIPT_PROCESSING,
    RECEIPT_SENT,
    RECEIPT_TERMINAL,
    InvoicePaymentReceiptOutbox,
)
from app.services.email import send_invoice_payment_receipt
from app.workers.base import BaseWorker, WorkerRegistry

MAX_ATTEMPTS = 5
BATCH_SIZE = 50
CLAIM_TTL = timedelta(minutes=10)
BACKOFF_BASE_SECONDS = 30
MAX_BACKOFF_SECONDS = 3600
MAX_ERROR_LENGTH = 1000


class InvoicePaymentReceiptWorker(BaseWorker):
    """Claim receipt outbox rows and retry delivery without touching invoices."""

    POLL_INTERVAL_SECONDS = 15
    COMPONENT_NAME = "invoice_payment_receipt_worker"
    MAX_CONCURRENCY = 5

    async def _process_items(self) -> None:
        await self.process_once()

    async def process_once(self) -> int:
        """Claim and process one bounded batch, returning the claimed count."""
        job_ids = await self._claim_jobs()
        results = await self.run_concurrently(self._deliver(job_id) for job_id in job_ids)
        for job_id, result in zip(job_ids, results, strict=True):
            if isinstance(result, BaseException):
                self.logger.error(
                    "invoice_receipt_delivery_crashed",
                    job_id=str(job_id),
                    error=type(result).__name__,
                    exc_info=result,
                )
        return len(job_ids)

    async def _claim_jobs(self) -> list[uuid.UUID]:
        now = datetime.now(UTC)
        stale_before = now - CLAIM_TTL
        async with AsyncSessionLocal() as db:
            jobs = list(
                (
                    await db.scalars(
                        select(InvoicePaymentReceiptOutbox)
                        .where(
                            or_(
                                and_(
                                    InvoicePaymentReceiptOutbox.status == RECEIPT_PENDING,
                                    InvoicePaymentReceiptOutbox.next_attempt_at <= now,
                                ),
                                and_(
                                    InvoicePaymentReceiptOutbox.status == RECEIPT_PROCESSING,
                                    InvoicePaymentReceiptOutbox.claimed_at < stale_before,
                                ),
                            )
                        )
                        .order_by(
                            InvoicePaymentReceiptOutbox.next_attempt_at,
                            InvoicePaymentReceiptOutbox.created_at,
                        )
                        .limit(BATCH_SIZE)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            claimed_ids: list[uuid.UUID] = []
            for job in jobs:
                if job.attempt_count >= MAX_ATTEMPTS:
                    job.status = RECEIPT_TERMINAL
                    job.terminal_at = now
                    job.claimed_at = None
                    job.last_error = "Claim expired after maximum attempts"
                    continue
                job.status = RECEIPT_PROCESSING
                job.claimed_at = now
                job.attempt_count += 1
                claimed_ids.append(job.id)
            await db.commit()
            return claimed_ids

    async def _deliver(self, job_id: uuid.UUID) -> None:
        snapshot = await self._load_snapshot(job_id)
        if snapshot is None:
            return
        if not snapshot["to_email"]:
            await self._mark_terminal(job_id, "Missing receipt recipient")
            return

        try:
            accepted = await send_invoice_payment_receipt(**snapshot)
            if not accepted:
                raise RuntimeError("Receipt provider did not accept the message")
        except Exception as exc:
            await self._mark_failure(job_id, exc)
            return

        now = datetime.now(UTC)
        async with AsyncSessionLocal() as db:
            job = await db.get(InvoicePaymentReceiptOutbox, job_id, with_for_update=True)
            if job is None or job.status != RECEIPT_PROCESSING:
                await db.rollback()
                return
            job.status = RECEIPT_SENT
            job.sent_at = now
            job.claimed_at = None
            job.last_error = None
            await db.commit()

    async def _load_snapshot(self, job_id: uuid.UUID) -> dict[str, Any] | None:
        async with AsyncSessionLocal() as db:
            job = await db.get(InvoicePaymentReceiptOutbox, job_id)
            if job is None or job.status != RECEIPT_PROCESSING:
                return None
            return {
                "to_email": job.recipient_email,
                "customer_name": job.customer_name,
                "business_name": job.business_name,
                "service_summary": job.service_summary,
                "invoice_number": job.invoice_number,
                "payment_amount": float(job.payment_amount),
                "invoice_total": float(job.invoice_total),
                "total_paid": float(job.total_paid),
                "balance_remaining": float(job.balance_remaining or 0),
                "currency": job.currency,
                "paid_at": job.paid_at,
                "logo_url": job.logo_url,
                "support_email": job.support_email,
                "support_phone": job.support_phone,
                "invoice_url": job.invoice_url,
                "idempotency_key": job.idempotency_key,
            }

    async def _mark_failure(self, job_id: uuid.UUID, exc: Exception) -> None:
        async with AsyncSessionLocal() as db:
            job = await db.get(InvoicePaymentReceiptOutbox, job_id, with_for_update=True)
            if job is None or job.status != RECEIPT_PROCESSING:
                await db.rollback()
                return
            error = f"{type(exc).__name__}: {exc}".replace("\n", " ").replace("\x00", "")[
                :MAX_ERROR_LENGTH
            ]
            if job.attempt_count >= MAX_ATTEMPTS:
                job.status = RECEIPT_TERMINAL
                job.terminal_at = datetime.now(UTC)
            else:
                delay = min(
                    BACKOFF_BASE_SECONDS * (2 ** (job.attempt_count - 1)),
                    MAX_BACKOFF_SECONDS,
                )
                job.status = RECEIPT_PENDING
                job.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
            job.claimed_at = None
            job.last_error = error
            await db.commit()

    async def _mark_terminal(self, job_id: uuid.UUID, error: str) -> None:
        async with AsyncSessionLocal() as db:
            job = await db.get(InvoicePaymentReceiptOutbox, job_id, with_for_update=True)
            if job is None or job.status != RECEIPT_PROCESSING:
                await db.rollback()
                return
            job.status = RECEIPT_TERMINAL
            job.terminal_at = datetime.now(UTC)
            job.claimed_at = None
            job.last_error = error[:MAX_ERROR_LENGTH]
            await db.commit()


registry = WorkerRegistry(InvoicePaymentReceiptWorker)
