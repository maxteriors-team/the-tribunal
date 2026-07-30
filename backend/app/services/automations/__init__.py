"""Automation engine support services (event emission, trigger constants)."""

from app.services.automations.conditions import (
    AUTOMATION_CONDITION_TRIGGERS,
    CONDITION_BACKLOG_BELOW_THRESHOLD,
    evaluate_backlog_condition,
)
from app.services.automations.events import (
    AUTOMATION_EVENT_TRIGGERS,
    EVENT_DEAL_STAGE_CHANGED,
    EVENT_KNOWLEDGE_DOCUMENT_UPLOADED,
    EVENT_MISSED_CALL,
    EVENT_OPPORTUNITY_CREATED,
    EVENT_REVIEW_RECEIVED,
    EVENT_REVIEW_REQUEST_RESPONSE,
    EVENT_ROLEPLAY_COMPLETED,
    emit_automation_event,
)

__all__ = [
    "AUTOMATION_CONDITION_TRIGGERS",
    "AUTOMATION_EVENT_TRIGGERS",
    "CONDITION_BACKLOG_BELOW_THRESHOLD",
    "EVENT_DEAL_STAGE_CHANGED",
    "EVENT_KNOWLEDGE_DOCUMENT_UPLOADED",
    "EVENT_MISSED_CALL",
    "EVENT_OPPORTUNITY_CREATED",
    "EVENT_REVIEW_RECEIVED",
    "EVENT_REVIEW_REQUEST_RESPONSE",
    "EVENT_ROLEPLAY_COMPLETED",
    "emit_automation_event",
    "evaluate_backlog_condition",
]
