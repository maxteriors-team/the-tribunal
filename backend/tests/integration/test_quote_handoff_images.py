"""Database-backed quote handoff image behavior and authorization boundaries."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_membership
from app.api.v1 import quotes
from app.db.session import AsyncSessionLocal, engine
from app.models.quote import Quote
from app.models.quote_handoff_image import (
    MAX_HANDOFF_IMAGE_BYTES,
    MAX_HANDOFF_IMAGES_PER_QUOTE,
    QuoteHandoffImage,
)
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\nfield-photo"


@dataclass
class Scenario:
    workspace_id: uuid.UUID
    other_workspace_id: uuid.UUID
    owned_quote_id: uuid.UUID
    other_owner_quote_id: uuid.UUID
    other_workspace_quote_id: uuid.UUID
    sales_user: User
    sales_membership: WorkspaceMembership


@asynccontextmanager
async def _scenario() -> AsyncIterator[Scenario]:
    await engine.dispose()
    suffix = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        workspace = Workspace(name="Handoff images", slug=f"handoff-{suffix}")
        other_workspace = Workspace(name="Other handoff", slug=f"other-handoff-{suffix}")
        sales_user = User(
            email=f"handoff-sales-{suffix}@example.com",
            full_name="Handoff Sales",
            hashed_password="not-used",
        )
        other_sales = User(
            email=f"handoff-other-{suffix}@example.com",
            full_name="Other Sales",
            hashed_password="not-used",
        )
        db.add_all([workspace, other_workspace, sales_user, other_sales])
        await db.flush()
        sales_membership = WorkspaceMembership(
            workspace_id=workspace.id,
            user_id=sales_user.id,
            role="sales_rep",
        )
        other_membership = WorkspaceMembership(
            workspace_id=workspace.id,
            user_id=other_sales.id,
            role="sales_rep",
        )
        owned_quote = Quote(
            workspace_id=workspace.id,
            number=f"HI-{suffix[:8]}",
            assigned_user_id=sales_user.id,
            created_by_id=sales_user.id,
        )
        other_owner_quote = Quote(
            workspace_id=workspace.id,
            number=f"HO-{suffix[:8]}",
            assigned_user_id=other_sales.id,
            created_by_id=other_sales.id,
        )
        other_workspace_quote = Quote(
            workspace_id=other_workspace.id,
            number=f"HW-{suffix[:8]}",
        )
        db.add_all(
            [
                sales_membership,
                other_membership,
                owned_quote,
                other_owner_quote,
                other_workspace_quote,
            ]
        )
        await db.commit()
        scenario = Scenario(
            workspace_id=workspace.id,
            other_workspace_id=other_workspace.id,
            owned_quote_id=owned_quote.id,
            other_owner_quote_id=other_owner_quote.id,
            other_workspace_quote_id=other_workspace_quote.id,
            sales_user=sales_user,
            sales_membership=sales_membership,
        )

    try:
        yield scenario
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(Workspace).where(
                    Workspace.id.in_([scenario.workspace_id, scenario.other_workspace_id])
                )
            )
            await db.execute(delete(User).where(User.id.in_([sales_user.id, other_sales.id])))
            await db.commit()
        await engine.dispose()


def _make_app(scenario: Scenario) -> FastAPI:
    app = FastAPI()
    app.include_router(quotes.router, prefix="/api/v1/workspaces/{workspace_id}/quotes")

    async def override_db() -> AsyncIterator[AsyncSession]:
        async with AsyncSessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: scenario.sales_user
    app.dependency_overrides[get_membership] = lambda: scenario.sales_membership
    return app


def _quote_url(scenario: Scenario, quote_id: uuid.UUID) -> str:
    return f"/api/v1/workspaces/{scenario.workspace_id}/quotes/{quote_id}"


@pytest.mark.parametrize(
    ("data", "content_type"),
    [
        (b"\xff\xd8\xffphoto", "image/jpeg"),
        (PNG, "image/png"),
        (b"RIFF\x04\x00\x00\x00WEBP", "image/webp"),
    ],
)
def test_supported_image_signatures_are_canonical(data: bytes, content_type: str) -> None:
    assert quotes._detect_handoff_image_type(data) == content_type


@pytest.mark.asyncio
async def test_upload_list_download_and_delete_image() -> None:
    async with _scenario() as scenario:
        app = _make_app(scenario)
        base = f"{_quote_url(scenario, scenario.owned_quote_id)}/handoff-images"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            upload = await client.post(
                base,
                files={"file": ('../../roof "before".png', PNG, "image/png")},
            )
            assert upload.status_code == 201, upload.text
            payload = upload.json()
            assert payload["filename"] == "roof _22before_22.png"
            assert payload["content_type"] == "image/png"
            assert payload["size_bytes"] == len(PNG)

            listing = await client.get(base)
            assert listing.status_code == 200
            assert listing.json() == {
                "images": [payload],
                "max_images": MAX_HANDOFF_IMAGES_PER_QUOTE,
                "max_image_bytes": MAX_HANDOFF_IMAGE_BYTES,
            }

            image_url = f"{base}/{payload['id']}"
            download_response = await client.get(f"{image_url}/download")
            assert download_response.status_code == 200
            assert download_response.content == PNG
            assert download_response.headers["content-type"] == "image/png"
            assert download_response.headers["x-content-type-options"] == "nosniff"
            assert download_response.headers["content-disposition"] == (
                'inline; filename="roof _22before_22.png"'
            )

            delete_response = await client.delete(image_url)
            assert delete_response.status_code == 204
            assert (await client.get(base)).json()["images"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "data", "claimed_type", "expected_status"),
    [
        ("empty.png", b"", "image/png", 422),
        ("mismatch.jpg", PNG, "image/jpeg", 422),
        ("vector.svg", b"<svg></svg>", "image/svg+xml", 422),
        ("large.png", PNG + b"x" * MAX_HANDOFF_IMAGE_BYTES, "image/png", 413),
    ],
)
async def test_upload_rejects_invalid_images(
    filename: str,
    data: bytes,
    claimed_type: str,
    expected_status: int,
) -> None:
    async with _scenario() as scenario:
        app = _make_app(scenario)
        base = f"{_quote_url(scenario, scenario.owned_quote_id)}/handoff-images"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                base,
                files={"file": (filename, data, claimed_type)},
            )
        assert response.status_code == expected_status
        async with AsyncSessionLocal() as db:
            count = await db.scalar(
                select(func.count(QuoteHandoffImage.id)).where(
                    QuoteHandoffImage.quote_id == scenario.owned_quote_id
                )
            )
            assert count == 0


@pytest.mark.asyncio
async def test_upload_enforces_count_limit() -> None:
    async with _scenario() as scenario:
        async with AsyncSessionLocal() as db:
            db.add_all(
                [
                    QuoteHandoffImage(
                        workspace_id=scenario.workspace_id,
                        quote_id=scenario.owned_quote_id,
                        filename=f"photo-{index}.png",
                        content_type="image/png",
                        size_bytes=len(PNG),
                        data=PNG,
                        uploaded_by_user_id=scenario.sales_user.id,
                    )
                    for index in range(MAX_HANDOFF_IMAGES_PER_QUOTE)
                ]
            )
            await db.commit()

        app = _make_app(scenario)
        base = f"{_quote_url(scenario, scenario.owned_quote_id)}/handoff-images"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                base,
                files={"file": ("one-too-many.png", PNG, "image/png")},
            )
        assert response.status_code == 409
        assert "at most" in response.json()["detail"]


@pytest.mark.asyncio
async def test_quote_owner_and_workspace_boundaries_hide_images() -> None:
    async with _scenario() as scenario:
        app = _make_app(scenario)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            other_owner_url = (
                f"{_quote_url(scenario, scenario.other_owner_quote_id)}/handoff-images"
            )
            owner_read_denied = await client.get(other_owner_url)
            owner_write_denied = await client.post(
                other_owner_url,
                files={"file": ("hidden.png", PNG, "image/png")},
            )
            workspace_denied = await client.get(
                f"{_quote_url(scenario, scenario.other_workspace_quote_id)}/handoff-images"
            )
        assert owner_read_denied.status_code == 404
        assert owner_write_denied.status_code == 404
        assert workspace_denied.status_code == 404


@pytest.mark.asyncio
async def test_deleting_removable_quote_cascades_handoff_images() -> None:
    async with _scenario() as scenario:
        app = _make_app(scenario)
        quote_url = _quote_url(scenario, scenario.owned_quote_id)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            upload = await client.post(
                f"{quote_url}/handoff-images",
                files={"file": ("before.png", PNG, "image/png")},
            )
            assert upload.status_code == 201, upload.text
            image_id = uuid.UUID(upload.json()["id"])
            deleted = await client.delete(quote_url)
            assert deleted.status_code == 204, deleted.text

        async with AsyncSessionLocal() as db:
            assert await db.get(QuoteHandoffImage, image_id) is None
