"""Strict schemas for the local context-accuracy golden harness."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Channel = Literal["sms", "voice", "crm_assistant"]
FailureClass = Literal[
    "stored_fact_recall",
    "cross_channel_continuity",
    "stale_conflicting_state",
    "pricing_availability_grounding",
    "quote_appointment_status",
    "tool_selection",
    "opt_out",
    "human_handoff",
]
Risk = Literal["low", "medium", "high"]
Freshness = Literal["fresh", "stale", "conflicting"]
ClaimDomain = Literal[
    "pricing",
    "availability",
    "booking",
    "quote",
    "appointment",
    "contact",
    "other",
]
RouteTier = Literal["cheap", "strong"]

_EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_PHONE_PATTERN = re.compile(r"(?<![A-Z_])\+?\d[\d(). -]{8,}\d(?![A-Z_])")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GoldenContextSource(StrictModel):
    source_id: str = Field(pattern=r"^src:[a-z0-9:_-]+$")
    freshness: Freshness
    fact_ids: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()


class RoutingInput(StrictModel):
    has_context_conflict: bool = False
    requires_tool_action: bool = False


class ScenarioExpectation(StrictModel):
    fact_ids: tuple[str, ...] = ()
    supported_claim_ids: tuple[str, ...] = ()
    stale_source_ids: tuple[str, ...] = ()
    required_actions: tuple[str, ...] = ()
    allowed_actions: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    handoff: bool
    sms_route: RouteTier | None = None
    max_temperature: float | None = Field(default=None, ge=0.0, le=2.0)


class GoldenScenario(StrictModel):
    scenario_id: str = Field(pattern=r"^[a-z0-9-]+$")
    channel: Channel
    failure_class: FailureClass
    risk: Risk
    redacted_turn: str = Field(min_length=8, max_length=500)
    context_sources: tuple[GoldenContextSource, ...]
    expected: ScenarioExpectation
    routing_input: RoutingInput | None = None

    @model_validator(mode="after")
    def validate_redaction_and_references(self) -> GoldenScenario:
        if _EMAIL_PATTERN.search(self.redacted_turn) or _PHONE_PATTERN.search(self.redacted_turn):
            raise ValueError("golden turns must not contain email addresses or phone numbers")
        if "[" not in self.redacted_turn or "]" not in self.redacted_turn:
            raise ValueError("golden turns must use explicit redaction placeholders")

        source_ids = {source.source_id for source in self.context_sources}
        if len(source_ids) != len(self.context_sources):
            raise ValueError("context source IDs must be unique per scenario")
        known_facts = {fact_id for source in self.context_sources for fact_id in source.fact_ids}
        if not set(self.expected.fact_ids).issubset(known_facts):
            raise ValueError("expected fact IDs must exist in context_sources")
        known_claims = {
            claim_id for source in self.context_sources for claim_id in source.claim_ids
        }
        if not set(self.expected.supported_claim_ids).issubset(known_claims):
            raise ValueError("supported claim IDs must exist in context_sources")
        stale_sources = {
            source.source_id
            for source in self.context_sources
            if source.freshness in {"stale", "conflicting"}
        }
        if not set(self.expected.stale_source_ids).issubset(stale_sources):
            raise ValueError("stale source IDs must refer to stale/conflicting sources")

        if self.channel == "sms":
            if self.expected.sms_route is None or self.expected.max_temperature is None:
                raise ValueError("SMS scenarios require route and temperature expectations")
            if self.routing_input is None:
                raise ValueError("SMS scenarios require routing_input")
        elif (
            self.expected.sms_route is not None
            or self.expected.max_temperature is not None
            or self.routing_input is not None
        ):
            raise ValueError("voice/CRM scenarios cannot define SMS routing expectations")
        return self


class CandidateClaim(StrictModel):
    claim_id: str
    domain: ClaimDomain


class CandidateObservation(StrictModel):
    """Body-free labels produced by a model adapter or reviewed shadow run."""

    scenario_id: str
    recalled_fact_ids: tuple[str, ...] = ()
    claims: tuple[CandidateClaim, ...] = ()
    relied_on_source_ids: tuple[str, ...] = ()
    tool_actions: tuple[str, ...] = ()
    handoff: bool
    human_correction: bool = False
