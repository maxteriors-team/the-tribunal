"""Validation and auth tests for the contacts API endpoints.

These tests exercise request validation and authorization without hitting a real
database. For endpoints requiring auth + workspace access, dependency overrides
replace `get_current_user`, `get_db`, and `get_workspace`.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_membership, get_workspace
from app.api.v1 import contacts as contacts_module

WS_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Minimal lifespan that skips workers, Redis, and DB setup."""
    yield


def _make_mock_workspace() -> MagicMock:
    """Create a mock Workspace object."""
    ws = MagicMock()
    ws.id = WS_ID
    ws.is_active = True
    ws.settings = {}
    return ws


def _make_mock_user() -> MagicMock:
    """Create a mock active User object."""
    user = MagicMock()
    user.id = 1
    user.is_active = True
    user.email = "tester@example.com"
    return user


def _make_auth_test_app(
    mock_db: AsyncMock,
    mock_workspace: MagicMock,
    mock_user: MagicMock,
) -> FastAPI:
    """Create a test app with auth + workspace dependencies overridden."""
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield mock_db

    async def override_get_workspace() -> MagicMock:
        return mock_workspace

    async def override_get_current_user() -> MagicMock:
        return mock_user

    async def override_get_membership() -> MagicMock:
        # "owner" -> admin tier -> every capability, so the capability gate
        # (require_capability) passes and these tests exercise validation.
        membership = MagicMock()
        membership.role = "owner"
        membership.workspace_id = mock_workspace.id
        membership.user_id = mock_user.id
        return membership

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_workspace] = override_get_workspace
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_membership] = override_get_membership

    app.include_router(
        contacts_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/contacts",
    )
    return app


def _make_noauth_test_app() -> FastAPI:
    """Create a test app without any dependency overrides (auth will fail)."""
    app = FastAPI(lifespan=_test_lifespan)
    app.include_router(
        contacts_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/contacts",
    )
    return app


@pytest.fixture
def mock_db() -> AsyncMock:
    """AsyncMock DB session fixture."""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.fixture
def mock_workspace() -> MagicMock:
    """Mock Workspace fixture."""
    return _make_mock_workspace()


@pytest.fixture
def mock_user() -> MagicMock:
    """Mock User fixture."""
    return _make_mock_user()


@pytest.fixture
async def client(
    mock_db: AsyncMock, mock_workspace: MagicMock, mock_user: MagicMock
) -> AsyncIterator[AsyncClient]:
    """Authenticated AsyncClient (dependency overrides bypass real auth)."""
    app = _make_auth_test_app(mock_db, mock_workspace, mock_user)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest.fixture
async def noauth_client() -> AsyncIterator[AsyncClient]:
    """Unauthenticated AsyncClient (no dependency overrides)."""
    app = _make_noauth_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


class TestCreateContactValidation:
    """Validation failures for POST /contacts (happy path auth)."""

    async def test_missing_first_name_returns_422(self, client: AsyncClient) -> None:
        """POST /contacts without first_name returns 422."""
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/contacts",
            json={"phone_number": "+15551234567"},
        )
        assert response.status_code == 422

    async def test_missing_phone_number_returns_422(self, client: AsyncClient) -> None:
        """POST /contacts without phone_number returns 422."""
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/contacts",
            json={"first_name": "Alice"},
        )
        assert response.status_code == 422

    async def test_empty_first_name_returns_422(self, client: AsyncClient) -> None:
        """POST /contacts with empty first_name (min_length=1) returns 422."""
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/contacts",
            json={"first_name": "", "phone_number": "+15551234567"},
        )
        assert response.status_code == 422

    async def test_invalid_email_returns_422(self, client: AsyncClient) -> None:
        """POST /contacts with invalid email format returns 422."""
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/contacts",
            json={
                "first_name": "Alice",
                "phone_number": "+15551234567",
                "email": "not-an-email",
            },
        )
        assert response.status_code == 422

    async def test_phone_too_short_returns_422(self, client: AsyncClient) -> None:
        """POST /contacts with phone_number shorter than 10 chars returns 422."""
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/contacts",
            json={"first_name": "Alice", "phone_number": "123"},
        )
        assert response.status_code == 422

    async def test_first_name_too_long_returns_422(self, client: AsyncClient) -> None:
        """POST /contacts with first_name > 100 chars returns 422."""
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/contacts",
            json={
                "first_name": "A" * 101,
                "phone_number": "+15551234567",
            },
        )
        assert response.status_code == 422

    async def test_empty_body_returns_422(self, client: AsyncClient) -> None:
        """POST /contacts with empty body returns 422."""
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/contacts",
            json={},
        )
        assert response.status_code == 422


class TestCreateContactSuccess:
    """Happy-path POST /contacts with mocked service."""

    async def test_create_contact_passes_fields_to_service(
        self,
        client: AsyncClient,
        mock_db: AsyncMock,
    ) -> None:
        """POST /contacts with valid data calls ContactService.create_contact.

        We verify the service layer is invoked with the correct fields and
        workspace_id. Response-serialization is a concern for the service
        layer's own tests, so here we just check the call.
        """
        from unittest.mock import patch

        create_mock = AsyncMock(side_effect=RuntimeError("short-circuit after service called"))

        with (
            patch.object(contacts_module.ContactService, "create_contact", new=create_mock),
            suppress(RuntimeError),
        ):
            await client.post(
                f"/api/v1/workspaces/{WS_ID}/contacts",
                json={
                    "first_name": "Alice",
                    "last_name": "Smith",
                    "email": "alice@example.com",
                    "phone_number": "+15551234567",
                },
            )

        create_mock.assert_awaited_once()
        kwargs = create_mock.call_args.kwargs
        assert kwargs["first_name"] == "Alice"
        assert kwargs["last_name"] == "Smith"
        assert kwargs["email"] == "alice@example.com"
        assert kwargs["phone_number"] == "+15551234567"
        assert kwargs["workspace_id"] == WS_ID


class TestListContactsAuth:
    """Tests for GET /contacts."""

    async def test_list_contacts_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        """GET /contacts without auth returns 401."""
        response = await noauth_client.get(f"/api/v1/workspaces/{WS_ID}/contacts")
        assert response.status_code == 401

    async def test_list_contacts_with_invalid_filters_json_returns_400(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        """GET /contacts with malformed `filters` JSON returns 400."""
        response = await client.get(f"/api/v1/workspaces/{WS_ID}/contacts?filters=not-json")
        assert response.status_code == 400

    async def test_list_contacts_invalid_page_returns_422(self, client: AsyncClient) -> None:
        """GET /contacts with page=0 (violates ge=1) returns 422."""
        response = await client.get(f"/api/v1/workspaces/{WS_ID}/contacts?page=0")
        assert response.status_code == 422

    async def test_list_contacts_page_size_too_large_returns_422(self, client: AsyncClient) -> None:
        """GET /contacts with page_size=200 (violates le=100) returns 422."""
        response = await client.get(f"/api/v1/workspaces/{WS_ID}/contacts?page_size=200")
        assert response.status_code == 422


class TestCreateContactAuth:
    """Auth failures for POST /contacts."""

    async def test_create_contact_without_auth_returns_401(
        self, noauth_client: AsyncClient
    ) -> None:
        """POST /contacts with valid body but no auth returns 401."""
        response = await noauth_client.post(
            f"/api/v1/workspaces/{WS_ID}/contacts",
            json={"first_name": "Alice", "phone_number": "+15551234567"},
        )
        assert response.status_code == 401


class TestGetContactAuth:
    """Auth failures for GET /contacts/{id}."""

    async def test_get_contact_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        """GET /contacts/{id} without auth returns 401."""
        response = await noauth_client.get(f"/api/v1/workspaces/{WS_ID}/contacts/1")
        assert response.status_code == 401

    async def test_get_nonexistent_contact_returns_404(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        """GET /contacts/{id} for unknown ID returns 404."""
        from unittest.mock import patch

        from app.services.contacts.exceptions import ContactNotFoundError

        with patch.object(
            contacts_module.ContactService,
            "get_contact",
            new=AsyncMock(side_effect=ContactNotFoundError("Contact not found")),
        ):
            response = await client.get(f"/api/v1/workspaces/{WS_ID}/contacts/999999")

        assert response.status_code == 404


class TestUpdateContactValidation:
    """Validation for PUT /contacts/{id}."""

    async def test_update_with_invalid_email_returns_422(self, client: AsyncClient) -> None:
        """PUT /contacts/{id} with invalid email returns 422."""
        response = await client.put(
            f"/api/v1/workspaces/{WS_ID}/contacts/1",
            json={"email": "not-an-email"},
        )
        assert response.status_code == 422

    async def test_update_empty_first_name_returns_422(self, client: AsyncClient) -> None:
        """PUT /contacts/{id} with empty first_name (min_length=1) returns 422."""
        response = await client.put(
            f"/api/v1/workspaces/{WS_ID}/contacts/1",
            json={"first_name": ""},
        )
        assert response.status_code == 422

    async def test_update_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        """PUT /contacts/{id} without auth returns 401."""
        response = await noauth_client.put(
            f"/api/v1/workspaces/{WS_ID}/contacts/1",
            json={"first_name": "Bob"},
        )
        assert response.status_code == 401


class TestDeleteContactAuth:
    """Auth for DELETE /contacts/{id}."""

    async def test_delete_contact_without_auth_returns_401(
        self, noauth_client: AsyncClient
    ) -> None:
        """DELETE /contacts/{id} without auth returns 401."""
        response = await noauth_client.delete(f"/api/v1/workspaces/{WS_ID}/contacts/1")
        assert response.status_code == 401


class TestBulkDeleteValidation:
    """Validation for POST /contacts/bulk-delete."""

    async def test_bulk_delete_missing_ids_returns_422(self, client: AsyncClient) -> None:
        """POST /contacts/bulk-delete without ids field returns 422."""
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/contacts/bulk-delete",
            json={},
        )
        assert response.status_code == 422

    async def test_bulk_delete_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        """POST /contacts/bulk-delete without auth returns 401."""
        response = await noauth_client.post(
            f"/api/v1/workspaces/{WS_ID}/contacts/bulk-delete",
            json={"ids": [1, 2, 3]},
        )
        assert response.status_code == 401
