"""Data-driven CRM assistant tool policy metadata."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pending_action import PendingAction
from app.services.ai.crm_assistant._tool_context import ToolArguments, ToolHandler

type ApprovedActionExecutor = Callable[[AsyncSession, PendingAction], Awaitable[dict[str, Any]]]


class ToolRiskLevel(StrEnum):
    """Operational risk categories for CRM assistant tools."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(slots=True, frozen=True)
class ApprovalPolicy:
    """Approval and confirmation requirements for a CRM assistant tool."""

    required: bool = False
    requires_confirmation: bool = False
    urgency: str = "normal"
    pending_message: str = "Approval required before I can run this CRM action."


@dataclass(slots=True, frozen=True)
class CRMToolMetadata:
    """Runtime metadata for one CRM assistant tool."""

    name: str
    handler: ToolHandler
    risk_level: ToolRiskLevel
    approval: ApprovalPolicy = ApprovalPolicy()
    approved_executor: ApprovedActionExecutor | None = None
    description_template: str | None = None

    @property
    def action_type(self) -> str:
        return f"crm_assistant.{self.name}"

    @property
    def requires_approval(self) -> bool:
        return self.approval.required

    @property
    def requires_confirmation(self) -> bool:
        return self.approval.requires_confirmation

    def describe(self, payload: ToolArguments) -> str:
        """Render a stable human-readable description for pending approval."""

        if self.description_template is None:
            return f"Run {self.name}"
        try:
            return self.description_template.format(**payload)
        except (KeyError, IndexError, ValueError):
            return f"Run {self.name}"


async def _missing_handler(_args: ToolArguments) -> dict[str, Any]:
    return {"success": False, "error": "Tool handler is not bound"}


async def execute_approved_crm_assistant_tool(
    db: AsyncSession,
    action: PendingAction,
) -> dict[str, Any]:
    """Execute an approved CRM assistant pending action through its tool handler."""

    from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor

    tool_name = action.action_type.removeprefix(CRM_ASSISTANT_ACTION_PREFIX)
    raw_user_id = action.context.get("user_id", 0)
    try:
        user_id = int(raw_user_id) if isinstance(raw_user_id, int | str) else 0
    except ValueError:
        user_id = 0
    executor = CRMToolExecutor(db=db, workspace_id=action.workspace_id, user_id=user_id)
    result = await executor.execute(tool_name, {**action.action_payload, "confirmed": True})
    return {"tool": tool_name, **result}


def get_tool_policy(tool_name: str) -> CRMToolMetadata:
    """Return policy metadata for a tool before a concrete handler is bound."""

    return _TOOL_POLICY_OVERRIDES.get(tool_name, _DEFAULT_TOOL_POLICY)


def get_approved_action_executor(action_type: str) -> ApprovedActionExecutor | None:
    """Return the approved-action executor bound to a CRM assistant action type."""

    if not action_type.startswith(CRM_ASSISTANT_ACTION_PREFIX):
        return None
    tool_name = action_type.removeprefix(CRM_ASSISTANT_ACTION_PREFIX)
    return get_tool_policy(tool_name).approved_executor


def build_tool_metadata(
    *,
    handlers: dict[str, ToolHandler],
) -> dict[str, CRMToolMetadata]:
    """Bind registered handlers to their data-driven risk and approval policy."""

    metadata: dict[str, CRMToolMetadata] = {}
    for name, handler in handlers.items():
        policy = get_tool_policy(name)
        metadata[name] = CRMToolMetadata(
            name=name,
            handler=handler,
            risk_level=policy.risk_level,
            approval=policy.approval,
            approved_executor=policy.approved_executor,
            description_template=policy.description_template,
        )
    return metadata


CRM_ASSISTANT_ACTION_PREFIX = "crm_assistant."

_DEFAULT_TOOL_POLICY = CRMToolMetadata(
    name="__default__",
    handler=_missing_handler,
    risk_level=ToolRiskLevel.LOW,
)


_TOOL_POLICY_OVERRIDES: dict[str, CRMToolMetadata] = {
    "create_contact": CRMToolMetadata(
        name="create_contact",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.MEDIUM,
    ),
    "send_sms": CRMToolMetadata(
        name="send_sms",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.HIGH,
        approval=ApprovalPolicy(
            required=True,
            requires_confirmation=True,
            urgency="high",
            pending_message="Approval required before I can send this SMS.",
        ),
        approved_executor=execute_approved_crm_assistant_tool,
        description_template="Send SMS to contact {contact_id}",
    ),
    "send_initial_message": CRMToolMetadata(
        name="send_initial_message",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.HIGH,
        approval=ApprovalPolicy(
            required=True,
            requires_confirmation=True,
            urgency="high",
            pending_message="Approval required before I can send this campaign message.",
        ),
        approved_executor=execute_approved_crm_assistant_tool,
        description_template=(
            "Send initial message for campaign {campaign_id} to contact {contact_id}"
        ),
    ),
    "start_campaign": CRMToolMetadata(
        name="start_campaign",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.HIGH,
        approval=ApprovalPolicy(
            required=True,
            requires_confirmation=True,
            urgency="high",
            pending_message="Approval required before I can start this campaign.",
        ),
        approved_executor=execute_approved_crm_assistant_tool,
        description_template="Start campaign {campaign_id}",
    ),
    "resume_campaign": CRMToolMetadata(
        name="resume_campaign",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.HIGH,
        approval=ApprovalPolicy(
            required=True,
            requires_confirmation=True,
            urgency="high",
            pending_message="Approval required before I can resume this campaign.",
        ),
        approved_executor=execute_approved_crm_assistant_tool,
        description_template="Resume campaign {campaign_id}",
    ),
    "pause_campaign": CRMToolMetadata(
        name="pause_campaign",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.MEDIUM,
    ),
    "plan_outbound_growth_workflow": CRMToolMetadata(
        name="plan_outbound_growth_workflow",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.MEDIUM,
    ),
    "create_automation": CRMToolMetadata(
        name="create_automation",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.HIGH,
        approval=ApprovalPolicy(
            required=True,
            requires_confirmation=True,
            pending_message="Approval required before I can create this automation.",
        ),
        approved_executor=execute_approved_crm_assistant_tool,
        description_template="Create automation {name}",
    ),
    "enable_automation": CRMToolMetadata(
        name="enable_automation",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.HIGH,
        approval=ApprovalPolicy(
            required=True,
            requires_confirmation=True,
            pending_message="Approval required before I can enable this automation.",
        ),
        approved_executor=execute_approved_crm_assistant_tool,
        description_template="Enable automation {automation_id}",
    ),
    "disable_automation": CRMToolMetadata(
        name="disable_automation",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.MEDIUM,
    ),
    "create_agent": CRMToolMetadata(
        name="create_agent",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.HIGH,
        approval=ApprovalPolicy(
            required=True,
            requires_confirmation=True,
            pending_message="Approval required before I can create this AI agent.",
        ),
        approved_executor=execute_approved_crm_assistant_tool,
        description_template="Create AI agent {name}",
    ),
    "update_agent": CRMToolMetadata(
        name="update_agent",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.HIGH,
        approval=ApprovalPolicy(
            required=True,
            requires_confirmation=True,
            pending_message="Approval required before I can update this AI agent.",
        ),
        approved_executor=execute_approved_crm_assistant_tool,
        description_template="Update AI agent {agent_id}",
    ),
    "assign_ai_responder": CRMToolMetadata(
        name="assign_ai_responder",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.HIGH,
        approval=ApprovalPolicy(
            required=True,
            requires_confirmation=True,
            pending_message="Approval required before I can assign this AI responder.",
        ),
        approved_executor=execute_approved_crm_assistant_tool,
        description_template=("Assign AI responder {agent_id} to conversation {conversation_id}"),
    ),
    "create_offer_draft": CRMToolMetadata(
        name="create_offer_draft",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.MEDIUM,
    ),
    "update_offer_draft": CRMToolMetadata(
        name="update_offer_draft",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.MEDIUM,
    ),
}
