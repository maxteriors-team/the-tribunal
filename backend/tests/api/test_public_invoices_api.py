"""Public invoice payment request contract."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db
from app.api.v1 import invoices as invoices_module
from app.schemas.invoice import PublicInvoicePaymentCheckout

pytestmark = pytest.mark.asyncio


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


@pytest.fixture
async def client() -> AsyncIterator[tuple[AsyncClient, AsyncMock]]:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    app.include_router(invoices_module.public_router, prefix="/api/v1/p/invoices")
    service = AsyncMock()
    service.create_public_payment_checkout.return_value = PublicInvoicePaymentCheckout(
        url="https://pay.example/session", amount=125.0, currency="USD"
    )

    with patch.object(invoices_module, "InvoiceService", return_value=service):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as async_client:
            yield async_client, service


async def test_pay_passes_only_selected_optional_uuids_to_service(
    client: tuple[AsyncClient, AsyncMock],
) -> None:
    async_client, service = client
    selected_id = uuid.uuid4()

    response = await async_client.post(
        "/api/v1/p/invoices/public-token/pay",
        json={"selected_optional_line_item_ids": [str(selected_id)]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "url": "https://pay.example/session",
        "amount": 125.0,
        "currency": "USD",
    }
    service.create_public_payment_checkout.assert_awaited_once_with(
        "public-token", [selected_id]
    )


async def test_pay_keeps_omitted_body_backward_compatible(
    client: tuple[AsyncClient, AsyncMock],
) -> None:
    async_client, service = client

    response = await async_client.post("/api/v1/p/invoices/public-token/pay")

    assert response.status_code == 200
    service.create_public_payment_checkout.assert_awaited_once_with("public-token", None)


async def test_pay_rejects_non_uuid_selection_before_service_call(
    client: tuple[AsyncClient, AsyncMock],
) -> None:
    async_client, service = client

    response = await async_client.post(
        "/api/v1/p/invoices/public-token/pay",
        json={"selected_optional_line_item_ids": ["not-a-uuid"]},
    )

    assert response.status_code == 422
    service.create_public_payment_checkout.assert_not_awaited()
