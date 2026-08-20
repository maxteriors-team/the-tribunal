"""Public Stripe Checkout return verification tests."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.v1 import public_payments
from app.services.payments import call_payment_service


def _app_with_db(db: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(public_payments.public_router, prefix="/api/v1/p/payments")

    async def _override_db():  # type: ignore[no-untyped-def]
        yield db

    app.dependency_overrides[get_db] = _override_db
    return app


def _result(value: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _call_payment(session_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        stripe_checkout_session_id=session_id,
        stripe_payment_intent_id=None,
        currency="USD",
        amount=125.0,
    )


def _invoice(session_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        stripe_checkout_session_id=session_id,
        stripe_payment_intent_id=None,
        currency="USD",
    )


def _stripe_session(
    payment: SimpleNamespace,
    *,
    payment_status: str = "paid",
    status: str = "complete",
) -> call_payment_service.CheckoutSessionDetails:
    return call_payment_service.CheckoutSessionDetails(
        payment_status=payment_status,
        status=status,
        payment_intent_id="pi_test_123",
        mode="payment",
        metadata={
            "kind": call_payment_service.PAYMENT_KIND,
            "call_payment_id": str(payment.id),
            "workspace_id": str(payment.workspace_id),
        },
        amount_total=12_500,
        currency="usd",
    )


@pytest.mark.asyncio
async def test_valid_checkout_session_is_verified_with_stripe(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    session_id = "cs_test_valid123"
    payment = _call_payment(session_id)
    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value = _result(payment)
    retrieve = AsyncMock(return_value=_stripe_session(payment))
    monkeypatch.setattr(call_payment_service, "is_payment_configured", lambda: True)
    monkeypatch.setattr(call_payment_service, "retrieve_checkout_session_details", retrieve)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app_with_db(db)),
        base_url="http://test",
    ) as client:
        response = await client.post(f"/api/v1/p/payments/checkout-sessions/{session_id}/verify")

    assert response.status_code == 200
    assert response.json() == {"status": "paid"}
    assert response.headers["cache-control"] == "no-store"
    retrieve.assert_awaited_once_with(session_id)
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_invoice_checkout_session_is_verified_with_stripe(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    session_id = "cs_test_invoice123"
    invoice = _invoice(session_id)
    db = AsyncMock(spec=AsyncSession)
    db.execute.side_effect = [_result(None), _result(invoice)]
    retrieve = AsyncMock(
        return_value=call_payment_service.CheckoutSessionDetails(
            payment_status="paid",
            status="complete",
            payment_intent_id="pi_test_invoice123",
            mode="payment",
            metadata={
                "invoice_id": str(invoice.id),
                "workspace_id": str(invoice.workspace_id),
            },
            amount_total=25_000,
            currency="usd",
        )
    )
    monkeypatch.setattr(call_payment_service, "is_payment_configured", lambda: True)
    monkeypatch.setattr(call_payment_service, "retrieve_checkout_session_details", retrieve)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app_with_db(db)),
        base_url="http://test",
    ) as client:
        response = await client.post(f"/api/v1/p/payments/checkout-sessions/{session_id}/verify")

    assert response.status_code == 200
    assert response.json() == {"status": "paid"}
    retrieve.assert_awaited_once_with(session_id)
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_checkout_session_is_rejected_before_stripe(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value = _result(None)
    retrieve = AsyncMock()
    monkeypatch.setattr(call_payment_service, "is_payment_configured", lambda: True)
    monkeypatch.setattr(call_payment_service, "retrieve_checkout_session_details", retrieve)
    app = _app_with_db(db)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/p/payments/checkout-sessions/cs_test_unknown123/verify"
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Payment session could not be verified."}
    assert response.headers["cache-control"] == "no-store"
    assert db.execute.await_count == 2
    retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_checkout_session_is_reported_without_success(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    session_id = "cs_test_expired123"
    payment = _call_payment(session_id)
    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value = _result(payment)
    retrieve = AsyncMock(
        return_value=_stripe_session(payment, payment_status="unpaid", status="expired")
    )
    monkeypatch.setattr(call_payment_service, "is_payment_configured", lambda: True)
    monkeypatch.setattr(call_payment_service, "retrieve_checkout_session_details", retrieve)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app_with_db(db)),
        base_url="http://test",
    ) as client:
        response = await client.post(f"/api/v1/p/payments/checkout-sessions/{session_id}/verify")

    assert response.status_code == 200
    assert response.json() == {"status": "expired"}
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_replayed_paid_session_is_read_only_and_reverified(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    session_id = "cs_test_replayed123"
    payment = _call_payment(session_id)
    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value = _result(payment)
    retrieve = AsyncMock(return_value=_stripe_session(payment))
    monkeypatch.setattr(call_payment_service, "is_payment_configured", lambda: True)
    monkeypatch.setattr(call_payment_service, "retrieve_checkout_session_details", retrieve)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app_with_db(db)),
        base_url="http://test",
    ) as client:
        first = await client.post(f"/api/v1/p/payments/checkout-sessions/{session_id}/verify")
        replay = await client.post(f"/api/v1/p/payments/checkout-sessions/{session_id}/verify")

    assert first.json() == {"status": "paid"}
    assert replay.json() == {"status": "paid"}
    assert retrieve.await_count == 2
    db.commit.assert_not_awaited()
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_checkout_session_is_reported_for_retry(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    session_id = "cs_test_pending123"
    payment = _call_payment(session_id)
    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value = _result(payment)
    retrieve = AsyncMock(
        return_value=_stripe_session(payment, payment_status="unpaid", status="open")
    )
    monkeypatch.setattr(call_payment_service, "is_payment_configured", lambda: True)
    monkeypatch.setattr(call_payment_service, "retrieve_checkout_session_details", retrieve)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app_with_db(db)),
        base_url="http://test",
    ) as client:
        response = await client.post(f"/api/v1/p/payments/checkout-sessions/{session_id}/verify")

    assert response.status_code == 200
    assert response.json() == {"status": "pending"}


@pytest.mark.asyncio
async def test_default_checkout_success_url_includes_stripe_session_id(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    create = MagicMock(
        return_value=SimpleNamespace(
            id="cs_test_created123",
            url="https://checkout.stripe.test/session",
            payment_intent=None,
        )
    )
    stripe_client = SimpleNamespace(
        checkout=SimpleNamespace(sessions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr(call_payment_service, "_stripe_client", lambda: stripe_client)

    await call_payment_service.create_payment_checkout_session(
        amount=125.0,
        currency="usd",
        product_name="Service payment",
        metadata={"kind": call_payment_service.PAYMENT_KIND},
    )

    params = create.call_args.kwargs["params"]
    assert params["success_url"].endswith("/payment-complete?session_id={CHECKOUT_SESSION_ID}")


@pytest.mark.asyncio
async def test_session_metadata_must_match_local_payment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    session_id = "cs_test_mismatch123"
    payment = _call_payment(session_id)
    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value = _result(payment)
    stripe_session = _stripe_session(payment)
    stripe_session.metadata["workspace_id"] = str(uuid.uuid4())
    monkeypatch.setattr(call_payment_service, "is_payment_configured", lambda: True)
    monkeypatch.setattr(
        call_payment_service,
        "retrieve_checkout_session_details",
        AsyncMock(return_value=stripe_session),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app_with_db(db)),
        base_url="http://test",
    ) as client:
        response = await client.post(f"/api/v1/p/payments/checkout-sessions/{session_id}/verify")

    assert response.status_code == 404
    assert response.json() == {"detail": "Payment session could not be verified."}
