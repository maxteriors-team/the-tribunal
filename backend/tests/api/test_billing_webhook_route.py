"""Route-level tests for the Stripe webhook (``POST /billing/webhook``).

The per-handler reconciliation logic is unit-tested in
``tests/services/invoices/test_invoice_service.py`` and
``tests/services/test_call_payment_service.py``. These tests close the Phase 1
gap by exercising the *route itself* — signature verification, the
metadata-based routing between the SaaS-subscription, in-call-payment, and
customer-invoice paths, and the documented status codes — which nothing else
covered.

Signatures are generated with the real Stripe HMAC scheme
(``t=<ts>,v1=hmac_sha256(secret, f"{ts}.{payload}")``) so the tests prove the
production ``stripe.Webhook.construct_event`` call accepts/rejects exactly what
Stripe would send, rather than mocking signature verification away.
"""

from __future__ import annotations

import hmac
import json
import time
import uuid
from hashlib import sha256
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1.billing import stripe_webhook
from app.core.config import settings

TEST_WEBHOOK_SECRET = "whsec_test_phase1_route_secret"


def _sign(payload: bytes, secret: str, *, timestamp: int | None = None) -> str:
    """Build a valid ``Stripe-Signature`` header for ``payload``.

    Mirrors ``stripe.WebhookSignature``: the signed payload is
    ``"{timestamp}.{raw_body}"`` and the v1 signature is its HMAC-SHA256.
    """
    ts = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{ts}.{payload.decode('utf-8')}".encode()
    signature = hmac.new(secret.encode("utf-8"), signed_payload, sha256).hexdigest()
    return f"t={ts},v1={signature}"


def _make_request(body: bytes, sig_header: str) -> MagicMock:
    """Minimal FastAPI ``Request`` stub the route reads ``body``/headers from."""
    request = MagicMock()
    request.body = AsyncMock(return_value=body)
    request.headers = {"stripe-signature": sig_header}
    return request


def _event(event_type: str, session_object: dict[str, Any]) -> bytes:
    """Serialize a Stripe event envelope to the exact bytes that get signed."""
    envelope = {
        "id": f"evt_{uuid.uuid4().hex}",
        "object": "event",
        "type": event_type,
        "data": {"object": session_object},
    }
    return json.dumps(envelope).encode("utf-8")


# ---------------------------------------------------------------------------
# Signature verification + status codes (run in the default CI gate)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_secret_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no configured secret the route refuses to process (fail closed)."""
    monkeypatch.setattr(settings, "stripe_webhook_secret", "")
    request = _make_request(b"{}", "")

    with pytest.raises(HTTPException) as exc:
        await stripe_webhook(request, MagicMock())

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_bad_signature_returns_400(monkeypatch: pytest.MonkeyPatch) -> None:
    """A payload whose signature does not match the secret is rejected as 400."""
    monkeypatch.setattr(settings, "stripe_webhook_secret", TEST_WEBHOOK_SECRET)
    body = _event("checkout.session.completed", {"id": "cs_x", "metadata": {}})
    # Sign with the wrong secret so verify_header fails.
    bad_header = _sign(body, "whsec_a_different_secret")
    request = _make_request(body, bad_header)

    with pytest.raises(HTTPException) as exc:
        await stripe_webhook(request, MagicMock())

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_valid_signature_routes_invoice_event_to_invoice_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A correctly-signed ``invoice_id`` session reaches the invoice handler.

    Proves signature verification passes *and* the metadata routing dispatches
    customer-invoice payments to ``handle_invoice_checkout_session_completed``
    (not the SaaS-subscription path), without needing a database.
    """
    from app.services.invoices import invoice_service

    monkeypatch.setattr(settings, "stripe_webhook_secret", TEST_WEBHOOK_SECRET)
    invoice_handler = AsyncMock()
    monkeypatch.setattr(
        invoice_service, "handle_invoice_checkout_session_completed", invoice_handler
    )

    invoice_id = str(uuid.uuid4())
    session = {
        "id": "cs_invoice_route",
        "mode": "payment",
        "payment_intent": "pi_invoice_route",
        "amount_total": 12500,
        "metadata": {"invoice_id": invoice_id, "workspace_id": str(uuid.uuid4())},
    }
    body = _event("checkout.session.completed", session)
    request = _make_request(body, _sign(body, TEST_WEBHOOK_SECRET))

    db = MagicMock()
    response = await stripe_webhook(request, db)

    assert response == {"status": "ok"}
    invoice_handler.assert_awaited_once()
    routed_session = invoice_handler.await_args.args[0]
    assert routed_session["metadata"]["invoice_id"] == invoice_id


@pytest.mark.asyncio
async def test_valid_signature_routes_in_call_payment_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A signed ``call_payment_id`` session routes to the in-call handler."""
    from app.services.payments import call_payment_service

    monkeypatch.setattr(settings, "stripe_webhook_secret", TEST_WEBHOOK_SECRET)
    call_handler = AsyncMock()
    monkeypatch.setattr(call_payment_service, "handle_checkout_session_completed", call_handler)

    session = {
        "id": "cs_call_route",
        "mode": "payment",
        "payment_intent": "pi_call_route",
        "amount_total": 5000,
        "metadata": {"call_payment_id": str(uuid.uuid4())},
    }
    body = _event("checkout.session.completed", session)
    request = _make_request(body, _sign(body, TEST_WEBHOOK_SECRET))

    response = await stripe_webhook(request, MagicMock())

    assert response == {"status": "ok"}
    call_handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_unhandled_event_type_is_acknowledged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An event type we do not act on still returns 200 so Stripe stops retrying."""
    monkeypatch.setattr(settings, "stripe_webhook_secret", TEST_WEBHOOK_SECRET)
    body = _event("payment_intent.created", {"id": "pi_noop"})
    request = _make_request(body, _sign(body, TEST_WEBHOOK_SECRET))

    response = await stripe_webhook(request, MagicMock())

    assert response == {"status": "ok"}


# ---------------------------------------------------------------------------
# End-to-end against the real DB (run with ``-m integration``)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_signed_webhook_flips_invoice_to_paid_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The full loop: a signed ``checkout.session.completed`` flips a sent
    invoice to ``paid``, and a Stripe retry of the same event is a no-op."""
    from app.db.session import AsyncSessionLocal, engine
    from app.models.workspace import Workspace
    from app.schemas.invoice import InvoiceCreate, InvoiceLineItemCreate
    from app.services.invoices import InvoiceService

    await engine.dispose()
    try:
        monkeypatch.setattr(settings, "stripe_webhook_secret", TEST_WEBHOOK_SECRET)

        async with AsyncSessionLocal() as db:
            ws = Workspace(
                id=uuid.uuid4(),
                name="Webhook Co",
                slug=f"whk-{uuid.uuid4().hex[:8]}",
            )
            db.add(ws)
            await db.flush()

            svc = InvoiceService(db)
            invoice = await svc.create_invoice(
                ws.id,
                InvoiceCreate(
                    line_items=[InvoiceLineItemCreate(name="Service call", unit_price=250.0)]
                ),
            )
            await svc.mark_sent(ws.id, invoice.id)

            session = {
                "id": "cs_route_e2e",
                "mode": "payment",
                "payment_intent": "pi_route_e2e",
                "amount_total": 25000,  # minor units -> $250.00
                "metadata": {
                    "invoice_id": str(invoice.id),
                    "workspace_id": str(ws.id),
                },
            }
            body = _event("checkout.session.completed", session)
            header = _sign(body, TEST_WEBHOOK_SECRET)

            response = await stripe_webhook(_make_request(body, header), db)
            assert response == {"status": "ok"}

            paid = await svc.get_invoice(ws.id, invoice.id)
            assert paid.status == "paid"
            assert paid.amount_paid == 250.0
            assert paid.paid_at is not None

            # Stripe retries on any perceived non-2xx; replaying must not double-bill.
            replay = await stripe_webhook(_make_request(body, header), db)
            assert replay == {"status": "ok"}
            after_replay = await svc.get_invoice(ws.id, invoice.id)
            assert after_replay.amount_paid == 250.0
    finally:
        await engine.dispose()
