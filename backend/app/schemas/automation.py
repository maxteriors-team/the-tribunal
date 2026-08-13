"""Automation schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

# Trigger identifiers accepted by the automation engine. Combines the legacy
# generic kinds (event/schedule/condition), the polling triggers evaluated
# against contacts, the event triggers drained from ``automation_events``, and
# the condition triggers evaluated against workspace state
# (``app.services.automations.conditions``).
AUTOMATION_TRIGGER_TYPES: tuple[str, ...] = (
    # Generic / legacy kinds
    "event",
    "schedule",
    "condition",
    # Polling triggers (contact-centric)
    "booking_created",
    "no_show",
    "contact_tagged",
    "never_booked",
    # Condition triggers (workspace state, no contact matching)
    "backlog_below_threshold",
    # Event triggers (emitted by services)
    "review_received",
    "review_request_response",
    "opportunity_created",
    "deal_stage_changed",
    "missed_call",
    "roleplay_completed",
    "knowledge_document_uploaded",
    # Lead-capture trigger (emitted by the public lead-form ingestion path)
    "lead_created",
    "lead_qualified",
    "appointment_booked",
    # Billing & field-service lifecycle triggers
    "quote_sent",
    "quote_approved",
    "quote_declined",
    "quote_converted",
    "invoice_sent",
    "invoice_paid",
    "job_scheduled",
    "job_completed",
)

# Action identifiers the automation worker dispatches on. Kept here (not in the
# worker) so schemas, the CRM assistant tool enum, and the worker share one
# source of truth; ``tests/workers/test_automation_worker.py`` asserts parity.
# ``add_tag``/``delay`` are accepted aliases of ``apply_tag``/``wait``.
AUTOMATION_ACTION_TYPES: tuple[str, ...] = (
    "send_sms",
    "send_email",
    "make_call",
    "enroll_campaign",
    "start_drip_campaign",
    "move_to_stage",
    "apply_tag",
    "add_tag",
    "wait",
    "delay",
    "branch",
)

# Control-flow steps move the workflow cursor instead of acting on a customer.
# The worker handles them in its step loop rather than its dispatch table, and
# they never pass through the approval gate — gating a ``wait`` would ask an
# operator to authorise a delay.
AUTOMATION_CONTROL_FLOW_ACTIONS: frozenset[str] = frozenset({"wait", "delay", "branch"})

_TRIGGER_PATTERN = "^(" + "|".join(AUTOMATION_TRIGGER_TYPES) + ")$"


class AutomationSendSMSConfig(BaseModel):
    """Typed fields supported by a ``send_sms`` action configuration."""

    model_config = ConfigDict(extra="allow")

    agent_id: UUID | None = Field(
        default=None,
        description="AI agent that owns the outbound message and subsequent SMS conversation",
    )


class AutomationActionSchema(BaseModel):
    """Schema for automation action.

    Steps are stored as raw JSONB, so this model's serialized shape *is* the
    stored shape. A step without an ``id`` therefore serializes without the key
    at all (see :meth:`_omit_absent_id`) rather than writing ``"id": null`` into
    every action of every automation in the product.
    """

    id: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Stable step id. Only needed on steps that a branch jumps to; "
            "steps authored before branching have none and still run."
        ),
    )
    type: str = Field(
        ...,
        description=(
            "Action type: send_sms, send_email, make_call, enroll_campaign, "
            "start_drip_campaign, move_to_stage, apply_tag/add_tag, wait/delay, branch"
        ),
    )
    config: dict[str, Any] = Field(
        default_factory=dict, description="Action-specific configuration"
    )

    @model_validator(mode="after")
    def _validate_typed_config(self) -> "AutomationActionSchema":
        """Validate typed action options while retaining the JSONB wire shape."""
        if self.type == "send_sms":
            typed = AutomationSendSMSConfig.model_validate(self.config)
            self.config = typed.model_dump(mode="json", exclude_none=True)
        return self

    @model_serializer(mode="wrap")
    def _omit_absent_id(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Drop ``id`` when unset so steps round-trip to their stored shape.

        Only branch targets need an id. Without this, adding the field would
        rewrite every existing automation's ``actions`` on its next save, and
        diffing stored steps against what an operator authored would show a
        spurious change on every row.

        Wrap-mode (rather than an override of ``model_dump``) because these are
        serialized *nested* inside the create/update schemas, which goes through
        the core serializer and would bypass an overridden method.
        """
        # Annotated: the handler is untyped, and mypy rejects returning Any
        # from a dict-declared function.
        data: dict[str, Any] = handler(self)
        if data.get("id") is None:
            data.pop("id", None)
        return data


class AutomationCreate(BaseModel):
    """Schema for creating an automation."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    trigger_type: str = Field(default="event", pattern=_TRIGGER_PATTERN)
    trigger_config: dict[str, Any] = Field(default_factory=dict)
    actions: list[AutomationActionSchema] = Field(default_factory=list)
    is_active: bool = True


class AutomationUpdate(BaseModel):
    """Schema for updating an automation."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    trigger_type: str | None = Field(default=None, pattern=_TRIGGER_PATTERN)
    trigger_config: dict[str, Any] | None = None
    actions: list[AutomationActionSchema] | None = None
    is_active: bool | None = None


class AutomationResponse(BaseModel):
    """Schema for automation response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    description: str | None
    trigger_type: str
    trigger_config: dict[str, Any]
    actions: list[dict[str, Any]]
    is_active: bool
    last_triggered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PaginatedAutomations(BaseModel):
    """Paginated automations response."""

    items: list[AutomationResponse]
    total: int
    page: int
    page_size: int
    pages: int


class AutomationStatsResponse(BaseModel):
    """Automation statistics response."""

    total: int
    active: int
    triggered_today: int
