"""API contracts for workspace time and attendance."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, model_validator

AttendanceStatus = Literal["open", "complete", "void"]
AttendanceSource = Literal["clock", "manual", "admin"]
TrimmedText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
OptionalNote = Annotated[str | None, Field(default=None, max_length=4000)]


class AttendanceDateRange(BaseModel):
    """Inclusive workspace-local date range, capped at 62 calendar days."""

    date_from: date
    date_to: date

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.date_to < self.date_from:
            raise ValueError("date_to must be on or after date_from")
        if (self.date_to - self.date_from).days > 61:
            raise ValueError("attendance date ranges cannot exceed 62 days")
        return self


class AttendanceAdminListQuery(AttendanceDateRange):
    user_id: int | None = Field(default=None, gt=0)


class AttendanceClockInRequest(BaseModel):
    request_id: uuid.UUID
    note: OptionalNote = None


class AttendanceClockOutRequest(BaseModel):
    request_id: uuid.UUID


class AttendancePauseRequest(BaseModel):
    request_id: uuid.UUID


class AttendanceManualEntryRequest(BaseModel):
    request_id: uuid.UUID
    reason: TrimmedText = Field(max_length=4000)
    user_id: int = Field(gt=0)
    started_at: AwareDatetime
    ended_at: AwareDatetime
    note: OptionalNote = None

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if self.ended_at <= self.started_at:
            raise ValueError("ended_at must be after started_at")
        return self


class AttendanceEntryUpdateRequest(BaseModel):
    request_id: uuid.UUID
    reason: TrimmedText = Field(max_length=4000)
    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    note: OptionalNote = None

    @model_validator(mode="after")
    def validate_correction(self) -> Self:
        changed = self.model_fields_set & {"started_at", "ended_at", "note"}
        if not changed:
            raise ValueError("at least one of started_at, ended_at, or note is required")
        if "ended_at" in self.model_fields_set and self.ended_at is None:
            raise ValueError("ended_at cannot be cleared; void the entry instead")
        if (
            self.started_at is not None
            and self.ended_at is not None
            and self.ended_at <= self.started_at
        ):
            raise ValueError("ended_at must be after started_at")
        return self


class AttendanceVoidRequest(BaseModel):
    request_id: uuid.UUID
    reason: TrimmedText = Field(max_length=4000)


class AttendanceExportRequest(AttendanceDateRange):
    """Raw hours export; payroll software must classify regular and overtime hours."""

    request_id: uuid.UUID
    user_id: int | None = Field(default=None, gt=0)


class AttendanceEntryResponse(BaseModel):
    id: uuid.UUID
    user_id: int
    employee_name: str
    employee_email: str
    started_at: datetime
    ended_at: datetime | None
    status: AttendanceStatus
    source: AttendanceSource
    note: str | None
    duration_seconds: int
    duration_hours: float
    gross_duration_seconds: int
    paused_seconds: int
    is_paused: bool
    pause_started_at: datetime | None
    calculated_at: datetime
    created_at: datetime
    updated_at: datetime


class AttendanceReportResponse(BaseModel):
    timezone: str
    entries: list[AttendanceEntryResponse]
    total_seconds: int
    open_entry: AttendanceEntryResponse | None


class AttendanceAdminReportResponse(BaseModel):
    timezone: str
    entries: list[AttendanceEntryResponse]
    total_seconds: int
    open_count: int
    employee_count: int
