"""Opportunity and pipeline business logic service."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.crud import get_nested_or_404, get_or_404
from app.db.pagination import paginate
from app.models.opportunity import Opportunity, OpportunityActivity, OpportunityLineItem
from app.models.pipeline import Pipeline, PipelineStage
from app.schemas.opportunity import (
    OpportunityCreate,
    OpportunityDetailResponse,
    OpportunityLineItemCreate,
    OpportunityLineItemUpdate,
    OpportunityResponse,
    OpportunityUpdate,
    PaginatedOpportunities,
    PipelineCreate,
    PipelineResponse,
    PipelineStageCreate,
    PipelineStageResponse,
    PipelineStageUpdate,
    PipelineUpdate,
)
from app.services.automations.events import (
    EVENT_DEAL_STAGE_CHANGED,
    EVENT_OPPORTUNITY_CREATED,
    emit_automation_event,
)
from app.services.exceptions import NotFoundError
from app.services.opportunities.default_pipeline import DEFAULT_PIPELINE_STAGES
from app.services.opportunities.opportunity_filters import apply_opportunity_filters

logger = structlog.get_logger()

_DEFAULT_STAGES = DEFAULT_PIPELINE_STAGES


class OpportunityService:
    """Service for pipeline and opportunity CRUD operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="opportunity_service")

    # ------------------------------------------------------------------
    # Pipeline methods
    # ------------------------------------------------------------------

    async def list_pipelines(self, workspace_id: uuid.UUID) -> list[PipelineResponse]:
        """List active pipelines with their stages."""
        result = await self.db.execute(
            select(Pipeline)
            .where(Pipeline.workspace_id == workspace_id)
            .where(Pipeline.is_active)
            .options(selectinload(Pipeline.stages))
        )
        pipelines = result.unique().scalars().all()
        return [PipelineResponse.model_validate(p) for p in pipelines]

    async def create_pipeline(
        self,
        workspace_id: uuid.UUID,
        pipeline_in: PipelineCreate,
    ) -> PipelineResponse:
        """Create a pipeline with default stages."""
        pipeline = Pipeline(
            workspace_id=workspace_id,
            **pipeline_in.model_dump(),
        )
        self.db.add(pipeline)
        await self.db.flush()

        for stage_data in _DEFAULT_STAGES:
            self.db.add(PipelineStage(pipeline_id=pipeline.id, **stage_data))

        await self.db.commit()
        await self.db.refresh(pipeline, ["stages"])

        self.log.info("pipeline_created", pipeline_id=pipeline.id, workspace_id=str(workspace_id))
        return PipelineResponse.model_validate(pipeline)

    async def get_pipeline(
        self,
        workspace_id: uuid.UUID,
        pipeline_id: uuid.UUID,
    ) -> PipelineResponse:
        """Get a pipeline by ID."""
        pipeline = await get_or_404(
            self.db,
            Pipeline,
            pipeline_id,
            workspace_id=workspace_id,
            options=[selectinload(Pipeline.stages)],
        )
        return PipelineResponse.model_validate(pipeline)

    async def update_pipeline(
        self,
        workspace_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        pipeline_in: PipelineUpdate,
    ) -> PipelineResponse:
        """Update a pipeline's fields."""
        pipeline = await get_or_404(self.db, Pipeline, pipeline_id, workspace_id=workspace_id)

        if pipeline_in.name is not None:
            pipeline.name = pipeline_in.name
        if pipeline_in.description is not None:
            pipeline.description = pipeline_in.description
        if pipeline_in.is_active is not None:
            pipeline.is_active = pipeline_in.is_active

        await self.db.commit()
        await self.db.refresh(pipeline)

        return PipelineResponse.model_validate(pipeline)

    async def delete_pipeline(
        self,
        workspace_id: uuid.UUID,
        pipeline_id: uuid.UUID,
    ) -> None:
        """Delete a pipeline."""
        pipeline = await get_or_404(self.db, Pipeline, pipeline_id, workspace_id=workspace_id)
        await self.db.delete(pipeline)
        await self.db.commit()

    # ------------------------------------------------------------------
    # Pipeline stage methods
    # ------------------------------------------------------------------

    async def create_pipeline_stage(
        self,
        workspace_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        stage_in: PipelineStageCreate,
    ) -> PipelineStageResponse:
        """Create a stage in an existing pipeline."""
        await get_or_404(self.db, Pipeline, pipeline_id, workspace_id=workspace_id)

        stage = PipelineStage(
            pipeline_id=pipeline_id,
            name=stage_in.name,
            description=stage_in.description,
            order=stage_in.order,
            probability=stage_in.probability,
            stage_type=stage_in.stage_type,
        )
        self.db.add(stage)
        await self.db.commit()
        await self.db.refresh(stage)

        return PipelineStageResponse.model_validate(stage)

    async def update_pipeline_stage(
        self,
        pipeline_id: uuid.UUID,
        stage_id: uuid.UUID,
        stage_in: PipelineStageUpdate,
    ) -> PipelineStageResponse:
        """Update a pipeline stage's fields."""
        stage = await get_nested_or_404(
            self.db,
            PipelineStage,
            stage_id,
            parent_field="pipeline_id",
            parent_id=pipeline_id,
            detail="Stage not found",
        )

        if stage_in.name is not None:
            stage.name = stage_in.name
        if stage_in.description is not None:
            stage.description = stage_in.description
        if stage_in.order is not None:
            stage.order = stage_in.order
        if stage_in.probability is not None:
            stage.probability = stage_in.probability
        if stage_in.stage_type is not None:
            stage.stage_type = stage_in.stage_type

        await self.db.commit()
        await self.db.refresh(stage)

        return PipelineStageResponse.model_validate(stage)

    # ------------------------------------------------------------------
    # Opportunity methods
    # ------------------------------------------------------------------

    def _enforce_owner(self, opportunity: Opportunity, restrict_to_user_id: int | None) -> None:
        """Object-level guard for the sales tier.

        When ``restrict_to_user_id`` is set (a sales caller, see
        :func:`app.core.permissions.pipeline_owner_scope`), an opportunity the
        caller does not own is treated as **not found** (404 rather than 403, so
        we never leak the existence of another rep's deal).
        """
        if restrict_to_user_id is not None and opportunity.assigned_user_id != restrict_to_user_id:
            raise NotFoundError("Opportunity not found")

    async def list_opportunities(
        self,
        workspace_id: uuid.UUID,
        pipeline_id: uuid.UUID | None = None,
        stage_id: uuid.UUID | None = None,
        page: int = 1,
        page_size: int = 50,
        search: str | None = None,
        *,
        owner_id: uuid.UUID | None = None,
        opportunity_status: str | None = None,
        source: str | None = None,
        value_min: Decimal | float | None = None,
        value_max: Decimal | float | None = None,
        probability_min: int | None = None,
        probability_max: int | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        restrict_to_user_id: int | None = None,
    ) -> PaginatedOpportunities:
        """List opportunities with optional filters.

        ``restrict_to_user_id`` scopes results to a single deal owner
        (``assigned_user_id``); the sales tier passes its own user id so reps
        see only their own pipeline.
        """
        query = apply_opportunity_filters(
            select(Opportunity),
            workspace_id,
            pipeline_id=pipeline_id,
            stage_id=stage_id,
            owner_id=owner_id,
            status=opportunity_status,
            source=source,
            search=search,
            value_min=value_min,
            value_max=value_max,
            probability_min=probability_min,
            probability_max=probability_max,
            created_after=created_after,
            created_before=created_before,
        )
        if restrict_to_user_id is not None:
            query = query.where(Opportunity.assigned_user_id == restrict_to_user_id)
        query = query.order_by(Opportunity.created_at.desc())

        # Eager-load line_items: OpportunityResponse serializes them, and a lazy
        # load during async serialization raises MissingGreenlet.
        query = query.options(selectinload(Opportunity.line_items))

        result = await paginate(self.db, query, page=page, page_size=page_size, unique=True)
        return result.build_response(
            item_model=OpportunityResponse,
            response_builder=PaginatedOpportunities,
        )

    async def create_opportunity(
        self,
        workspace_id: uuid.UUID,
        opportunity_in: OpportunityCreate,
        assigned_user_id: int | None = None,
    ) -> OpportunityResponse:
        """Create an opportunity after validating pipeline and stage.

        ``assigned_user_id`` sets the deal owner. ``OpportunityCreate`` carries no
        owner field, so this is the only way to assign on create; the sales tier
        passes its own user id (forced self-assignment).
        """
        pipeline_query = select(Pipeline).where(
            (Pipeline.id == opportunity_in.pipeline_id) & (Pipeline.workspace_id == workspace_id)
        )
        pipeline = (await self.db.execute(pipeline_query)).scalar_one_or_none()
        if not pipeline:
            raise NotFoundError("Pipeline not found")

        stage = None
        if opportunity_in.stage_id:
            stage_query = select(PipelineStage).where(PipelineStage.id == opportunity_in.stage_id)
            stage = (await self.db.execute(stage_query)).scalar_one_or_none()
            if not stage:
                raise NotFoundError("Stage not found")

        opportunity = Opportunity(
            workspace_id=workspace_id,
            probability=stage.probability if stage else 0,
            **opportunity_in.model_dump(),
        )
        if assigned_user_id is not None:
            opportunity.assigned_user_id = assigned_user_id
        self.db.add(opportunity)
        await self.db.flush()
        await emit_automation_event(
            self.db,
            workspace_id=workspace_id,
            event_type=EVENT_OPPORTUNITY_CREATED,
            contact_id=opportunity.primary_contact_id,
            payload={
                "opportunity_id": str(opportunity.id),
                "name": opportunity.name,
                "amount": float(opportunity.amount) if opportunity.amount is not None else None,
                "stage": stage.name if stage else None,
                "source": opportunity.source,
            },
        )
        await self.db.commit()
        # Refresh line_items so the response can serialize the (empty) collection
        # without triggering a lazy load outside the async greenlet.
        await self.db.refresh(opportunity, ["line_items"])

        return OpportunityResponse.model_validate(opportunity)

    async def get_opportunity(
        self,
        workspace_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        restrict_to_user_id: int | None = None,
    ) -> OpportunityDetailResponse:
        """Get an opportunity by ID (sales callers are scoped to their own)."""
        opportunity = await get_or_404(
            self.db,
            Opportunity,
            opportunity_id,
            workspace_id=workspace_id,
            options=[
                selectinload(Opportunity.line_items),
                selectinload(Opportunity.activities),
            ],
        )
        self._enforce_owner(opportunity, restrict_to_user_id)
        return OpportunityDetailResponse.model_validate(opportunity)

    async def update_opportunity(
        self,
        workspace_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        opportunity_in: OpportunityUpdate,
        user_id: int,
        restrict_to_user_id: int | None = None,
    ) -> OpportunityResponse:
        """Update an opportunity, logging stage/status changes as activities."""
        opportunity = await get_or_404(
            self.db, Opportunity, opportunity_id, workspace_id=workspace_id
        )
        self._enforce_owner(opportunity, restrict_to_user_id)
        if restrict_to_user_id is not None:
            # A sales caller may not reassign a deal away from (or to) themselves.
            opportunity_in = opportunity_in.model_copy(
                update={"assigned_user_id": restrict_to_user_id}
            )

        # Stage change — update probability and log activity
        if opportunity_in.stage_id and opportunity_in.stage_id != opportunity.stage_id:
            stage_query = select(PipelineStage).where(PipelineStage.id == opportunity_in.stage_id)
            stage = (await self.db.execute(stage_query)).scalar_one_or_none()
            if not stage:
                raise NotFoundError("Stage not found")

            old_stage_query = select(PipelineStage).where(PipelineStage.id == opportunity.stage_id)
            old_stage = (await self.db.execute(old_stage_query)).scalar_one_or_none()

            self.db.add(
                OpportunityActivity(
                    opportunity_id=opportunity_id,
                    user_id=user_id,
                    activity_type="stage_changed",
                    old_value=old_stage.name if old_stage else "None",
                    new_value=stage.name,
                    description=(
                        f"Moved from {old_stage.name if old_stage else 'None'} to {stage.name}"
                    ),
                )
            )

            opportunity.stage_id = opportunity_in.stage_id
            opportunity.probability = stage.probability
            opportunity.stage_changed_at = datetime.now(UTC)

            await emit_automation_event(
                self.db,
                workspace_id=workspace_id,
                event_type=EVENT_DEAL_STAGE_CHANGED,
                contact_id=opportunity.primary_contact_id,
                payload={
                    "opportunity_id": str(opportunity.id),
                    "name": opportunity.name,
                    "old_stage": old_stage.name if old_stage else None,
                    "stage": stage.name,
                    "probability": stage.probability,
                },
            )

        # Simple field updates
        for field in [
            "name",
            "description",
            "amount",
            "currency",
            "expected_close_date",
            "assigned_user_id",
            "source",
            "lead_source_id",
            "lead_source_campaign_id",
            "attribution_confidence",
            "lost_reason",
            "is_active",
        ]:
            value = getattr(opportunity_in, field, None)
            if value is not None:
                setattr(opportunity, field, value)

        # Status change — log activity
        if opportunity_in.status is not None and opportunity_in.status != opportunity.status:
            self.db.add(
                OpportunityActivity(
                    opportunity_id=opportunity_id,
                    user_id=user_id,
                    activity_type="status_changed",
                    old_value=opportunity.status,
                    new_value=opportunity_in.status,
                    description=(
                        f"Status changed from {opportunity.status} to {opportunity_in.status}"
                    ),
                )
            )
            opportunity.status = opportunity_in.status
            is_closed = opportunity_in.status in ("won", "lost", "abandoned")
            opportunity.closed_date = datetime.now(UTC).date() if is_closed else None
            opportunity.closed_by_id = user_id if is_closed else None

        await self.db.commit()
        await self.db.refresh(opportunity, ["line_items"])

        return OpportunityResponse.model_validate(opportunity)

    async def delete_opportunity(
        self,
        workspace_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        restrict_to_user_id: int | None = None,
    ) -> None:
        """Delete an opportunity (sales callers may only delete their own)."""
        opportunity = await get_or_404(
            self.db, Opportunity, opportunity_id, workspace_id=workspace_id
        )
        self._enforce_owner(opportunity, restrict_to_user_id)
        await self.db.delete(opportunity)
        await self.db.commit()

    # ------------------------------------------------------------------
    # Line item methods
    # ------------------------------------------------------------------

    async def create_line_item(
        self,
        workspace_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        item_in: OpportunityLineItemCreate,
        restrict_to_user_id: int | None = None,
    ) -> dict[str, uuid.UUID | float]:
        """Create a line item for an opportunity."""
        opportunity = await get_or_404(
            self.db, Opportunity, opportunity_id, workspace_id=workspace_id
        )
        self._enforce_owner(opportunity, restrict_to_user_id)

        total = (item_in.quantity * item_in.unit_price) - item_in.discount
        line_item = OpportunityLineItem(
            opportunity_id=opportunity_id,
            name=item_in.name,
            description=item_in.description,
            quantity=item_in.quantity,
            unit_price=item_in.unit_price,
            discount=item_in.discount,
            total=total,
        )
        self.db.add(line_item)
        await self.db.commit()
        await self.db.refresh(line_item)

        return {"id": line_item.id, "total": float(line_item.total)}

    async def update_line_item(
        self,
        workspace_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        item_id: uuid.UUID,
        item_in: OpportunityLineItemUpdate,
        restrict_to_user_id: int | None = None,
    ) -> dict[str, uuid.UUID | float]:
        """Update a line item and recalculate its total."""
        # Verify opportunity belongs to workspace (and to the caller, if sales).
        opportunity = await get_or_404(
            self.db, Opportunity, opportunity_id, workspace_id=workspace_id
        )
        self._enforce_owner(opportunity, restrict_to_user_id)

        line_item = await get_nested_or_404(
            self.db,
            OpportunityLineItem,
            item_id,
            parent_field="opportunity_id",
            parent_id=opportunity_id,
            detail="Line item not found",
        )

        if item_in.name is not None:
            line_item.name = item_in.name
        if item_in.description is not None:
            line_item.description = item_in.description
        if item_in.quantity is not None:
            line_item.quantity = item_in.quantity
        if item_in.unit_price is not None:
            line_item.unit_price = item_in.unit_price
        if item_in.discount is not None:
            line_item.discount = item_in.discount

        line_item.total = (line_item.quantity * line_item.unit_price) - line_item.discount

        await self.db.commit()
        await self.db.refresh(line_item)

        return {"id": line_item.id, "total": float(line_item.total)}

    async def delete_line_item(
        self,
        workspace_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        item_id: uuid.UUID,
        restrict_to_user_id: int | None = None,
    ) -> None:
        """Delete a line item."""
        # Verify opportunity belongs to workspace (and to the caller, if sales).
        opportunity = await get_or_404(
            self.db, Opportunity, opportunity_id, workspace_id=workspace_id
        )
        self._enforce_owner(opportunity, restrict_to_user_id)

        line_item = await get_nested_or_404(
            self.db,
            OpportunityLineItem,
            item_id,
            parent_field="opportunity_id",
            parent_id=opportunity_id,
            detail="Line item not found",
        )
        await self.db.delete(line_item)
        await self.db.commit()
