"""Assignment- and workspace-scoped job handoff image behavior."""

from __future__ import annotations

import asyncio
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
from app.models.job_handoff_image import JobHandoffImage
from app.models.quote import Quote
from app.models.quote_handoff_image import (
    MAX_HANDOFF_IMAGE_BYTES,
    MAX_HANDOFF_IMAGES_PER_QUOTE,
    QuoteHandoffImage,
)
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\nassigned-field-photo"


@dataclass
class Scenario:
    workspace_id: uuid.UUID
    other_workspace_id: uuid.UUID
    quote_id: uuid.UUID
    quote_image_id: uuid.UUID
    assigned_job_id: uuid.UUID
    direct_job_id: uuid.UUID
    other_job_id: uuid.UUID
    other_image_id: uuid.UUID
    assigned_user: User
    unassigned_user: User
    dispatcher_user: User


@asynccontextmanager
async def _scenario() -> AsyncIterator[Scenario]:
    await engine.dispose()
    suffix = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        workspace = Workspace(name="Job handoff images", slug=f"job-handoff-{suffix}")
        other_workspace = Workspace(name="Other job handoff", slug=f"other-job-handoff-{suffix}")
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
        db.add_all([workspace, other_workspace, assigned_user, unassigned_user, dispatcher_user])
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
        other_phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
        contact = Contact(
            workspace_id=workspace.id,
            first_name="Image",
            last_name="Customer",
            phone_number=phone,
            phone_hash=hash_phone(phone),
        )
        other_contact = Contact(
            workspace_id=other_workspace.id,
            first_name="Other",
            last_name="Customer",
            phone_number=other_phone,
            phone_hash=hash_phone(other_phone),
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
        db.add_all([contact, other_contact, assigned_technician, unassigned_technician])
        await db.flush()
        quote = Quote(
            workspace_id=workspace.id,
            contact_id=contact.id,
            number=f"JHI-{suffix[:8]}",
            created_by_id=dispatcher_user.id,
        )
        db.add(quote)
        await db.flush()
        quote_image = QuoteHandoffImage(
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
        direct_job = Job(
            workspace_id=workspace.id,
            contact_id=contact.id,
            title="Service call",
        )
        other_job = Job(
            workspace_id=other_workspace.id,
            contact_id=other_contact.id,
            title="Other workspace job",
        )
        db.add_all([quote_image, assigned_job, direct_job, other_job])
        await db.flush()
        other_image = JobHandoffImage(
            workspace_id=other_workspace.id,
            job_id=other_job.id,
            filename="hidden.png",
            content_type="image/png",
            size_bytes=len(PNG),
            data=PNG,
        )
        db.add_all(
            [
                other_image,
                JobAssignment(
                    job_id=assigned_job.id,
                    technician_id=assigned_technician.id,
                ),
                JobAssignment(
                    job_id=direct_job.id,
                    technician_id=assigned_technician.id,
                ),
            ]
        )
        await db.commit()
        scenario = Scenario(
            workspace_id=workspace.id,
            other_workspace_id=other_workspace.id,
            quote_id=quote.id,
            quote_image_id=quote_image.id,
            assigned_job_id=assigned_job.id,
            direct_job_id=direct_job.id,
            other_job_id=other_job.id,
            other_image_id=other_image.id,
            assigned_user=assigned_user,
            unassigned_user=unassigned_user,
            dispatcher_user=dispatcher_user,
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


def _make_app(identity: dict[str, User]) -> FastAPI:
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


def _quote_images_url(scenario: Scenario) -> str:
    return f"/api/v1/workspaces/{scenario.workspace_id}/quotes/{scenario.quote_id}/handoff-images"


@pytest.mark.asyncio
async def test_assigned_technician_lists_and_downloads_quote_images() -> None:
    async with _scenario() as scenario:
        identity = {"user": scenario.assigned_user}
        app = _make_app(identity)
        base = _job_images_url(scenario, scenario.assigned_job_id)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            listing = await client.get(base)
            assert listing.status_code == 200, listing.text
            assert listing.json()["images"][0] == {
                "id": str(scenario.quote_image_id),
                "source": "quote",
                "filename": "roof-before.png",
                "content_type": "image/png",
                "size_bytes": len(PNG),
                "created_at": listing.json()["images"][0]["created_at"],
            }

            download = await client.get(f"{base}/{scenario.quote_image_id}/download")
            assert download.status_code == 200
            assert download.content == PNG
            assert download.headers["content-type"] == "image/png"
            assert download.headers["x-content-type-options"] == "nosniff"
            assert download.headers["cache-control"].startswith("private")


@pytest.mark.asyncio
async def test_dispatcher_uploads_downloads_and_deletes_direct_job_image() -> None:
    async with _scenario() as scenario:
        identity = {"user": scenario.dispatcher_user}
        app = _make_app(identity)
        base = _job_images_url(scenario, scenario.direct_job_id)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            upload = await client.post(
                base,
                files={"file": ('../../site "before".png', PNG, "image/png")},
            )
            assert upload.status_code == 201, upload.text
            payload = upload.json()
            assert payload["source"] == "job"
            assert payload["filename"] == "site _22before_22.png"
            assert payload["size_bytes"] == len(PNG)
            assert "data" not in payload

            listing = await client.get(base)
            assert listing.status_code == 200
            assert listing.json()["images"] == [payload]
            assert listing.json()["max_images"] == MAX_HANDOFF_IMAGES_PER_QUOTE

            download = await client.get(f"{base}/{payload['id']}/download")
            assert download.status_code == 200
            assert download.content == PNG
            assert download.headers["content-disposition"].startswith("inline;")
            assert download.headers["x-content-type-options"] == "nosniff"
            assert download.headers["cache-control"].startswith("private")

            deleted = await client.delete(f"{base}/{payload['id']}")
            assert deleted.status_code == 204, deleted.text
            assert (await client.get(f"{base}/{payload['id']}/download")).status_code == 404
            assert (await client.get(base)).json()["images"] == []


@pytest.mark.asyncio
async def test_job_and_quote_images_merge_for_assigned_technician() -> None:
    async with _scenario() as scenario:
        identity = {"user": scenario.dispatcher_user}
        app = _make_app(identity)
        base = _job_images_url(scenario, scenario.assigned_job_id)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            upload = await client.post(
                base,
                files={"file": ("job-reference.png", PNG, "image/png")},
            )
            assert upload.status_code == 201, upload.text
            job_image_id = upload.json()["id"]

            identity["user"] = scenario.assigned_user
            listing = await client.get(base)
            assert listing.status_code == 200
            assert [image["source"] for image in listing.json()["images"]] == ["job", "quote"]
            assert (await client.get(f"{base}/{job_image_id}/download")).status_code == 200

            identity["user"] = scenario.dispatcher_user
            immutable_delete = await client.delete(f"{base}/{scenario.quote_image_id}")
            assert immutable_delete.status_code == 404
            quote_listing = await client.get(_quote_images_url(scenario))
            assert quote_listing.status_code == 200
            assert [image["id"] for image in quote_listing.json()["images"]] == [
                str(scenario.quote_image_id)
            ]


@pytest.mark.asyncio
async def test_job_upload_rejects_invalid_empty_spoofed_and_oversized_files() -> None:
    async with _scenario() as scenario:
        identity = {"user": scenario.dispatcher_user}
        app = _make_app(identity)
        base = _job_images_url(scenario, scenario.direct_job_id)
        oversized = PNG + b"x" * (MAX_HANDOFF_IMAGE_BYTES - len(PNG) + 1)
        cases = [
            (("bad.png", b"not-an-image", "image/png"), 422),
            (("spoofed.jpg", PNG, "image/jpeg"), 422),
            (("empty.png", b"", "image/png"), 422),
            (("oversized.png", oversized, "image/png"), 413),
        ]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for file, expected_status in cases:
                response = await client.post(base, files={"file": file})
                assert response.status_code == expected_status, response.text
            assert (await client.get(base)).json()["images"] == []


@pytest.mark.asyncio
async def test_quote_and_job_uploads_share_one_image_limit() -> None:
    async with _scenario() as scenario:
        async with AsyncSessionLocal() as db:
            db.add_all(
                [
                    JobHandoffImage(
                        workspace_id=scenario.workspace_id,
                        job_id=scenario.assigned_job_id,
                        filename=f"job-photo-{index}.png",
                        content_type="image/png",
                        size_bytes=len(PNG),
                        data=PNG,
                        uploaded_by_user_id=scenario.dispatcher_user.id,
                    )
                    for index in range(MAX_HANDOFF_IMAGES_PER_QUOTE - 1)
                ]
            )
            await db.commit()

        identity = {"user": scenario.dispatcher_user}
        app = _make_app(identity)
        job_base = _job_images_url(scenario, scenario.assigned_job_id)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            job_upload = await client.post(
                job_base,
                files={"file": ("too-many-job.png", PNG, "image/png")},
            )
            quote_upload = await client.post(
                _quote_images_url(scenario),
                files={"file": ("too-many-quote.png", PNG, "image/png")},
            )
            listing = await client.get(job_base)
        assert job_upload.status_code == 409
        assert quote_upload.status_code == 409
        assert len(listing.json()["images"]) == MAX_HANDOFF_IMAGES_PER_QUOTE


@pytest.mark.asyncio
async def test_concurrent_quote_and_job_uploads_cannot_exceed_shared_limit() -> None:
    async with _scenario() as scenario:
        async with AsyncSessionLocal() as db:
            db.add_all(
                [
                    JobHandoffImage(
                        workspace_id=scenario.workspace_id,
                        job_id=scenario.assigned_job_id,
                        filename=f"existing-{index}.png",
                        content_type="image/png",
                        size_bytes=len(PNG),
                        data=PNG,
                        uploaded_by_user_id=scenario.dispatcher_user.id,
                    )
                    for index in range(MAX_HANDOFF_IMAGES_PER_QUOTE - 2)
                ]
            )
            await db.commit()

        identity = {"user": scenario.dispatcher_user}
        app = _make_app(identity)
        transport = ASGITransport(app=app)
        async with (
            AsyncClient(transport=transport, base_url="http://test") as job_client,
            AsyncClient(transport=transport, base_url="http://test") as quote_client,
        ):
            job_upload, quote_upload = await asyncio.gather(
                job_client.post(
                    _job_images_url(scenario, scenario.assigned_job_id),
                    files={"file": ("concurrent-job.png", PNG, "image/png")},
                ),
                quote_client.post(
                    _quote_images_url(scenario),
                    files={"file": ("concurrent-quote.png", PNG, "image/png")},
                ),
            )
            listing = await job_client.get(_job_images_url(scenario, scenario.assigned_job_id))

        assert sorted([job_upload.status_code, quote_upload.status_code]) == [201, 409]
        assert len(listing.json()["images"]) == MAX_HANDOFF_IMAGES_PER_QUOTE


@pytest.mark.asyncio
async def test_technicians_cannot_write_job_or_quote_images() -> None:
    async with _scenario() as scenario:
        identity = {"user": scenario.assigned_user}
        app = _make_app(identity)
        job_base = _job_images_url(scenario, scenario.assigned_job_id)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            job_upload = await client.post(
                job_base,
                files={"file": ("blocked.png", PNG, "image/png")},
            )
            job_delete = await client.delete(f"{job_base}/{scenario.quote_image_id}")
            quote_listing = await client.get(_quote_images_url(scenario))
            quote_upload = await client.post(
                _quote_images_url(scenario),
                files={"file": ("blocked.png", PNG, "image/png")},
            )
        assert job_upload.status_code == 403
        assert job_delete.status_code == 403
        assert quote_listing.status_code == 403
        assert quote_upload.status_code == 403


@pytest.mark.asyncio
async def test_unassigned_technician_cannot_list_or_download_images() -> None:
    async with _scenario() as scenario:
        identity = {"user": scenario.unassigned_user}
        app = _make_app(identity)
        base = _job_images_url(scenario, scenario.assigned_job_id)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            listing = await client.get(base)
            download = await client.get(f"{base}/{scenario.quote_image_id}/download")
        assert listing.status_code == 404
        assert download.status_code == 404


@pytest.mark.asyncio
async def test_cross_workspace_job_and_image_ids_stay_hidden() -> None:
    async with _scenario() as scenario:
        identity = {"user": scenario.dispatcher_user}
        app = _make_app(identity)
        own_job_base = _job_images_url(scenario, scenario.direct_job_id)
        other_job_base = _job_images_url(scenario, scenario.other_job_id)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            cross_job_list = await client.get(other_job_base)
            cross_job_upload = await client.post(
                other_job_base,
                files={"file": ("blocked.png", PNG, "image/png")},
            )
            cross_image_download = await client.get(
                f"{own_job_base}/{scenario.other_image_id}/download"
            )
            cross_image_delete = await client.delete(f"{own_job_base}/{scenario.other_image_id}")
        assert cross_job_list.status_code == 404
        assert cross_job_upload.status_code == 404
        assert cross_image_download.status_code == 404
        assert cross_image_delete.status_code == 404
