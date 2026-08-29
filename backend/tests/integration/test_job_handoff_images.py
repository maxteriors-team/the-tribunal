"""Assignment-scoped job access to quote handoff images."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.v1 import jobs, quotes
from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.field_service import Job, JobAssignment, Technician
from app.models.quote import Quote
from app.models.quote_handoff_image import QuoteHandoffImage
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\nassigned-field-photo"


@dataclass
class Scenario:
    workspace_id: uuid.UUID
    quote_id: uuid.UUID
    image_id: uuid.UUID
    assigned_job_id: uuid.UUID
    no_source_job_id: uuid.UUID
    assigned_user: User
    unassigned_user: User
    dispatcher_user: User


@asynccontextmanager
async def _scenario() -> AsyncIterator[Scenario]:
    await engine.dispose()
    suffix = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        workspace = Workspace(name="Job handoff images", slug=f"job-handoff-{suffix}")
        assigned_user = User(
            email=f"assigned-tech-{suffix}@example.com",
            full_name="Assigned Technician",
            hashed_password="not-used",
        )
        unassigned_user = User(
            email=f"unassigned-tech-{suffix}@example.com",
            full_name="Unassigned Technician",
            hashed_password="not-used",
        )
        dispatcher_user = User(
            email=f"handoff-dispatch-{suffix}@example.com",
            full_name="Dispatcher",
            hashed_password="not-used",
        )
        db.add_all([workspace, assigned_user, unassigned_user, dispatcher_user])
        await db.flush()
        db.add_all(
            [
                WorkspaceMembership(
                    workspace_id=workspace.id,
                    user_id=assigned_user.id,
                    role="technician",
                ),
                WorkspaceMembership(
                    workspace_id=workspace.id,
                    user_id=unassigned_user.id,
                    role="technician",
                ),
                WorkspaceMembership(
                    workspace_id=workspace.id,
                    user_id=dispatcher_user.id,
                    role="dispatcher",
                ),
            ]
        )
        phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
        contact = Contact(
            workspace_id=workspace.id,
            first_name="Image",
            last_name="Customer",
            phone_number=phone,
            phone_hash=hash_phone(phone),
        )
        assigned_technician = Technician(
            workspace_id=workspace.id,
            user_id=assigned_user.id,
            name="Assigned Technician",
        )
        unassigned_technician = Technician(
            workspace_id=workspace.id,
            user_id=unassigned_user.id,
            name="Unassigned Technician",
        )
        db.add_all([contact, assigned_technician, unassigned_technician])
        await db.flush()
        quote = Quote(
            workspace_id=workspace.id,
            contact_id=contact.id,
            number=f"JHI-{suffix[:8]}",
            created_by_id=dispatcher_user.id,
        )
        db.add(quote)
        await db.flush()
        image = QuoteHandoffImage(
            workspace_id=workspace.id,
            quote_id=quote.id,
            filename="roof-before.png",
            content_type="image/png",
            size_bytes=len(PNG),
            data=PNG,
            uploaded_by_user_id=dispatcher_user.id,
        )
        assigned_job = Job(
            workspace_id=workspace.id,
            contact_id=contact.id,
            source_quote_id=quote.id,
            title="Install roofline lights",
        )
        no_source_job = Job(
            workspace_id=workspace.id,
            contact_id=contact.id,
            title="Service call",
        )
        db.add_all([image, assigned_job, no_source_job])
        await db.flush()
        db.add_all(
            [
                JobAssignment(
                    job_id=assigned_job.id,
                    technician_id=assigned_technician.id,
                ),
                JobAssignment(
                    job_id=no_source_job.id,
                    technician_id=assigned_technician.id,
                ),
            ]
        )
        await db.commit()
        scenario = Scenario(
            workspace_id=workspace.id,
            quote_id=quote.id,
            image_id=image.id,
            assigned_job_id=assigned_job.id,
            no_source_job_id=no_source_job.id,
            assigned_user=assigned_user,
            unassigned_user=unassigned_user,
            dispatcher_user=dispatcher_user,
        )

    try:
        yield scenario
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Workspace).where(Workspace.id == scenario.workspace_id))
            await db.execute(
                delete(User).where(
                    User.id.in_(
                        [
                            scenario.assigned_user.id,
                            scenario.unassigned_user.id,
                            scenario.dispatcher_user.id,
                        ]
                    )
                )
            )
            await db.commit()
        await engine.dispose()


def _make_app(scenario: Scenario, identity: dict[str, User]) -> FastAPI:
    app = FastAPI()
    app.include_router(jobs.router, prefix="/api/v1/workspaces/{workspace_id}/jobs")
    app.include_router(quotes.router, prefix="/api/v1/workspaces/{workspace_id}/quotes")

    async def override_db() -> AsyncIterator[AsyncSession]:
        async with AsyncSessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    return app


def _job_images_url(scenario: Scenario, job_id: uuid.UUID) -> str:
    return f"/api/v1/workspaces/{scenario.workspace_id}/jobs/{job_id}/handoff-images"


@pytest.mark.asyncio
async def test_assigned_technician_lists_and_downloads_images() -> None:
    async with _scenario() as scenario:
        identity = {"user": scenario.assigned_user}
        app = _make_app(scenario, identity)
        base = _job_images_url(scenario, scenario.assigned_job_id)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            listing = await client.get(base)
            assert listing.status_code == 200, listing.text
            assert [item["id"] for item in listing.json()["images"]] == [str(scenario.image_id)]

            download = await client.get(f"{base}/{scenario.image_id}/download")
            assert download.status_code == 200
            assert download.content == PNG
            assert download.headers["content-type"] == "image/png"
            assert download.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_unassigned_technician_cannot_list_or_download_images() -> None:
    async with _scenario() as scenario:
        identity = {"user": scenario.unassigned_user}
        app = _make_app(scenario, identity)
        base = _job_images_url(scenario, scenario.assigned_job_id)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            listing = await client.get(base)
            download = await client.get(f"{base}/{scenario.image_id}/download")
        assert listing.status_code == 404
        assert download.status_code == 404


@pytest.mark.asyncio
async def test_dispatcher_can_read_and_job_without_source_quote_is_empty() -> None:
    async with _scenario() as scenario:
        identity = {"user": scenario.dispatcher_user}
        app = _make_app(scenario, identity)
        assigned_base = _job_images_url(scenario, scenario.assigned_job_id)
        empty_base = _job_images_url(scenario, scenario.no_source_job_id)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get(assigned_base)).status_code == 200
            empty = await client.get(empty_base)
            missing_download = await client.get(f"{empty_base}/{scenario.image_id}/download")
        assert empty.status_code == 200
        assert empty.json()["images"] == []
        assert missing_download.status_code == 404


@pytest.mark.asyncio
async def test_technician_cannot_use_quote_image_routes() -> None:
    async with _scenario() as scenario:
        identity = {"user": scenario.assigned_user}
        app = _make_app(scenario, identity)
        quote_base = (
            f"/api/v1/workspaces/{scenario.workspace_id}/quotes/{scenario.quote_id}/handoff-images"
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            listing = await client.get(quote_base)
            upload = await client.post(
                quote_base,
                files={"file": ("blocked.png", PNG, "image/png")},
            )
            delete_response = await client.delete(f"{quote_base}/{scenario.image_id}")
        assert listing.status_code == 403
        assert upload.status_code == 403
        assert delete_response.status_code == 403
