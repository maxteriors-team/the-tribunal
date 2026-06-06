"""Deal Coach schemas.

The Deal Coach synthesizes the whole relationship for an opportunity (all
calls' sentiment/objections, SMS cadence, pipeline stage, lead/engagement
scores) into a single operator-facing coaching card: deal health, the top
risk, the single next-best action, and a ready-to-approve drafted action.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Higher = healthier. Status buckets mirror Gong/Clari deal-board semantics.
DealHealthStatus = Literal["healthy", "watch", "at_risk", "critical"]
ActionChannel = Literal["sms", "call", "email", "offer", "task"]
GeneratedBy = Literal["llm", "heuristic"]


class NextBestAction(BaseModel):
    """The single recommended next move for the operator."""

    title: str
    rationale: str
    channel: ActionChannel
    timing: str  # e.g. "Today", "Tomorrow AM", "Within 48h"


class DraftedAction(BaseModel):
    """A ready-to-approve draft of the next-best action.

    Maps directly onto a PendingAction so a single click queues it through
    the existing HITL approval gate.
    """

    action_type: str
    channel: ActionChannel
    description: str
    body: str  # the drafted message/script the operator will send
    payload: dict[str, object] = Field(default_factory=dict)


class DealSignals(BaseModel):
    """Deterministic per-deal signals aggregated from existing data.

    These are computed (not invented by the LLM) and are surfaced so the
    operator can see the evidence behind the coaching.
    """

    days_since_last_contact: int | None = None
    days_in_stage: int | None = None
    lead_score: int = 0
    engagement_score: int = 0
    stage_name: str | None = None
    probability: int = 0
    call_count: int = 0
    sms_count: int = 0
    last_call_sentiment: str | None = None
    sentiment_trend: Literal["improving", "declining", "flat", "unknown"] = "unknown"
    objections: list[str] = Field(default_factory=list)
    open_next_steps: list[str] = Field(default_factory=list)
    awaiting_reply: bool = False
    expected_close_overdue: bool = False


class DealCoachCard(BaseModel):
    """The full coaching card for one opportunity."""

    opportunity_id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    amount: float | None = None
    currency: str = "USD"
    primary_contact_id: int | None = None
    contact_name: str | None = None
    deal_health: DealHealthStatus
    health_score: int = Field(ge=0, le=100)
    health_summary: str
    top_risk: str
    risk_factors: list[str] = Field(default_factory=list)
    next_best_action: NextBestAction
    drafted_action: DraftedAction
    signals: DealSignals
    generated_by: GeneratedBy
    generated_at: datetime


class AtRiskDeal(BaseModel):
    """One ranked at-risk deal for the proactive list view."""

    opportunity_id: uuid.UUID
    name: str
    amount: float | None = None
    currency: str = "USD"
    primary_contact_id: int | None = None
    contact_name: str | None = None
    stage_name: str | None = None
    deal_health: DealHealthStatus
    health_score: int = Field(ge=0, le=100)
    risk_score: int = Field(ge=0, le=100)  # higher = more at risk
    top_risk: str
    days_since_last_contact: int | None = None
    amount_at_risk: float = 0.0


class AtRiskDealsResponse(BaseModel):
    """Ranked list of at-risk deals (most at-risk first)."""

    items: list[AtRiskDeal]
    total: int
    total_amount_at_risk: float = 0.0


class DraftActionRequest(BaseModel):
    """Optional operator overrides when queuing the drafted action."""

    model_config = ConfigDict(extra="forbid")

    channel: ActionChannel | None = None
    body: str | None = None
    description: str | None = None


class DraftActionResponse(BaseModel):
    """Result of queuing a drafted action through the approval gate."""

    decision: Literal["pending", "auto", "blocked"]
    pending_action_id: uuid.UUID | None = None
    action_type: str
    description: str
