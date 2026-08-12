"""Integration tests for :class:`app.services.jobs.JobService`.

Hits the real database (marked ``integration``; deselected by default, run with
``-m integration``). Each test opens an ``AsyncSessionLocal`` and never commits,
so the transaction rolls back on close and the dev database stays clean.

Coverage: CRUD + status derivation, schedule, assign/unassign idempotency,
``list_for_user`` resolution (technician + crew visibility, empty for non-techs),
list filters (status / crew / technician / date range), and cross-workspace 404s.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.core.encryption import hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.field_service import Crew, JobAssignment, JobStatus, Technician
from app.models.lighting_project import LightingProject
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.services.jobs import JobService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the asyncpg pool around each test to avoid closed-loop reuse."""
    await engine.dispose()
    yield
    await engine.dispose()


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Dispatch", slug=f"disp-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _user(db) -> User:
    email = f"tech-{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email=email,
        email_hash=hash_value(email),
        hashed_password="x",
        full_name="Field Worker",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _member(db, workspace_id: uuid.UUID, user_id: int) -> WorkspaceMembership:
    membership = WorkspaceMembership(workspace_id=workspace_id, user_id=user_id, role="dispatcher")
    db.add(membership)
    await db.flush()
    return membership


async def _contact(db, workspace_id: uuid.UUID) -> Contact:
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Ada",
        last_name="Lovelace",
        email=f"ada-{uuid.uuid4().hex[:6]}@example.com",
        phone_number=f"+1555{uuid.uuid4().int % 10_000_000:07d}",
    )
    db.add(contact)
    await db.flush()
    return contact


async def _crew(db, workspace_id: uuid.UUID) -> Crew:
    crew = Crew(workspace_id=workspace_id, name=f"Crew {uuid.uuid4().hex[:6]}")
    db.add(crew)
    await db.flush()
    return crew


async def _technician(
    db,
    workspace_id: uuid.UUID,
    *,
    user_id: int | None = None,
    crew_id: uuid.UUID | None = None,
    is_active: bool = True,
) -> Technician:
    tech = Technician(
        workspace_id=workspace_id,
        name=f"Tech {uuid.uuid4().hex[:6]}",
        user_id=user_id,
        crew_id=crew_id,
        is_active=is_active,
    )
    db.add(tech)
    await db.flush()
    return tech


def _window() -> tuple[datetime, datetime]:
    start = datetime.now(UTC) + timedelta(days=1)
    return start, start + timedelta(hours=2)


def _landscape_document() -> dict:
    return {
        "version": 2,
        "activeShotId": "other",
        "shots": [
            {
                "id": "install-front",
                "photo": {
                    "dataUrl": "data:image/png;base64,AAAA",
                    "width": 1200,
                    "height": 800,
                },
                "design": {
                    "calibration": None,
                    "runs": [],
                    "items": [
                        {
                            "id": "fixture-1",
                            "productId": "uplight",
                            "at": {"x": 20, "y": 30},
                            "sizePx": 24,
                            "catalogSku": "UP-01",
                        }
                    ],
                    "planImages": [],
                },
                "dusk": 0.4,
                "sheet": {
                    "label": "Front",
                    "drawingTitle": "Installation",
                    "drawingNumber": "L-1",
                },
            },
            {
                "id": "other",
                "photo": {
                    "dataUrl": "data:image/png;base64,BBBB",
                    "width": 800,
                    "height": 600,
                },
                "design": {"calibration": None, "runs": [], "items": [], "planImages": []},
                "dusk": 0.1,
            },
        ],
        "updatedAt": "2026-08-12T00:00:00Z",
        "procurement": {
            "fixture-1": {
                "catalogSku": "UP-01",
                "orderedQuantity": 4,
                "receivedQuantity": 2,
                "supplierNote": "private cost/vendor note",
            }
        },
        "precon": {"responses": [], "leadInstaller": "Hidden", "notes": "Field brief"},
    }


# --------------------------------------------------------------------------- #
# Create + status derivation
# --------------------------------------------------------------------------- #
async def test_create_without_window_is_unscheduled() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        job = await JobService(db).create(ws.id, {"contact_id": contact.id, "title": "Fix HVAC"})
        assert job.status == JobStatus.UNSCHEDULED
        assert job.scheduled_start is None
        assert job.technicians == []


async def test_create_with_window_is_scheduled() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        start, end = _window()
        job = await JobService(db).create(
            ws.id,
            {
                "contact_id": contact.id,
                "title": "Install",
                "scheduled_start": start,
                "scheduled_end": end,
            },
        )
        assert job.status == JobStatus.SCHEDULED


async def test_create_with_technicians_tags_them() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        t1 = await _technician(db, ws.id)
        t2 = await _technician(db, ws.id)
        job = await JobService(db).create(
            ws.id,
            {
                "contact_id": contact.id,
                "title": "Two-tech job",
                "technician_ids": [t1.id, t2.id, t1.id],  # duplicate is ignored
            },
        )
        assert {t.id for t in job.technicians} == {t1.id, t2.id}


async def test_create_cross_workspace_contact_404() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        other = await _workspace(db)
        foreign_contact = await _contact(db, other.id)
        with pytest.raises(HTTPException) as exc:
            await JobService(db).create(ws.id, {"contact_id": foreign_contact.id, "title": "X"})
        assert exc.value.status_code == 404


async def test_create_cross_workspace_technician_404() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        other = await _workspace(db)
        contact = await _contact(db, ws.id)
        foreign_tech = await _technician(db, other.id)
        with pytest.raises(HTTPException) as exc:
            await JobService(db).create(
                ws.id,
                {
                    "contact_id": contact.id,
                    "title": "X",
                    "technician_ids": [foreign_tech.id],
                },
            )
        assert exc.value.status_code == 404


async def test_create_inactive_technician_404() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        retired = await _technician(db, ws.id, is_active=False)
        with pytest.raises(HTTPException) as exc:
            await JobService(db).create(
                ws.id,
                {
                    "contact_id": contact.id,
                    "title": "Retired crew is invalid",
                    "technician_ids": [retired.id],
                },
            )
        assert exc.value.status_code == 404


# --------------------------------------------------------------------------- #
# Schedule + update status transitions
# --------------------------------------------------------------------------- #
async def test_schedule_flips_unscheduled_to_scheduled() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        service = JobService(db)
        job = await service.create(ws.id, {"contact_id": contact.id, "title": "Q"})
        start, end = _window()
        scheduled = await service.schedule(job.id, ws.id, start, end)
        assert scheduled.status == JobStatus.SCHEDULED
        assert scheduled.scheduled_start == start


async def test_update_clearing_window_returns_to_unscheduled() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        service = JobService(db)
        start, end = _window()
        job = await service.create(
            ws.id,
            {
                "contact_id": contact.id,
                "title": "Q",
                "scheduled_start": start,
                "scheduled_end": end,
            },
        )
        cleared = await service.update(
            job.id, ws.id, {"scheduled_start": None, "scheduled_end": None}
        )
        assert cleared.status == JobStatus.UNSCHEDULED


async def test_update_inverted_window_rejected() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        service = JobService(db)
        start, end = _window()
        job = await service.create(
            ws.id,
            {
                "contact_id": contact.id,
                "title": "Q",
                "scheduled_start": start,
                "scheduled_end": end,
            },
        )
        # PATCH only the end to before the existing start (partial window edit).
        with pytest.raises(HTTPException) as exc:
            await service.update(job.id, ws.id, {"scheduled_end": start - timedelta(hours=1)})
        assert exc.value.status_code == 400


async def test_update_explicit_status_is_preserved() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        service = JobService(db)
        start, end = _window()
        job = await service.create(
            ws.id,
            {
                "contact_id": contact.id,
                "title": "Q",
                "scheduled_start": start,
                "scheduled_end": end,
            },
        )
        updated = await service.update(job.id, ws.id, {"status": JobStatus.IN_PROGRESS})
        assert updated.status == JobStatus.IN_PROGRESS


# --------------------------------------------------------------------------- #
# Assign / unassign idempotency
# --------------------------------------------------------------------------- #
async def test_assign_is_idempotent() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        tech = await _technician(db, ws.id)
        service = JobService(db)
        job = await service.create(ws.id, {"contact_id": contact.id, "title": "Q"})

        await service.assign_technicians(job.id, ws.id, [tech.id])
        result = await service.assign_technicians(job.id, ws.id, [tech.id])
        assert [t.id for t in result.technicians] == [tech.id]

        rows = (
            await db.execute(JobAssignment.__table__.select().where(JobAssignment.job_id == job.id))
        ).all()
        assert len(rows) == 1


async def test_unassign_removes_and_is_noop_when_absent() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        tech = await _technician(db, ws.id)
        service = JobService(db)
        job = await service.create(
            ws.id,
            {"contact_id": contact.id, "title": "Q", "technician_ids": [tech.id]},
        )
        removed = await service.unassign_technician(job.id, ws.id, tech.id)
        assert removed.technicians == []
        # Removing again is a no-op (no error).
        again = await service.unassign_technician(job.id, ws.id, tech.id)
        assert again.technicians == []


# --------------------------------------------------------------------------- #
# list filters
# --------------------------------------------------------------------------- #
async def test_list_filters_by_status_crew_and_technician() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        crew = await _crew(db, ws.id)
        tech = await _technician(db, ws.id)
        service = JobService(db)

        unscheduled = await service.create(ws.id, {"contact_id": contact.id, "title": "U"})
        in_crew = await service.create(
            ws.id, {"contact_id": contact.id, "title": "C", "crew_id": crew.id}
        )
        tagged = await service.create(
            ws.id,
            {"contact_id": contact.id, "title": "T", "technician_ids": [tech.id]},
        )

        by_status = await service.list(ws.id, status=JobStatus.UNSCHEDULED)
        ids = {item.id for item in by_status["items"]}
        assert {unscheduled.id, in_crew.id, tagged.id} <= ids

        by_crew = await service.list(ws.id, crew_id=crew.id)
        assert [item.id for item in by_crew["items"]] == [in_crew.id]

        by_tech = await service.list(ws.id, technician_id=tech.id)
        assert [item.id for item in by_tech["items"]] == [tagged.id]


async def test_list_filters_by_business_location() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        service = JobService(db)
        from app.services.field_service import BusinessLocationService

        branch = await BusinessLocationService(db).create(ws.id, {"name": "Austin"})
        at_branch = await service.create(
            ws.id,
            {
                "contact_id": contact.id,
                "title": "At branch",
                "business_location_id": branch.id,
            },
        )
        unassigned = await service.create(ws.id, {"contact_id": contact.id, "title": "Unassigned"})

        # Filtering by the branch returns only that branch's job.
        filtered = await service.list(ws.id, business_location_id=branch.id)
        assert [item.id for item in filtered["items"]] == [at_branch.id]

        # No filter returns everything (today's behavior).
        every = {item.id for item in (await service.list(ws.id))["items"]}
        assert {at_branch.id, unassigned.id} <= every


async def test_create_with_cross_workspace_location_is_404() -> None:
    async with AsyncSessionLocal() as db:
        ws_a = await _workspace(db)
        ws_b = await _workspace(db)
        contact = await _contact(db, ws_a.id)
        from app.services.field_service import BusinessLocationService

        branch_b = await BusinessLocationService(db).create(ws_b.id, {"name": "Dallas"})
        with pytest.raises(HTTPException) as exc:
            await JobService(db).create(
                ws_a.id,
                {
                    "contact_id": contact.id,
                    "title": "X",
                    "business_location_id": branch_b.id,
                },
            )
        assert exc.value.status_code == 404


async def test_list_filters_by_date_range() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        service = JobService(db)
        base = datetime.now(UTC) + timedelta(days=10)
        await service.create(
            ws.id,
            {
                "contact_id": contact.id,
                "title": "in-range",
                "scheduled_start": base,
                "scheduled_end": base + timedelta(hours=1),
            },
        )
        out = base + timedelta(days=40)
        await service.create(
            ws.id,
            {
                "contact_id": contact.id,
                "title": "out-of-range",
                "scheduled_start": out,
                "scheduled_end": out + timedelta(hours=1),
            },
        )
        result = await service.list(
            ws.id,
            date_from=base - timedelta(days=1),
            date_to=base + timedelta(days=1),
        )
        titles = {item.title for item in result["items"]}
        assert titles == {"in-range"}


# --------------------------------------------------------------------------- #
# list_for_user resolution
# --------------------------------------------------------------------------- #
async def test_list_for_user_includes_direct_and_crew_jobs() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        user = await _user(db)
        await _member(db, ws.id, user.id)
        crew = await _crew(db, ws.id)
        tech = await _technician(db, ws.id, user_id=user.id, crew_id=crew.id)
        other_tech = await _technician(db, ws.id)
        service = JobService(db)

        direct = await service.create(
            ws.id,
            {"contact_id": contact.id, "title": "direct", "technician_ids": [tech.id]},
        )
        via_crew = await service.create(
            ws.id, {"contact_id": contact.id, "title": "crew", "crew_id": crew.id}
        )
        # A job for someone else, not on this user's calendar.
        await service.create(
            ws.id,
            {
                "contact_id": contact.id,
                "title": "other",
                "technician_ids": [other_tech.id],
            },
        )

        result = await service.list_for_user(ws.id, user.id)
        assert {item.id for item in result["items"]} == {direct.id, via_crew.id}


async def test_list_for_user_empty_when_not_a_technician() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        user = await _user(db)
        await _member(db, ws.id, user.id)
        service = JobService(db)
        await service.create(ws.id, {"contact_id": contact.id, "title": "Q"})

        result = await service.list_for_user(ws.id, user.id)
        assert result == {"items": [], "total": 0}


# --------------------------------------------------------------------------- #
# Cross-workspace isolation
# --------------------------------------------------------------------------- #
async def test_get_cross_workspace_404() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        other = await _workspace(db)
        contact = await _contact(db, ws.id)
        job = await JobService(db).create(ws.id, {"contact_id": contact.id, "title": "Q"})
        with pytest.raises(HTTPException) as exc:
            await JobService(db).get(job.id, other.id)
        assert exc.value.status_code == 404


async def test_installation_plan_is_redacted_and_assignment_scoped() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        assigned_user = await _user(db)
        assigned = await _member(db, ws.id, assigned_user.id)
        assigned.role = "technician"
        assigned_tech = await _technician(db, ws.id, user_id=assigned_user.id)
        crew_user = await _user(db)
        crew_tech = await _technician(db, ws.id, user_id=crew_user.id)
        crew = await _crew(db, ws.id)
        crew_tech.crew_id = crew.id
        project = LightingProject(
            workspace_id=ws.id,
            contact_id=contact.id,
            name="Front plan",
            document=_landscape_document(),
            version=4,
            installation_shot_id="install-front",
        )
        db.add(project)
        await db.flush()
        job = await JobService(db).create(
            ws.id,
            {
                "contact_id": contact.id,
                "title": "Install",
                "lighting_project_id": project.id,
                "crew_id": crew.id,
                "technician_ids": [assigned_tech.id],
            },
        )

        plan = await JobService(db).get_installation_plan(
            job.id,
            ws.id,
            membership=assigned,
            user_id=assigned_user.id,
        )
        payload = plan.model_dump(mode="json", by_alias=True)
        assert plan.selected_shot_id == "install-front"
        assert plan.photo.data_url.endswith("AAAA")
        assert plan.fixture_schedule[0].catalog_sku == "UP-01"
        assert plan.precon_field_brief == "Field brief"
        assert "procurement" not in payload
        assert "leadInstaller" not in str(payload)
        assert "BBBB" not in str(payload)

        crew_membership = await _member(db, ws.id, crew_user.id)
        crew_membership.role = "technician"
        crew_plan = await JobService(db).get_installation_plan(
            job.id,
            ws.id,
            membership=crew_membership,
            user_id=crew_user.id,
        )
        assert crew_plan.selected_shot_id == "install-front"

        unassigned_user = await _user(db)
        unassigned = await _member(db, ws.id, unassigned_user.id)
        unassigned.role = "technician"
        with pytest.raises(HTTPException) as exc:
            await JobService(db).get_installation_plan(
                job.id,
                ws.id,
                membership=unassigned,
                user_id=unassigned_user.id,
            )
        assert exc.value.status_code == 404

        unassigned.role = "sales_rep"
        with pytest.raises(HTTPException) as exc:
            await JobService(db).get_installation_plan(
                job.id,
                ws.id,
                membership=unassigned,
                user_id=unassigned_user.id,
            )
        assert exc.value.status_code == 404

        unassigned.role = "manager"
        manager_plan = await JobService(db).get_installation_plan(
            job.id,
            ws.id,
            membership=unassigned,
            user_id=unassigned_user.id,
        )
        assert manager_plan.project_id == project.id

        other = await _workspace(db)
        with pytest.raises(HTTPException) as exc:
            await JobService(db).get_installation_plan(
                job.id,
                other.id,
                membership=unassigned,
                user_id=unassigned_user.id,
            )
        assert exc.value.status_code == 404
