"""Voice call read tools for the CRM assistant.

A call is a ``Message`` row with ``channel == "voice"``; workspace ownership
lives on its ``Conversation``, so every query here joins and scopes through it
exactly as ``/calls`` does.

Read-only. Placing or hanging up a call spends money and reaches a customer, so
those stay on the HTTP surface.

Two disclosure rules govern this module:

- ``recording_url`` is **never** returned. It is an ``EncryptedString`` on the
  model — a direct link to the call audio. Tool results become model context and
  the model can compose outbound SMS, so a recording link in context is one
  hallucinated paraphrase away from being texted to the wrong person. Operators
  open the recording in the app instead.
- ``transcript`` and captured-message text **are** returned, because they are the
  answer to "what happened on the call" — but they are the customer's own words,
  i.e. untrusted input reaching the model. They are length-bounded here, and the
  system prompt instructs the model to treat them as data, never instructions.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from app.db.scope import apply_workspace_scope
from app.models.conversation import Conversation, Message, MessageDirection
from app.services.ai.crm_assistant._pagination import count_matching, listing, parse_limit
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
    parse_uuid,
)
from app.services.ai.crm_assistant._tool_errors import invalid_argument, invalid_id, not_found

# Transcripts are unbounded customer speech. A long call can run to tens of
# thousands of characters, which would crowd out the rest of the context window,
# so a single transcript is capped and explicitly marked when it was cut.
_MAX_TRANSCRIPT_CHARS = 6_000
_MAX_CAPTURE_CHARS = 1_000

_DIRECTIONS = frozenset(direction.value for direction in MessageDirection)


def _clip(text: str | None, maximum: int) -> tuple[str | None, bool]:
    """Bound untrusted text, reporting whether it was truncated."""

    if text is None:
        return None, False
    if len(text) <= maximum:
        return text, False
    return text[:maximum], True


class CallAssistantTools:
    """Read the workspace's voice call history."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_calls": self.list_calls,
            "get_call": self.get_call,
        }

    def _scoped_calls(self) -> Any:
        """Base query: voice messages owned by this workspace, newest first.

        The workspace filter is applied to ``Conversation`` (which holds the
        column) rather than to ``Message``, so it cannot be accidentally
        satisfied by a message id alone.
        """
        return apply_workspace_scope(
            select(Message).join(Conversation, Message.conversation_id == Conversation.id),
            Conversation,
            self.context.workspace_id,
        ).where(Message.channel == "voice")

    @staticmethod
    def _summary(message: Message) -> dict[str, Any]:
        """One row for a call list: outcome and metadata, no transcript."""
        conversation = message.conversation
        contact = conversation.contact if conversation else None
        return {
            "call_id": str(message.id),
            "direction": message.direction,
            "status": message.status,
            "duration_seconds": message.duration_seconds,
            "is_ai": message.is_ai,
            "booking_outcome": message.booking_outcome,
            "contact_id": conversation.contact_id if conversation else None,
            "contact_name": contact.full_name if contact else None,
            "agent_name": message.agent.name if message.agent else None,
            "created_at": message.created_at.isoformat() if message.created_at else None,
        }

    async def list_calls(self, args: ToolArguments) -> dict[str, object]:
        limit = parse_limit(args.get("limit"), default=10, maximum=50)
        if limit is None:
            return invalid_argument("limit must be an integer between 1 and 50.")

        contact_id = args.get("contact_id")
        if contact_id is not None and (
            isinstance(contact_id, bool) or not isinstance(contact_id, int)
        ):
            return invalid_argument("contact_id must be an integer contact id.")

        direction = args.get("direction")
        if direction is not None and direction not in _DIRECTIONS:
            return invalid_argument(
                "direction must be inbound or outbound.",
                f"Use one of: {', '.join(sorted(_DIRECTIONS))}.",
            )

        status = args.get("status")
        if status is not None and not isinstance(status, str):
            return invalid_argument("status must be a string.")

        booked_only = args.get("booked_only")
        if booked_only is not None and not isinstance(booked_only, bool):
            return invalid_argument("booked_only must be a boolean.")

        query = self._scoped_calls()
        if contact_id is not None:
            query = query.where(Conversation.contact_id == contact_id)
        if direction is not None:
            query = query.where(Message.direction == direction)
        if status is not None:
            query = query.where(Message.status == status)
        if booked_only:
            query = query.where(Message.booking_outcome.is_not(None))

        total = await count_matching(self.context.db, Message, query)
        result = await self.context.db.execute(
            query.options(
                joinedload(Message.conversation).joinedload(Conversation.contact),
                joinedload(Message.agent),
            )
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        calls = result.unique().scalars().all()
        return listing([self._summary(call) for call in calls], total=total)

    async def get_call(self, args: ToolArguments) -> dict[str, object]:
        call_id = parse_uuid(args.get("call_id"))
        if call_id is None:
            return invalid_id("call_id", "Call list_calls to get a valid call id.")

        result = await self.context.db.execute(
            self._scoped_calls()
            .where(Message.id == call_id)
            .options(
                joinedload(Message.conversation).joinedload(Conversation.contact),
                joinedload(Message.agent),
                selectinload(Message.phone_messages),
            )
        )
        call = result.unique().scalar_one_or_none()
        if call is None:
            # A call in another workspace is indistinguishable from a missing
            # one, so an id cannot be used to probe for existence.
            return not_found("Call", "Call list_calls to get a visible id.")

        transcript, transcript_truncated = _clip(call.transcript, _MAX_TRANSCRIPT_CHARS)
        data = self._summary(call)
        data.update(
            {
                "conversation_id": str(call.conversation_id) if call.conversation_id else None,
                "transcript": transcript,
                "transcript_truncated": transcript_truncated,
                "captured_messages": self._captures(call),
                # recording_url is deliberately omitted; see the module docstring.
                "recording_available": call.recording_url is not None,
            }
        )
        return {"success": True, "data": data}

    @staticmethod
    def _captures(call: Message) -> list[dict[str, Any]]:
        """Take-a-message records the voice agent captured during the call."""
        captures = getattr(call, "phone_messages", None) or []
        rows = []
        for capture in sorted(captures, key=lambda item: item.created_at):
            body, truncated = _clip(capture.message_body, _MAX_CAPTURE_CHARS)
            rows.append(
                {
                    "caller_name": capture.caller_name,
                    "callback_number": capture.callback_number,
                    "reason": capture.reason,
                    "urgency": str(capture.urgency),
                    "preferred_callback_time": capture.preferred_callback_time,
                    "status": str(capture.status),
                    "message_body": body,
                    "message_body_truncated": truncated,
                    "created_at": capture.created_at.isoformat() if capture.created_at else None,
                }
            )
        return rows
