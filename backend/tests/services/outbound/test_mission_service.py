"""Service tests for outbound mission lifecycle and Lead Miner aggregates."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.db.pagination import PaginationResult
from app.models.lead_prospect import ProspectStatus
from app.models.outbound_mission import MissionStatus
from app.models.outbound_sequence import SequenceEnrollmentStatus
from app.schemas.outbound_mission import OutboundMissionCreate, OutboundMissionUpdate
from app.services.outbound.mission_service import OutboundMissionService

WS_ID = uuid.uuid4()
MISSION_ID = uuid.uuid4()
PROSPECT_ID = uuid.uuid4()
SEQUENCE_ID = uuid.uuid4()
OFFER_ID = uuid.uuid4()
AGENT_ID = uuid.uuid4()


def _scalar_one_result(value: Any) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _rows_result(rows: list[tuple[Any, ...]]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.add = MagicMock()
    return db


def _make_mission(
    *,
    status: MissionStatus = MissionStatus.DRAFT,
    mission_id: uuid.UUID = MISSION_ID,
    default_sequence_id: uuid.UUID | None = None,
) -> MagicMock:
    mission = MagicMock()
    mission.id = mission_id
    mission.workspace_id = WS_ID
    mission.created_by_id = 1
    mission.offer_id = None
    mission.default_agent_id = None
    mission.default_sequence_id = default_sequence_id
    mission.name = "Mission"
    mission.description = None
    mission.objective = "book_call"
    mission.status = status
    mission.target_audience = {}
    mission.discovery_config = {}
    mission.enrichment_config = {}
    mission.sequence_config = {}
    mission.default_from_phone_number = None
    mission.default_from_email = None
    mission.daily_prospect_cap = 100
    mission.daily_outreach_cap = 50
    mission.timezone = "America/New_York"
    mission.total_prospects_discovered = 50
    mission.total_prospects_enriched = 30
    mission.total_prospects_contacted = 20
    mission.total_prospects_replied = 5
    mission.total_prospects_qualified = 2
    mission.total_contacts_created = 1
    mission.total_appointments_booked = 1
    now = datetime.now(UTC)
    mission.started_at = None
    mission.paused_at = None
    mission.completed_at = None
    mission.archived_at = None
    mission.last_run_at = None
    mission.next_run_at = None
    mission.created_at = now
    mission.updated_at = now
    return mission


def _make_prospect(*, status: ProspectStatus = ProspectStatus.NEW) -> MagicMock:
    prospect = MagicMock()
    prospect.id = PROSPECT_ID
    prospect.workspace_id = WS_ID
    prospect.mission_id = MISSION_ID
    prospect.status = status
    prospect.suppression_reason = None
    return prospect


def _make_sequence() -> MagicMock:
    sequence = MagicMock()
    sequence.id = SEQUENCE_ID
    sequence.workspace_id = WS_ID
    sequence.name = "Default sequence"
    sequence.description = None
    sequence.status = "active"
    sequence.is_default = True
    sequence.steps = []
    sequence.channel_priority = None
    sequence.max_attempts_per_step = 1
    sequence.sending_hours_start = None
    sequence.sending_hours_end = None
    sequence.sending_days = None
    sequence.timezone = "America/New_York"
    sequence.total_enrollments = 0
    sequence.total_completed = 0
    sequence.total_replied = 0
    sequence.total_converted = 0
    now = datetime.now(UTC)
    sequence.created_at = now
    sequence.updated_at = now
    return sequence


class TestMissionLifecycle:
    async def test_start_from_draft_sets_started_timestamp_once(self) -> None:
        db = _make_db()
        mission = _make_mission(status=MissionStatus.DRAFT)
        db.execute = AsyncMock(return_value=_scalar_one_result(mission))
        service = OutboundMissionService(db)

        result = await service.start_mission(WS_ID, MISSION_ID)

        assert result is mission
        assert mission.status == MissionStatus.ACTIVE
        assert mission.started_at is not None
        assert mission.paused_at is None
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(mission)

    async def test_resume_from_paused_preserves_original_started_at(self) -> None:
        db = _make_db()
        mission = _make_mission(status=MissionStatus.PAUSED)
        original_started_at = datetime(2026, 1, 1, tzinfo=UTC)
        mission.started_at = original_started_at
        mission.paused_at = datetime.now(UTC)
        db.execute = AsyncMock(return_value=_scalar_one_result(mission))
        service = OutboundMissionService(db)

        await service.resume_mission(WS_ID, MISSION_ID)

        assert mission.status == MissionStatus.ACTIVE
        assert mission.started_at == original_started_at
        assert mission.paused_at is None

    async def test_archive_already_archived_raises_400(self) -> None:
        db = _make_db()
        mission = _make_mission(status=MissionStatus.ARCHIVED)
        db.execute = AsyncMock(return_value=_scalar_one_result(mission))
        service = OutboundMissionService(db)

        with pytest.raises(HTTPException) as exc:
            await service.archive_mission(WS_ID, MISSION_ID)

        assert exc.value.status_code == 400
        assert exc.value.detail == "Cannot archive mission in status 'archived'"
        db.commit.assert_not_awaited()

    async def test_update_active_mission_raises_400(self) -> None:
        db = _make_db()
        mission = _make_mission(status=MissionStatus.ACTIVE)
        db.execute = AsyncMock(return_value=_scalar_one_result(mission))
        service = OutboundMissionService(db)

        with pytest.raises(HTTPException) as exc:
            await service.update_mission(
                WS_ID,
                MISSION_ID,
                OutboundMissionUpdate(name="Renamed"),
            )

        assert exc.value.status_code == 400
        assert "Cannot edit" in str(exc.value.detail)
        db.commit.assert_not_awaited()

    async def test_delete_active_mission_raises_400(self) -> None:
        db = _make_db()
        mission = _make_mission(status=MissionStatus.ACTIVE)
        db.execute = AsyncMock(return_value=_scalar_one_result(mission))
        service = OutboundMissionService(db)

        with pytest.raises(HTTPException) as exc:
            await service.delete_mission(WS_ID, MISSION_ID)

        assert exc.value.status_code == 400
        db.delete.assert_not_awaited()
        db.commit.assert_not_awaited()


class TestWorkspaceForeignKeyValidation:
    async def test_create_validates_offer_agent_and_sequence_workspace(self) -> None:
        db = _make_db()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(OFFER_ID),
                _scalar_one_result(AGENT_ID),
                _scalar_one_result(SEQUENCE_ID),
            ]
        )
        mission_in = OutboundMissionCreate(
            name="FK mission",
            offer_id=OFFER_ID,
            default_agent_id=AGENT_ID,
            default_sequence_id=SEQUENCE_ID,
        )
        service = OutboundMissionService(db)

        async def fake_refresh(obj: Any) -> None:
            template = _make_mission(mission_id=uuid.uuid4(), default_sequence_id=SEQUENCE_ID)
            for attr in vars(template):
                if not attr.startswith("_"):
                    setattr(obj, attr, getattr(template, attr))
            obj.name = mission_in.name
            obj.offer_id = OFFER_ID
            obj.default_agent_id = AGENT_ID
            obj.default_sequence_id = SEQUENCE_ID

        db.refresh = AsyncMock(side_effect=fake_refresh)

        mission = await service.create_mission(WS_ID, mission_in, created_by_id=1)

        assert mission.name == "FK mission"
        assert mission.offer_id == OFFER_ID
        assert db.execute.await_count == 3
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    async def test_update_unknown_sequence_raises_404_before_mutating(self) -> None:
        db = _make_db()
        mission = _make_mission(status=MissionStatus.DRAFT)
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(mission),
                _scalar_one_result(None),
            ]
        )
        service = OutboundMissionService(db)

        with pytest.raises(HTTPException) as exc:
            await service.update_mission(
                WS_ID,
                MISSION_ID,
                OutboundMissionUpdate(default_sequence_id=SEQUENCE_ID),
            )

        assert exc.value.status_code == 404
        assert exc.value.detail == "Outbound sequence not found"
        assert mission.default_sequence_id is None
        db.commit.assert_not_awaited()


class TestStatsAndProspectSelection:
    async def test_stats_rates_guard_against_zero_contacted(self) -> None:
        db = _make_db()
        mission = _make_mission()
        mission.total_prospects_contacted = 0
        mission.total_prospects_replied = 3
        mission.total_prospects_qualified = 2
        mission.total_appointments_booked = 1
        db.execute = AsyncMock(return_value=_scalar_one_result(mission))
        service = OutboundMissionService(db)

        response = await service.get_mission_stats(WS_ID, MISSION_ID)

        assert response.total_prospects_contacted == 0
        assert response.reply_rate == 0
        assert response.qualification_rate == 0
        assert response.booking_rate == 0

    async def test_select_suppressed_prospect_raises_400(self) -> None:
        db = _make_db()
        mission = _make_mission()
        prospect = _make_prospect(status=ProspectStatus.SUPPRESSED)
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(mission),
                _scalar_one_result(prospect),
            ]
        )
        service = OutboundMissionService(db)

        with pytest.raises(HTTPException) as exc:
            await service.select_mission_prospect(WS_ID, MISSION_ID, PROSPECT_ID)

        assert exc.value.status_code == 400
        assert exc.value.detail == "Cannot select prospect in status 'suppressed'"
        db.commit.assert_not_awaited()

    async def test_suppress_records_reason(self) -> None:
        db = _make_db()
        mission = _make_mission()
        prospect = _make_prospect()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(mission),
                _scalar_one_result(prospect),
            ]
        )
        service = OutboundMissionService(db)

        result = await service.suppress_mission_prospect(
            WS_ID,
            MISSION_ID,
            PROSPECT_ID,
            reason="no consent",
        )

        assert result is prospect
        assert prospect.status == ProspectStatus.SUPPRESSED
        assert prospect.suppression_reason == "no consent"
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(prospect)


class TestSequenceOverviewAndPagination:
    async def test_sequence_overview_returns_default_sequence_and_counts(self) -> None:
        db = _make_db()
        sequence = _make_sequence()
        mission = _make_mission(default_sequence_id=sequence.id)
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(mission),
                _scalar_one_result(sequence),
                _rows_result(
                    [
                        (SequenceEnrollmentStatus.ACTIVE, 2),
                        (SequenceEnrollmentStatus.COMPLETED, 3),
                    ]
                ),
            ]
        )
        service = OutboundMissionService(db)

        overview = await service.get_mission_sequence_overview(WS_ID, MISSION_ID)

        assert overview["mission_id"] == str(MISSION_ID)
        assert overview["default_sequence"]["id"] == str(SEQUENCE_ID)
        assert overview["enrollment_counts"] == {
            SequenceEnrollmentStatus.ACTIVE.value: 2,
            SequenceEnrollmentStatus.COMPLETED.value: 3,
        }
        assert overview["total_enrollments"] == 5

    async def test_list_missions_uses_service_paginate(self) -> None:
        db = _make_db()
        mission = _make_mission()
        service = OutboundMissionService(db)

        with patch(
            "app.services.outbound.mission_service.paginate",
            new_callable=AsyncMock,
        ) as mock_paginate:
            mock_paginate.return_value = PaginationResult(
                items=[mission], total=1, page=1, page_size=50, pages=1
            )
            response = await service.list_missions(
                WS_ID,
                page=1,
                page_size=50,
                status_filter=MissionStatus.DRAFT,
                objective="book_call",
                search="Mission",
            )

        assert response.total == 1
        assert response.items[0].id == MISSION_ID
        mock_paginate.assert_awaited_once()
