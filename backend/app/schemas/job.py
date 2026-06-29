"""Schemas for field-service jobs (work orders) and worker assignments.

A *job* is a unit of field work for a customer. Dispatch tags one or more
technicians to it and gives it a time window; each assigned worker then sees the
job on their calendar. Status is derived/maintained server-side by
:class:`app.services.jobs.JobService`, never set directly by API callers.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.field_service import JobStatus


class JobCreate(BaseModel):
    """Create a job. Optionally pre-scheduled and/or pre-assigned to workers."""

    contact_id: int = Field(..., description="Owning customer contact id")
    service_location_id: uuid.UUID | None = Field(None, description="Job site")
    crew_id: uuid.UUID | None = Field(None, description="Optional dispatch lane/crew")
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    technician_ids: list[uuid.UUID] = Field(
        default_factory=list, description="Technicians to tag onto this job"
    )

    @model_validator(mode="after")
    def _check_window(self) -> "JobCreate":
        """Both ends of a time window must be supplied together and ordered."""
        if (self.scheduled_start is None) != (self.scheduled_end is None):
            raise ValueError("scheduled_start and scheduled_end must be provided together")
        if (
            self.scheduled_start is not None
            and self.scheduled_end is not None
            and self.scheduled_end <= self.scheduled_start
        ):
            raise ValueError("scheduled_end must be after scheduled_start")
        return self


class JobUpdate(BaseModel):
    """Partial update for a job. Status is recomputed from the time window."""

    service_location_id: uuid.UUID | None = None
    crew_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = Field(None, description="Link this job to a billing invoice")
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    status: JobStatus | None = Field(
        None,
        description="Advance lifecycle (e.g. in_progress/completed/cancelled)",
    )


class JobScheduleRequest(BaseModel):
    """Set a job's time window (flips unscheduled -> scheduled)."""

    scheduled_start: datetime
    scheduled_end: datetime

    @model_validator(mode="after")
    def _check_order(self) -> "JobScheduleRequest":
        if self.scheduled_end <= self.scheduled_start:
            raise ValueError("scheduled_end must be after scheduled_start")
        return self


class JobAssignRequest(BaseModel):
    """Tag one or more technicians onto a job."""

    technician_ids: list[uuid.UUID] = Field(..., min_length=1)


class TechnicianSummary(BaseModel):
    """Compact technician view for rendering avatars/chips on the calendar."""

    id: uuid.UUID
    name: str
    color: str

    model_config = {"from_attributes": True}


class JobResponse(BaseModel):
    """Job response, including its assigned technicians."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    contact_id: int
    service_location_id: uuid.UUID | None
    crew_id: uuid.UUID | None
    invoice_id: uuid.UUID | None = None
    title: str
    description: str | None
    status: JobStatus
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    external_source: str | None
    external_id: str | None
    technicians: list[TechnicianSummary] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    """List of jobs."""

    items: list[JobResponse]
    total: int
