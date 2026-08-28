"""Opportunity and pipeline CRM assistant tools."""

from __future__ import annotations

import uuid

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select

from app.core.permissions import pipeline_owner_scope
from app.models.pipeline import Pipeline, PipelineStage
from app.schemas.opportunity import OpportunityCreate, OpportunityUpdate
from app.services.ai.crm_assistant._pagination import listing
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
    parse_uuid,
)
from app.services.ai.crm_assistant._tool_errors import (
    invalid_argument,
    invalid_id,
    not_found,
    unavailable,
    validation_failed,
)
from app.services.exceptions import (
    NotFoundError,
    ServiceError,
)
from app.services.exceptions import (
    ValidationError as ServiceValidationError,
)
from app.services.opportunities import OpportunityService

_OPPORTUNITY_FIELDS = {
    "name",
    "description",
    "amount",
    "currency",
    "expected_close_date",
    "source",
    "status",
    "lost_reason",
    "stage_id",
    "primary_contact_id",
    "assigned_user_id",
}


class _OpportunityInputError(ValueError):
    def __init__(self, response: dict[str, object]) -> None:
        super().__init__()
        self.response = response


def _required_user(context: CRMToolContext, purpose: str) -> int:
    user_id = context.user_id
    if isinstance(user_id, int) and not isinstance(user_id, bool):
        return user_id
    raise _OpportunityInputError(
        unavailable(f"An authenticated user is required for opportunity {purpose}.")
    )


def _create_opportunity_input(
    context: CRMToolContext, args: ToolArguments
) -> tuple[OpportunityCreate, int, int | None]:
    user_id = _required_user(context, "creation")
    if set(args) - (_OPPORTUNITY_FIELDS | {"pipeline_id"}):
        raise _OpportunityInputError(
            invalid_argument("Create opportunity received unsupported fields.")
        )
    try:
        opportunity_in = OpportunityCreate(**args)
    except PydanticValidationError as exc:
        raise _OpportunityInputError(
            validation_failed("Opportunity", "Fields did not match the required opportunity shape.")
        ) from exc
    return opportunity_in, user_id, pipeline_owner_scope(context.role, user_id)


def _update_opportunity_input(
    context: CRMToolContext, args: ToolArguments
) -> tuple[uuid.UUID, OpportunityUpdate, int, int | None]:
    user_id = _required_user(context, "updates")
    opportunity_id = parse_uuid(args.get("opportunity_id"))
    if opportunity_id is None:
        raise _OpportunityInputError(
            invalid_id("opportunity_id", "Call list_opportunities to get a valid opportunity id.")
        )
    payload = {key: value for key, value in args.items() if key != "opportunity_id"}
    if set(payload) - _OPPORTUNITY_FIELDS:
        raise _OpportunityInputError(
            invalid_argument("Update opportunity received unsupported fields.")
        )
    if not payload:
        raise _OpportunityInputError(
            invalid_argument("Provide at least one opportunity field to update.")
        )
    try:
        opportunity_in = OpportunityUpdate(**payload)
    except PydanticValidationError as exc:
        raise _OpportunityInputError(
            validation_failed(
                "Opportunity update", "Fields did not match the required opportunity shape."
            )
        ) from exc
    return (
        opportunity_id,
        opportunity_in,
        user_id,
        pipeline_owner_scope(context.role, user_id),
    )


def _opportunity_service_error(
    exc: ServiceError, *, label: str, not_found_hint: str, fallback: str
) -> dict[str, object]:
    if isinstance(exc, NotFoundError):
        return not_found("Opportunity resource", not_found_hint)
    if isinstance(exc, ServiceValidationError):
        return validation_failed(label, exc.message)
    return validation_failed(label, fallback)


class OpportunityAssistantTools:
    """Workspace- and owner-scoped opportunity operations."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context
        self.service = OpportunityService(context.db)

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_pipeline_stages": self.list_pipeline_stages,
            "list_opportunities": self.list_opportunities,
            "get_opportunity": self.get_opportunity,
            "create_opportunity": self.create_opportunity,
            "update_opportunity": self.update_opportunity,
        }

    async def list_pipeline_stages(self, args: ToolArguments) -> dict[str, object]:
        """List ordered pipeline stages, always scoped to the current workspace."""

        pipeline_name = str(args.get("pipeline_name") or "").strip()
        stage_name = str(args.get("stage_name") or "").strip()

        stmt = (
            select(Pipeline, PipelineStage)
            .join(PipelineStage, PipelineStage.pipeline_id == Pipeline.id)
            .where(Pipeline.workspace_id == self.context.workspace_id)
        )
        if pipeline_name:
            stmt = stmt.where(Pipeline.name.ilike(f"%{pipeline_name}%"))
        if stage_name:
            stmt = stmt.where(PipelineStage.name.ilike(f"%{stage_name}%"))

        result = await self.context.db.execute(
            stmt.order_by(Pipeline.name.asc(), PipelineStage.order.asc(), PipelineStage.id.asc())
        )
        rows = result.all()
        return listing(
            [
                {
                    "pipeline_id": str(pipeline.id),
                    "pipeline_name": pipeline.name,
                    "pipeline_is_active": pipeline.is_active,
                    "stage_id": str(stage.id),
                    "stage_name": stage.name,
                    "stage_order": stage.order,
                    "stage_type": stage.stage_type,
                    "stage_probability": stage.probability,
                }
                for pipeline, stage in rows
            ],
            total=len(rows),
        )

    async def list_opportunities(self, args: ToolArguments) -> dict[str, object]:
        user_id = self._user_id()
        if user_id is None:
            return unavailable("An authenticated user is required for opportunity access.")
        limit = args.get("limit", 10)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            return invalid_argument("limit must be an integer between 1 and 50.")

        page = await self.service.list_opportunities(
            self.context.workspace_id,
            page=1,
            page_size=limit,
            restrict_to_user_id=pipeline_owner_scope(self.context.role, user_id),
        )
        return listing(
            [item.model_dump(mode="json") for item in page.items],
            total=page.total,
        )

    async def get_opportunity(self, args: ToolArguments) -> dict[str, object]:
        user_id = self._user_id()
        if user_id is None:
            return unavailable("An authenticated user is required for opportunity access.")
        opportunity_id = parse_uuid(args.get("opportunity_id"))
        if opportunity_id is None:
            return invalid_id(
                "opportunity_id", "Call list_opportunities to get a valid opportunity id."
            )
        try:
            opportunity = await self.service.get_opportunity(
                self.context.workspace_id,
                opportunity_id,
                restrict_to_user_id=pipeline_owner_scope(self.context.role, user_id),
            )
        except NotFoundError:
            return not_found(
                "Opportunity", "Call list_opportunities to get an opportunity visible to you."
            )
        return {"success": True, "data": opportunity.model_dump(mode="json")}

    async def create_opportunity(self, args: ToolArguments) -> dict[str, object]:
        try:
            opportunity_in, _user_id, owner_scope = _create_opportunity_input(self.context, args)
        except _OpportunityInputError as exc:
            return exc.response
        if not await self._stage_belongs_to_pipeline(
            opportunity_in.stage_id, opportunity_in.pipeline_id
        ):
            return not_found(
                "Pipeline stage",
                "Call list_pipeline_stages and use a stage from the selected pipeline.",
            )
        try:
            opportunity = await self.service.create_opportunity(
                self.context.workspace_id,
                opportunity_in,
                assigned_user_id=owner_scope,
            )
        except ServiceError as exc:
            return _opportunity_service_error(
                exc,
                label="Opportunity",
                not_found_hint="Use pipeline, stage, contact, and owner IDs from this workspace.",
                fallback="The opportunity could not be created.",
            )
        return {"success": True, "data": opportunity.model_dump(mode="json")}

    async def update_opportunity(self, args: ToolArguments) -> dict[str, object]:
        try:
            opportunity_id, opportunity_in, user_id, owner_scope = _update_opportunity_input(
                self.context, args
            )
        except _OpportunityInputError as exc:
            return exc.response
        try:
            current = await self.service.get_opportunity(
                self.context.workspace_id,
                opportunity_id,
                restrict_to_user_id=owner_scope,
            )
        except ServiceError as exc:
            return _opportunity_service_error(
                exc,
                label="Opportunity update",
                not_found_hint="Call list_opportunities to get an opportunity visible to you.",
                fallback="The opportunity could not be read.",
            )
        if opportunity_in.stage_id is not None and not await self._stage_belongs_to_pipeline(
            opportunity_in.stage_id, current.pipeline_id
        ):
            return not_found(
                "Pipeline stage",
                "Call list_pipeline_stages and use a stage from this opportunity's pipeline.",
            )
        try:
            opportunity = await self.service.update_opportunity(
                self.context.workspace_id,
                opportunity_id,
                opportunity_in,
                user_id,
                restrict_to_user_id=owner_scope,
            )
        except ServiceError as exc:
            return _opportunity_service_error(
                exc,
                label="Opportunity update",
                not_found_hint="Use contact, owner, and stage IDs from this workspace.",
                fallback="The opportunity could not be updated.",
            )
        return {"success": True, "data": opportunity.model_dump(mode="json")}

    async def _stage_belongs_to_pipeline(
        self, stage_id: uuid.UUID | None, pipeline_id: uuid.UUID
    ) -> bool:
        if stage_id is None:
            return True
        result = await self.context.db.execute(
            select(PipelineStage.id)
            .join(Pipeline, Pipeline.id == PipelineStage.pipeline_id)
            .where(
                PipelineStage.id == stage_id,
                PipelineStage.pipeline_id == pipeline_id,
                Pipeline.workspace_id == self.context.workspace_id,
            )
        )
        return result.scalar_one_or_none() is not None

    def _user_id(self) -> int | None:
        user_id = self.context.user_id
        return user_id if isinstance(user_id, int) and not isinstance(user_id, bool) else None
