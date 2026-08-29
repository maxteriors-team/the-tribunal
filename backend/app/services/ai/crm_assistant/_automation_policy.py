"""Automation types the CRM assistant may safely author."""

from app.schemas.automation import AUTOMATION_ACTION_TYPES, AUTOMATION_TRIGGER_TYPES

CRM_ASSISTANT_AUTOMATION_TRIGGER_TYPES = tuple(
    trigger
    for trigger in AUTOMATION_TRIGGER_TYPES
    if trigger not in {"event", "generic_event", "schedule", "condition"}
)
CRM_ASSISTANT_AUTOMATION_ACTION_TYPES = tuple(
    action for action in AUTOMATION_ACTION_TYPES if action not in {"add_tag", "delay"}
)
