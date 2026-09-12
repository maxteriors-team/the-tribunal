"""One-click unsubscribe must accept POST, not just GET.

Marketing mail carries ``List-Unsubscribe-Post: List-Unsubscribe=One-Click``
(RFC 8058), so Gmail and Yahoo POST the unsubscribe URL directly with no human
clicking through. A GET-only route answers that POST with 405 and the opt-out is
dropped — while the mailbox provider still shows the customer "unsubscribed".
Both ends report success and the person keeps getting mail, which is the failure
mode these tests exist to prevent.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.email_unsubscribe import public_router
from app.db.session import get_db

UNSUBSCRIBE_PATHS = ["/unsubscribe", "/unsubscribe-contact"]


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(public_router)
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=_make_app()),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest.mark.parametrize("path", UNSUBSCRIBE_PATHS)
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_unsubscribe_accepts_get_and_post(
    client: AsyncClient, path: str, method: str
) -> None:
    """Both verbs reach the handler; neither is rejected at the routing layer."""
    response = await client.request(method, path, params={"token": "not-a-real-token"})

    assert response.status_code == 200, f"{method} {path} must not 405"
    assert "invalid or has expired" in response.text


@pytest.mark.parametrize("path", UNSUBSCRIBE_PATHS)
async def test_unsubscribe_rejects_unused_verbs(client: AsyncClient, path: str) -> None:
    """Only the two verbs one-click needs — no accidental DELETE/PUT surface."""
    response = await client.request("DELETE", path, params={"token": "x"})

    assert response.status_code == 405
