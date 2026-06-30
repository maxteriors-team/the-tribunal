"""Workspace-scoped CRUD + schedule materialization for recurring job templates.

Two responsibilities:

1. **CRUD** (workspace-scoped, tenant-safe like :class:`app.services.jobs.JobService`):
   create/list/get/update/delete templates, validating that the contact, site,
   crew, and default technicians all belong to the caller's workspace.
2. **Materialization**: turn a template's next occurrence into a concrete
   :class:`Job`. :meth:`materialize_due` is the global worker entrypoint (it
   scans every workspace's due templates); :meth:`run_template` lets an operator
   force-generate the next job for one template on demand. Both share
   :meth:`_materialize_one`, which is **idempotent per occurrence**: each
   occurrence start produces exactly one job, and the template cursor
   (``next_run_at``) advances by ``interval`` × ``frequency`` after each one.
   Idempotency is enforced at the database — a partial-unique index on
   ``(recurring_template_id, scheduled_start)`` — so concurrent runs (overlapping
   ticks, multiple replicas, or a tick racing an operator "generate next now")
   cannot create duplicates; the in-process check is only a fast pre-filter.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import assert_workspace_owned, select_workspace_owned
from app.models.contact import Contact
from app.models.field_service import (
    Crew,
    Job,
    JobAssignment,
    JobStatus,
    ServiceLocation,
    Technician,
)
from app.models.recurring_job import RecurrenceFrequency, RecurringJobTemplate
from app.schemas.recurring_job import RecurringJobTemplateResponse

logger = structlog.get_logger()

# Safety cap on occurrences advanced per template per run, so a misconfigured
# (tiny interval, far-future cursor) template can never loop unbounded in a tick.
_MAX_OCCURRENCES_PER_RUN = 60


def advance_occurrence(moment: datetime, frequency: str, interval: int) -> datetime:
    """Return the next occurrence after ``moment`` for ``frequency``×``interval``.

    Uses calendar-aware arithmetic (``relativedelta``) for month/quarter/year so
    e.g. a monthly job anchored on the 31st rolls to month-end correctly.
    """
    step = max(int(interval), 1)
    match RecurrenceFrequency(frequency):
        case RecurrenceFrequency.WEEKLY:
            return moment + timedelta(weeks=step)
        case RecurrenceFrequency.BIWEEKLY:
            return moment + timedelta(weeks=2 * step)
        case RecurrenceFrequency.MONTHLY:
            return moment + relativedelta(months=step)
        case RecurrenceFrequency.QUARTERLY:
            return moment + relativedelta(months=3 * step)
        case RecurrenceFrequency.YEARLY:
            return moment + relativedelta(years=step)


class RecurringJobService:
    """CRUD and materialization for recurring job templates."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="recurring_job_service")

    # ------------------------------------------------------------------ #
    # Reference validation (tenant-safe)
    # ------------------------------------------------------------------ #
    async def _assert_contact(self, contact_id: int, workspace_id: uuid.UUID) -> None:
        await assert_workspace_owned(
            self.db, Contact, contact_id, workspace_id, detail="Contact not found"
        )

    async def _validate_refs(self, workspace_id: uuid.UUID, data: dict[str, Any]) -> None:
        """Validate optional site/crew/technician references when present."""
        location_id = data.get("service_location_id")
        if location_id is not None:
            await assert_workspace_owned(
                self.db,
                ServiceLocation,
                location_id,
                workspace_id,
                detail="Service location not found",
            )
        crew_id = data.get("crew_id")
        if crew_id is not None:
            await assert_workspace_owned(
                self.db, Crew, crew_id, workspace_id, detail="Crew not found"
            )
        technician_ids = data.get("default_technician_ids")
        if technician_ids:
            for technician_id in set(technician_ids):
                await assert_workspace_owned(
                    self.db,
                    Technician,
                    technician_id,
                    workspace_id,
                    detail="Technician not found",
                )

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    @staticmethod
    def _to_response(template: RecurringJobTemplate) -> RecurringJobTemplateResponse:
        return RecurringJobTemplateResponse.model_validate(template)

    async def _load(self, template_id: uuid.UUID, workspace_id: uuid.UUID) -> RecurringJobTemplate:
        return await assert_workspace_owned(
            self.db,
            RecurringJobTemplate,
            template_id,
            workspace_id,
            detail="Recurring job template not found",
        )

    async def list(
        self, workspace_id: uuid.UUID, *, is_active: bool | None = None
    ) -> dict[str, Any]:
        criteria: list[Any] = []
        if is_active is not None:
            criteria.append(RecurringJobTemplate.is_active.is_(is_active))
        query = select_workspace_owned(RecurringJobTemplate, workspace_id, *criteria).order_by(
            RecurringJobTemplate.next_run_at.asc()
        )
        rows = (await self.db.execute(query)).scalars().all()
        return {"items": [self._to_response(row) for row in rows], "total": len(rows)}

    async def get(
        self, template_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> RecurringJobTemplateResponse:
        return self._to_response(await self._load(template_id, workspace_id))

    # ------------------------------------------------------------------ #
    # Mutations
    # ------------------------------------------------------------------ #
    async def create(
        self, workspace_id: uuid.UUID, data: dict[str, Any], *, created_by_id: int | None = None
    ) -> RecurringJobTemplateResponse:
        await self._assert_contact(data["contact_id"], workspace_id)
        await self._validate_refs(workspace_id, data)

        template = RecurringJobTemplate(
            workspace_id=workspace_id,
            frequency=str(data.pop("frequency")),
            created_by_id=created_by_id,
            **data,
        )
        self.db.add(template)
        await self.db.flush()
        await self.db.refresh(template)
        self.log.info("recurring_template_created", template_id=str(template.id))
        return self._to_response(template)

    async def update(
        self, template_id: uuid.UUID, workspace_id: uuid.UUID, data: dict[str, Any]
    ) -> RecurringJobTemplateResponse:
        template = await self._load(template_id, workspace_id)
        await self._validate_refs(workspace_id, data)
        if "frequency" in data and data["frequency"] is not None:
            data["frequency"] = str(data["frequency"])
        for key, value in data.items():
            setattr(template, key, value)
        await self.db.flush()
        await self.db.refresh(template)
        return self._to_response(template)

    async def delete(self, template_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        template = await self._load(template_id, workspace_id)
        await self.db.delete(template)
        await self.db.flush()

    # ------------------------------------------------------------------ #
    # Materialization
    # ------------------------------------------------------------------ #
    async def _existing_occurrence(self, template_id: uuid.UUID, scheduled_start: datetime) -> bool:
        """True if a job was already generated for this template at this start."""
        row = (
            await self.db.execute(
                select(Job.id).where(
                    Job.recurring_template_id == template_id,
                    Job.scheduled_start == scheduled_start,
                )
            )
        ).first()
        return row is not None

    async def _live_technician_ids(
        self, technician_ids: Sequence[uuid.UUID], workspace_id: uuid.UUID
    ) -> Sequence[uuid.UUID]:
        """Filter default technicians down to those that still exist in-workspace."""
        if not technician_ids:
            return []
        rows = (
            (
                await self.db.execute(
                    select(Technician.id).where(
                        Technician.workspace_id == workspace_id,
                        Technician.id.in_(set(technician_ids)),
                    )
                )
            )
            .scalars()
            .all()
        )
        live = set(rows)
        # Preserve the template's order, dropping any removed technicians.
        return [tid for tid in dict.fromkeys(technician_ids) if tid in live]

    async def _materialize_one(
        self, template: RecurringJobTemplate, now: datetime, *, force: bool = False
    ) -> Sequence[Job]:
        """Generate due occurrence jobs for one template; advance its cursor.

        Generates every occurrence whose start falls within the template's lead
        window (``next_run_at <= now + generate_days_ahead``). When ``force`` is
        set, the *first* occurrence is generated unconditionally (the operator's
        "generate next now" action) even if it is beyond the lead window.
        """
        created: list[Job] = []
        technician_ids: Sequence[uuid.UUID] = await self._live_technician_ids(
            list(template.default_technician_ids or []), template.workspace_id
        )

        for iteration in range(_MAX_OCCURRENCES_PER_RUN):
            lead_cutoff = now + timedelta(days=template.generate_days_ahead)
            due = template.next_run_at <= lead_cutoff
            # ``force`` materializes only the *first* occurrence unconditionally
            # (the operator's "generate next now"); it never cascades into future
            # occurrences once the cursor has advanced past the lead window.
            if not due and not (force and iteration == 0):
                break

            occurrence_start = template.next_run_at
            occurrence_end = occurrence_start + timedelta(minutes=template.duration_minutes)

            # Idempotency. The cheap SELECT pre-check skips the common
            # already-generated case, but the *authoritative* guard is the
            # partial-unique index (recurring_template_id, scheduled_start):
            # the insert runs in a savepoint, and if a concurrent run (an
            # overlapping tick, another replica, or an operator "generate next
            # now") won the race, the IntegrityError makes us skip rather than
            # duplicate. The cursor still advances either way.
            if not await self._existing_occurrence(template.id, occurrence_start):
                job = Job(
                    workspace_id=template.workspace_id,
                    contact_id=template.contact_id,
                    service_location_id=template.service_location_id,
                    crew_id=template.crew_id,
                    recurring_template_id=template.id,
                    title=template.title,
                    description=template.description,
                    status=JobStatus.SCHEDULED,
                    scheduled_start=occurrence_start,
                    scheduled_end=occurrence_end,
                )
                try:
                    async with self.db.begin_nested():
                        self.db.add(job)
                        await self.db.flush()
                        for technician_id in technician_ids:
                            self.db.add(JobAssignment(job_id=job.id, technician_id=technician_id))
                except IntegrityError:
                    # Lost the race for this occurrence; another run created it.
                    self.log.info(
                        "recurring_job_materialize_skipped_duplicate",
                        template_id=str(template.id),
                        scheduled_start=occurrence_start.isoformat(),
                    )
                else:
                    created.append(job)
                    self.log.info(
                        "recurring_job_materialized",
                        template_id=str(template.id),
                        job_id=str(job.id),
                        scheduled_start=occurrence_start.isoformat(),
                    )

            template.last_run_at = now
            template.next_run_at = advance_occurrence(
                template.next_run_at, template.frequency, template.interval
            )

        if created:
            await self.db.flush()
        return created

    async def materialize_due(self, *, now: datetime | None = None) -> int:
        """Worker entrypoint: generate due jobs across **all** workspaces.

        Returns the number of jobs created. A template is in scope when it is
        active and its next occurrence is within a year (a coarse pre-filter);
        the precise per-template lead-window check happens in
        :meth:`_materialize_one`.
        """
        moment = now or datetime.now(UTC)
        coarse_cutoff = moment + timedelta(days=365)
        templates = (
            (
                await self.db.execute(
                    select(RecurringJobTemplate)
                    .where(
                        RecurringJobTemplate.is_active.is_(True),
                        RecurringJobTemplate.next_run_at <= coarse_cutoff,
                    )
                    .order_by(RecurringJobTemplate.next_run_at.asc())
                )
            )
            .scalars()
            .all()
        )
        total = 0
        for template in templates:
            created = await self._materialize_one(template, moment)
            total += len(created)
        return total

    async def run_template(
        self, template_id: uuid.UUID, workspace_id: uuid.UUID, *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Force-generate the next occurrence(s) for one template (operator action)."""
        template = await self._load(template_id, workspace_id)
        moment = now or datetime.now(UTC)
        created = await self._materialize_one(template, moment, force=True)
        await self.db.refresh(template)
        return {"created": len(created), "template": self._to_response(template)}
