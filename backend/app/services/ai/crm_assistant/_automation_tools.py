"""Automation (workflow) CRM assistant tools."""

from __future__ import annotations

import uuid
from typing import Any

from app.db.scope import get_workspace_owned, select_workspace_owned
from app.models.automation import Automation
from app.schemas.automation import AutomationCreate, AutomationUpdate
from app.services.ai.crm_assistant._pagination import count_matching, listing
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
    parse_uuid,
    without_confirmation,
)
from app.services.ai.crm_assistant._tool_errors import (
    invalid_argument,
    invalid_id,
    not_found,
    validation_failed,
)


class AutomationAssistantTools:
    """Read, create, and toggle event-triggered workflow automations."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_automations": self.list_automations,
            "get_automation": self.get_automation,
            "create_automation": self.create_automation,
            "update_automation": self.update_automation,
            "delete_automation": self.delete_automation,
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
            "last_evaluated_at": (
                automation.last_evaluated_at.isoformat() if automation.last_evaluated_at else None
            ),
            "created_at": automation.created_at.isoformat() if automation.created_at else None,
            "updated_at": automation.updated_at.isoformat() if automation.updated_at else None,
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
        stmt = select_workspace_owned(Automation, self.context.workspace_id)
        if args.get("active_only"):
            stmt = stmt.where(Automation.is_active.is_(True))

        total = await count_matching(self.context.db, Automation, stmt)
        result = await self.context.db.execute(
            stmt.order_by(Automation.created_at.desc()).limit(limit)
        )
        automations = result.scalars().all()

        return listing(
            [self.serialize_automation(a) for a in automations],
            total=total,
        )

    async def get_automation(self, args: ToolArguments) -> dict[str, object]:
        automation_id = parse_uuid(args.get("automation_id"))
        if automation_id is None:
            return invalid_id("automation_id", "Call list_automations to get a valid id.")

        automation = await self.get_automation_for_workspace(automation_id)
        if automation is None:
            return not_found("Automation", "Call list_automations to get a valid id.")

        return {"success": True, "data": self.serialize_automation(automation)}

    async def create_automation(self, args: ToolArguments) -> dict[str, object]:
        try:
            automation_in = AutomationCreate(**without_confirmation(args))
        except ValueError as exc:
            return validation_failed("Automation", str(exc))

        if not automation_in.actions:
            return invalid_argument(
                "An automation needs at least one action.",
                "Add an entry to `actions` describing what should happen.",
            )

        automation = Automation(
            workspace_id=self.context.workspace_id,
            **automation_in.model_dump(mode="json"),
        )
        self.context.db.add(automation)
        await self.context.db.flush()

        return {"success": True, "data": self.serialize_automation(automation)}

    async def update_automation(self, args: ToolArguments) -> dict[str, object]:  # noqa: PLR0911
        automation_id = parse_uuid(args.get("automation_id"))
        if automation_id is None:
            return invalid_id("automation_id", "Call list_automations to get a valid id.")

        automation = await self.get_automation_for_workspace(automation_id)
        if automation is None:
            return not_found("Automation", "Call list_automations to get a valid id.")

        payload = {
            key: value
            for key, value in without_confirmation(args).items()
            if key != "automation_id"
        }
        if not payload:
            return invalid_argument(
                "No automation changes were provided.",
                "Provide at least one field to update.",
            )

        try:
            automation_in = AutomationUpdate(**payload)
        except ValueError as exc:
            return validation_failed("Automation update", str(exc))

        update_data = automation_in.model_dump(mode="json", exclude_unset=True)
        if update_data.get("actions") == []:
            return invalid_argument(
                "An automation needs at least one action.",
                "Provide the complete ordered action list.",
            )

        non_nullable_fields = {"name", "trigger_type", "trigger_config", "actions", "is_active"}
        cleared_fields = sorted(
            field
            for field in non_nullable_fields
            if field in update_data and update_data[field] is None
        )
        if cleared_fields:
            return invalid_argument(
                f"Automation fields cannot be null: {', '.join(cleared_fields)}.",
                "Omit fields that should remain unchanged.",
            )

        for field, value in update_data.items():
            setattr(automation, field, value)
        await self.context.db.flush()

        return {"success": True, "data": self.serialize_automation(automation)}

    async def delete_automation(self, args: ToolArguments) -> dict[str, object]:
        automation_id = parse_uuid(args.get("automation_id"))
        if automation_id is None:
            return invalid_id("automation_id", "Call list_automations to get a valid id.")

        automation = await self.get_automation_for_workspace(automation_id)
        if automation is None:
            return not_found("Automation", "Call list_automations to get a valid id.")

        deleted = {"id": str(automation.id), "name": automation.name, "deleted": True}
        await self.context.db.delete(automation)
        await self.context.db.flush()
        return {"success": True, "data": deleted}

    async def enable_automation(self, args: ToolArguments) -> dict[str, object]:
        return await self._set_active(args, is_active=True)

    async def disable_automation(self, args: ToolArguments) -> dict[str, object]:
        return await self._set_active(args, is_active=False)

    async def _set_active(self, args: ToolArguments, *, is_active: bool) -> dict[str, object]:
        automation_id = parse_uuid(args.get("automation_id"))
        if automation_id is None:
            return invalid_id("automation_id", "Call list_automations to get a valid id.")

        automation = await self.get_automation_for_workspace(automation_id)
        if automation is None:
            return not_found("Automation", "Call list_automations to get a valid id.")

        automation.is_active = is_active
        await self.context.db.flush()

        return {"success": True, "data": self.serialize_automation(automation)}
