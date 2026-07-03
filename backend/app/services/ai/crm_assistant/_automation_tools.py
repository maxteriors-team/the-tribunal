"""Automation (workflow) CRM assistant tools."""

from __future__ import annotations

import uuid
from typing import Any

from app.db.scope import get_workspace_owned, select_workspace_owned
from app.models.automation import Automation
from app.schemas.automation import AutomationCreate
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
    parse_uuid,
    without_confirmation,
)


class AutomationAssistantTools:
    """Read, create, and toggle event-triggered workflow automations."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_automations": self.list_automations,
            "create_automation": self.create_automation,
            "enable_automation": self.enable_automation,
            "disable_automation": self.disable_automation,
        }

    @staticmethod
    def serialize_automation(automation: Automation) -> dict[str, Any]:
        return {
            "id": str(automation.id),
            "name": automation.name,
            "description": automation.description,
            "trigger_type": automation.trigger_type,
            "trigger_config": automation.trigger_config,
            "actions": automation.actions,
            "is_active": automation.is_active,
            "last_triggered_at": (
                automation.last_triggered_at.isoformat() if automation.last_triggered_at else None
            ),
            "created_at": automation.created_at.isoformat() if automation.created_at else None,
        }

    async def get_automation_for_workspace(self, automation_id: uuid.UUID) -> Automation | None:
        return await get_workspace_owned(
            self.context.db,
            Automation,
            automation_id,
            self.context.workspace_id,
        )

    async def list_automations(self, args: ToolArguments) -> dict[str, object]:
        limit = min(args.get("limit", 10), 50)
        stmt = (
            select_workspace_owned(Automation, self.context.workspace_id)
            .order_by(Automation.created_at.desc())
            .limit(limit)
        )
        if args.get("active_only"):
            stmt = stmt.where(Automation.is_active.is_(True))

        result = await self.context.db.execute(stmt)
        automations = result.scalars().all()

        return {
            "success": True,
            "data": [self.serialize_automation(a) for a in automations],
            "count": len(automations),
        }

    async def create_automation(self, args: ToolArguments) -> dict[str, object]:
        try:
            automation_in = AutomationCreate(**without_confirmation(args))
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        if not automation_in.actions:
            return {"success": False, "error": "Automation needs at least one action"}

        automation = Automation(
            workspace_id=self.context.workspace_id,
            **automation_in.model_dump(mode="json"),
        )
        self.context.db.add(automation)
        await self.context.db.flush()

        return {"success": True, "data": self.serialize_automation(automation)}

    async def enable_automation(self, args: ToolArguments) -> dict[str, object]:
        return await self._set_active(args, is_active=True)

    async def disable_automation(self, args: ToolArguments) -> dict[str, object]:
        return await self._set_active(args, is_active=False)

    async def _set_active(self, args: ToolArguments, *, is_active: bool) -> dict[str, object]:
        automation_id = parse_uuid(args.get("automation_id"))
        if automation_id is None:
            return {"success": False, "error": "Invalid automation_id"}

        automation = await self.get_automation_for_workspace(automation_id)
        if automation is None:
            return {"success": False, "error": "Automation not found"}

        automation.is_active = is_active
        await self.context.db.flush()

        return {"success": True, "data": self.serialize_automation(automation)}
