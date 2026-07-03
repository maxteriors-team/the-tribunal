"""CRM assistant tool executor registry and approval gate."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.crm_assistant._agent_tools import AgentAssistantTools
from app.services.ai.crm_assistant._appointment_tools import AppointmentAssistantTools
from app.services.ai.crm_assistant._automation_tools import AutomationAssistantTools
from app.services.ai.crm_assistant._campaign_tools import CampaignAssistantTools
from app.services.ai.crm_assistant._contact_tools import ContactAssistantTools
from app.services.ai.crm_assistant._conversation_tools import ConversationAssistantTools
from app.services.ai.crm_assistant._offer_tools import OfferAssistantTools
from app.services.ai.crm_assistant._opportunity_tools import OpportunityAssistantTools
from app.services.ai.crm_assistant._outbound_tools import OutboundAssistantTools
from app.services.ai.crm_assistant._tool_context import CRMToolContext, ToolArguments, ToolHandler
from app.services.ai.crm_assistant._tool_metadata import CRMToolMetadata, build_tool_metadata
from app.services.approval.approval_gate_service import approval_gate_service


class CRMToolExecutor:
    """Execute CRM tool calls on behalf of the assistant."""

    def __init__(self, db: AsyncSession, workspace_id: uuid.UUID, user_id: int) -> None:
        self.context = CRMToolContext(db=db, workspace_id=workspace_id, user_id=user_id)
        self.db = db
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.log = structlog.get_logger(service="crm_tool_executor")
        self.tool_metadata = self._build_tool_metadata()
        self.handlers = {name: metadata.handler for name, metadata in self.tool_metadata.items()}

    def _build_handlers(self) -> dict[str, ToolHandler]:
        handlers: dict[str, ToolHandler] = {}
        modules = (
            ContactAssistantTools(self.context),
            CampaignAssistantTools(self.context),
            AutomationAssistantTools(self.context),
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

    def _build_tool_metadata(self) -> dict[str, CRMToolMetadata]:
        return build_tool_metadata(handlers=self._build_handlers())

    @staticmethod
    def _is_explicitly_confirmed(args: ToolArguments) -> bool:
        return bool(args.get("confirmed") or args.get("user_confirmed"))

    async def _queue_pending_action(
        self,
        metadata: CRMToolMetadata,
        arguments: ToolArguments,
    ) -> dict[str, Any]:
        payload = {
            key: value
            for key, value in arguments.items()
            if key not in {"confirmed", "user_confirmed"}
        }
        decision, approval_result = await approval_gate_service.check_and_execute_or_queue(
            db=self.db,
            agent_id=None,
            workspace_id=self.workspace_id,
            action_type=metadata.action_type,
            action_payload=payload,
            description=metadata.describe(payload),
            context={
                "source": "crm_assistant",
                "user_id": self.user_id,
                "risk_level": metadata.risk_level.value,
                "requires_confirmation": metadata.requires_confirmation,
            },
            urgency=metadata.approval.urgency,
            require_approval_without_agent=True,
        )
        if decision == "blocked":
            return {"success": False, "error": "Action blocked by approval policy"}
        if decision != "pending" or approval_result is None:
            return {"success": False, "error": "Approval gate did not create a pending action"}
        return {
            "success": False,
            "pending_approval": True,
            "pending_action_id": approval_result["action_id"],
            "message": metadata.approval.pending_message,
        }

    async def execute(self, function_name: str, arguments: ToolArguments) -> dict[str, Any]:
        """Dispatch a tool call to the appropriate handler."""

        metadata = self.tool_metadata.get(function_name)
        if metadata is None:
            return {"success": False, "error": f"Unknown function: {function_name}"}
        try:
            if metadata.requires_approval and not self._is_explicitly_confirmed(arguments):
                return await self._queue_pending_action(metadata, arguments)
            return await metadata.handler(arguments)
        except Exception:
            self.log.exception("tool_execution_failed", function_name=function_name)
            return {"success": False, "error": f"Failed to execute {function_name}"}
