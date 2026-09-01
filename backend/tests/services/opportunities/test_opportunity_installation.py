"""Focused unit coverage for structured deal calls and installation dates."""

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.models.call_outcome import OutcomeType
from app.models.field_service import JobStatus, JobVisit
from app.schemas.opportunity import OpportunityInstallationDateUpdate, OpportunityNoteCreate
from app.services.exceptions import ValidationError as ServiceValidationError
from app.services.jobs import JobService
from app.services.opportunities import OpportunityService


class _Result:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[object]:
        return self.rows


def _db() -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock()
    db.scalar = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _opportunity(*, assigned_user_id: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        assigned_user_id=assigned_user_id,
        workspace=SimpleNamespace(settings={"timezone": "America/New_York"}),
    )


def _job(
    *,
    status: JobStatus = JobStatus.UNSCHEDULED,
    scheduled_start: datetime | None = None,
    scheduled_end: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        created_at=datetime.now(UTC),
    )


def test_call_note_requires_structured_outcome_and_nonblank_note() -> None:
    note = OpportunityNoteCreate(
        kind="call",
        outcome=OutcomeType.NO_ANSWER,
        body="  Left voicemail; retry tomorrow.  ",
    )
    assert note.body == "Left voicemail; retry tomorrow."

    with pytest.raises(PydanticValidationError, match="outcome is required"):
        OpportunityNoteCreate(kind="call", body="No answer")
    with pytest.raises(PydanticValidationError, match="only allowed"):
        OpportunityNoteCreate(kind="note", outcome=OutcomeType.COMPLETED, body="Spoke")
    with pytest.raises(PydanticValidationError, match="must include a note"):
        OpportunityNoteCreate(kind="call", outcome=OutcomeType.NO_ANSWER, body="   ")


async def test_call_note_persists_outcome_on_deal_activity() -> None:
    db = _db()
    opportunity = _opportunity(assigned_user_id=7)
    note = OpportunityNoteCreate(
        kind="call",
        outcome=OutcomeType.APPOINTMENT_BOOKED,
        body="Demo booked for Friday",
    )

    with patch(
        "app.services.opportunities.opportunity_service.get_or_404",
        new=AsyncMock(return_value=opportunity),
    ):
        activity = await OpportunityService(db).add_note(
            uuid.uuid4(),
            opportunity.id,
            note,
            user_id=7,
            restrict_to_user_id=7,
        )

    assert activity.activity_type == "call"
    assert activity.description == "Demo booked for Friday"
    assert activity.new_value == OutcomeType.APPOINTMENT_BOOKED.value
    db.commit.assert_awaited_once()


async def test_unscheduled_job_gets_workspace_local_all_day_installation() -> None:
    db = _db()
    opportunity = _opportunity(assigned_user_id=7)
    job = _job()
    db.execute.return_value = _Result([job])
    workspace_id = uuid.uuid4()
    installation_date = date(2026, 3, 8)  # US daylight-saving transition day.

    with (
        patch(
            "app.services.opportunities.opportunity_service.get_or_404",
            new=AsyncMock(return_value=opportunity),
        ),
        patch("app.services.opportunities.opportunity_service.JobService") as job_service,
    ):
        job_service.return_value.schedule = AsyncMock()
        response = await OpportunityService(db).set_installation_date(
            workspace_id,
            opportunity.id,
            OpportunityInstallationDateUpdate(installation_date=installation_date),
            user_id=7,
            restrict_to_user_id=7,
        )

    assert response.job_id == job.id
    assert response.scheduled_start == datetime(2026, 3, 8, 5, tzinfo=UTC)
    assert response.scheduled_end == datetime(2026, 3, 9, 4, tzinfo=UTC)
    job_service.return_value.schedule.assert_awaited_once_with(
        job.id,
        workspace_id,
        response.scheduled_start,
        response.scheduled_end,
        anytime=True,
    )
    activity = db.add.call_args.args[0]
    assert activity.activity_type == "installation_scheduled"
    assert activity.new_value == "2026-03-08"
    db.commit.assert_awaited_once()


async def test_reschedule_keeps_local_working_hours_across_dst() -> None:
    db = _db()
    opportunity = _opportunity()
    job = _job(
        status=JobStatus.SCHEDULED,
        scheduled_start=datetime(2026, 3, 6, 14, tzinfo=UTC),
        scheduled_end=datetime(2026, 3, 6, 22, tzinfo=UTC),
    )
    db.execute.return_value = _Result([job])

    with (
        patch(
            "app.services.opportunities.opportunity_service.get_or_404",
            new=AsyncMock(return_value=opportunity),
        ),
        patch("app.services.opportunities.opportunity_service.JobService") as job_service,
    ):
        job_service.return_value.schedule = AsyncMock()
        response = await OpportunityService(db).set_installation_date(
            uuid.uuid4(),
            opportunity.id,
            OpportunityInstallationDateUpdate(installation_date=date(2026, 3, 9)),
        )

    assert response.scheduled_start == datetime(2026, 3, 9, 13, tzinfo=UTC)
    assert response.scheduled_end == datetime(2026, 3, 9, 21, tzinfo=UTC)
    assert job_service.return_value.schedule.await_args.kwargs["anytime"] is None


async def test_installation_date_rejects_missing_or_ambiguous_linked_job() -> None:
    opportunity = _opportunity()
    update = OpportunityInstallationDateUpdate(installation_date=date(2026, 6, 1))

    for rows, message in (
        ([], "No unscheduled or scheduled job"),
        ([_job(), _job()], "provide job_id"),
    ):
        db = _db()
        db.execute.return_value = _Result(rows)
        with (
            patch(
                "app.services.opportunities.opportunity_service.get_or_404",
                new=AsyncMock(return_value=opportunity),
            ),
            pytest.raises(ServiceValidationError, match=message),
        ):
            await OpportunityService(db).set_installation_date(uuid.uuid4(), opportunity.id, update)
        db.commit.assert_not_awaited()


async def test_same_installation_date_is_idempotent() -> None:
    db = _db()
    opportunity = _opportunity()
    job = _job(
        status=JobStatus.SCHEDULED,
        scheduled_start=datetime(2026, 6, 1, 13, tzinfo=UTC),
        scheduled_end=datetime(2026, 6, 1, 21, tzinfo=UTC),
    )
    db.execute.return_value = _Result([job])

    with (
        patch(
            "app.services.opportunities.opportunity_service.get_or_404",
            new=AsyncMock(return_value=opportunity),
        ),
        patch("app.services.opportunities.opportunity_service.JobService") as job_service,
    ):
        await OpportunityService(db).set_installation_date(
            uuid.uuid4(),
            opportunity.id,
            OpportunityInstallationDateUpdate(installation_date=date(2026, 6, 1)),
        )

    job_service.assert_not_called()
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


async def test_job_schedule_marks_new_primary_visit_anytime() -> None:
    db = _db()
    service = JobService(db)
    job = _job()
    service._load = AsyncMock(side_effect=[job, job])
    service._emit_status_event = AsyncMock()
    service._one_response = AsyncMock(return_value=SimpleNamespace(id=job.id))
    db.scalar.return_value = None
    start = datetime(2026, 6, 1, tzinfo=UTC)
    end = datetime(2026, 6, 2, tzinfo=UTC)

    await service.schedule(job.id, uuid.uuid4(), start, end, anytime=True)

    visit = db.add.call_args.args[0]
    assert isinstance(visit, JobVisit)
    assert visit.starts_at == start
    assert visit.ends_at == end
    assert visit.anytime is True
