"""Regression coverage for retired Quo HTTP surfaces."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.parametrize(
    ("method", "path"),
    [
        (
            "GET",
            f"/api/v1/workspaces/{uuid.uuid4()}/integrations/quo/active-line",
        ),
        ("POST", f"/webhooks/quo/{uuid.uuid4()}"),
    ],
)
async def test_retired_quo_routes_return_not_found(method: str, path: str) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.request(method, path, json={})

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
