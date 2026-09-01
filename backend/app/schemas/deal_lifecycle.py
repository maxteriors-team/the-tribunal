"""Workspace settings schema for automated deal lifecycle transitions."""

import uuid
from datetime import time

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DealLifecycleSettings(BaseModel):
    """Tenant-owned pipeline roles and operator timing for deal automation."""

    model_config = ConfigDict(extra="forbid")

    pipeline_id: uuid.UUID | None = None
    new_lead_stage_id: uuid.UUID | None = None
    contacted_no_answer_stage_id: uuid.UUID | None = None
    visit_demo_scheduled_stage_id: uuid.UUID | None = None
    qualified_stage_id: uuid.UUID | None = None
    quote_follow_up_stage_id: uuid.UUID | None = None
    won_stage_id: uuid.UUID | None = None
    job_completed_stage_id: uuid.UUID | None = None
    unqualified_stage_id: uuid.UUID | None = None
    follow_up_assignee_user_id: int | None = Field(default=None, gt=0)
    end_of_day_cutoff: time = time(17, 0)

    @field_validator("end_of_day_cutoff")
    @classmethod
    def validate_local_cutoff(cls, value: time) -> time:
        """Keep the cutoff a workspace-local wall time, not a fixed UTC offset."""
        if value.tzinfo is not None:
            raise ValueError("end_of_day_cutoff must not include a timezone offset")
        return value

    @property
    def is_configured(self) -> bool:
        """Return whether every resource reference is present and unambiguous."""
        return (
            self.pipeline_id is not None
            and self.follow_up_assignee_user_id is not None
            and len(self.stage_ids) == 8
        )

    @property
    def stage_ids(self) -> frozenset[uuid.UUID]:
        """Return configured stage IDs for tenant-ownership validation."""
        values = (
            self.new_lead_stage_id,
            self.contacted_no_answer_stage_id,
            self.visit_demo_scheduled_stage_id,
            self.qualified_stage_id,
            self.quote_follow_up_stage_id,
            self.won_stage_id,
            self.job_completed_stage_id,
            self.unqualified_stage_id,
        )
        return frozenset(value for value in values if value is not None)

    @model_validator(mode="after")
    def validate_complete_unique_mapping(self) -> "DealLifecycleSettings":
        """Reject partial or ambiguous mappings before any automation can use them."""
        references = (
            self.pipeline_id,
            self.new_lead_stage_id,
            self.contacted_no_answer_stage_id,
            self.visit_demo_scheduled_stage_id,
            self.qualified_stage_id,
            self.quote_follow_up_stage_id,
            self.won_stage_id,
            self.job_completed_stage_id,
            self.unqualified_stage_id,
            self.follow_up_assignee_user_id,
        )
        configured_count = sum(value is not None for value in references)
        if configured_count not in {0, len(references)}:
            raise ValueError(
                "pipeline, every lifecycle stage, and follow-up assignee must be "
                "configured together"
            )
        if configured_count and len(self.stage_ids) != 8:
            raise ValueError("every lifecycle role must use a different pipeline stage")
        return self
