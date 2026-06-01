"""Conversation CRM assistant tools."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.conversation import Conversation, Message
from app.services.ai.crm_assistant._agent_tools import AgentAssistantTools
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
    parse_uuid,
)


class ConversationAssistantTools:
    """Read conversations and assign AI responders."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context
        self.agent_tools = AgentAssistantTools(context)

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "assign_ai_responder": self.assign_ai_responder,
            "get_conversation": self.get_conversation,
            "list_recent_conversations": self.list_recent_conversations,
        }

    async def get_conversation_for_workspace(
        self,
        conversation_id: uuid.UUID,
    ) -> Conversation | None:
        result = await self.context.db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.workspace_id == self.context.workspace_id,
            )
        )
        return result.scalar_one_or_none()

    async def assign_ai_responder(self, args: ToolArguments) -> dict[str, object]:
        conversation_id = parse_uuid(args.get("conversation_id"))
        agent_id = parse_uuid(args.get("agent_id"))
        if conversation_id is None:
            return {"success": False, "error": "Invalid conversation_id"}
        if agent_id is None:
            return {"success": False, "error": "Invalid agent_id"}

        conversation = await self.get_conversation_for_workspace(conversation_id)
        if conversation is None:
            return {"success": False, "error": "Conversation not found"}
        agent = await self.agent_tools.get_agent_for_workspace(agent_id)
        if agent is None:
            return {"success": False, "error": "Agent not found"}

        conversation.assigned_agent_id = agent.id
        conversation.ai_enabled = args.get("ai_enabled", True)
        conversation.ai_paused = False
        conversation.ai_paused_until = None
        await self.context.db.flush()
        return {
            "success": True,
            "message": f"Assigned {agent.name} as AI responder",
            "data": {"conversation_id": str(conversation.id), "agent_id": str(agent.id)},
        }

    async def get_conversation(self, args: ToolArguments) -> dict[str, object]:
        contact_id = args["contact_id"]
        limit = min(args.get("limit", 20), 100)

        conv_result = await self.context.db.execute(
            select(Conversation)
            .where(
                Conversation.workspace_id == self.context.workspace_id,
                Conversation.contact_id == contact_id,
            )
            .order_by(Conversation.last_message_at.desc())
            .limit(1)
        )
        conversation = conv_result.scalar_one_or_none()
        if not conversation:
            return {"success": True, "data": [], "count": 0}

        msg_result = await self.context.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = msg_result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "direction": message.direction,
                    "body": message.body,
                    "channel": message.channel,
                    "created_at": message.created_at.isoformat() if message.created_at else None,
                }
                for message in reversed(messages)
            ],
            "count": len(messages),
        }

    async def list_recent_conversations(self, args: ToolArguments) -> dict[str, object]:
        limit = min(args.get("limit", 10), 50)
        stmt = (
            select(Conversation)
            .where(Conversation.workspace_id == self.context.workspace_id)
            .order_by(Conversation.last_message_at.desc())
            .limit(limit)
        )
        result = await self.context.db.execute(stmt)
        conversations = result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "id": str(conversation.id),
                    "contact_phone": conversation.contact_phone,
                    "last_message": conversation.last_message_preview,
                    "last_message_at": (
                        conversation.last_message_at.isoformat()
                        if conversation.last_message_at
                        else None
                    ),
                    "unread_count": conversation.unread_count,
                }
                for conversation in conversations
            ],
            "count": len(conversations),
        }
