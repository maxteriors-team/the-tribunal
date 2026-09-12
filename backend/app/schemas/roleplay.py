"""Practice-arena (roleplay) schemas."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# === Persona schemas ===


class ProspectPersonaResponse(BaseModel):
    """A synthetic prospect persona."""

    id: uuid.UUID
    workspace_id: uuid.UUID | None
    slug: str
    name: str
    description: str | None
    difficulty: str
    channel: str
    persona_prompt: str
    opening_message: str | None
    objections: list[str]
    goal: str | None
    is_builtin: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProspectPersonaCreate(BaseModel):
    """Create a custom workspace persona."""

    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    slug: str | None = Field(default=None, max_length=100)
    difficulty: str = "medium"
    channel: str = "sms"
    persona_prompt: str = Field(min_length=1)
    opening_message: str | None = None
    objections: list[str] = Field(default_factory=list)
    goal: str | None = None


class ProspectPersonaUpdate(BaseModel):
    """Update a custom workspace persona."""

    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    difficulty: str | None = None
    channel: str | None = None
    persona_prompt: str | None = None
    opening_message: str | None = None
    objections: list[str] | None = None
    goal: str | None = None


# === Rehearsal run schemas ===


class RehearsalTranscriptTurn(BaseModel):
    """One turn in a rehearsal transcript."""

    role: str
    content: str


class RehearsalRunSummary(BaseModel):
    """Lightweight rehearsal run for list views."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    agent_id: uuid.UUID | None
    persona_id: uuid.UUID | None
    agent_name: str | None
    persona_name: str | None
    rehearsee: str
    channel: str
    status: str
    pending_action: str | None = None
    attempt_count: int = 0
    retryable: bool = False
    overall_score: float | None
    objection_coverage: float | None
    booking_attempted: bool | None
    tone_score: float | None
    created_at: datetime
    completed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class RehearsalRunResponse(RehearsalRunSummary):
    """Full rehearsal run including transcript and report."""

    max_turns: int
    transcript: list[RehearsalTranscriptTurn]
    scores: dict[str, Any]
    strengths: list[str]
    gaps: list[str]
    suggestions: list[str]
    summary: str | None
    error: str | None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CreateRehearsalRequest(BaseModel):
    """Start a rehearsal of an agent (or human rep) against a persona."""

    idempotency_key: uuid.UUID
    agent_id: uuid.UUID
    persona_id: uuid.UUID
    rehearsee: Literal["ai", "human"] = "ai"
    channel: Literal["sms", "voice"] | None = None
    max_turns: int = Field(default=6, ge=1, le=12)


class HumanTurnRequest(BaseModel):
    """A human rep's reply during a live rehearsal."""

    message: str = Field(min_length=1, max_length=4000)
    expected_turn_count: int = Field(ge=1, le=25)


class RetryRehearsalRequest(BaseModel):
    """Retry only the failure the caller observed, not a later failed attempt."""

    expected_attempt_count: int = Field(ge=0)
