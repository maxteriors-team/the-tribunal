"""Improvement suggestions management endpoints."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import extract, func, select

from app.api.crud import get_or_404
from app.api.deps import DB, CurrentUser, get_workspace, require_route_capabilities
from app.core.permissions import Capability
from app.db.pagination import paginate
from app.db.scope import apply_workspace_scope
from app.models.agent import Agent
from app.models.improvement_suggestion import ImprovementSuggestion
from app.models.prompt_version import PromptVersion
from app.models.workspace import Workspace
from app.schemas.improvement_suggestion import (
    ApproveResponse,
    GenerateSuggestionsRequest,
    ImprovementSuggestionListResponse,
    ImprovementSuggestionResponse,
    RejectSuggestionRequest,
)
from app.services.ai.prompt_improvement_service import PromptImprovementService

router = APIRouter(
    dependencies=[
        Depends(require_route_capabilities(Capability.CRM_READ, Capability.WORKSPACE_MANAGE))
    ]
)


@router.get("", response_model=ImprovementSuggestionListResponse)
async def list_suggestions(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    agent_id: uuid.UUID | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ImprovementSuggestionListResponse:
    """List improvement suggestions for a workspace.

    Optionally filter by agent_id and/or status.
    """
    # Build query with workspace filter via agent
    query = apply_workspace_scope(
        select(ImprovementSuggestion).join(Agent, ImprovementSuggestion.agent_id == Agent.id),
        Agent,
        workspace_id,
    ).order_by(ImprovementSuggestion.created_at.desc())

    if agent_id:
        query = query.where(ImprovementSuggestion.agent_id == agent_id)

    if status_filter:
        query = query.where(ImprovementSuggestion.status == status_filter)

    result = await paginate(db, query, page=page, page_size=page_size)

    return ImprovementSuggestionListResponse(
        items=[
            ImprovementSuggestionResponse(
                id=s.id,
                agent_id=s.agent_id,
                source_version_id=s.source_version_id,
                suggested_prompt=s.suggested_prompt,
                suggested_greeting=s.suggested_greeting,
                mutation_type=s.mutation_type,
                analysis_summary=s.analysis_summary,
                expected_improvement=s.expected_improvement,
                status=s.status,
                reviewed_at=s.reviewed_at.isoformat() if s.reviewed_at else None,
                reviewed_by_id=s.reviewed_by_id,
                rejection_reason=s.rejection_reason,
                created_version_id=s.created_version_id,
                created_at=s.created_at.isoformat(),
            )
            for s in result.items
        ],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        pages=result.pages,
    )


@router.get("/pending-count")
async def get_pending_count(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, int]:
    """Get count of pending suggestions for the workspace."""
    result = await db.execute(
        apply_workspace_scope(
            select(func.count(ImprovementSuggestion.id)).join(
                Agent, ImprovementSuggestion.agent_id == Agent.id
            ),
            Agent,
            workspace_id,
        ).where(ImprovementSuggestion.status == "pending")
    )
    count = result.scalar() or 0

    return {"pending_count": count}


@router.get("/stats")
async def get_suggestion_stats(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, int]:
    """Get suggestion stats for the workspace.

    Returns approved_count, rejected_count, and auto_generated_count (current month).
    """
    # Approved count
    approved_result = await db.execute(
        apply_workspace_scope(
            select(func.count(ImprovementSuggestion.id)).join(
                Agent, ImprovementSuggestion.agent_id == Agent.id
            ),
            Agent,
            workspace_id,
        ).where(ImprovementSuggestion.status == "approved")
    )
    approved_count = approved_result.scalar() or 0

    # Rejected count
    rejected_result = await db.execute(
        apply_workspace_scope(
            select(func.count(ImprovementSuggestion.id)).join(
                Agent, ImprovementSuggestion.agent_id == Agent.id
            ),
            Agent,
            workspace_id,
        ).where(ImprovementSuggestion.status == "rejected")
    )
    rejected_count = rejected_result.scalar() or 0

    # Auto-generated count (current month)
    now = datetime.now(UTC)
    auto_generated_result = await db.execute(
        apply_workspace_scope(
            select(func.count(ImprovementSuggestion.id)).join(
                Agent, ImprovementSuggestion.agent_id == Agent.id
            ),
            Agent,
            workspace_id,
        ).where(
            extract("year", ImprovementSuggestion.created_at) == now.year,
            extract("month", ImprovementSuggestion.created_at) == now.month,
        )
    )
    auto_generated_count = auto_generated_result.scalar() or 0

    return {
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "auto_generated_count": auto_generated_count,
    }


@router.get("/{suggestion_id}", response_model=ImprovementSuggestionResponse)
async def get_suggestion(
    workspace_id: uuid.UUID,
    suggestion_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> ImprovementSuggestionResponse:
    """Get a specific improvement suggestion."""
    result = await db.execute(
        apply_workspace_scope(
            select(ImprovementSuggestion).join(Agent, ImprovementSuggestion.agent_id == Agent.id),
            Agent,
            workspace_id,
        ).where(ImprovementSuggestion.id == suggestion_id)
    )
    suggestion = result.scalar_one_or_none()

    if not suggestion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suggestion not found",
        )

    return ImprovementSuggestionResponse(
        id=suggestion.id,
        agent_id=suggestion.agent_id,
        source_version_id=suggestion.source_version_id,
        suggested_prompt=suggestion.suggested_prompt,
        suggested_greeting=suggestion.suggested_greeting,
        mutation_type=suggestion.mutation_type,
        analysis_summary=suggestion.analysis_summary,
        expected_improvement=suggestion.expected_improvement,
        status=suggestion.status,
        reviewed_at=suggestion.reviewed_at.isoformat() if suggestion.reviewed_at else None,
        reviewed_by_id=suggestion.reviewed_by_id,
        rejection_reason=suggestion.rejection_reason,
        created_version_id=suggestion.created_version_id,
        created_at=suggestion.created_at.isoformat(),
    )


@router.post("/{suggestion_id}/approve", response_model=ApproveResponse)
async def approve_suggestion(
    workspace_id: uuid.UUID,
    suggestion_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    activate: bool = Query(True),
) -> ApproveResponse:
    """Approve a suggestion and create a new prompt version.

    If activate=True (default), the new version is activated for A/B testing.
    """
    # Verify suggestion belongs to workspace
    result = await db.execute(
        apply_workspace_scope(
            select(ImprovementSuggestion).join(Agent, ImprovementSuggestion.agent_id == Agent.id),
            Agent,
            workspace_id,
        ).where(ImprovementSuggestion.id == suggestion_id)
    )
    suggestion = result.scalar_one_or_none()

    if not suggestion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suggestion not found",
        )

    try:
        service = PromptImprovementService()
        updated_suggestion, new_version = await service.approve_suggestion(
            db=db,
            suggestion_id=suggestion_id,
            user_id=current_user.id,
            activate=activate,
        )

        return ApproveResponse(
            suggestion=ImprovementSuggestionResponse(
                id=updated_suggestion.id,
                agent_id=updated_suggestion.agent_id,
                source_version_id=updated_suggestion.source_version_id,
                suggested_prompt=updated_suggestion.suggested_prompt,
                suggested_greeting=updated_suggestion.suggested_greeting,
                mutation_type=updated_suggestion.mutation_type,
                analysis_summary=updated_suggestion.analysis_summary,
                expected_improvement=updated_suggestion.expected_improvement,
                status=updated_suggestion.status,
                reviewed_at=updated_suggestion.reviewed_at.isoformat()
                if updated_suggestion.reviewed_at
                else None,
                reviewed_by_id=updated_suggestion.reviewed_by_id,
                rejection_reason=updated_suggestion.rejection_reason,
                created_version_id=updated_suggestion.created_version_id,
                created_at=updated_suggestion.created_at.isoformat(),
            ),
            created_version_id=new_version.id,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.post("/{suggestion_id}/reject", response_model=ImprovementSuggestionResponse)
async def reject_suggestion(
    workspace_id: uuid.UUID,
    suggestion_id: uuid.UUID,
    body: RejectSuggestionRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> ImprovementSuggestionResponse:
    """Reject a suggestion with optional reason."""
    # Verify suggestion belongs to workspace
    result = await db.execute(
        apply_workspace_scope(
            select(ImprovementSuggestion).join(Agent, ImprovementSuggestion.agent_id == Agent.id),
            Agent,
            workspace_id,
        ).where(ImprovementSuggestion.id == suggestion_id)
    )
    suggestion = result.scalar_one_or_none()

    if not suggestion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suggestion not found",
        )

    try:
        service = PromptImprovementService()
        updated = await service.reject_suggestion(
            db=db,
            suggestion_id=suggestion_id,
            user_id=current_user.id,
            reason=body.reason,
        )

        return ImprovementSuggestionResponse(
            id=updated.id,
            agent_id=updated.agent_id,
            source_version_id=updated.source_version_id,
            suggested_prompt=updated.suggested_prompt,
            suggested_greeting=updated.suggested_greeting,
            mutation_type=updated.mutation_type,
            analysis_summary=updated.analysis_summary,
            expected_improvement=updated.expected_improvement,
            status=updated.status,
            reviewed_at=updated.reviewed_at.isoformat() if updated.reviewed_at else None,
            reviewed_by_id=updated.reviewed_by_id,
            rejection_reason=updated.rejection_reason,
            created_version_id=updated.created_version_id,
            created_at=updated.created_at.isoformat(),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


# =============================================================================
# Agent-specific endpoints for generating suggestions
# =============================================================================


@router.post("/agents/{agent_id}/generate", response_model=list[ImprovementSuggestionResponse])
async def generate_suggestions_for_agent(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    body: GenerateSuggestionsRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> list[ImprovementSuggestionResponse]:
    """Generate improvement suggestions for an agent's active prompt.

    Analyzes recent call performance and generates AI-powered improvement suggestions.
    """
    # Verify agent exists and belongs to workspace
    agent = await get_or_404(db, Agent, agent_id, workspace_id=workspace_id)

    # Get active version
    result = await db.execute(
        select(PromptVersion).where(
            PromptVersion.agent_id == agent_id,
            PromptVersion.is_active.is_(True),
            PromptVersion.arm_status == "active",
        )
    )
    active_version = result.scalar_one_or_none()

    if not active_version:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active prompt version found for this agent",
        )

    # Check minimum calls
    if active_version.total_calls < agent.auto_improve_min_calls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Need at least {agent.auto_improve_min_calls} calls "
            f"(current: {active_version.total_calls})",
        )

    service = PromptImprovementService()

    # Analyze performance
    analysis = await service.analyze_performance(db, active_version)

    # Generate variations
    variations = await service.generate_variations(
        active_version, analysis, num_variations=body.num_suggestions
    )

    # Create suggestions
    suggestions: list[ImprovementSuggestionResponse] = []
    for variation in variations:
        suggestion = await service.create_suggestion(
            db=db,
            version=active_version,
            variation=variation,
            analysis_summary=analysis.summary,
        )
        suggestions.append(
            ImprovementSuggestionResponse(
                id=suggestion.id,
                agent_id=suggestion.agent_id,
                source_version_id=suggestion.source_version_id,
                suggested_prompt=suggestion.suggested_prompt,
                suggested_greeting=suggestion.suggested_greeting,
                mutation_type=suggestion.mutation_type,
                analysis_summary=suggestion.analysis_summary,
                expected_improvement=suggestion.expected_improvement,
                status=suggestion.status,
                reviewed_at=None,
                reviewed_by_id=None,
                rejection_reason=None,
                created_version_id=None,
                created_at=suggestion.created_at.isoformat(),
            )
        )

    await db.commit()

    return suggestions
