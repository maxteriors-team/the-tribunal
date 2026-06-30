"""Opportunity management endpoints."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from app.api.deps import (
    DB,
    CanReadCRM,
    CanWriteCRM,
    CanWritePipelineOwn,
    CurrentUser,
)
from app.api.service_errors import ServiceErrorRoute
from app.core.permissions import pipeline_owner_scope
from app.schemas.deal_coach import (
    AtRiskDealsResponse,
    DealCoachCard,
    DraftActionRequest,
    DraftActionResponse,
)
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
from app.services.opportunities import OpportunityService
from app.services.opportunities.deal_coach_service import DealCoachService

router = APIRouter(route_class=ServiceErrorRoute)


# Pipeline endpoints
@router.get("/pipelines", response_model=list[PipelineResponse])
async def list_pipelines(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> list[PipelineResponse]:
    """List all pipelines in a workspace."""
    service = OpportunityService(db)
    return await service.list_pipelines(workspace_id)


@router.post("/pipelines", response_model=PipelineResponse, status_code=status.HTTP_201_CREATED)
async def create_pipeline(
    workspace_id: uuid.UUID,
    pipeline_in: PipelineCreate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> PipelineResponse:
    """Create a new pipeline."""
    service = OpportunityService(db)
    return await service.create_pipeline(workspace_id, pipeline_in)


@router.get("/pipelines/{pipeline_id}", response_model=PipelineResponse)
async def get_pipeline(
    workspace_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> PipelineResponse:
    """Get a specific pipeline."""
    service = OpportunityService(db)
    return await service.get_pipeline(workspace_id, pipeline_id)


@router.put("/pipelines/{pipeline_id}", response_model=PipelineResponse)
async def update_pipeline(
    workspace_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    pipeline_in: PipelineUpdate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> PipelineResponse:
    """Update a pipeline."""
    service = OpportunityService(db)
    return await service.update_pipeline(workspace_id, pipeline_id, pipeline_in)


@router.delete("/pipelines/{pipeline_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pipeline(
    workspace_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> None:
    """Delete a pipeline."""
    service = OpportunityService(db)
    await service.delete_pipeline(workspace_id, pipeline_id)


# Pipeline stage endpoints
@router.post(
    "/pipelines/{pipeline_id}/stages",
    response_model=PipelineStageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_pipeline_stage(
    workspace_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    stage_in: PipelineStageCreate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> PipelineStageResponse:
    """Create a new pipeline stage."""
    service = OpportunityService(db)
    return await service.create_pipeline_stage(workspace_id, pipeline_id, stage_in)


@router.put("/pipelines/{pipeline_id}/stages/{stage_id}", response_model=PipelineStageResponse)
async def update_pipeline_stage(
    workspace_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    stage_id: uuid.UUID,
    stage_in: PipelineStageUpdate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> PipelineStageResponse:
    """Update a pipeline stage."""
    service = OpportunityService(db)
    return await service.update_pipeline_stage(pipeline_id, stage_id, stage_in)


# Opportunity endpoints
@router.get("", response_model=PaginatedOpportunities)
async def list_opportunities(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
    pipeline_id: Annotated[uuid.UUID | None, Query()] = None,
    stage_id: Annotated[uuid.UUID | None, Query()] = None,
    owner_id: Annotated[uuid.UUID | None, Query()] = None,
    opportunity_status: Annotated[str | None, Query(alias="status")] = None,
    source: Annotated[str | None, Query()] = None,
    value_min: Annotated[Decimal | None, Query(ge=0)] = None,
    value_max: Annotated[Decimal | None, Query(ge=0)] = None,
    probability_min: Annotated[int | None, Query(ge=0, le=100)] = None,
    probability_max: Annotated[int | None, Query(ge=0, le=100)] = None,
    created_after: Annotated[datetime | None, Query()] = None,
    created_before: Annotated[datetime | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    search: str | None = None,
) -> PaginatedOpportunities:
    """List opportunities in a workspace (sales callers see only their own)."""
    service = OpportunityService(db)
    return await service.list_opportunities(
        workspace_id,
        pipeline_id=pipeline_id,
        stage_id=stage_id,
        page=page,
        page_size=page_size,
        search=search,
        owner_id=owner_id,
        opportunity_status=opportunity_status,
        source=source,
        value_min=value_min,
        value_max=value_max,
        probability_min=probability_min,
        probability_max=probability_max,
        created_after=created_after,
        created_before=created_before,
        restrict_to_user_id=pipeline_owner_scope(membership.role, current_user.id),
    )


# Deal Coach endpoints
#
# ``/coaching/at-risk`` is declared before ``/{opportunity_id}`` so the literal
# path is never parsed as an opportunity UUID.
@router.get("/coaching/at-risk", response_model=AtRiskDealsResponse)
async def list_at_risk_deals(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    min_risk_score: Annotated[int, Query(ge=0, le=100)] = 25,
) -> AtRiskDealsResponse:
    """Rank open opportunities by AI deal-risk score (most at-risk first)."""
    service = DealCoachService(db)
    return await service.list_at_risk(workspace_id, limit=limit, min_risk_score=min_risk_score)


@router.post("", response_model=OpportunityResponse, status_code=status.HTTP_201_CREATED)
async def create_opportunity(
    workspace_id: uuid.UUID,
    opportunity_in: OpportunityCreate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWritePipelineOwn,
) -> OpportunityResponse:
    """Create a new opportunity (sales callers are forced to self-assign)."""
    service = OpportunityService(db)
    return await service.create_opportunity(
        workspace_id,
        opportunity_in,
        assigned_user_id=pipeline_owner_scope(membership.role, current_user.id),
    )


@router.get("/{opportunity_id}", response_model=OpportunityDetailResponse)
async def get_opportunity(
    workspace_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> OpportunityDetailResponse:
    """Get a specific opportunity (sales callers are scoped to their own)."""
    service = OpportunityService(db)
    return await service.get_opportunity(
        workspace_id,
        opportunity_id,
        restrict_to_user_id=pipeline_owner_scope(membership.role, current_user.id),
    )


@router.put("/{opportunity_id}", response_model=OpportunityResponse)
async def update_opportunity(
    workspace_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    opportunity_in: OpportunityUpdate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWritePipelineOwn,
) -> OpportunityResponse:
    """Update an opportunity (sales callers may only touch their own)."""
    service = OpportunityService(db)
    return await service.update_opportunity(
        workspace_id,
        opportunity_id,
        opportunity_in,
        current_user.id,
        restrict_to_user_id=pipeline_owner_scope(membership.role, current_user.id),
    )


@router.delete("/{opportunity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_opportunity(
    workspace_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanWritePipelineOwn,
) -> None:
    """Delete an opportunity (sales callers may only delete their own)."""
    service = OpportunityService(db)
    await service.delete_opportunity(
        workspace_id,
        opportunity_id,
        restrict_to_user_id=pipeline_owner_scope(membership.role, current_user.id),
    )


@router.get("/{opportunity_id}/coach", response_model=DealCoachCard)
async def coach_opportunity(
    workspace_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> DealCoachCard:
    """Get the AI Deal Coach card for one opportunity."""
    service = DealCoachService(db)
    return await service.coach_opportunity(workspace_id, opportunity_id)


@router.post(
    "/{opportunity_id}/coach/draft-action",
    response_model=DraftActionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def draft_coach_action(
    workspace_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanWritePipelineOwn,
    body: DraftActionRequest | None = None,
) -> DraftActionResponse:
    """Queue the coach's drafted next-best action through the approval gate."""
    service = DealCoachService(db)
    decision, action_id, action_type, description = await service.queue_drafted_action(
        workspace_id,
        opportunity_id,
        channel=body.channel if body else None,
        body=body.body if body else None,
        description=body.description if body else None,
    )
    return DraftActionResponse(
        decision=decision,  # type: ignore[arg-type]
        pending_action_id=action_id,
        action_type=action_type,
        description=description,
    )


# Line items endpoints
@router.post(
    "/{opportunity_id}/line-items",
    response_model=dict[str, uuid.UUID | float],
    status_code=status.HTTP_201_CREATED,
)
async def create_line_item(
    workspace_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    item_in: OpportunityLineItemCreate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWritePipelineOwn,
) -> dict[str, Any]:
    """Create a line item for an opportunity."""
    service = OpportunityService(db)
    return await service.create_line_item(
        workspace_id,
        opportunity_id,
        item_in,
        restrict_to_user_id=pipeline_owner_scope(membership.role, current_user.id),
    )


@router.put(
    "/{opportunity_id}/line-items/{item_id}",
    response_model=dict[str, uuid.UUID | float],
)
async def update_line_item(
    workspace_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    item_id: uuid.UUID,
    item_in: OpportunityLineItemUpdate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWritePipelineOwn,
) -> dict[str, Any]:
    """Update a line item."""
    service = OpportunityService(db)
    return await service.update_line_item(
        workspace_id,
        opportunity_id,
        item_id,
        item_in,
        restrict_to_user_id=pipeline_owner_scope(membership.role, current_user.id),
    )


@router.delete("/{opportunity_id}/line-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_line_item(
    workspace_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanWritePipelineOwn,
) -> None:
    """Delete a line item."""
    service = OpportunityService(db)
    await service.delete_line_item(
        workspace_id,
        opportunity_id,
        item_id,
        restrict_to_user_id=pipeline_owner_scope(membership.role, current_user.id),
    )
