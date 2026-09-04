"""Public standings and private Lighting League response contracts."""

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class TechnicianScoreboardPeriod(BaseModel):
    start_date: date
    end_date: date
    starts_at: datetime
    ends_at: datetime
    timezone: str


class TechnicianScoreboardRules(BaseModel):
    attendance_day_xp: int
    completed_job_xp: int
    upsell_base_xp: int
    upsell_value_divisor: int
    upsell_value_bonus_cap: int
    upsell_max_xp: int


class TechnicianScoreboardLevel(BaseModel):
    number: int
    title: str
    lifetime_xp: int


class TechnicianScoreboardStanding(BaseModel):
    technician_id: uuid.UUID
    name: str
    rank: int | None
    monthly_xp: int
    level_number: int
    level_title: str
    is_viewer: bool


class TechnicianScoreboardDetail(BaseModel):
    technician_id: uuid.UUID
    name: str
    lifetime_xp: int
    monthly_xp: int
    level_number: int
    level_title: str
    current_level_threshold: int
    next_level_number: int | None
    next_level_title: str | None
    next_level_threshold: int | None
    xp_into_level: int
    xp_to_next_level: int | None
    level_progress: Annotated[float, Field(ge=0, le=1)]
    attendance_days: int
    completed_jobs: int
    approved_upsells: int
    attendance_xp: int
    job_xp: int
    upsell_xp: int


class TechnicianScoreboardResponse(BaseModel):
    period: TechnicianScoreboardPeriod
    rules: TechnicianScoreboardRules
    levels: list[TechnicianScoreboardLevel]
    standings: list[TechnicianScoreboardStanding]
    viewer_detail: TechnicianScoreboardDetail | None
    viewer_level_seen: int | None


class TechnicianLevelAcknowledgementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Annotated[int, Field(ge=1, le=10)]


class TechnicianLevelAcknowledgementResponse(BaseModel):
    level_seen: int
