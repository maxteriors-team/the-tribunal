""" "What is waiting on me" read tools for the CRM assistant.

Two queues an operator is expected to work: actions the AI has parked for human
approval, and nudges raised for a person to follow up.

Read-only, deliberately. Approving a pending action is the human half of the
approval gate that guards every risky tool in this assistant -- letting the
model clear its own queue would make that gate decorative. The assistant can
tell you what is waiting; you approve it in the app.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, or_, select

from app.core.permissions import Capability, role_can
from app.db.scope import select_workspace_owned
from app.models.human_nudge import HumanNudge
from app.models.pending_action import PendingAction
from app.services.ai.crm_assistant._pagination import count_matching, listing, parse_limit
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
)
from app.services.ai.crm_assistant._tool_errors import invalid_argument

_MAX_SUMMARY_CHARS = 500


class QueueAssistantTools:
    """Read the approval queue and the nudge queue."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_pending_actions": self.list_pending_actions,
            "list_nudges": self.list_nudges,
        }

    async def list_pending_actions(self, args: ToolArguments) -> dict[str, object]:
        limit = parse_limit(args.get("limit"), default=10, maximum=50)
        if limit is None:
            return invalid_argument("limit must be an integer between 1 and 50.")

        status = args.get("status", "pending")
        if status is not None and not isinstance(status, str):
            return invalid_argument("status must be a string.")

        query = select_workspace_owned(PendingAction, self.context.workspace_id)
        if status is not None:
            query = query.where(PendingAction.status == status)

        total = await count_matching(self.context.db, PendingAction, query)
        result = await self.context.db.execute(
            query.order_by(PendingAction.created_at.desc()).limit(limit)
        )
        actions = result.scalars().all()
        return listing(
            [
                {
                    "id": str(action.id),
                    "action_type": action.action_type,
                    "status": action.status,
                    "urgency": action.urgency,
                    # The human-readable summary. ``action_payload`` is omitted:
                    # it holds the drafted message body, which the operator
                    # should approve in the app rather than have paraphrased.
                    "description": (action.description or "")[:_MAX_SUMMARY_CHARS] or None,
                    "expires_at": action.expires_at.isoformat() if action.expires_at else None,
                    "created_at": action.created_at.isoformat() if action.created_at else None,
                }
                for action in actions
            ],
            total=total,
        )

    def _nudge_visibility(self) -> Any:
        """The caller's nudge scope, mirroring ``_nudge_visibility`` on the route.

        A nudge is personal work: you see the ones assigned to you, and only a
        ``crm:write`` tier additionally sees unassigned legacy rows. Re-deriving
        this rule instead of reusing its shape is how the assistant would quietly
        become a way to read a colleague's queue.
        """
        assignment = HumanNudge.assigned_to_user_id == self.context.user_id
        if role_can(self.context.role, Capability.CRM_WRITE):
            assignment = or_(assignment, HumanNudge.assigned_to_user_id.is_(None))
        return and_(HumanNudge.workspace_id == self.context.workspace_id, assignment)

    async def list_nudges(self, args: ToolArguments) -> dict[str, object]:
        limit = parse_limit(args.get("limit"), default=10, maximum=50)
        if limit is None:
            return invalid_argument("limit must be an integer between 1 and 50.")

        status = args.get("status", "pending")
        if status is not None and not isinstance(status, str):
            return invalid_argument("status must be a string.")

        priority = args.get("priority")
        if priority is not None and not isinstance(priority, str):
            return invalid_argument("priority must be a string.")

        query = select(HumanNudge).where(self._nudge_visibility())
        if status is not None:
            query = query.where(HumanNudge.status == status)
        if priority is not None:
            query = query.where(HumanNudge.priority == priority)

        total = await count_matching(self.context.db, HumanNudge, query)
        result = await self.context.db.execute(
            query.order_by(HumanNudge.created_at.desc()).limit(limit)
        )
        nudges = result.scalars().all()
        return listing(
            [
                {
                    "id": str(nudge.id),
                    "nudge_type": nudge.nudge_type,
                    "status": nudge.status,
                    "priority": nudge.priority,
                    "contact_id": nudge.contact_id,
                    "title": nudge.title,
                    # Nudge copy is generated from CRM data; bound it so a long
                    # queue cannot crowd out the rest of the context window.
                    "message": (nudge.message or "")[:_MAX_SUMMARY_CHARS] or None,
                    "suggested_action": nudge.suggested_action,
                    "due_date": nudge.due_date.isoformat() if nudge.due_date else None,
                    "created_at": nudge.created_at.isoformat() if nudge.created_at else None,
                }
                for nudge in nudges
            ],
            total=total,
        )
