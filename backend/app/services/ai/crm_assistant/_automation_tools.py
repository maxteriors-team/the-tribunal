"""Automation (workflow) CRM assistant tools."""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from app.db.scope import get_workspace_owned, select_workspace_owned
from app.models.agent import Agent
from app.models.automation import Automation
from app.models.campaign import Campaign
from app.models.drip_campaign import DripCampaign
from app.models.pipeline import Pipeline, PipelineStage
from app.models.tag import Tag
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
    conflict,
    invalid_argument,
    invalid_id,
    not_found,
    validation_failed,
)
from app.services.ai.crm_assistant._tools import (
    CRM_ASSISTANT_AUTOMATION_ACTION_TYPES,
    CRM_ASSISTANT_AUTOMATION_TRIGGER_TYPES,
)
from app.services.automations.runner import GOTO_END, MAX_WAIT
from app.services.contacts.contact_filter_validation import validate_contact_filter_rules


class AutomationWorkflowValidationError(ValueError):
    """An assistant-authored automation is not executable as supplied."""


_STEP_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_TARGET_PATTERN = re.compile(r"^(?:__end__|[A-Za-z][A-Za-z0-9_-]{0,63})$")
_MAX_TEMPLATE_LENGTH = 20_000


def _text(value: object, label: str, *, maximum: int = _MAX_TEMPLATE_LENGTH) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise AutomationWorkflowValidationError(
            f"{label} must be a non-empty string of at most {maximum:,} characters"
        )
    return value.strip()


def _uuid_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise AutomationWorkflowValidationError(f"{label} must be a UUID")
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise AutomationWorkflowValidationError(f"{label} must be a UUID") from exc


def _exact_config(
    raw: object,
    label: str,
    *,
    allowed: set[str],
    required: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise AutomationWorkflowValidationError(f"{label} config must be an object")
    extras = set(raw) - allowed
    missing = required - set(raw)
    if extras:
        raise AutomationWorkflowValidationError(f"{label} config has unsupported fields")
    if missing:
        raise AutomationWorkflowValidationError(f"{label} config is missing required fields")
    return dict(raw)


def _fallbacks(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or len(value) > 50:
        raise AutomationWorkflowValidationError(f"{label} fallbacks must be an object")
    normalized: dict[str, str] = {}
    for key, fallback in value.items():
        if not isinstance(key, str) or not key or len(key) > 100:
            raise AutomationWorkflowValidationError(f"{label} has an invalid fallback key")
        if not isinstance(fallback, str) or len(fallback) > 500:
            raise AutomationWorkflowValidationError(f"{label} has an invalid fallback value")
        normalized[key] = fallback
    return normalized


def _validate_message_config(raw: object, *, email: bool) -> dict[str, Any]:
    label = "send_email" if email else "send_sms"
    allowed = (
        {"subject", "message", "fallbacks"}
        if email
        else {
            "message",
            "agent_id",
            "require_consent",
            "fallbacks",
        }
    )
    required = {"subject", "message"} if email else {"message"}
    config = _exact_config(raw, label, allowed=allowed, required=required)
    normalized: dict[str, Any] = {
        "message": _text(config["message"], f"{label}.message"),
    }
    if email:
        normalized["subject"] = _text(config["subject"], f"{label}.subject", maximum=1_000)
    if "agent_id" in config:
        normalized["agent_id"] = _uuid_text(config["agent_id"], f"{label}.agent_id")
    if "require_consent" in config:
        if not isinstance(config["require_consent"], bool):
            raise AutomationWorkflowValidationError("send_sms.require_consent must be a boolean")
        normalized["require_consent"] = config["require_consent"]
    if "fallbacks" in config:
        normalized["fallbacks"] = _fallbacks(config["fallbacks"], label)
    return normalized


def _validate_wait_config(raw: object) -> dict[str, int]:
    config = _exact_config(
        raw,
        "wait",
        allowed={"minutes", "hours", "days"},
    )
    if len(config) != 1:
        raise AutomationWorkflowValidationError("wait requires exactly one duration unit")
    unit, value = next(iter(config.items()))
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AutomationWorkflowValidationError("wait duration must be a positive integer")
    try:
        duration = timedelta(**{unit: value})
    except OverflowError as exc:
        raise AutomationWorkflowValidationError("wait duration exceeds 365 days") from exc
    if duration > MAX_WAIT:
        raise AutomationWorkflowValidationError("wait duration exceeds 365 days")
    return {unit: value}


def _validate_branch_config(raw: object) -> dict[str, Any]:
    config = _exact_config(
        raw,
        "branch",
        allowed={"condition", "then_goto", "else_goto"},
        required={"condition", "then_goto", "else_goto"},
    )
    condition = _exact_config(
        config["condition"],
        "branch.condition",
        allowed={"rules", "logic"},
        required={"rules"},
    )
    rules, logic = validate_contact_filter_rules(condition["rules"], condition.get("logic", "and"))
    normalized: dict[str, Any] = {
        "condition": {"rules": rules, "logic": logic},
    }
    for key in ("then_goto", "else_goto"):
        target = config[key]
        if not isinstance(target, str) or not _TARGET_PATTERN.fullmatch(target):
            raise AutomationWorkflowValidationError(f"branch.{key} must name a valid step id")
        normalized[key] = target
    return normalized


def _validate_make_call_config(raw: object) -> dict[str, Any]:
    config = _exact_config(raw, "make_call", allowed={"agent_id"})
    return (
        {"agent_id": _uuid_text(config["agent_id"], "make_call.agent_id")}
        if "agent_id" in config
        else {}
    )


def _validate_campaign_config(raw: object) -> dict[str, Any]:
    config = _exact_config(
        raw, "enroll_campaign", allowed={"campaign_id"}, required={"campaign_id"}
    )
    return {"campaign_id": _uuid_text(config["campaign_id"], "campaign_id")}


def _validate_drip_config(raw: object) -> dict[str, Any]:
    config = _exact_config(
        raw,
        "start_drip_campaign",
        allowed={"drip_campaign_id", "enroll_contact"},
        required={"drip_campaign_id"},
    )
    normalized: dict[str, Any] = {
        "drip_campaign_id": _uuid_text(config["drip_campaign_id"], "drip_campaign_id")
    }
    if "enroll_contact" in config:
        if not isinstance(config["enroll_contact"], bool):
            raise AutomationWorkflowValidationError(
                "start_drip_campaign.enroll_contact must be a boolean"
            )
        normalized["enroll_contact"] = config["enroll_contact"]
    return normalized


def _validate_stage_config(raw: object) -> dict[str, Any]:
    config = _exact_config(
        raw,
        "move_to_stage",
        allowed={"stage_id", "pipeline_id"},
        required={"stage_id"},
    )
    normalized = {"stage_id": _uuid_text(config["stage_id"], "stage_id")}
    if "pipeline_id" in config:
        normalized["pipeline_id"] = _uuid_text(config["pipeline_id"], "pipeline_id")
    return normalized


def _validate_tag_config(raw: object) -> dict[str, Any]:
    config = _exact_config(raw, "apply_tag", allowed={"tag"}, required={"tag"})
    return {"tag": _text(config["tag"], "apply_tag.tag", maximum=100)}


_ACTION_CONFIG_VALIDATORS: dict[str, Callable[[object], dict[str, Any]]] = {
    "send_sms": lambda raw: _validate_message_config(raw, email=False),
    "send_email": lambda raw: _validate_message_config(raw, email=True),
    "make_call": _validate_make_call_config,
    "enroll_campaign": _validate_campaign_config,
    "start_drip_campaign": _validate_drip_config,
    "move_to_stage": _validate_stage_config,
    "apply_tag": _validate_tag_config,
    "wait": _validate_wait_config,
    "branch": _validate_branch_config,
}


def _validate_action_config(action_type: str, raw: object) -> dict[str, Any]:
    validator = _ACTION_CONFIG_VALIDATORS.get(action_type)
    if validator is None:
        raise AutomationWorkflowValidationError("Automation action type is unsupported")
    return validator(raw)


def _validate_actions(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 50:
        raise AutomationWorkflowValidationError("actions must contain between 1 and 50 steps")
    normalized: list[dict[str, Any]] = []
    step_ids: set[str] = set()
    for index, step in enumerate(raw, start=1):
        if not isinstance(step, dict) or set(step) - {"id", "type", "config"}:
            raise AutomationWorkflowValidationError(f"Action {index} has unsupported fields")
        action_type = step.get("type")
        if (
            not isinstance(action_type, str)
            or action_type not in CRM_ASSISTANT_AUTOMATION_ACTION_TYPES
        ):
            raise AutomationWorkflowValidationError(f"Action {index} type is unsupported")
        normalized_step: dict[str, Any] = {
            "type": action_type,
            "config": _validate_action_config(action_type, step.get("config")),
        }
        if "id" in step:
            step_id = step["id"]
            if not isinstance(step_id, str) or not _STEP_ID_PATTERN.fullmatch(step_id):
                raise AutomationWorkflowValidationError(f"Action {index} has an invalid step id")
            if step_id in step_ids:
                raise AutomationWorkflowValidationError("Automation step ids must be unique")
            step_ids.add(step_id)
            normalized_step["id"] = step_id
        normalized.append(normalized_step)
    _validate_control_flow(normalized)
    return normalized


def _validate_control_flow(actions: list[dict[str, Any]]) -> None:
    id_to_index = {step["id"]: index for index, step in enumerate(actions) if "id" in step}
    graph: dict[int, set[int]] = {index: set() for index in range(len(actions))}
    for index, step in enumerate(actions):
        if step["type"] == "branch":
            for key in ("then_goto", "else_goto"):
                target = step["config"][key]
                if target == GOTO_END:
                    continue
                if target not in id_to_index:
                    raise AutomationWorkflowValidationError("Branch target step was not found")
                graph[index].add(id_to_index[target])
        elif index + 1 < len(actions):
            graph[index].add(index + 1)

    state = [0] * len(actions)

    def visit(node: int) -> None:
        if state[node] == 1:
            raise AutomationWorkflowValidationError("Automation control flow cannot contain cycles")
        if state[node] == 2:
            return
        state[node] = 1
        for neighbor in graph[node]:
            visit(neighbor)
        state[node] = 2

    for node in graph:
        visit(node)


def _validate_trigger(trigger_type: object, raw: object) -> tuple[str, dict[str, Any]]:
    if (
        not isinstance(trigger_type, str)
        or trigger_type not in CRM_ASSISTANT_AUTOMATION_TRIGGER_TYPES
    ):
        raise AutomationWorkflowValidationError("Automation trigger type is unsupported")
    if trigger_type == "contact_tagged":
        config = _exact_config(raw, trigger_type, allowed={"tag"}, required={"tag"})
        return trigger_type, {"tag": _text(config["tag"], "contact_tagged.tag", maximum=100)}
    if trigger_type == "never_booked":
        config = _exact_config(raw, trigger_type, allowed={"inactivity_days"})
        if "inactivity_days" in config:
            days = config["inactivity_days"]
            if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 3_650:
                raise AutomationWorkflowValidationError(
                    "never_booked.inactivity_days must be between 1 and 3650"
                )
        return trigger_type, config
    if trigger_type == "backlog_below_threshold":
        config = _exact_config(
            raw,
            trigger_type,
            allowed={"threshold_weeks", "cooldown_days"},
            required={"threshold_weeks", "cooldown_days"},
        )
        threshold = config["threshold_weeks"]
        cooldown = config["cooldown_days"]
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, int | float)
            or (isinstance(threshold, float) and not math.isfinite(threshold))
            or not 0 < threshold <= 104
        ):
            raise AutomationWorkflowValidationError(
                "backlog_below_threshold.threshold_weeks must be between 0 and 104"
            )
        if isinstance(cooldown, bool) or not isinstance(cooldown, int) or not 1 <= cooldown <= 365:
            raise AutomationWorkflowValidationError(
                "backlog_below_threshold.cooldown_days must be between 1 and 365"
            )
        return trigger_type, config
    if trigger_type == "lead_created":
        config = _exact_config(
            raw,
            trigger_type,
            allowed={"lead_source_public_key", "lead_source_id", "source_detail"},
        )
        normalized = {
            key: _text(value, f"lead_created.{key}", maximum=255) for key, value in config.items()
        }
        if "lead_source_id" in normalized:
            normalized["lead_source_id"] = _uuid_text(
                normalized["lead_source_id"], "lead_created.lead_source_id"
            )
        return trigger_type, normalized
    if trigger_type == "job_completed":
        config = _exact_config(raw, trigger_type, allowed={"lighting_project_only"})
        if "lighting_project_only" in config and not isinstance(
            config["lighting_project_only"], bool
        ):
            raise AutomationWorkflowValidationError(
                "job_completed.lighting_project_only must be a boolean"
            )
        return trigger_type, config
    config = _exact_config(raw, trigger_type, allowed=set())
    return trigger_type, config


class _AutomationInputError(ValueError):
    def __init__(self, response: dict[str, object]) -> None:
        super().__init__()
        self.response = response


def _automation_update_payload(
    args: ToolArguments, automation: Automation
) -> tuple[dict[str, Any], list[dict[str, Any]], str | None, dict[str, Any] | None]:
    payload = {
        key: value for key, value in without_confirmation(args).items() if key != "automation_id"
    }
    allowed = {"name", "description", "trigger_type", "trigger_config", "actions"}
    if set(payload) - allowed:
        raise _AutomationInputError(
            invalid_argument(
                "Update automation received unsupported fields.",
                "Use enable_automation or disable_automation to change active state.",
            )
        )
    if not payload:
        raise _AutomationInputError(
            invalid_argument(
                "No automation changes were provided.",
                "Provide at least one field to update.",
            )
        )
    if automation.is_active:
        raise _AutomationInputError(
            conflict(
                "Active automations cannot be edited.",
                "Disable the automation, edit the inactive draft, then enable it separately.",
            )
        )

    actions: list[dict[str, Any]] | None = None
    try:
        if "actions" in payload:
            actions = _validate_actions(payload["actions"])
            payload["actions"] = actions
        automation_in = AutomationUpdate(**payload)
    except AutomationWorkflowValidationError as exc:
        raise _AutomationInputError(validation_failed("Automation update", str(exc))) from exc
    except ValueError as exc:
        raise _AutomationInputError(
            validation_failed(
                "Automation update", "Fields did not match the required automation shape."
            )
        ) from exc

    update_data = automation_in.model_dump(mode="json", exclude_unset=True)
    non_nullable_fields = {"name", "trigger_type", "trigger_config", "actions"}
    cleared_fields = sorted(
        field
        for field in non_nullable_fields
        if field in update_data and update_data[field] is None
    )
    if cleared_fields:
        raise _AutomationInputError(
            invalid_argument(
                f"Automation fields cannot be null: {', '.join(cleared_fields)}.",
                "Omit fields that should remain unchanged.",
            )
        )

    trigger_type: str | None = None
    trigger_config: dict[str, Any] | None = None
    try:
        if "trigger_type" in update_data or "trigger_config" in update_data:
            trigger_type, trigger_config = _validate_trigger(
                update_data.get("trigger_type", automation.trigger_type),
                update_data.get("trigger_config", automation.trigger_config),
            )
            update_data["trigger_type"] = trigger_type
            update_data["trigger_config"] = trigger_config
    except AutomationWorkflowValidationError as exc:
        raise _AutomationInputError(validation_failed("Automation update", str(exc))) from exc
    except ValueError as exc:
        raise _AutomationInputError(
            validation_failed("Automation update", "Contact filter rules are invalid.")
        ) from exc
    if actions is not None:
        update_data["actions"] = actions
    return update_data, actions or [], trigger_type, trigger_config


def _collect_action_references(
    actions: list[dict[str, Any]],
) -> dict[str, set[uuid.UUID]]:
    references: dict[str, set[uuid.UUID]] = {
        "agents": set(),
        "campaigns": set(),
        "drips": set(),
        "pipelines": set(),
        "stages": set(),
        "tags": set(),
    }
    for action in actions:
        config = action["config"]
        action_type = action["type"]
        if action_type in {"send_sms", "make_call"} and config.get("agent_id"):
            references["agents"].add(uuid.UUID(config["agent_id"]))
        elif action_type == "enroll_campaign":
            references["campaigns"].add(uuid.UUID(config["campaign_id"]))
        elif action_type == "start_drip_campaign":
            references["drips"].add(uuid.UUID(config["drip_campaign_id"]))
        elif action_type == "move_to_stage":
            references["stages"].add(uuid.UUID(config["stage_id"]))
            if config.get("pipeline_id"):
                references["pipelines"].add(uuid.UUID(config["pipeline_id"]))
        elif action_type == "branch":
            references["tags"].update(
                uuid.UUID(value)
                for rule in config["condition"]["rules"]
                if rule["field"] == "tags"
                for value in rule["value"]
            )
    return references


def _stage_pipeline_mismatch(
    actions: list[dict[str, Any]], stage_map: dict[uuid.UUID, uuid.UUID]
) -> bool:
    return any(
        action["type"] == "move_to_stage"
        and action["config"].get("pipeline_id")
        and stage_map[uuid.UUID(action["config"]["stage_id"])]
        != uuid.UUID(action["config"]["pipeline_id"])
        for action in actions
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
        payload = without_confirmation(args)
        allowed = {"name", "description", "trigger_type", "trigger_config", "actions"}
        if set(payload) - allowed:
            return invalid_argument(
                "Create automation received unsupported fields.",
                "Activation is separate; create the inactive draft first.",
            )
        try:
            trigger_type, trigger_config = _validate_trigger(
                payload.get("trigger_type"), payload.get("trigger_config", {})
            )
            actions = _validate_actions(payload.get("actions"))
        except AutomationWorkflowValidationError as exc:
            return validation_failed("Automation", str(exc))
        except ValueError:
            return validation_failed("Automation", "Contact filter rules are invalid.")

        resource_error = await self._validate_references(
            actions,
            trigger_type=trigger_type,
            trigger_config=trigger_config,
        )
        if resource_error is not None:
            return resource_error

        payload.update(
            {
                "trigger_type": trigger_type,
                "trigger_config": trigger_config,
                "actions": actions,
                "is_active": False,
            }
        )
        try:
            automation_in = AutomationCreate(**payload)
        except ValueError:
            return validation_failed(
                "Automation", "Fields did not match the required automation shape."
            )

        data = automation_in.model_dump(mode="json")
        data["actions"] = actions
        data["is_active"] = False
        automation = Automation(workspace_id=self.context.workspace_id, **data)
        self.context.db.add(automation)
        await self.context.db.flush()
        return {"success": True, "data": self.serialize_automation(automation)}

    async def update_automation(self, args: ToolArguments) -> dict[str, object]:
        automation_id = parse_uuid(args.get("automation_id"))
        if automation_id is None:
            return invalid_id("automation_id", "Call list_automations to get a valid id.")

        automation = await self.get_automation_for_workspace(automation_id)
        if automation is None:
            return not_found("Automation", "Call list_automations to get a valid id.")
        try:
            update_data, actions, trigger_type, trigger_config = _automation_update_payload(
                args, automation
            )
        except _AutomationInputError as exc:
            return exc.response

        resource_error = await self._validate_references(
            actions,
            trigger_type=trigger_type,
            trigger_config=trigger_config,
        )
        if resource_error is not None:
            return resource_error

        for field, value in update_data.items():
            setattr(automation, field, value)
        await self.context.db.flush()
        return {"success": True, "data": self.serialize_automation(automation)}

    async def _workspace_ids(self, model: Any, ids: set[uuid.UUID]) -> set[uuid.UUID]:
        if not ids:
            return set()
        result = await self.context.db.execute(
            select(model.id).where(
                model.id.in_(ids),
                model.workspace_id == self.context.workspace_id,
            )
        )
        return set(result.scalars().all())

    async def _workspace_stage_map(self, stage_ids: set[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
        if not stage_ids:
            return {}
        result = await self.context.db.execute(
            select(PipelineStage.id, PipelineStage.pipeline_id)
            .join(Pipeline, Pipeline.id == PipelineStage.pipeline_id)
            .where(
                PipelineStage.id.in_(stage_ids),
                Pipeline.workspace_id == self.context.workspace_id,
            )
        )
        return {row[0]: row[1] for row in result.all()}

    async def _trigger_tag_exists(
        self, trigger_type: str | None, trigger_config: dict[str, Any] | None
    ) -> bool:
        if trigger_type != "contact_tagged" or trigger_config is None:
            return True
        result = await self.context.db.execute(
            select(Tag.id)
            .where(
                Tag.workspace_id == self.context.workspace_id,
                func.lower(Tag.name) == trigger_config["tag"].lower(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _validate_references(
        self,
        actions: list[dict[str, Any]],
        *,
        trigger_type: str | None,
        trigger_config: dict[str, Any] | None,
    ) -> dict[str, object] | None:
        references = _collect_action_references(actions)
        resource_models = (
            (Agent, "agents"),
            (Campaign, "campaigns"),
            (DripCampaign, "drips"),
            (Pipeline, "pipelines"),
            (Tag, "tags"),
        )
        for model, key in resource_models:
            if await self._workspace_ids(model, references[key]) != references[key]:
                return not_found(
                    "Referenced automation resource",
                    "List resources in this workspace and use one of those IDs.",
                )

        stage_map = await self._workspace_stage_map(references["stages"])
        if set(stage_map) != references["stages"]:
            return not_found(
                "Referenced automation resource",
                "List pipeline stages in this workspace and use one of those IDs.",
            )
        if _stage_pipeline_mismatch(actions, stage_map):
            return not_found(
                "Referenced automation resource",
                "Use a pipeline stage that belongs to the selected pipeline.",
            )
        if not await self._trigger_tag_exists(trigger_type, trigger_config):
            return not_found(
                "Referenced automation resource",
                "Call list_tags and use an existing workspace tag name.",
            )
        return None

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
