"""Data-driven CRM assistant tool policy metadata."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Capability, role_can
from app.core.roles import WorkspaceRole
from app.models.pending_action import PendingAction
from app.models.workspace import WorkspaceMembership
from app.services.ai.crm_assistant._tool_context import ToolArguments, ToolHandler
from app.services.ai.crm_assistant._tool_errors import internal_error, not_permitted

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
    required_capability: Capability = Capability.WORKSPACE_MANAGE

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
    return internal_error("This tool")


async def execute_approved_crm_assistant_tool(
    db: AsyncSession,
    action: PendingAction,
) -> dict[str, Any]:
    """Execute an approved CRM assistant pending action through its tool handler."""

    from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor

    tool_name = action.action_type.removeprefix(CRM_ASSISTANT_ACTION_PREFIX)
    raw_user_id = action.context.get("user_id", 0)
    try:
        user_id = (
            int(raw_user_id)
            if not isinstance(raw_user_id, bool) and isinstance(raw_user_id, int | str)
            else 0
        )
    except ValueError:
        user_id = 0

    membership_result = await db.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == action.workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    )
    membership = membership_result.scalar_one_or_none()
    # The queued role is audit context only; authorization uses this current membership.
    role = membership.role if membership is not None else None
    known_roles = {workspace_role.value for workspace_role in WorkspaceRole}
    required_capability = tool_capability(tool_name)
    if role not in known_roles or not role_can(role, required_capability):
        return {
            "tool": tool_name,
            **not_permitted(
                "The requester no longer has permission to run this action.",
                "Review their current workspace membership and queue a new action if appropriate.",
            ),
        }

    executor = CRMToolExecutor(
        db=db,
        workspace_id=action.workspace_id,
        user_id=user_id,
        role=role,
    )
    # A human approved this pending action, so the gate is satisfied. This is
    # passed as a keyword argument rather than a tool-payload key precisely so
    # the model can never forge it.
    result = await executor.execute(
        tool_name,
        dict(action.action_payload),
        approval_granted=True,
    )
    return {"tool": tool_name, **result}


def get_tool_policy(tool_name: str) -> CRMToolMetadata:
    """Return policy metadata for a tool before a concrete handler is bound."""

    return _TOOL_POLICY_OVERRIDES.get(tool_name, _DEFAULT_TOOL_POLICY)


def tool_capability(tool_name: str) -> Capability:
    """Return the capability a caller must hold to run ``tool_name``.

    Unlisted tools resolve to :data:`Capability.WORKSPACE_MANAGE` (admin only),
    so a tool added without a policy entry is admin-gated by omission rather
    than open by omission. ``tests/api/test_technician_surface_probe.py`` asserts
    every declared tool appears in :data:`_TOOL_CAPABILITIES`, so the fallback is
    a safety net and not the intended path.
    """

    return _TOOL_CAPABILITIES.get(tool_name, Capability.WORKSPACE_MANAGE)


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
            required_capability=tool_capability(name),
        )
    return metadata


# Tool → capability required to run it.
#
# Each entry mirrors the capability the equivalent HTTP route already enforces,
# so the assistant cannot become a side door around the router gates:
#
#   * contacts   (``app/api/v1/contacts.py``)   read ``crm:read``, write ``crm:write``
#   * campaigns  (``app/api/v1/campaigns.py``)  read ``crm:read``, write ``outreach:write``
#   * automations(``app/api/v1/automations.py``)read ``crm:read``, write ``outreach:write``
#   * offers     (``app/api/v1/offers.py``)     read ``crm:read``, write ``outreach:write``
#   * agents     (``app/api/v1/agents.py``)     read ``crm:read``, write ``workspace:manage``
#   * outbound SMS                              ``comms:send``
#   * dashboard metrics                         ``reports:view``
#
# Appointment writes are the one policy this map *sets* rather than mirrors:
# ``app/api/v1/appointments.py`` carries no capability gate today (tracked as an
# open finding), so scheduling is mapped to ``jobs:write`` — the schedule is the
# dispatch tier's surface. Tiers below dispatch keep booking through the
# appointments UI, which this map does not touch.
_TOOL_CAPABILITIES: dict[str, Capability] = {
    # ── reads: crm:read ────────────────────────────────────────────────
    "search_contacts": Capability.CRM_READ,
    "find_contacts": Capability.CRM_READ,
    "get_contact": Capability.CRM_READ,
    "get_contact_context": Capability.CRM_READ,
    "get_conversation": Capability.CRM_READ,
    "list_recent_conversations": Capability.CRM_READ,
    "list_tags": Capability.CRM_READ,
    "list_segments": Capability.CRM_READ,
    "preview_segment": Capability.CRM_READ,
    "list_campaigns": Capability.CRM_READ,
    "list_campaign_contacts": Capability.CRM_READ,
    "summarize_campaign": Capability.CRM_READ,
    "list_automations": Capability.CRM_READ,
    "get_automation": Capability.CRM_READ,
    "list_agents": Capability.CRM_READ,
    "get_agent": Capability.CRM_READ,
    "list_offers": Capability.CRM_READ,
    "get_offer_details": Capability.CRM_READ,
    "list_opportunities": Capability.CRM_READ,
    "get_opportunity": Capability.CRM_READ,
    "list_pipeline_stages": Capability.CRM_READ,
    "list_appointments": Capability.CRM_READ,
    "get_appointment": Capability.CRM_READ,
    "get_today_queue": Capability.CRM_READ,
    # ── revenue/performance metrics: reports:view (admin tier) ─────────
    "get_dashboard_stats": Capability.REPORTS_VIEW,
    # ── contact writes: crm:write ──────────────────────────────────────
    "create_contact": Capability.CRM_WRITE,
    "update_contact": Capability.CRM_WRITE,
    "add_contact_note": Capability.CRM_WRITE,
    "add_contact_tags": Capability.CRM_WRITE,
    "create_segment": Capability.CRM_WRITE,
    "update_segment": Capability.CRM_WRITE,
    # ── owner-scoped pipeline writes: pipeline:write_own ────────────────
    "create_opportunity": Capability.PIPELINE_WRITE_OWN,
    "update_opportunity": Capability.PIPELINE_WRITE_OWN,
    # ── outreach authoring: outreach:write ─────────────────────────────
    "create_campaign": Capability.OUTREACH_WRITE,
    "update_campaign": Capability.OUTREACH_WRITE,
    "enroll_campaign_audience": Capability.OUTREACH_WRITE,
    "start_campaign": Capability.OUTREACH_WRITE,
    "pause_campaign": Capability.OUTREACH_WRITE,
    "resume_campaign": Capability.OUTREACH_WRITE,
    "plan_outbound_growth_workflow": Capability.OUTREACH_WRITE,
    "create_automation": Capability.OUTREACH_WRITE,
    "update_automation": Capability.OUTREACH_WRITE,
    "enable_automation": Capability.OUTREACH_WRITE,
    "disable_automation": Capability.OUTREACH_WRITE,
    "delete_automation": Capability.OUTREACH_WRITE,
    "create_offer_draft": Capability.OUTREACH_WRITE,
    "update_offer_draft": Capability.OUTREACH_WRITE,
    # ── customer messaging: comms:send ─────────────────────────────────
    "send_sms": Capability.COMMS_SEND,
    # ── schedule writes: jobs:write ────────────────────────────────────
    "create_appointment": Capability.JOBS_WRITE,
    "update_appointment": Capability.JOBS_WRITE,
    "delete_appointment": Capability.JOBS_WRITE,
    # ── AI agent configuration: workspace:manage ───────────────────────
    "create_agent": Capability.WORKSPACE_MANAGE,
    "update_agent": Capability.WORKSPACE_MANAGE,
    "assign_ai_responder": Capability.WORKSPACE_MANAGE,
    # ── product help: any member who can reach the assistant ───────────
    "search_help": Capability.CRM_READ,
}


CRM_ASSISTANT_ACTION_PREFIX = "crm_assistant."

_DEFAULT_TOOL_POLICY = CRMToolMetadata(
    name="__default__",
    handler=_missing_handler,
    risk_level=ToolRiskLevel.LOW,
)


_TOOL_POLICY_OVERRIDES: dict[str, CRMToolMetadata] = {
    "get_contact": CRMToolMetadata(
        name="get_contact",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.LOW,
    ),
    "get_contact_context": CRMToolMetadata(
        name="get_contact_context",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.LOW,
    ),
    "find_contacts": CRMToolMetadata(
        name="find_contacts",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.LOW,
    ),
    "create_contact": CRMToolMetadata(
        name="create_contact",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.MEDIUM,
    ),
    "update_contact": CRMToolMetadata(
        name="update_contact",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.MEDIUM,
    ),
    "add_contact_note": CRMToolMetadata(
        name="add_contact_note",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.MEDIUM,
    ),
    "add_contact_tags": CRMToolMetadata(
        name="add_contact_tags",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.MEDIUM,
    ),
    "create_segment": CRMToolMetadata(
        name="create_segment",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.MEDIUM,
    ),
    "update_segment": CRMToolMetadata(
        name="update_segment",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.MEDIUM,
    ),
    "create_opportunity": CRMToolMetadata(
        name="create_opportunity",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.MEDIUM,
    ),
    "update_opportunity": CRMToolMetadata(
        name="update_opportunity",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.MEDIUM,
    ),
    "create_campaign": CRMToolMetadata(
        name="create_campaign",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.MEDIUM,
    ),
    "update_campaign": CRMToolMetadata(
        name="update_campaign",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.MEDIUM,
    ),
    "enroll_campaign_audience": CRMToolMetadata(
        name="enroll_campaign_audience",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.MEDIUM,
    ),
    "list_campaign_contacts": CRMToolMetadata(
        name="list_campaign_contacts",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.LOW,
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
    "get_automation": CRMToolMetadata(
        name="get_automation",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.LOW,
    ),
    "create_automation": CRMToolMetadata(
        name="create_automation",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.MEDIUM,
    ),
    "update_automation": CRMToolMetadata(
        name="update_automation",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.MEDIUM,
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
    "delete_automation": CRMToolMetadata(
        name="delete_automation",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.HIGH,
        approval=ApprovalPolicy(
            required=True,
            requires_confirmation=True,
            pending_message="Approval required before I can delete this automation.",
        ),
        approved_executor=execute_approved_crm_assistant_tool,
        description_template="Delete automation {automation_id}",
    ),
    "create_appointment": CRMToolMetadata(
        name="create_appointment",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.HIGH,
        approval=ApprovalPolicy(
            required=True,
            requires_confirmation=True,
            pending_message="Approval required before I schedule this calendar event.",
        ),
        approved_executor=execute_approved_crm_assistant_tool,
        description_template="Schedule appointment for contact {contact_id} at {scheduled_at}",
    ),
    "update_appointment": CRMToolMetadata(
        name="update_appointment",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.HIGH,
        approval=ApprovalPolicy(
            required=True,
            requires_confirmation=True,
            pending_message="Approval required before I change this calendar event.",
        ),
        approved_executor=execute_approved_crm_assistant_tool,
        description_template="Update appointment {appointment_id}",
    ),
    "delete_appointment": CRMToolMetadata(
        name="delete_appointment",
        handler=_missing_handler,
        risk_level=ToolRiskLevel.HIGH,
        approval=ApprovalPolicy(
            required=True,
            requires_confirmation=True,
            pending_message="Approval required before I delete this calendar event.",
        ),
        approved_executor=execute_approved_crm_assistant_tool,
        description_template="Delete appointment {appointment_id}",
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
