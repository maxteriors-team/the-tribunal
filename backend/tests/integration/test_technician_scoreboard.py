"""End-to-end persistence, ranking, and authorization for Lighting League."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_membership, get_transactional_db
from app.api.v1 import technician_scoreboard as scoreboard_api
from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine, transaction_boundary
from app.models.attendance import AttendanceEntry
from app.models.catalog import CatalogItem
from app.models.contact import Contact
from app.models.field_service import Job, JobAssignment, JobStatus, Technician
from app.models.quote import Quote
from app.models.technician_xp_award import TechnicianXpAward
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.schemas.attendance import (
    AttendanceClockInRequest,
    AttendanceClockOutRequest,
    AttendanceEntryUpdateRequest,
    AttendanceManualEntryRequest,
    AttendanceVoidRequest,
)
from app.schemas.upsell import UpsellQuoteLine, UpsellQuoteRequest
from app.services.attendance import AttendanceService
from app.services.exceptions import NotFoundError
from app.services.jobs.job_service import JobService
from app.services.quotes.quote_service import QuoteService
from app.services.technician_scoreboard import TechnicianScoreboardService
from app.services.upsell.upsell_service import UpsellService

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Seed:
    workspace_id: uuid.UUID
    other_workspace_id: uuid.UUID
    owner_id: int
    technician_user_ids: tuple[int, int, int]
    owner_membership_id: int
    technician_membership_ids: tuple[int, int, int]
    technician_ids: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    inactive_technician_id: uuid.UUID
    other_technician_id: uuid.UUID
    contact_id: int


@asynccontextmanager
async def _seeded() -> AsyncIterator[Seed]:
    await engine.dispose()
    suffix = uuid.uuid4().hex
    user_ids: list[int] = []
    workspace_ids: list[uuid.UUID] = []
    async with AsyncSessionLocal() as db:
        workspace = Workspace(
            name="Lighting League Test",
            slug=f"lighting-league-{suffix}",
            settings={"timezone": "America/New_York"},
        )
        other_workspace = Workspace(
            name="Other Lighting League",
            slug=f"other-lighting-league-{suffix}",
            settings={"timezone": "UTC"},
        )
        users = [
            User(
                email=f"league-owner-{suffix}@example.com",
                full_name="Office Owner",
                hashed_password="not-used",
            ),
            User(
                email=f"league-alex-{suffix}@example.com",
                full_name="Alex Amp",
                hashed_password="not-used",
            ),
            User(
                email=f"league-bailey-{suffix}@example.com",
                full_name="Bailey Beam",
                hashed_password="not-used",
            ),
            User(
                email=f"league-zero-{suffix}@example.com",
                full_name="Zero Watt",
                hashed_password="not-used",
            ),
            User(
                email=f"league-inactive-{suffix}@example.com",
                full_name="Inactive Tech",
                hashed_password="not-used",
            ),
            User(
                email=f"league-other-{suffix}@example.com",
                full_name="Other Tech",
                hashed_password="not-used",
            ),
        ]
        db.add_all([workspace, other_workspace, *users])
        await db.flush()
        user_ids = [user.id for user in users]
        workspace_ids = [workspace.id, other_workspace.id]

        memberships = [
            WorkspaceMembership(workspace_id=workspace.id, user_id=users[0].id, role="owner"),
            WorkspaceMembership(workspace_id=workspace.id, user_id=users[1].id, role="technician"),
            WorkspaceMembership(workspace_id=workspace.id, user_id=users[2].id, role="technician"),
            WorkspaceMembership(workspace_id=workspace.id, user_id=users[3].id, role="technician"),
            WorkspaceMembership(workspace_id=workspace.id, user_id=users[4].id, role="technician"),
            WorkspaceMembership(
                workspace_id=other_workspace.id, user_id=users[5].id, role="technician"
            ),
        ]
        db.add_all(memberships)
        phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
        contact = Contact(
            workspace_id=workspace.id,
            first_name="League",
            last_name="Customer",
            phone_number=phone,
            phone_hash=hash_phone(phone),
        )
        technicians = [
            Technician(workspace_id=workspace.id, user_id=users[1].id, name="Alex Amp"),
            Technician(workspace_id=workspace.id, user_id=users[2].id, name="Bailey Beam"),
            Technician(workspace_id=workspace.id, user_id=users[3].id, name="Zero Watt"),
            Technician(
                workspace_id=workspace.id,
                user_id=users[4].id,
                name="Inactive Tech",
                is_active=False,
            ),
            Technician(
                workspace_id=other_workspace.id,
                user_id=users[5].id,
                name="Other Tech",
            ),
        ]
        db.add_all([contact, *technicians])
        await db.commit()
        seed = Seed(
            workspace_id=workspace.id,
            other_workspace_id=other_workspace.id,
            owner_id=users[0].id,
            technician_user_ids=(users[1].id, users[2].id, users[3].id),
            owner_membership_id=memberships[0].id,
            technician_membership_ids=(memberships[1].id, memberships[2].id, memberships[3].id),
            technician_ids=(technicians[0].id, technicians[1].id, technicians[2].id),
            inactive_technician_id=technicians[3].id,
            other_technician_id=technicians[4].id,
            contact_id=contact.id,
        )
    try:
        yield seed
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Workspace).where(Workspace.id.in_(workspace_ids)))
            await db.commit()
            await db.execute(delete(User).where(User.id.in_(user_ids)))
            await db.commit()
        await engine.dispose()


async def _membership(db: AsyncSession, membership_id: int) -> WorkspaceMembership:
    return (
        await db.execute(select(WorkspaceMembership).where(WorkspaceMembership.id == membership_id))
    ).scalar_one()


async def _awards(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    category: str | None = None,
) -> list[TechnicianXpAward]:
    statement = (
        select(TechnicianXpAward)
        .where(TechnicianXpAward.workspace_id == workspace_id)
        .execution_options(populate_existing=True)
    )
    if category:
        statement = statement.where(TechnicianXpAward.category == category)
    return list((await db.scalars(statement.order_by(TechnicianXpAward.source_key))).all())


def _app(membership: WorkspaceMembership | None) -> FastAPI:
    app = FastAPI()
    app.include_router(
        scoreboard_api.router,
        prefix="/api/v1/workspaces/{workspace_id}/technician-scoreboard",
    )

    async def override_db() -> AsyncIterator[AsyncSession]:
        async with AsyncSessionLocal() as db:
            yield db

    async def override_transactional_db() -> AsyncIterator[AsyncSession]:
        async with AsyncSessionLocal() as db, transaction_boundary(db):
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_transactional_db] = override_transactional_db
    if membership is not None:

        async def override_membership() -> WorkspaceMembership:
            return membership

        app.dependency_overrides[get_membership] = override_membership
    return app


async def test_clock_out_awards_once_and_idempotent_retry_does_not_duplicate() -> None:
    async with _seeded() as seed, AsyncSessionLocal() as db:
        membership = await _membership(db, seed.technician_membership_ids[0])
        service = AttendanceService(db)
        await service.clock_in(
            seed.workspace_id,
            membership,
            AttendanceClockInRequest(request_id=uuid.uuid4()),
        )
        request = AttendanceClockOutRequest(request_id=uuid.uuid4())
        first = await service.clock_out(seed.workspace_id, membership, request)
        retry = await service.clock_out(seed.workspace_id, membership, request)

        assert retry.id == first.id
        awards = await _awards(db, seed.workspace_id, category="attendance")
        assert len(awards) == 1
        assert awards[0].points == 25
        assert awards[0].source_key.startswith("attendance:")
        assert awards[0].revoked_at is None
        await db.commit()


async def test_attendance_reconciles_one_award_per_local_day_across_edits_and_voids() -> None:
    async with _seeded() as seed, AsyncSessionLocal() as db:
        owner = await _membership(db, seed.owner_membership_id)
        service = AttendanceService(db)
        user_id = seed.technician_user_ids[0]
        first = await service.create_manual_entry(
            seed.workspace_id,
            owner,
            AttendanceManualEntryRequest(
                request_id=uuid.uuid4(),
                reason="Verified field shift",
                user_id=user_id,
                started_at=datetime(2026, 9, 2, 13, tzinfo=UTC),
                ended_at=datetime(2026, 9, 2, 15, tzinfo=UTC),
            ),
        )
        second = await service.create_manual_entry(
            seed.workspace_id,
            owner,
            AttendanceManualEntryRequest(
                request_id=uuid.uuid4(),
                reason="Verified second visit",
                user_id=user_id,
                started_at=datetime(2026, 9, 2, 16, tzinfo=UTC),
                ended_at=datetime(2026, 9, 2, 18, tzinfo=UTC),
            ),
        )
        awards = await _awards(db, seed.workspace_id, category="attendance")
        assert [(row.source_key, row.points, row.revoked_at) for row in awards] == [
            ("attendance:2026-09-02", 25, None)
        ]

        await service.void_entry(
            seed.workspace_id,
            owner,
            first.id,
            AttendanceVoidRequest(request_id=uuid.uuid4(), reason="Duplicate shift"),
        )
        assert (await _awards(db, seed.workspace_id, category="attendance"))[0].revoked_at is None
        await service.void_entry(
            seed.workspace_id,
            owner,
            second.id,
            AttendanceVoidRequest(request_id=uuid.uuid4(), reason="Wrong employee"),
        )
        assert (await _awards(db, seed.workspace_id, category="attendance"))[0].revoked_at

        moved = await service.create_manual_entry(
            seed.workspace_id,
            owner,
            AttendanceManualEntryRequest(
                request_id=uuid.uuid4(),
                reason="Verified shift",
                user_id=user_id,
                started_at=datetime(2026, 9, 3, 13, tzinfo=UTC),
                ended_at=datetime(2026, 9, 3, 15, tzinfo=UTC),
            ),
        )
        await service.update_entry(
            seed.workspace_id,
            owner,
            moved.id,
            AttendanceEntryUpdateRequest(
                request_id=uuid.uuid4(),
                reason="Correct local workday",
                started_at=datetime(2026, 9, 4, 13, tzinfo=UTC),
                ended_at=datetime(2026, 9, 4, 15, tzinfo=UTC),
            ),
        )
        by_key = {row.source_key: row for row in await _awards(db, seed.workspace_id)}
        assert by_key["attendance:2026-09-03"].revoked_at is not None
        assert by_key["attendance:2026-09-04"].revoked_at is None
        await db.commit()


async def test_concurrent_attendance_reconciliation_is_idempotent() -> None:
    async with _seeded() as seed:
        user_id = seed.technician_user_ids[0]
        async with AsyncSessionLocal() as db:
            entry = AttendanceEntry(
                workspace_id=seed.workspace_id,
                user_id=user_id,
                source="manual",
                status="complete",
                started_at=datetime(2026, 9, 5, 13, tzinfo=UTC),
                ended_at=datetime(2026, 9, 5, 14, tzinfo=UTC),
                created_by_id=seed.owner_id,
            )
            db.add(entry)
            await db.commit()

        async def reconcile() -> None:
            async with AsyncSessionLocal() as db:
                await TechnicianScoreboardService(db).reconcile_attendance_days(
                    seed.workspace_id, user_id, {date(2026, 9, 5)}
                )
                await db.commit()

        await asyncio.gather(reconcile(), reconcile())
        async with AsyncSessionLocal() as db:
            rows = await _awards(db, seed.workspace_id, category="attendance")
            assert len(rows) == 1
            assert rows[0].source_key == "attendance:2026-09-05"


async def test_job_completion_snapshots_full_crew_and_reactivation_keeps_original_awards() -> None:
    async with _seeded() as seed, AsyncSessionLocal() as db:
        job = Job(
            workspace_id=seed.workspace_id,
            contact_id=seed.contact_id,
            title="Install lighting",
        )
        db.add(job)
        await db.flush()
        db.add_all(
            [
                JobAssignment(job_id=job.id, technician_id=seed.technician_ids[0]),
                JobAssignment(job_id=job.id, technician_id=seed.technician_ids[1]),
            ]
        )
        await db.commit()

        service = JobService(db)
        await service.update(job.id, seed.workspace_id, {"status": JobStatus.COMPLETED})
        await db.commit()
        first_awards = await _awards(db, seed.workspace_id, category="job")
        assert {row.technician_id for row in first_awards} == set(seed.technician_ids[:2])
        assert {row.points for row in first_awards} == {100}
        original_times = {row.technician_id: row.awarded_at for row in first_awards}

        db.add(JobAssignment(job_id=job.id, technician_id=seed.technician_ids[2]))
        await db.commit()
        assert len(await _awards(db, seed.workspace_id, category="job")) == 2

        await service.update(job.id, seed.workspace_id, {"status": JobStatus.IN_PROGRESS})
        await db.commit()
        assert all(row.revoked_at is not None for row in await _awards(db, seed.workspace_id))

        await service.update(job.id, seed.workspace_id, {"status": JobStatus.COMPLETED})
        await db.commit()
        recompleted = await _awards(db, seed.workspace_id, category="job")
        assert {row.technician_id for row in recompleted} == set(seed.technician_ids[:2])
        assert all(row.revoked_at is None for row in recompleted)
        assert {row.technician_id: row.awarded_at for row in recompleted} == original_times

        await service.delete(job.id, seed.workspace_id)
        await db.commit()
        assert all(
            row.revoked_at is not None
            for row in await _awards(db, seed.workspace_id, category="job")
        )


async def test_onsite_flow_marks_quote_origin_server_side() -> None:
    async with _seeded() as seed, AsyncSessionLocal() as db:
        job = Job(
            workspace_id=seed.workspace_id,
            contact_id=seed.contact_id,
            title="On-site add-on",
            status=JobStatus.SCHEDULED,
        )
        item = CatalogItem(
            workspace_id=seed.workspace_id,
            name="Path light",
            unit_price=Decimal("100.00"),
            is_attachable=True,
            is_active=True,
            attach_targets=[],
        )
        db.add_all([job, item])
        await db.flush()
        db.add(JobAssignment(job_id=job.id, technician_id=seed.technician_ids[0]))
        await db.flush()

        created = await UpsellService(db).create_quote(
            seed.workspace_id,
            job.id,
            UpsellQuoteRequest(line_items=[UpsellQuoteLine(catalog_item_id=item.id, quantity=1)]),
            user_id=seed.technician_user_ids[0],
            role="lead_technician",
        )
        persisted = await db.get(Quote, created.id)

        assert persisted is not None
        assert persisted.is_onsite_upsell is True


async def test_only_first_approval_of_marked_onsite_quote_awards_capped_value_xp() -> None:
    async with _seeded() as seed, AsyncSessionLocal() as db:
        ordinary = Quote(
            workspace_id=seed.workspace_id,
            contact_id=seed.contact_id,
            number=f"ORD-{uuid.uuid4().hex[:8]}",
            status="sent",
            created_by_id=seed.technician_user_ids[0],
            total=Decimal("500.00"),
        )
        onsite = Quote(
            workspace_id=seed.workspace_id,
            contact_id=seed.contact_id,
            number=f"UP-{uuid.uuid4().hex[:8]}",
            status="sent",
            created_by_id=seed.technician_user_ids[0],
            total=Decimal("9999.00"),
            is_onsite_upsell=True,
        )
        draft = Quote(
            workspace_id=seed.workspace_id,
            contact_id=seed.contact_id,
            number=f"DRAFT-{uuid.uuid4().hex[:8]}",
            status="draft",
            created_by_id=seed.technician_user_ids[0],
            total=Decimal("2000.00"),
            is_onsite_upsell=True,
        )
        db.add_all([ordinary, onsite, draft])
        await db.commit()

        service = QuoteService(db)
        await service.approve_quote(seed.workspace_id, ordinary.id)
        assert await _awards(db, seed.workspace_id, category="upsell") == []
        await service.approve_quote(seed.workspace_id, onsite.id)
        await service.approve_quote(seed.workspace_id, onsite.id)

        rows = await _awards(db, seed.workspace_id, category="upsell")
        assert len(rows) == 1
        assert rows[0].source_key == f"upsell:{onsite.id}"
        assert rows[0].points == 200
        assert all(row.source_key != f"upsell:{draft.id}" for row in rows)


async def test_monthly_ranking_lifetime_progress_and_query_count() -> None:
    async with _seeded() as seed, AsyncSessionLocal() as db:
        awards = [
            TechnicianXpAward(
                workspace_id=seed.workspace_id,
                technician_id=seed.technician_ids[0],
                category="job",
                source_key=f"job:{uuid.uuid4()}",
                points=100,
                awarded_at=datetime(2026, 9, 1, 4, tzinfo=UTC),
            ),
            TechnicianXpAward(
                workspace_id=seed.workspace_id,
                technician_id=seed.technician_ids[0],
                category="attendance",
                source_key="attendance:2026-08-31",
                points=25,
                awarded_at=datetime(2026, 9, 1, 3, 59, tzinfo=UTC),
            ),
            TechnicianXpAward(
                workspace_id=seed.workspace_id,
                technician_id=seed.technician_ids[1],
                category="upsell",
                source_key=f"upsell:{uuid.uuid4()}",
                points=100,
                awarded_at=datetime(2026, 9, 20, 12, tzinfo=UTC),
            ),
            TechnicianXpAward(
                workspace_id=seed.workspace_id,
                technician_id=seed.technician_ids[0],
                category="upsell",
                source_key=f"upsell:{uuid.uuid4()}",
                points=200,
                awarded_at=datetime(2026, 9, 10, 12, tzinfo=UTC),
                revoked_at=datetime(2026, 9, 11, 12, tzinfo=UTC),
            ),
            TechnicianXpAward(
                workspace_id=seed.workspace_id,
                technician_id=seed.inactive_technician_id,
                category="job",
                source_key=f"job:{uuid.uuid4()}",
                points=999,
                awarded_at=datetime(2026, 9, 10, 12, tzinfo=UTC),
            ),
        ]
        db.add_all(awards)
        await db.commit()

        selects = 0

        def count_selects(
            _conn: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: bool,
        ) -> None:
            nonlocal selects
            if statement.lstrip().upper().startswith("SELECT"):
                selects += 1

        event.listen(engine.sync_engine, "before_cursor_execute", count_selects)
        try:
            result = await TechnicianScoreboardService(db).get_scoreboard(
                seed.workspace_id,
                viewer_user_id=seed.technician_user_ids[0],
                now=datetime(2026, 9, 15, 12, tzinfo=UTC),
            )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", count_selects)

        assert result.period.starts_at == datetime(2026, 9, 1, 4, tzinfo=UTC)
        assert result.period.ends_at == datetime(2026, 10, 1, 4, tzinfo=UTC)
        assert [(row.name, row.rank, row.monthly_xp) for row in result.standings] == [
            ("Alex Amp", 1, 100),
            ("Bailey Beam", 1, 100),
            ("Zero Watt", None, 0),
        ]
        assert result.viewer_detail is not None
        assert result.viewer_detail.lifetime_xp == 125
        assert result.viewer_detail.completed_jobs == 1
        assert result.viewer_detail.attendance_days == 0
        assert selects <= 3


async def test_api_minimizes_public_fields_and_fails_closed_for_peer_and_tenant_details() -> None:
    async with _seeded() as seed, AsyncSessionLocal() as db:
        db.add(
            TechnicianXpAward(
                workspace_id=seed.workspace_id,
                technician_id=seed.technician_ids[0],
                category="job",
                source_key=f"job:{uuid.uuid4()}",
                points=100,
            )
        )
        await db.commit()
        technician_membership = await _membership(db, seed.technician_membership_ids[0])
        owner_membership = await _membership(db, seed.owner_membership_id)

        technician_app = _app(technician_membership)
        async with AsyncClient(
            transport=ASGITransport(app=technician_app), base_url="http://test"
        ) as client:
            response = await client.get(
                f"/api/v1/workspaces/{seed.workspace_id}/technician-scoreboard"
            )
            assert response.status_code == 200
            body = response.json()
            assert set(body["standings"][0]) == {
                "technician_id",
                "name",
                "rank",
                "monthly_xp",
                "level_number",
                "level_title",
                "is_viewer",
            }
            assert "lifetime_xp" not in body["standings"][1]
            assert body["viewer_detail"]["technician_id"] == str(seed.technician_ids[0])
            assert "source_key" not in str(body)

            peer = await client.get(
                f"/api/v1/workspaces/{seed.workspace_id}/technician-scoreboard/technicians/"
                f"{seed.technician_ids[1]}"
            )
            missing = await client.get(
                f"/api/v1/workspaces/{seed.workspace_id}/technician-scoreboard/technicians/"
                f"{uuid.uuid4()}"
            )
            cross_tenant = await client.get(
                f"/api/v1/workspaces/{seed.workspace_id}/technician-scoreboard/technicians/"
                f"{seed.other_technician_id}"
            )
            assert peer.status_code == missing.status_code == cross_tenant.status_code == 404
            assert peer.json() == missing.json() == cross_tenant.json()

        owner_app = _app(owner_membership)
        async with AsyncClient(
            transport=ASGITransport(app=owner_app), base_url="http://test"
        ) as client:
            detail_response = await client.get(
                f"/api/v1/workspaces/{seed.workspace_id}/technician-scoreboard/technicians/"
                f"{seed.technician_ids[1]}"
            )
            assert detail_response.status_code == 200
            assert detail_response.json()["name"] == "Bailey Beam"

        anonymous_app = _app(None)
        async with AsyncClient(
            transport=ASGITransport(app=anonymous_app), base_url="http://test"
        ) as client:
            denied = await client.get(
                f"/api/v1/workspaces/{seed.workspace_id}/technician-scoreboard"
            )
            assert denied.status_code in {401, 403}


async def test_level_acknowledgement_is_bounded_earned_and_monotonic() -> None:
    async with _seeded() as seed, AsyncSessionLocal() as db:
        db.add(
            TechnicianXpAward(
                workspace_id=seed.workspace_id,
                technician_id=seed.technician_ids[0],
                category="job",
                source_key=f"job:{uuid.uuid4()}",
                points=500,
            )
        )
        await db.commit()
        membership = await _membership(db, seed.technician_membership_ids[0])
        app = _app(membership)
        url = f"/api/v1/workspaces/{seed.workspace_id}/technician-scoreboard/me/acknowledge-level"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            too_high = await client.post(url, json={"level": 3})
            assert too_high.status_code == 400
            extra_fields = await client.post(url, json={"level": 2, "points": 999999})
            assert extra_fields.status_code == 422
            acknowledged = await client.post(url, json={"level": 2})
            assert acknowledged.status_code == 200
            assert acknowledged.json() == {"level_seen": 2}
            lower = await client.post(url, json={"level": 1})
            assert lower.status_code == 200
            assert lower.json() == {"level_seen": 2}

        async with AsyncSessionLocal() as verify_db:
            technician = await verify_db.get(Technician, seed.technician_ids[0])
            assert technician is not None
            assert technician.scoreboard_level_seen == 2


async def test_service_detail_helper_returns_same_not_found_for_all_hidden_rows() -> None:
    async with _seeded() as seed, AsyncSessionLocal() as db:
        service = TechnicianScoreboardService(db)
        errors: list[str] = []
        for technician_id in (seed.technician_ids[1], uuid.uuid4(), seed.other_technician_id):
            with pytest.raises(NotFoundError) as exc_info:
                await service.get_technician_detail(
                    seed.workspace_id,
                    technician_id,
                    requester_user_id=seed.technician_user_ids[0],
                    can_view_peers=False,
                )
            errors.append(str(exc_info.value))
        assert len(set(errors)) == 1


async def test_manager_selection_hides_a_technician_without_losing_xp() -> None:
    async with _seeded() as seed, AsyncSessionLocal() as db:
        technician = await db.get(Technician, seed.technician_ids[0])
        assert technician is not None
        db.add(
            TechnicianXpAward(
                workspace_id=seed.workspace_id,
                technician_id=technician.id,
                category="job",
                source_key="job:before-league-opt-out",
                points=100,
            )
        )
        technician.scoreboard_enabled = False
        await db.commit()

        service = TechnicianScoreboardService(db)
        hidden = await service.get_scoreboard(
            seed.workspace_id, viewer_user_id=seed.technician_user_ids[0]
        )
        assert technician.id not in {row.technician_id for row in hidden.standings}
        assert hidden.viewer_detail is None
        with pytest.raises(NotFoundError):
            await service.get_technician_detail(
                seed.workspace_id,
                technician.id,
                requester_user_id=seed.owner_id,
                can_view_peers=True,
            )
        with pytest.raises(NotFoundError):
            await service.acknowledge_level(seed.workspace_id, seed.technician_user_ids[0], 1)

        technician.scoreboard_enabled = True
        await db.commit()
        visible = await service.get_scoreboard(
            seed.workspace_id, viewer_user_id=seed.technician_user_ids[0]
        )
        assert visible.viewer_detail is not None
        assert visible.viewer_detail.lifetime_xp == 100
