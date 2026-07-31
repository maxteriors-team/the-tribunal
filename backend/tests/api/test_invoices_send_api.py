"""HTTP contract for sending an invoice.

Offline-mockable style (cf. ``test_prebooking_audience_api.py``): no real
database, the service is an ``AsyncMock``. What matters here is the *wire* — a
send that reached nobody has to arrive at the browser saying so.

The failure this locks down: ``mark_sent`` transitions an invoice to ``sent``
even when there is no bill-to contact to email. If ``delivery`` is dropped
between the service and the response model, the dashboard shows a green
"invoice sent" toast for an invoice the customer never received, and the
operator waits on a payment that was never requested.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import (
    get_current_user,
    get_db,
    get_membership,
    get_transactional_db,
    get_workspace,
)
from app.api.v1 import invoices as invoices_module
from app.schemas.invoice import InvoiceSendResponse

pytestmark = pytest.mark.asyncio

WS_ID = uuid.uuid4()
INVOICE_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _make_user() -> MagicMock:
    user = MagicMock()
    user.id = 7
    user.is_active = True
    user.email = "owner@example.com"
    return user


def _make_workspace() -> MagicMock:
    ws = MagicMock()
    ws.id = WS_ID
    ws.is_active = True
    return ws


def _make_membership() -> MagicMock:
    membership = MagicMock()
    membership.workspace_id = WS_ID
    membership.user_id = 7
    # Owner holds billing:write, which the send route gates on.
    membership.role = "owner"
    return membership


def _send_response(delivery: str, delivered_to: str | None) -> InvoiceSendResponse:
    now = datetime.now(UTC)
    return InvoiceSendResponse(
        id=INVOICE_ID,
        workspace_id=WS_ID,
        number="INV-000001",
        status="sent",
        subtotal=200.0,
        tax_amount=0.0,
        discount_amount=0.0,
        total=200.0,
        amount_paid=0.0,
        currency="USD",
        created_at=now,
        updated_at=now,
        line_items=[],
        delivery=delivery,  # type: ignore[arg-type]
        delivered_to=delivered_to,
    )


@pytest.fixture
def mock_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
async def client(mock_service: AsyncMock) -> AsyncIterator[AsyncClient]:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_transactional_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: _make_user()
    app.dependency_overrides[get_workspace] = lambda: _make_workspace()
    app.dependency_overrides[get_membership] = lambda: _make_membership()
    app.include_router(
        invoices_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/invoices",
    )

    with patch.object(invoices_module, "InvoiceService", return_value=mock_service):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            yield ac


def _url() -> str:
    return f"/api/v1/workspaces/{WS_ID}/invoices/{INVOICE_ID}/send"


async def test_a_delivered_invoice_names_the_recipient(
    client: AsyncClient, mock_service: AsyncMock
) -> None:
    mock_service.mark_sent.return_value = _send_response("emailed", "customer@example.com")

    response = await client.post(_url())

    assert response.status_code == 200
    body = response.json()
    assert body["delivery"] == "emailed"
    assert body["delivered_to"] == "customer@example.com"


async def test_an_invoice_that_reached_nobody_says_so_over_the_wire(
    client: AsyncClient, mock_service: AsyncMock
) -> None:
    """The regression: `sent` status, but nothing was emailed."""
    mock_service.mark_sent.return_value = _send_response("skipped_no_email", None)

    response = await client.post(_url())

    assert response.status_code == 200
    body = response.json()
    # Status still transitions...
    assert body["status"] == "sent"
    # ...but the caller can tell the customer got nothing.
    assert body["delivery"] == "skipped_no_email"
    assert body["delivered_to"] is None
