"""CRM assistant tool executor registry and approval gate."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.crm_assistant._agent_tools import AgentAssistantTools
from app.services.ai.crm_assistant._appointment_tools import AppointmentAssistantTools
from app.services.ai.crm_assistant._automation_tools import AutomationAssistantTools
from app.services.ai.crm_assistant._campaign_tools import CampaignAssistantTools
from app.services.ai.crm_assistant._contact_tools import ContactAssistantTools
from app.services.ai.crm_assistant._conversation_tools import ConversationAssistantTools
from app.services.ai.crm_assistant._help_tools import HelpAssistantTools
from app.services.ai.crm_assistant._offer_tools import OfferAssistantTools
from app.services.ai.crm_assistant._opportunity_tools import OpportunityAssistantTools
from app.services.ai.crm_assistant._outbound_tools import OutboundAssistantTools
from app.services.ai.crm_assistant._tool_context import CRMToolContext, ToolArguments, ToolHandler
from app.services.ai.crm_assistant._tool_errors import (
    internal_error,
    invalid_argument,
    not_permitted,
    unavailable,
    unknown_tool,
)
from app.services.ai.crm_assistant._tool_metadata import CRMToolMetadata, build_tool_metadata
from app.services.approval.approval_gate_service import approval_gate_service

# Approval flags a model might try to set on itself. They are never part of a
# tool schema; anything arriving under these keys is stripped and logged.
_APPROVAL_FLAG_KEYS = frozenset({"confirmed", "user_confirmed"})


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
            HelpAssistantTools(self.context),
        )
        for module in modules:
            handlers.update(module.handlers())
        return handlers

    def _build_tool_metadata(self) -> dict[str, CRMToolMetadata]:
        return build_tool_metadata(handlers=self._build_handlers())

    @staticmethod
    def _strip_approval_flags(args: ToolArguments) -> tuple[ToolArguments, list[str]]:
        """Remove any model-supplied approval flags and report what was found.

        ``confirmed`` used to be a parameter in the tool schema the model writes,
        gating approval on `args.get("confirmed")`. Nothing stopped the model
        from emitting `confirmed: true` itself, which walked straight past the
        human approval gate on send_sms, start_campaign, create_automation and
        create_agent. ``user_confirmed`` was honoured too and appeared in no
        schema at all. Approval is now the executor's decision alone, so these
        keys are stripped and their presence logged as an attempted bypass.
        """
        present = [key for key in _APPROVAL_FLAG_KEYS if key in args]
        if not present:
            return args, []
        return {
            key: value for key, value in args.items() if key not in _APPROVAL_FLAG_KEYS
        }, present

    async def _queue_pending_action(
        self,
        metadata: CRMToolMetadata,
        arguments: ToolArguments,
    ) -> dict[str, Any]:
        """Route a gated action into the human approval queue."""
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
            return not_permitted(
                "That action was blocked by the workspace approval policy.",
                "Tell the operator it needs a policy change; do not retry.",
            )
        if decision != "pending" or approval_result is None:
            return unavailable(
                "The approval queue could not accept this action.",
                "Tell the operator the action was not queued.",
            )
        return {
            "success": False,
            "code": "pending_approval",
            "pending_approval": True,
            "pending_action_id": approval_result["action_id"],
            "message": metadata.approval.pending_message,
            "retryable": False,
            "hint": (
                "Tell the operator it is waiting for their approval in this chat. "
                "Do not call the tool again."
            ),
        }

    async def execute(
        self,
        function_name: str,
        arguments: ToolArguments,
        *,
        approval_granted: bool = False,
    ) -> dict[str, Any]:
        """Dispatch a tool call to the appropriate handler.

        ``approval_granted`` is the *only* way to skip the approval gate, and it
        is a Python keyword argument — not tool JSON — so a model cannot reach
        it. Only :func:`execute_approved_crm_assistant_tool`, running after a
        human approved the pending action, passes it.
        """

        metadata = self.tool_metadata.get(function_name)
        if metadata is None:
            self.log.warning("unknown_tool_called", function_name=function_name)
            return unknown_tool(function_name)

        arguments, forged_flags = self._strip_approval_flags(arguments)
        if forged_flags and not approval_granted:
            self.log.warning(
                "crm_assistant_approval_flag_ignored",
                function_name=function_name,
                flags=forged_flags,
                requires_approval=metadata.requires_approval,
            )

        try:
            if metadata.requires_approval and not approval_granted:
                return await self._queue_pending_action(metadata, arguments)
            return await metadata.handler(arguments)
        except (KeyError, TypeError, ValueError) as exc:
            # Bad tool arguments: the model can fix these itself, so name the
            # offending field. Exception text is logged, never returned.
            self.log.warning(
                "tool_argument_error",
                function_name=function_name,
                error_type=type(exc).__name__,
                exc_info=True,
            )
            return invalid_argument(
                f"{function_name} rejected the arguments it was given.",
                "Check the required parameters in the tool schema and call it again.",
            )
        except SQLAlchemyError:
            self.log.exception("tool_database_error", function_name=function_name)
            return unavailable(
                "The database is not reachable right now.",
                "Tell the operator to try again shortly; do not retry automatically.",
            )
        except Exception:
            self.log.exception("tool_execution_failed", function_name=function_name)
            return internal_error(function_name)
