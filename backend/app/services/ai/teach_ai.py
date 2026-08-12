"""Create workspace-scoped, human-approved corrections for AI text replies."""

import re
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.agent_training_example import AgentTrainingExample
from app.models.conversation import Conversation, Message, MessageDirection
from app.models.outbound_action_audit_log import OutboundActionAuditLog


@dataclass(frozen=True, slots=True)
class SavedTrainingExample:
    """Saved lesson plus non-sensitive display metadata."""

    example: AgentTrainingExample
    agent_name: str


def _materially_equal(left: str, right: str) -> bool:
    """Ignore casing, whitespace, and punctuation-only edits."""
    normalized_left = re.sub(r"[^a-z0-9]+", "", left.casefold())
    normalized_right = re.sub(r"[^a-z0-9]+", "", right.casefold())
    return normalized_left == normalized_right


async def save_training_example(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    source_message_id: uuid.UUID,
    ideal_response: str,
    note: str | None,
    user_id: int,
) -> SavedTrainingExample:
    """Validate and upsert one approved correction without logging its bodies."""
    conversation_result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.workspace_id == workspace_id,
        )
    )
    conversation = conversation_result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    source_result = await db.execute(
        select(Message, Agent)
        .join(Agent, Agent.id == Message.agent_id)
        .where(
            Message.id == source_message_id,
            Message.conversation_id == conversation_id,
            Message.direction == MessageDirection.OUTBOUND,
            Message.is_ai.is_(True),
            Agent.workspace_id == workspace_id,
        )
    )
    source_row = source_result.one_or_none()
    if source_row is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Source message must be an AI-generated outbound reply from this conversation",
        )
    source_message, agent = source_row

    if _materially_equal(source_message.body, ideal_response):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Ideal response must materially differ from the AI reply",
        )

    inbound_result = await db.execute(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.direction == MessageDirection.INBOUND,
            Message.created_at < source_message.created_at,
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    customer_message = inbound_result.scalar_one_or_none()
    if customer_message is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No prior customer message exists for this AI reply",
        )

    existing_result = await db.execute(
        select(AgentTrainingExample).where(
            AgentTrainingExample.source_message_id == source_message_id
        )
    )
    example = existing_result.scalar_one_or_none()
    is_update = example is not None
    if example is None:
        example = AgentTrainingExample(
            workspace_id=workspace_id,
            agent_id=agent.id,
            conversation_id=conversation_id,
            source_message_id=source_message_id,
            created_by_user_id=user_id,
            customer_message=customer_message.body,
            ai_response=source_message.body,
            ideal_response=ideal_response,
            operator_note=note,
            is_active=True,
        )
        db.add(example)
    else:
        # Workspace/agent are derived from the validated source message, never the client.
        example.workspace_id = workspace_id
        example.agent_id = agent.id
        example.conversation_id = conversation_id
        example.created_by_user_id = user_id
        example.customer_message = customer_message.body
        example.ai_response = source_message.body
        example.ideal_response = ideal_response
        example.operator_note = note
        example.is_active = True

    await db.flush()
    db.add(
        OutboundActionAuditLog(
            workspace_id=workspace_id,
            agent_id=agent.id,
            action_type="teach_ai_correction_saved",
            action_payload={
                "training_example_id": str(example.id),
                "conversation_id": str(conversation_id),
                "source_message_id": str(source_message_id),
                "operation": "updated" if is_update else "created",
            },
            compliance_result={"message_bodies_logged": False},
            decision="approved",
            reason="Human-approved agent guidance",
            source="conversation_teach_ai",
            actor_user_id=user_id,
            contact_id=conversation.contact_id,
            message_id=source_message_id,
        )
    )
    await db.commit()
    await db.refresh(example)
    return SavedTrainingExample(example=example, agent_name=agent.name)
