"""Auth, capability, and redaction tests for the inventory routes.

Offline-mockable style (cf. ``test_jobs_api.py``): no real database. The
services are replaced with ``AsyncMock``s so these tests assert the HTTP
contract — auth, the capability matrix, body validation, and the
``billing:read`` cost-redaction wiring — rather than posting math, which
``tests/services/inventory/`` covers against a real database.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_membership, get_transactional_db
from app.api.v1 import inventory as inventory_module

WS_ID = uuid.uuid4()
ITEM_ID = uuid.uuid4()
LOCATION_ID = uuid.uuid4()
OTHER_LOCATION_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _mount(app: FastAPI) -> None:
    app.include_router(
        inventory_module.router, prefix="/api/v1/workspaces/{workspace_id}/inventory"
    )


def _make_user() -> MagicMock:
    user = MagicMock()
    user.id = 7
    user.is_active = True
    return user


def _make_membership(role: str) -> MagicMock:
    membership = MagicMock()
    membership.workspace_id = WS_ID
    membership.user_id = 7
    membership.role = role
    return membership


def _item_payload(**overrides: object) -> dict[str, object]:
    now = datetime.now(UTC).isoformat()
    base: dict[str, object] = {
        "id": str(ITEM_ID),
        "workspace_id": str(WS_ID),
        "catalog_item_id": None,
        "name": "Sodium hypochlorite",
        "sku": "SH-12",
        "unit_of_measure": "gallon",
        "is_active": True,
        "valuation_method": "weighted_average",
        "reorder_point": 10.0,
        "reorder_quantity": 50.0,
        "safety_stock": 5.0,
        "lead_time_days": 7,
        "supplier_name": "Chem Co",
        "supplier_sku": None,
        "notes": None,
        "quantity_on_hand": 8.0,
        "total_value": 32.0,
        "avg_unit_cost": 4.0,
        "is_low_stock": True,
        "last_movement_at": now,
        "created_at": now,
        "updated_at": now,
    }
    base.update(overrides)
    return base


def _ledger_payload(**overrides: object) -> dict[str, object]:
    now = datetime.now(UTC).isoformat()
    base: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "item_id": str(ITEM_ID),
        "item_name": "Sodium hypochlorite",
        "location_id": str(LOCATION_ID),
        "location_name": "Main",
        "quantity_delta": 10.0,
        "unit_cost": 4.0,
        "value_delta": 40.0,
        "reason": "receipt",
        "reference_type": None,
        "reference_id": None,
        "occurred_at": now,
        "note": None,
        "quantity_after": 10.0,
        "value_after": 40.0,
        "unit_cost_after": 4.0,
        "created_at": now,
    }
    base.update(overrides)
    return base


@pytest.fixture
def mock_inventory_service() -> AsyncMock:
    service = AsyncMock()
    service.list_items.return_value = {
        "items": [_item_payload()],
        "total": 1,
        "page": 1,
        "page_size": 50,
        "pages": 1,
    }
    service.get_item.return_value = _item_payload()
    service.create_item.return_value = _item_payload()
    service.update_item.return_value = _item_payload(name="Renamed")
    service.delete_item.return_value = None
    service.list_ledger.return_value = {
        "items": [_ledger_payload()],
        "total": 1,
        "page": 1,
        "page_size": 50,
        "pages": 1,
    }
    service.list_stock.return_value = {"items": [], "total": 0, "total_value": 0.0}
    service.list_locations.return_value = []
    service.create_location.return_value = {
        "id": str(LOCATION_ID),
        "workspace_id": str(WS_ID),
        "name": "Truck 1",
        "kind": "truck",
        "crew_id": None,
        "is_active": True,
        "is_default": False,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    service.update_location.return_value = service.create_location.return_value
    service.delete_location.return_value = None
    return service


@pytest.fixture
def mock_stock_service() -> AsyncMock:
    service = AsyncMock()
    entry = MagicMock()
    service.receive.return_value = entry
    service.adjust.return_value = entry
    service.transfer.return_value = (entry, entry)
    return service


def _client_factory(
    role: str,
    mock_inventory_service: AsyncMock,
    mock_stock_service: AsyncMock,
) -> AsyncClient:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_transactional_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: _make_user()
    app.dependency_overrides[get_membership] = lambda: _make_membership(role)
    _mount(app)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


@pytest.fixture
async def admin_client(
    mock_inventory_service: AsyncMock, mock_stock_service: AsyncMock
) -> AsyncIterator[AsyncClient]:
    """Owner: holds every capability including billing."""
    with (
        patch.object(inventory_module, "InventoryService", return_value=mock_inventory_service),
        patch.object(inventory_module, "StockService", wraps=None) as stock_cls,
    ):
        stock_cls.return_value = mock_stock_service
        stock_cls.entry_response = MagicMock(return_value=_ledger_payload())
        async with _client_factory("owner", mock_inventory_service, mock_stock_service) as ac:
            yield ac


@pytest.fixture
async def technician_client(
    mock_inventory_service: AsyncMock, mock_stock_service: AsyncMock
) -> AsyncIterator[AsyncClient]:
    """Field technician: ``jobs:read`` only — no billing, no jobs:write."""
    with (
        patch.object(inventory_module, "InventoryService", return_value=mock_inventory_service),
        patch.object(inventory_module, "StockService", wraps=None) as stock_cls,
    ):
        stock_cls.return_value = mock_stock_service
        stock_cls.entry_response = MagicMock(return_value=_ledger_payload())
        async with _client_factory("technician", mock_inventory_service, mock_stock_service) as ac:
            yield ac


@pytest.fixture
async def noauth_client() -> AsyncIterator[AsyncClient]:
    app = FastAPI(lifespan=_test_lifespan)
    _mount(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac


def _base(path: str = "") -> str:
    return f"/api/v1/workspaces/{WS_ID}/inventory{path}"


class TestAuth:
    async def test_list_items_requires_auth(self, noauth_client: AsyncClient) -> None:
        assert (await noauth_client.get(_base("/items"))).status_code == 401

    async def test_receive_requires_auth(self, noauth_client: AsyncClient) -> None:
        response = await noauth_client.post(
            _base(f"/items/{ITEM_ID}/receipts"), json={"quantity": 1, "unit_cost": 1}
        )
        assert response.status_code == 401


class TestCapabilityGates:
    """Reads are jobs:read; value-changing writes are billing:write."""

    async def test_technician_can_read_stock(self, technician_client: AsyncClient) -> None:
        assert (await technician_client.get(_base("/stock"))).status_code == 200

    async def test_technician_can_read_items(self, technician_client: AsyncClient) -> None:
        assert (await technician_client.get(_base("/items"))).status_code == 200

    async def test_technician_cannot_create_items(self, technician_client: AsyncClient) -> None:
        response = await technician_client.post(_base("/items"), json={"name": "Soap"})
        assert response.status_code == 403

    async def test_technician_cannot_receive_stock(self, technician_client: AsyncClient) -> None:
        response = await technician_client.post(
            _base(f"/items/{ITEM_ID}/receipts"), json={"quantity": 5, "unit_cost": 2}
        )
        assert response.status_code == 403

    async def test_technician_cannot_transfer_stock(self, technician_client: AsyncClient) -> None:
        """Loading a van is jobs:write; the field tier does not hold it."""
        response = await technician_client.post(
            _base("/transfers"),
            json={
                "item_id": str(ITEM_ID),
                "from_location_id": str(LOCATION_ID),
                "to_location_id": str(OTHER_LOCATION_ID),
                "quantity": 2,
            },
        )
        assert response.status_code == 403

    async def test_admin_can_create_items(self, admin_client: AsyncClient) -> None:
        response = await admin_client.post(_base("/items"), json={"name": "Soap"})
        assert response.status_code == 201

    async def test_admin_receipt_returns_the_posted_movement(
        self, admin_client: AsyncClient, mock_stock_service: AsyncMock
    ) -> None:
        response = await admin_client.post(
            _base(f"/items/{ITEM_ID}/receipts"), json={"quantity": 5, "unit_cost": 2.5}
        )
        assert response.status_code == 201
        assert response.json()["reason"] == "receipt"
        mock_stock_service.receive.assert_awaited_once()


class TestCostRedaction:
    """``include_costs`` is derived from ``billing:read`` at the route."""

    async def test_reads_pass_include_costs_false_without_billing_read(
        self, technician_client: AsyncClient, mock_inventory_service: AsyncMock
    ) -> None:
        await technician_client.get(_base("/items"))
        assert mock_inventory_service.list_items.await_args.kwargs["include_costs"] is False

        await technician_client.get(_base("/stock"))
        assert mock_inventory_service.list_stock.await_args.kwargs["include_costs"] is False

        await technician_client.get(_base(f"/items/{ITEM_ID}/ledger"))
        assert mock_inventory_service.list_ledger.await_args.kwargs["include_costs"] is False

    async def test_reads_pass_include_costs_true_for_billing_readers(
        self, admin_client: AsyncClient, mock_inventory_service: AsyncMock
    ) -> None:
        await admin_client.get(_base("/items"))
        assert mock_inventory_service.list_items.await_args.kwargs["include_costs"] is True


class TestValidation:
    async def test_receipt_rejects_non_positive_quantity(self, admin_client: AsyncClient) -> None:
        response = await admin_client.post(
            _base(f"/items/{ITEM_ID}/receipts"), json={"quantity": 0, "unit_cost": 1}
        )
        assert response.status_code == 422

    async def test_receipt_rejects_negative_cost(self, admin_client: AsyncClient) -> None:
        response = await admin_client.post(
            _base(f"/items/{ITEM_ID}/receipts"), json={"quantity": 1, "unit_cost": -5}
        )
        assert response.status_code == 422

    async def test_item_create_rejects_unimplemented_valuation_method(
        self, admin_client: AsyncClient
    ) -> None:
        response = await admin_client.post(
            _base("/items"), json={"name": "Soap", "valuation_method": "fifo"}
        )
        assert response.status_code == 422

    async def test_list_forwards_low_stock_filter(
        self, admin_client: AsyncClient, mock_inventory_service: AsyncMock
    ) -> None:
        await admin_client.get(_base("/items"), params={"low_stock": "true"})
        assert mock_inventory_service.list_items.await_args.kwargs["low_stock_only"] is True
