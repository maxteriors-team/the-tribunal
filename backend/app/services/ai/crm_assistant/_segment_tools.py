"""Saved-audience tools for the CRM assistant."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.db.scope import get_workspace_owned, select_workspace_owned
from app.models.contact import Contact
from app.models.segment import Segment
from app.models.tag import Tag
from app.services.ai.crm_assistant._pagination import count_matching, listing
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
    parse_uuid,
)
from app.services.ai.crm_assistant._tool_errors import (
    conflict,
    invalid_argument,
    invalid_id,
    not_found,
)
from app.services.contacts.contact_filter_validation import (
    ContactFilterValidationError,
    validate_contact_filter_rules,
)
from app.services.contacts.contact_filters import apply_contact_filters


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _enum_value(value: object) -> object:
    return value.value if hasattr(value, "value") else value


def _serialize_segment(segment: Segment) -> dict[str, Any]:
    definition = segment.definition if isinstance(segment.definition, dict) else {}
    return {
        "id": str(segment.id),
        "name": segment.name,
        "description": segment.description,
        "is_dynamic": segment.is_dynamic,
        "filter_logic": definition.get("logic"),
        "filter_rules": definition.get("rules"),
        "contact_count": segment.contact_count,
        "last_computed_at": _iso(segment.last_computed_at),
        "created_at": _iso(segment.created_at),
        "updated_at": _iso(segment.updated_at),
    }


def _serialize_contact(contact: Contact) -> dict[str, Any]:
    return {
        "id": contact.id,
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "company_name": contact.company_name,
        "email": contact.email,
        "phone": contact.phone_number,
        "status": _enum_value(contact.status),
        "source": contact.source,
        "lead_score": contact.lead_score,
        "engagement_score": contact.engagement_score,
    }


def _bounded_limit(value: object, *, default: int, maximum: int) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        return None
    return value


class _SegmentInputError(ValueError):
    def __init__(self, response: dict[str, object]) -> None:
        super().__init__()
        self.response = response


def _segment_update_values(args: ToolArguments) -> dict[str, object]:
    editable = {"name", "description", "filter_rules", "filter_logic"}
    if not editable.intersection(args):
        raise _SegmentInputError(invalid_argument("Provide at least one segment field to update."))
    values: dict[str, object] = {}
    if "name" in args:
        name = SegmentAssistantTools._validated_name(args["name"])
        if name is None:
            raise _SegmentInputError(
                invalid_argument("name must contain 1 to 255 non-whitespace characters.")
            )
        values["name"] = name
    if "description" in args:
        description = args["description"]
        if description is not None and (
            not isinstance(description, str) or len(description) > 2_000
        ):
            raise _SegmentInputError(
                invalid_argument("description must be a string of at most 2,000 characters.")
            )
        values["description"] = description
    return values


class SegmentAssistantTools:
    """Workspace-scoped tag and dynamic-segment operations."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_tags": self.list_tags,
            "list_segments": self.list_segments,
            "preview_segment": self.preview_segment,
            "create_segment": self.create_segment,
            "update_segment": self.update_segment,
        }

    async def list_tags(self, args: ToolArguments) -> dict[str, object]:
        limit = _bounded_limit(args.get("limit"), default=50, maximum=100)
        if limit is None:
            return invalid_argument("limit must be an integer between 1 and 100.")
        stmt = select_workspace_owned(Tag, self.context.workspace_id)
        total = await count_matching(self.context.db, Tag, stmt)
        result = await self.context.db.execute(stmt.order_by(Tag.name, Tag.id).limit(limit))
        return listing(
            [
                {"id": str(tag.id), "name": tag.name, "color": tag.color}
                for tag in result.scalars().all()
            ],
            total=total,
        )

    async def list_segments(self, args: ToolArguments) -> dict[str, object]:
        limit = _bounded_limit(args.get("limit"), default=20, maximum=50)
        if limit is None:
            return invalid_argument("limit must be an integer between 1 and 50.")
        stmt = select_workspace_owned(Segment, self.context.workspace_id)
        total = await count_matching(self.context.db, Segment, stmt)
        result = await self.context.db.execute(
            stmt.order_by(Segment.updated_at.desc(), Segment.id).limit(limit)
        )
        return listing(
            [_serialize_segment(segment) for segment in result.scalars().all()],
            total=total,
        )

    async def preview_segment(self, args: ToolArguments) -> dict[str, object]:
        segment_id = parse_uuid(args.get("segment_id"))
        if segment_id is None:
            return invalid_id("segment_id", "Call list_segments to get a valid segment id.")
        sample_limit = _bounded_limit(args.get("sample_limit"), default=5, maximum=25)
        if sample_limit is None:
            return invalid_argument("sample_limit must be an integer between 1 and 25.")
        segment = await self._get_segment(segment_id)
        if segment is None:
            return not_found("Segment", "Call list_segments to get a valid segment id.")

        validated = await self._validated_definition(segment.definition)
        if isinstance(validated, dict):
            return validated
        rules, logic = validated
        count = await self._count_contacts(rules, logic)
        query = apply_contact_filters(
            select(Contact).where(Contact.workspace_id == self.context.workspace_id),
            self.context.workspace_id,
            filter_rules=rules,
            filter_logic=logic,
        ).order_by(Contact.created_at.desc(), Contact.id.desc())
        result = await self.context.db.execute(query.limit(sample_limit))
        return {
            "success": True,
            "data": {
                "segment": _serialize_segment(segment),
                "current_count": count,
                "sample": [_serialize_contact(contact) for contact in result.scalars().all()],
            },
        }

    async def create_segment(self, args: ToolArguments) -> dict[str, object]:
        name = self._validated_name(args.get("name"))
        if name is None:
            return invalid_argument("name must contain 1 to 255 non-whitespace characters.")
        description = args.get("description")
        if description is not None and (
            not isinstance(description, str) or len(description) > 2_000
        ):
            return invalid_argument("description must be a string of at most 2,000 characters.")

        validated = await self._validated_definition(
            {"rules": args.get("filter_rules"), "logic": args.get("filter_logic", "and")}
        )
        if isinstance(validated, dict):
            return validated
        rules, logic = validated
        count = await self._count_contacts(rules, logic)
        now = datetime.now(UTC)
        segment = Segment(
            workspace_id=self.context.workspace_id,
            name=name,
            description=description,
            definition={"rules": rules, "logic": logic},
            is_dynamic=True,
            contact_count=count,
            last_computed_at=now,
        )
        self.context.db.add(segment)
        await self.context.db.flush()
        return {"success": True, "data": _serialize_segment(segment)}

    async def update_segment(self, args: ToolArguments) -> dict[str, object]:
        try:
            segment_id = parse_uuid(args.get("segment_id"))
            if segment_id is None:
                raise _SegmentInputError(
                    invalid_id("segment_id", "Call list_segments to get a valid segment id.")
                )
            segment = await self._get_segment(segment_id)
            if segment is None:
                raise _SegmentInputError(
                    not_found("Segment", "Call list_segments to get a valid segment id.")
                )
            if not segment.is_dynamic:
                raise _SegmentInputError(
                    conflict("Only dynamic segments can be edited by the assistant.")
                )
            values = _segment_update_values(args)
            current = segment.definition if isinstance(segment.definition, dict) else {}
            definition = {
                "rules": args.get("filter_rules", current.get("rules")),
                "logic": args.get("filter_logic", current.get("logic", "and")),
            }
            validated = await self._validated_definition(definition)
            if isinstance(validated, dict):
                raise _SegmentInputError(validated)
            rules, logic = validated
            contact_count = await self._count_contacts(rules, logic)
        except _SegmentInputError as exc:
            return exc.response

        for field, value in values.items():
            setattr(segment, field, value)
        segment.definition = {"rules": rules, "logic": logic}
        segment.contact_count = contact_count
        segment.last_computed_at = datetime.now(UTC)
        await self.context.db.flush()
        return {"success": True, "data": _serialize_segment(segment)}

    async def _get_segment(self, segment_id: uuid.UUID) -> Segment | None:
        return await get_workspace_owned(
            self.context.db,
            Segment,
            segment_id,
            self.context.workspace_id,
        )

    @staticmethod
    def _validated_name(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped if 1 <= len(stripped) <= 255 else None

    async def _validated_definition(
        self, definition: object
    ) -> tuple[list[dict[str, Any]], str] | dict[str, object]:
        if not isinstance(definition, dict):
            return invalid_argument("Segment definition is malformed.")
        try:
            rules, logic = validate_contact_filter_rules(
                definition.get("rules"),
                definition.get("logic", "and"),
            )
        except ContactFilterValidationError as exc:
            return invalid_argument(str(exc), "Use only the documented segment filter fields.")
        if not await self._tags_belong_to_workspace(rules):
            return not_found("Tag", "Call list_tags and use tag IDs from this workspace.")
        return rules, logic

    async def _tags_belong_to_workspace(self, rules: list[dict[str, Any]]) -> bool:
        tag_ids = {
            uuid.UUID(tag_id)
            for rule in rules
            if rule["field"] == "tags"
            for tag_id in rule["value"]
        }
        if not tag_ids:
            return True
        result = await self.context.db.execute(
            select(Tag.id).where(
                Tag.workspace_id == self.context.workspace_id,
                Tag.id.in_(tag_ids),
            )
        )
        return set(result.scalars().all()) == tag_ids

    async def _count_contacts(self, rules: list[dict[str, Any]], logic: str) -> int:
        query = apply_contact_filters(
            select(func.count(Contact.id)).where(Contact.workspace_id == self.context.workspace_id),
            self.context.workspace_id,
            filter_rules=rules,
            filter_logic=logic,
        )
        result = await self.context.db.execute(query)
        return int(result.scalar_one())
