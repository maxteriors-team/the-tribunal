"""CRM assistant tool executor registry and approval gate."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.crm_assistant._agent_tools import AgentAssistantTools
from app.services.ai.crm_assistant._appointment_tools import AppointmentAssistantTools
from app.services.ai.crm_assistant._campaign_tools import CampaignAssistantTools
from app.services.ai.crm_assistant._contact_tools import ContactAssistantTools
from app.services.ai.crm_assistant._conversation_tools import ConversationAssistantTools
from app.services.ai.crm_assistant._offer_tools import OfferAssistantTools
from app.services.ai.crm_assistant._opportunity_tools import OpportunityAssistantTools
from app.services.ai.crm_assistant._outbound_tools import OutboundAssistantTools
from app.services.ai.crm_assistant._tool_context import CRMToolContext, ToolArguments, ToolHandler
from app.services.approval.approval_gate_service import approval_gate_service

_APPROVAL_GATED_TOOLS = {
    "send_sms",
    "send_initial_message",
    "start_campaign",
    "resume_campaign",
    "create_agent",
    "update_agent",
    "assign_ai_responder",
}


class CRMToolExecutor:
    """Execute CRM tool calls on behalf of the assistant."""

    def __init__(self, db: AsyncSession, workspace_id: uuid.UUID, user_id: int) -> None:
        self.context = CRMToolContext(db=db, workspace_id=workspace_id, user_id=user_id)
        self.db = db
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.log = structlog.get_logger(service="crm_tool_executor")
        self.handlers = self._build_handlers()

    def _build_handlers(self) -> dict[str, ToolHandler]:
        handlers: dict[str, ToolHandler] = {}
        modules = (
            ContactAssistantTools(self.context),
            CampaignAssistantTools(self.context),
            AgentAssistantTools(self.context),
            ConversationAssistantTools(self.context),
            AppointmentAssistantTools(self.context),
            OpportunityAssistantTools(self.context),
            OfferAssistantTools(self.context),
            OutboundAssistantTools(self.context),
        )
        for module in modules:
            handlers.update(module.handlers())
        return handlers

    @staticmethod
    def _is_explicitly_confirmed(args: ToolArguments) -> bool:
        return bool(args.get("confirmed") or args.get("user_confirmed"))

    async def _queue_pending_action(
        self,
        function_name: str,
        arguments: ToolArguments,
    ) -> dict[str, Any]:
        payload = {
            key: value
            for key, value in arguments.items()
            if key not in {"confirmed", "user_confirmed"}
        }
        decision, metadata = await approval_gate_service.check_and_execute_or_queue(
            db=self.db,
            agent_id=None,
            workspace_id=self.workspace_id,
            action_type=f"crm_assistant.{function_name}",
            action_payload=payload,
            description=self._describe_pending_action(function_name, payload),
            context={"source": "crm_assistant", "user_id": self.user_id},
            urgency=(
                "high"
                if function_name
                in {"send_sms", "send_initial_message", "start_campaign", "resume_campaign"}
                else "normal"
            ),
            require_approval_without_agent=True,
        )
        if decision != "pending" or metadata is None:
            return {"success": False, "error": "Approval gate did not create a pending action"}
        return {
            "success": False,
            "pending_approval": True,
            "pending_action_id": metadata["action_id"],
            "message": "Approval required before I can run this outbound CRM action.",
        }

    @staticmethod
    def _describe_pending_action(function_name: str, payload: ToolArguments) -> str:
        descriptions = {
            "send_sms": f"Send SMS to contact {payload.get('contact_id')}",
            "send_initial_message": (
                f"Send initial message for campaign {payload.get('campaign_id')} "
                f"to contact {payload.get('contact_id')}"
            ),
            "start_campaign": f"Start campaign {payload.get('campaign_id')}",
            "resume_campaign": f"Resume campaign {payload.get('campaign_id')}",
            "create_agent": f"Create AI agent {payload.get('name', '(unnamed)')}",
            "update_agent": f"Update AI agent {payload.get('agent_id')}",
            "assign_ai_responder": (
                f"Assign AI responder {payload.get('agent_id')} "
                f"to conversation {payload.get('conversation_id')}"
            ),
        }
        return descriptions.get(function_name, f"Run {function_name}")

    async def execute(self, function_name: str, arguments: ToolArguments) -> dict[str, Any]:
        """Dispatch a tool call to the appropriate handler."""

        handler = self.handlers.get(function_name)
        if not handler:
            return {"success": False, "error": f"Unknown function: {function_name}"}
        try:
            if function_name in _APPROVAL_GATED_TOOLS and not self._is_explicitly_confirmed(
                arguments
            ):
                return await self._queue_pending_action(function_name, arguments)
            return await handler(arguments)
        except Exception:
            self.log.exception("tool_execution_failed", function_name=function_name)
            return {"success": False, "error": f"Failed to execute {function_name}"}
