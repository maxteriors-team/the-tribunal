"""Auth, validation, and routing tests for the referral-partner routes.

Offline-mockable style (cf. ``test_jobs_api.py``): no real database. The
``ReferralPartnerService`` is replaced with an ``AsyncMock`` so these tests assert
the HTTP contract — auth gating, body validation, status codes, query forwarding,
and that ``/scoreboard`` is not swallowed by the ``/{partner_id}`` route — rather
than service internals (covered by
``tests/services/lead_sources/test_referral_partner_scoreboard.py``).
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
from app.api.v1 import referral_partners as partners_module
from app.models.referral_partner import ReferralPartnerType
from app.schemas.referral_partner import (
    ReferralPartnerListResponse,
    ReferralPartnerResponse,
    ReferralPartnerScoreboardResponse,
    ReferralPartnerScoreboardRow,
)

WS_ID = uuid.uuid4()
PARTNER_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _mount(app: FastAPI) -> None:
    app.include_router(
        partners_module.router, prefix="/api/v1/workspaces/{workspace_id}/referral-partners"
    )


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
    membership.role = "owner"
    return membership


def _partner() -> ReferralPartnerResponse:
    now = datetime.now(UTC)
    return ReferralPartnerResponse(
        id=PARTNER_ID,
        workspace_id=WS_ID,
        name="Dana Ruiz",
        company="Keller Williams",
        partner_type=ReferralPartnerType.REALTOR,
        email="dana@example.com",
        phone="+15551230000",
        notes=None,
        contact_id=None,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def mock_service() -> AsyncMock:
    """A ReferralPartnerService stand-in returning canned responses."""
    service = AsyncMock()
    service.list.return_value = ReferralPartnerListResponse(items=[_partner()], total=1)
    service.get.return_value = _partner()
    service.create.return_value = _partner()
    service.update.return_value = _partner()
    service.delete.return_value = None
    service.scoreboard.return_value = ReferralPartnerScoreboardResponse(
        items=[
            ReferralPartnerScoreboardRow(
                partner_id=PARTNER_ID,
                name="Dana Ruiz",
                partner_type=ReferralPartnerType.REALTOR,
                referrals_sent=4,
                jobs_closed=2,
                close_rate=0.5,
                total_revenue=12_000.0,
                average_job_value=6_000.0,
                days_since_last_referral=91,
                is_gone_quiet=True,
            )
        ],
        total=1,
        total_referrals_sent=4,
        total_jobs_closed=2,
        total_revenue=12_000.0,
    )
    return service


@pytest.fixture
async def client(mock_service: AsyncMock) -> AsyncIterator[AsyncClient]:
    """Authenticated owner client with the service patched out."""
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_transactional_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: _make_user()
    app.dependency_overrides[get_workspace] = lambda: _make_workspace()
    app.dependency_overrides[get_membership] = lambda: _make_membership()
    _mount(app)

    with patch.object(partners_module, "ReferralPartnerService", return_value=mock_service):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            yield ac


@pytest.fixture
async def noauth_client() -> AsyncIterator[AsyncClient]:
    """Unauthenticated client: the real auth dependency runs (expects 401)."""
    app = FastAPI(lifespan=_test_lifespan)
    _mount(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac


def _base(path: str = "") -> str:
    return f"/api/v1/workspaces/{WS_ID}/referral-partners{path}"


class TestAuth:
    """Partner data is workspace-private; every route requires authentication."""

    async def test_list_requires_auth(self, noauth_client: AsyncClient) -> None:
        assert (await noauth_client.get(_base())).status_code == 401

    async def test_scoreboard_requires_auth(self, noauth_client: AsyncClient) -> None:
        assert (await noauth_client.get(_base("/scoreboard"))).status_code == 401

    async def test_create_requires_auth(self, noauth_client: AsyncClient) -> None:
        response = await noauth_client.post(_base(), json={"name": "Dana"})
        assert response.status_code == 401

    async def test_delete_requires_auth(self, noauth_client: AsyncClient) -> None:
        assert (await noauth_client.delete(_base(f"/{PARTNER_ID}"))).status_code == 401


class TestListAndGet:
    async def test_list_returns_items(self, client: AsyncClient, mock_service: AsyncMock) -> None:
        response = await client.get(_base())
        assert response.status_code == 200
        assert response.json()["total"] == 1
        mock_service.list.assert_awaited_once()

    async def test_list_forwards_filters(
        self, client: AsyncClient, mock_service: AsyncMock
    ) -> None:
        response = await client.get(
            _base(), params={"is_active": "true", "partner_type": "realtor"}
        )
        assert response.status_code == 200
        kwargs = mock_service.list.await_args.kwargs
        assert kwargs["is_active"] is True
        assert kwargs["partner_type"] == ReferralPartnerType.REALTOR

    async def test_get_returns_partner(self, client: AsyncClient) -> None:
        response = await client.get(_base(f"/{PARTNER_ID}"))
        assert response.status_code == 200
        assert response.json()["id"] == str(PARTNER_ID)

    async def test_partner_id_must_be_a_uuid(self, client: AsyncClient) -> None:
        assert (await client.get(_base("/not-a-uuid"))).status_code == 422


class TestScoreboard:
    async def test_scoreboard_route_is_not_shadowed_by_partner_id(
        self, client: AsyncClient, mock_service: AsyncMock
    ) -> None:
        """``/scoreboard`` must resolve to the report, not a 422 UUID parse."""
        response = await client.get(_base("/scoreboard"))
        assert response.status_code == 200
        mock_service.scoreboard.assert_awaited_once()
        mock_service.get.assert_not_awaited()

    async def test_scoreboard_defaults_are_applied(
        self, client: AsyncClient, mock_service: AsyncMock
    ) -> None:
        response = await client.get(_base("/scoreboard"))
        assert response.status_code == 200
        kwargs = mock_service.scoreboard.await_args.kwargs
        assert kwargs["quiet_after_days"] == 60
        assert kwargs["gone_quiet_only"] is False

    async def test_gone_quiet_filter_is_forwarded(
        self, client: AsyncClient, mock_service: AsyncMock
    ) -> None:
        response = await client.get(
            _base("/scoreboard"), params={"gone_quiet_only": "true", "quiet_after_days": 90}
        )
        assert response.status_code == 200
        kwargs = mock_service.scoreboard.await_args.kwargs
        assert kwargs["gone_quiet_only"] is True
        assert kwargs["quiet_after_days"] == 90

    async def test_scoreboard_exposes_the_rate_and_quiet_flag(self, client: AsyncClient) -> None:
        row = (await client.get(_base("/scoreboard"))).json()["items"][0]
        assert row["close_rate"] == 0.5
        assert row["is_gone_quiet"] is True
        assert row["days_since_last_referral"] == 91

    async def test_zero_quiet_window_rejected(self, client: AsyncClient) -> None:
        """A zero-day window would flag every partner, including today's."""
        response = await client.get(_base("/scoreboard"), params={"quiet_after_days": 0})
        assert response.status_code == 422


class TestWriteValidation:
    async def test_create_valid(self, client: AsyncClient, mock_service: AsyncMock) -> None:
        response = await client.post(_base(), json={"name": "Dana Ruiz", "partner_type": "realtor"})
        assert response.status_code == 201
        assert mock_service.create.await_args.args[0] == WS_ID

    async def test_create_missing_name_422(self, client: AsyncClient) -> None:
        assert (await client.post(_base(), json={"partner_type": "realtor"})).status_code == 422

    async def test_create_blank_name_422(self, client: AsyncClient) -> None:
        assert (await client.post(_base(), json={"name": ""})).status_code == 422

    async def test_create_unknown_partner_type_422(self, client: AsyncClient) -> None:
        response = await client.post(_base(), json={"name": "Dana", "partner_type": "wizard"})
        assert response.status_code == 422

    async def test_create_invalid_email_422(self, client: AsyncClient) -> None:
        response = await client.post(_base(), json={"name": "Dana", "email": "not-an-email"})
        assert response.status_code == 422

    async def test_update_sends_only_supplied_fields(
        self, client: AsyncClient, mock_service: AsyncMock
    ) -> None:
        """Partial update must not blank the fields the operator left alone."""
        response = await client.put(_base(f"/{PARTNER_ID}"), json={"is_active": False})
        assert response.status_code == 200
        assert mock_service.update.await_args.args[2] == {"is_active": False}

    async def test_delete_returns_204(self, client: AsyncClient, mock_service: AsyncMock) -> None:
        response = await client.delete(_base(f"/{PARTNER_ID}"))
        assert response.status_code == 204
        mock_service.delete.assert_awaited_once()
