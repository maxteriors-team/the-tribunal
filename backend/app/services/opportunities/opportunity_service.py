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
from app.models.contact import Contact
from app.models.opportunity import (
    Opportunity,
    OpportunityActivity,
    OpportunityLineItem,
    OpportunityTask,
)
from app.models.pipeline import Pipeline, PipelineStage
from app.schemas.opportunity import (
    OpportunityCreate,
    OpportunityDetailResponse,
    OpportunityLineItemCreate,
    OpportunityLineItemUpdate,
    OpportunityNoteCreate,
    OpportunityResponse,
    OpportunityTaskCreate,
    OpportunityTaskUpdate,
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
from app.services.opportunities.pipeline_removal import remove_from_pipeline
from app.services.workspaces.membership import assert_active_workspace_member

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
        owner_id: int | None = None,
        contact_id: int | None = None,
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

        ``contact_id`` narrows to the deals a single contact is the primary
        contact on — what the contact sidebar renders so an operator can see a
        lead is already on the board instead of adding a duplicate card.
        """
        query = apply_opportunity_filters(
            select(Opportunity),
            workspace_id,
            pipeline_id=pipeline_id,
            stage_id=stage_id,
            owner_id=owner_id,
            contact_id=contact_id,
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

        # Eager-load response relationships for the whole page, avoiding one
        # contact/owner/line-item query per opportunity.
        query = query.options(
            selectinload(Opportunity.line_items),
            selectinload(Opportunity.primary_contact),
            selectinload(Opportunity.assigned_user),
        )

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
        """Create an opportunity after validating pipeline, stage, and owner.

        ``assigned_user_id`` is a role-enforced override for sales callers;
        managers may select the owner through ``OpportunityCreate``.
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

        primary_contact = None
        if opportunity_in.primary_contact_id is not None:
            primary_contact = await get_or_404(
                self.db,
                Contact,
                opportunity_in.primary_contact_id,
                workspace_id=workspace_id,
                detail="Contact not found",
            )

        requested_owner_id = (
            assigned_user_id if assigned_user_id is not None else opportunity_in.assigned_user_id
        )
        assignee = None
        if requested_owner_id is not None:
            assignee = await assert_active_workspace_member(
                self.db, workspace_id, requested_owner_id
            )
        opportunity = Opportunity(
            workspace_id=workspace_id,
            probability=stage.probability if stage else 0,
            primary_contact_id=opportunity_in.primary_contact_id,
            primary_contact=primary_contact,
            assigned_user_id=requested_owner_id,
            assigned_user=assignee,
            **opportunity_in.model_dump(exclude={"assigned_user_id", "primary_contact_id"}),
        )
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
        # Refresh response relationships so async serialization never lazy-loads.
        await self.db.refresh(opportunity, ["line_items", "primary_contact", "assigned_user"])

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
                # Eager-loaded with its assignee: serializing either lazily here
                # raises MissingGreenlet and 500s the detail sheet.
                selectinload(Opportunity.tasks).selectinload(OpportunityTask.assigned_user),
                selectinload(Opportunity.primary_contact),
                selectinload(Opportunity.assigned_user),
            ],
        )
        self._enforce_owner(opportunity, restrict_to_user_id)
        return OpportunityDetailResponse.model_validate(opportunity)

    async def move_stage(
        self,
        workspace_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        stage_id: uuid.UUID,
        *,
        user_id: int | None = None,
        source: str = "automation",
    ) -> Opportunity | None:
        """Move an opportunity to ``stage_id`` — the single source of truth for a
        stage change.

        Runs the full side-effect block: a ``stage_changed``
        :class:`OpportunityActivity` (``user_id`` may be ``None`` for an
        automation-driven move), a probability + ``stage_changed_at`` update, and
        an :data:`EVENT_DEAL_STAGE_CHANGED` emission. ``source`` labels who moved
        the deal (``"manual"`` for API callers, ``"automation"`` for the worker).

        Idempotent: when ``stage_id`` already equals the opportunity's current
        stage this is a no-op — no activity, no probability change, and **no
        event** — so a ``move -> deal_stage_changed -> move`` cycle terminates
        after one hop. Callers own the transaction (no commit here).

        Returns the opportunity, or ``None`` when it does not exist in
        ``workspace_id`` (callers treat that as skip, not error).
        """
        opportunity = await self.db.get(Opportunity, opportunity_id)
        if opportunity is None or opportunity.workspace_id != workspace_id:
            return None

        # Idempotency / loop brake: nothing to do (and nothing to emit) when the
        # deal is already in the requested stage.
        if not stage_id or stage_id == opportunity.stage_id:
            return opportunity

        stage_query = select(PipelineStage).where(PipelineStage.id == stage_id)
        stage = (await self.db.execute(stage_query)).scalar_one_or_none()
        if not stage:
            raise NotFoundError("Stage not found")

        old_stage_query = select(PipelineStage).where(PipelineStage.id == opportunity.stage_id)
        old_stage = (await self.db.execute(old_stage_query)).scalar_one_or_none()

        self.db.add(
            OpportunityActivity(
                opportunity_id=opportunity.id,
                user_id=user_id,
                activity_type="stage_changed",
                old_value=old_stage.name if old_stage else "None",
                new_value=stage.name,
                description=(
                    f"Moved from {old_stage.name if old_stage else 'None'} to {stage.name}"
                ),
            )
        )

        opportunity.stage_id = stage_id
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
                "source": source,
            },
        )
        self.log.info(
            "opportunity_stage_moved",
            opportunity_id=str(opportunity.id),
            stage_id=str(stage_id),
            source=source,
        )
        return opportunity

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
        owner_was_requested = (
            restrict_to_user_id is not None or "assigned_user_id" in opportunity_in.model_fields_set
        )
        requested_owner_id = (
            restrict_to_user_id
            if restrict_to_user_id is not None
            else opportunity_in.assigned_user_id
        )
        if owner_was_requested:
            assignee = None
            if requested_owner_id is not None:
                assignee = await assert_active_workspace_member(
                    self.db, workspace_id, requested_owner_id
                )
            opportunity.assigned_user_id = requested_owner_id
            opportunity.assigned_user = assignee

        if "primary_contact_id" in opportunity_in.model_fields_set:
            primary_contact = None
            if opportunity_in.primary_contact_id is not None:
                primary_contact = await get_or_404(
                    self.db,
                    Contact,
                    opportunity_in.primary_contact_id,
                    workspace_id=workspace_id,
                    detail="Contact not found",
                )
            opportunity.primary_contact_id = opportunity_in.primary_contact_id
            opportunity.primary_contact = primary_contact

        # Stage change — delegate to move_stage so the activity log, probability
        # update, stage_changed_at, and deal_stage_changed event stay in one
        # place. move_stage is idempotent, so passing the current stage is a safe
        # no-op (the != guard below just avoids a redundant lookup).
        if opportunity_in.stage_id and opportunity_in.stage_id != opportunity.stage_id:
            await self.move_stage(
                workspace_id,
                opportunity_id,
                opportunity_in.stage_id,
                user_id=user_id,
                source="manual",
            )

        # Simple field updates
        for field in [
            "name",
            "description",
            "amount",
            "currency",
            "expected_close_date",
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
        await self.db.refresh(opportunity, ["line_items", "primary_contact", "assigned_user"])

        return OpportunityResponse.model_validate(opportunity)

    async def remove_from_pipeline(
        self,
        workspace_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        user_id: int,
        restrict_to_user_id: int | None = None,
    ) -> OpportunityResponse:
        """Take a deal off the board without destroying it.

        The softer counterpart to :meth:`delete_opportunity`: the card and its
        activity history survive, and the contact is marked so an automatic
        quote-send card is not put straight back (which would make the button
        look broken).
        """
        opportunity = await get_or_404(
            self.db, Opportunity, opportunity_id, workspace_id=workspace_id
        )
        self._enforce_owner(opportunity, restrict_to_user_id)

        await remove_from_pipeline(self.db, opportunity, user_id=user_id)
        await self.db.commit()
        await self.db.refresh(opportunity, ["line_items", "primary_contact", "assigned_user"])

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

    async def add_note(
        self,
        workspace_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        note_in: OpportunityNoteCreate,
        user_id: int | None = None,
        restrict_to_user_id: int | None = None,
    ) -> OpportunityActivity:
        """Record a note or status update against the deal.

        Stored as an activity so operator commentary lands in the same timeline
        as the automatic stage changes -- a note filed somewhere else is a note
        nobody reads next to the event that prompted it.
        """
        opportunity = await get_or_404(
            self.db, Opportunity, opportunity_id, workspace_id=workspace_id
        )
        self._enforce_owner(opportunity, restrict_to_user_id)

        activity = OpportunityActivity(
            opportunity_id=opportunity_id,
            user_id=user_id,
            activity_type=note_in.kind,
            description=note_in.body.strip(),
        )
        self.db.add(activity)
        await self.db.commit()
        await self.db.refresh(activity)
        return activity

    async def list_tasks(
        self,
        workspace_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        restrict_to_user_id: int | None = None,
    ) -> list[OpportunityTask]:
        """List a deal's follow-ups, soonest-due first with done ones last."""
        opportunity = await get_or_404(
            self.db, Opportunity, opportunity_id, workspace_id=workspace_id
        )
        self._enforce_owner(opportunity, restrict_to_user_id)

        result = await self.db.execute(
            select(OpportunityTask)
            .where(OpportunityTask.opportunity_id == opportunity_id)
            .options(selectinload(OpportunityTask.assigned_user))
            .order_by(
                # Open work first, then by when it is due. NULLS LAST keeps
                # undated tasks from burying the ones with a deadline.
                OpportunityTask.completed_at.is_not(None),
                OpportunityTask.due_at.asc().nulls_last(),
                OpportunityTask.created_at.asc(),
            )
        )
        return list(result.scalars().all())

    async def create_task(
        self,
        workspace_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        task_in: OpportunityTaskCreate,
        user_id: int | None = None,
        restrict_to_user_id: int | None = None,
    ) -> OpportunityTask:
        """Create a follow-up task on an opportunity."""
        opportunity = await get_or_404(
            self.db, Opportunity, opportunity_id, workspace_id=workspace_id
        )
        self._enforce_owner(opportunity, restrict_to_user_id)

        if task_in.assigned_user_id is not None:
            await assert_active_workspace_member(
                self.db,
                workspace_id,
                task_in.assigned_user_id,
            )

        task = OpportunityTask(
            opportunity_id=opportunity_id,
            title=task_in.title.strip(),
            notes=task_in.notes,
            due_at=task_in.due_at,
            # Untagged follow-ups default to whoever created them.
            assigned_user_id=task_in.assigned_user_id or user_id,
            created_by_id=user_id,
        )
        self.db.add(task)
        await self.db.commit()
        return await self._load_task(task.id)

    async def update_task(
        self,
        workspace_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        task_id: uuid.UUID,
        task_in: OpportunityTaskUpdate,
        user_id: int | None = None,
        restrict_to_user_id: int | None = None,
    ) -> OpportunityTask:
        """Patch a task, translating ``completed`` into a completion timestamp."""
        opportunity = await get_or_404(
            self.db, Opportunity, opportunity_id, workspace_id=workspace_id
        )
        self._enforce_owner(opportunity, restrict_to_user_id)

        task = await get_nested_or_404(
            self.db,
            OpportunityTask,
            task_id,
            parent_field="opportunity_id",
            parent_id=opportunity_id,
            detail="Task not found",
        )

        fields = task_in.model_dump(exclude_unset=True)
        completed = fields.pop("completed", None)
        assigned_user_id = fields.get("assigned_user_id")
        if assigned_user_id is not None:
            await assert_active_workspace_member(
                self.db,
                workspace_id,
                assigned_user_id,
            )
        for field, value in fields.items():
            setattr(task, field, value)

        if completed is True and task.completed_at is None:
            task.completed_at = datetime.now(UTC)
            task.completed_by_id = user_id
        elif completed is False:
            task.completed_at = None
            task.completed_by_id = None

        await self.db.commit()
        return await self._load_task(task.id)

    async def delete_task(
        self,
        workspace_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        task_id: uuid.UUID,
        restrict_to_user_id: int | None = None,
    ) -> None:
        """Delete a task."""
        opportunity = await get_or_404(
            self.db, Opportunity, opportunity_id, workspace_id=workspace_id
        )
        self._enforce_owner(opportunity, restrict_to_user_id)

        task = await get_nested_or_404(
            self.db,
            OpportunityTask,
            task_id,
            parent_field="opportunity_id",
            parent_id=opportunity_id,
            detail="Task not found",
        )
        await self.db.delete(task)
        await self.db.commit()

    async def _load_task(self, task_id: uuid.UUID) -> OpportunityTask:
        """Re-read a task with its assignee eager-loaded.

        Serializing ``assignee`` off a freshly committed row would lazy-load
        inside async serialization and raise ``MissingGreenlet``.
        """
        result = await self.db.execute(
            select(OpportunityTask)
            .where(OpportunityTask.id == task_id)
            .options(selectinload(OpportunityTask.assigned_user))
        )
        return result.scalar_one()
