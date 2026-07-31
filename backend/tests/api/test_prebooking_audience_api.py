"""HTTP contract for the pre-booking audience slices.

Offline-mockable style (cf. ``test_jobs_api.py``): no real database. The audience
service is replaced with an ``AsyncMock`` so these assert the *route* — that the
new seasonal-renewal slice is actually reachable over HTTP, that its bounds are
enforced at the edge, and that the router forwards the flags rather than
dropping them. Selection behaviour is proven against a real database in
``tests/services/prebooking/test_prebooking_flow.py``.

The forwarding assertion is the point: a query parameter that parses but never
reaches the service is the failure mode that looks fine in a schema diff and
silently mails last season's renewal offer to the entire contact table.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
from app.api.v1 import prebooking as prebooking_module
from app.services.prebooking.audience import AudienceCounts

WS_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _mount(app: FastAPI) -> None:
    app.include_router(
        prebooking_module.workspace_router,
        prefix="/api/v1/workspaces/{workspace_id}/pre-booking",
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


@pytest.fixture
def mock_service() -> AsyncMock:
    service = AsyncMock()
    service.preview.return_value = AudienceCounts(
        total=143,
        past_customers=900,
        unsold_quotes=210,
        prior_season_christmas=143,
        excluded_opted_out=12,
        excluded_already_enrolled=0,
    )
    return service


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
    _mount(app)

    with patch.object(
        prebooking_module, "PreBookingAudienceService", return_value=mock_service
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            yield ac


def _url() -> str:
    return f"/api/v1/workspaces/{WS_ID}/pre-booking/audience"


async def test_the_renewal_count_crosses_the_wire(client: AsyncClient) -> None:
    response = await client.get(_url())

    assert response.status_code == 200
    assert response.json()["prior_season_christmas"] == 143


async def test_the_renewal_slice_is_off_unless_asked_for(
    client: AsyncClient, mock_service: AsyncMock
) -> None:
    await client.get(_url())

    assert mock_service.preview.await_args.kwargs["include_prior_season_christmas"] is False
    assert mock_service.preview.await_args.kwargs["seasons_back"] is None


async def test_a_renewal_push_forwards_every_flag_to_the_service(
    client: AsyncClient, mock_service: AsyncMock
) -> None:
    """Broad slices off, seasonal on — the shape of an actual renewal campaign."""
    response = await client.get(
        _url(),
        params={
            "include_past_customers": "false",
            "include_unsold_quotes": "false",
            "include_prior_season_christmas": "true",
            "seasons_back": 1,
        },
    )

    assert response.status_code == 200
    kwargs = mock_service.preview.await_args.kwargs
    assert kwargs["include_past_customers"] is False
    assert kwargs["include_unsold_quotes"] is False
    assert kwargs["include_prior_season_christmas"] is True
    assert kwargs["seasons_back"] == 1


@pytest.mark.parametrize("seasons_back", [0, -1, 11])
async def test_an_out_of_range_lookback_is_rejected_at_the_edge(
    client: AsyncClient, seasons_back: int
) -> None:
    """A season count of zero or a decade back is a typo, not a query."""
    response = await client.get(_url(), params={"seasons_back": seasons_back})

    assert response.status_code == 422
