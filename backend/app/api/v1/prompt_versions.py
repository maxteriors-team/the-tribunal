"""Prompt version management endpoints."""

import uuid
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.crud import get_or_404
from app.api.deps import DB, CurrentUser, get_workspace
from app.db.pagination import paginate
from app.models.agent import Agent
from app.models.prompt_version import PromptVersion
from app.models.prompt_version_stats import PromptVersionStats
from app.models.workspace import Workspace
from app.schemas.prompt_version import (
    ArmStatusUpdate,
    PromptVersionActivateResponse,
    PromptVersionCreate,
    PromptVersionListResponse,
    PromptVersionResponse,
    PromptVersionRollbackResponse,
    PromptVersionStatsResponse,
    PromptVersionUpdate,
    VersionComparisonItem,
    VersionComparisonResponse,
    WinnerDetectionResponse,
)
from app.services.ai.bandit_statistics import BanditStatisticsService
from app.services.ai.prompt_version_service import PromptVersionService

router = APIRouter()


@router.get("", response_model=PromptVersionListResponse)
async def list_prompt_versions(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> PromptVersionListResponse:
    """List all prompt versions for an agent."""
    # Verify agent exists and belongs to workspace
    await get_or_404(db, Agent, agent_id, workspace_id=workspace_id)

    query = (
        select(PromptVersion)
        .where(PromptVersion.agent_id == agent_id)
        .order_by(PromptVersion.version_number.desc())
    )

    result = await paginate(db, query, page=page, page_size=page_size)

    return PromptVersionListResponse(**result.to_response(PromptVersionResponse))


@router.get("/active", response_model=list[PromptVersionResponse])
async def get_active_prompt_versions(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> list[PromptVersionResponse]:
    """Get all active prompt versions for an agent.

    Returns versions that are is_active=True and arm_status='active'.
    For single-version mode, returns a list with one item.
    For multi-variant A/B testing, returns all active variants.
    """
    await get_or_404(db, Agent, agent_id, workspace_id=workspace_id)

    service = PromptVersionService()
    active_versions = await service.get_active_versions(db, agent_id)

    return [PromptVersionResponse.model_validate(v) for v in active_versions]


@router.post("", response_model=PromptVersionResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt_version(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    body: PromptVersionCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> PromptVersionResponse:
    """Create a new prompt version.

    If system_prompt is not provided, snapshots from the current agent settings.
    """
    await get_or_404(db, Agent, agent_id, workspace_id=workspace_id)

    service = PromptVersionService()
    version = await service.create_version(
        db=db,
        agent_id=agent_id,
        system_prompt=body.system_prompt,
        initial_greeting=body.initial_greeting,
        temperature=body.temperature,
        change_summary=body.change_summary,
        created_by_id=current_user.id,
        is_baseline=body.is_baseline,
        activate=False,
        traffic_percentage=body.traffic_percentage,
        experiment_id=body.experiment_id,
    )

    return PromptVersionResponse.model_validate(version)


@router.get("/{version_id}", response_model=PromptVersionResponse)
async def get_prompt_version(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> PromptVersionResponse:
    """Get a specific prompt version."""
    await get_or_404(db, Agent, agent_id, workspace_id=workspace_id)

    result = await db.execute(
        select(PromptVersion).where(
            PromptVersion.id == version_id,
            PromptVersion.agent_id == agent_id,
        )
    )
    version = result.scalar_one_or_none()

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt version not found",
        )

    return PromptVersionResponse.model_validate(version)


@router.put("/{version_id}", response_model=PromptVersionResponse)
async def update_prompt_version(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    body: PromptVersionUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> PromptVersionResponse:
    """Update prompt version metadata (change_summary, is_baseline only)."""
    await get_or_404(db, Agent, agent_id, workspace_id=workspace_id)

    result = await db.execute(
        select(PromptVersion).where(
            PromptVersion.id == version_id,
            PromptVersion.agent_id == agent_id,
        )
    )
    version = result.scalar_one_or_none()

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt version not found",
        )

    if body.change_summary is not None:
        version.change_summary = body.change_summary

    if body.is_baseline is not None:
        version.is_baseline = body.is_baseline

    if body.traffic_percentage is not None:
        version.traffic_percentage = body.traffic_percentage

    if body.experiment_id is not None:
        version.experiment_id = body.experiment_id

    await db.commit()
    await db.refresh(version)

    return PromptVersionResponse.model_validate(version)


@router.post("/{version_id}/activate", response_model=PromptVersionActivateResponse)
async def activate_prompt_version(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> PromptVersionActivateResponse:
    """Activate a prompt version, deactivating any currently active version."""
    await get_or_404(db, Agent, agent_id, workspace_id=workspace_id)

    # Verify version belongs to agent
    result = await db.execute(
        select(PromptVersion).where(
            PromptVersion.id == version_id,
            PromptVersion.agent_id == agent_id,
        )
    )
    version = result.scalar_one_or_none()

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt version not found",
        )

    service = PromptVersionService()
    activated, deactivated_id = await service.activate_version(db, version_id)

    return PromptVersionActivateResponse(
        activated_version=PromptVersionResponse.model_validate(activated),
        deactivated_version_id=deactivated_id,
    )


@router.post("/{version_id}/rollback", response_model=PromptVersionRollbackResponse)
async def rollback_to_version(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> PromptVersionRollbackResponse:
    """Rollback to a previous prompt version by creating a new version with its content."""
    await get_or_404(db, Agent, agent_id, workspace_id=workspace_id)

    # Verify version belongs to agent
    result = await db.execute(
        select(PromptVersion).where(
            PromptVersion.id == version_id,
            PromptVersion.agent_id == agent_id,
        )
    )
    version = result.scalar_one_or_none()

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt version not found",
        )

    service = PromptVersionService()
    new_version = await service.rollback_to_version(
        db=db,
        version_id=version_id,
        created_by_id=current_user.id,
    )

    return PromptVersionRollbackResponse(
        new_version=PromptVersionResponse.model_validate(new_version),
        rolled_back_from=version_id,
    )


@router.get("/{version_id}/stats", response_model=PromptVersionStatsResponse)
async def get_prompt_version_stats(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    days: int = Query(30, ge=1, le=365),
) -> PromptVersionStatsResponse:
    """Get aggregated performance stats for a prompt version."""
    await get_or_404(db, Agent, agent_id, workspace_id=workspace_id)

    result = await db.execute(
        select(PromptVersion).where(
            PromptVersion.id == version_id,
            PromptVersion.agent_id == agent_id,
        )
    )
    version = result.scalar_one_or_none()

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt version not found",
        )

    # Calculate date range
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    # Aggregate stats from daily stats table
    stats_result = await db.execute(
        select(
            func.sum(PromptVersionStats.total_calls).label("total_calls"),
            func.sum(PromptVersionStats.completed_calls).label("completed_calls"),
            func.sum(PromptVersionStats.failed_calls).label("failed_calls"),
            func.sum(PromptVersionStats.appointments_booked).label("appointments_booked"),
            func.sum(PromptVersionStats.leads_qualified).label("leads_qualified"),
            func.avg(PromptVersionStats.avg_duration_seconds).label("avg_duration"),
            func.avg(PromptVersionStats.avg_quality_score).label("avg_quality"),
            func.min(PromptVersionStats.stat_date).label("min_date"),
            func.max(PromptVersionStats.stat_date).label("max_date"),
        ).where(
            PromptVersionStats.prompt_version_id == version_id,
            PromptVersionStats.stat_date >= start_date,
            PromptVersionStats.stat_date <= end_date,
        )
    )
    row = stats_result.one()

    total_calls = row.total_calls or 0
    completed_calls = row.completed_calls or 0
    appointments = row.appointments_booked or 0
    qualified = row.leads_qualified or 0

    # Calculate rates
    booking_rate = (appointments / completed_calls) if completed_calls > 0 else None
    qual_rate = (qualified / completed_calls) if completed_calls > 0 else None
    completion_rate = (completed_calls / total_calls) if total_calls > 0 else None

    # Fall back to denormalized counters if no daily stats
    if total_calls == 0:
        total_calls = version.total_calls
        completed_calls = version.successful_calls
        appointments = version.booked_appointments
        booking_rate = (appointments / completed_calls) if completed_calls > 0 else None
        completion_rate = (completed_calls / total_calls) if total_calls > 0 else None

    return PromptVersionStatsResponse(
        prompt_version_id=version.id,
        version_number=version.version_number,
        is_active=version.is_active,
        is_baseline=version.is_baseline,
        total_calls=total_calls,
        completed_calls=completed_calls,
        failed_calls=row.failed_calls or 0,
        appointments_booked=appointments,
        leads_qualified=qualified,
        booking_rate=booking_rate,
        qualification_rate=qual_rate,
        completion_rate=completion_rate,
        avg_duration_seconds=row.avg_duration,
        avg_quality_score=row.avg_quality,
        stats_from=datetime.combine(row.min_date, datetime.min.time()) if row.min_date else None,
        stats_to=datetime.combine(row.max_date, datetime.min.time()) if row.max_date else None,
    )


# =============================================================================
# Multi-Variant A/B Testing Endpoints
# =============================================================================


@router.post("/{version_id}/activate-for-testing", response_model=PromptVersionResponse)
async def activate_version_for_testing(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> PromptVersionResponse:
    """Activate a version for A/B testing without deactivating others.

    Unlike the standard activate endpoint, this allows multiple versions
    to be active simultaneously for multi-variant testing.
    """
    await get_or_404(db, Agent, agent_id, workspace_id=workspace_id)

    result = await db.execute(
        select(PromptVersion).where(
            PromptVersion.id == version_id,
            PromptVersion.agent_id == agent_id,
        )
    )
    version = result.scalar_one_or_none()

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt version not found",
        )

    service = PromptVersionService()
    activated = await service.activate_for_testing(db, version_id)

    return PromptVersionResponse.model_validate(activated)


@router.post("/{version_id}/deactivate", response_model=PromptVersionResponse)
async def deactivate_prompt_version(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> PromptVersionResponse:
    """Deactivate a version without eliminating it."""
    await get_or_404(db, Agent, agent_id, workspace_id=workspace_id)

    result = await db.execute(
        select(PromptVersion).where(
            PromptVersion.id == version_id,
            PromptVersion.agent_id == agent_id,
        )
    )
    version = result.scalar_one_or_none()

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt version not found",
        )

    service = PromptVersionService()
    deactivated = await service.deactivate_version(db, version_id)

    return PromptVersionResponse.model_validate(deactivated)


@router.post("/{version_id}/pause", response_model=PromptVersionResponse)
async def pause_prompt_version(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> PromptVersionResponse:
    """Pause a version (temporarily exclude from bandit selection)."""
    await get_or_404(db, Agent, agent_id, workspace_id=workspace_id)

    result = await db.execute(
        select(PromptVersion).where(
            PromptVersion.id == version_id,
            PromptVersion.agent_id == agent_id,
        )
    )
    version = result.scalar_one_or_none()

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt version not found",
        )

    try:
        service = PromptVersionService()
        paused = await service.pause_version(db, version_id)
        return PromptVersionResponse.model_validate(paused)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.post("/{version_id}/resume", response_model=PromptVersionResponse)
async def resume_prompt_version(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> PromptVersionResponse:
    """Resume a paused version."""
    await get_or_404(db, Agent, agent_id, workspace_id=workspace_id)

    result = await db.execute(
        select(PromptVersion).where(
            PromptVersion.id == version_id,
            PromptVersion.agent_id == agent_id,
        )
    )
    version = result.scalar_one_or_none()

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt version not found",
        )

    try:
        service = PromptVersionService()
        resumed = await service.resume_version(db, version_id)
        return PromptVersionResponse.model_validate(resumed)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.post("/{version_id}/eliminate", response_model=PromptVersionResponse)
async def eliminate_prompt_version(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> PromptVersionResponse:
    """Eliminate a version from A/B testing permanently.

    This is a terminal state - eliminated versions cannot be reactivated.
    Use this when statistical analysis shows a version is clearly inferior.
    """
    await get_or_404(db, Agent, agent_id, workspace_id=workspace_id)

    result = await db.execute(
        select(PromptVersion).where(
            PromptVersion.id == version_id,
            PromptVersion.agent_id == agent_id,
        )
    )
    version = result.scalar_one_or_none()

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt version not found",
        )

    service = PromptVersionService()
    eliminated = await service.eliminate_version(db, version_id)

    return PromptVersionResponse.model_validate(eliminated)


@router.put("/{version_id}/arm-status", response_model=PromptVersionResponse)
async def update_arm_status(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    body: ArmStatusUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> PromptVersionResponse:
    """Update the arm status of a version.

    Valid statuses: active, paused, eliminated
    """
    await get_or_404(db, Agent, agent_id, workspace_id=workspace_id)

    result = await db.execute(
        select(PromptVersion).where(
            PromptVersion.id == version_id,
            PromptVersion.agent_id == agent_id,
        )
    )
    version = result.scalar_one_or_none()

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt version not found",
        )

    try:
        service = PromptVersionService()
        updated = await service.update_arm_status(db, version_id, body.arm_status)
        return PromptVersionResponse.model_validate(updated)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


# =============================================================================
# Statistical Comparison Endpoints
# =============================================================================


@router.get("/compare", response_model=VersionComparisonResponse)
async def compare_versions(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    winner_threshold: float = Query(0.95, ge=0.5, le=0.999),
) -> VersionComparisonResponse:
    """Compare all active versions with statistical analysis.

    Returns probability each version is best, credible intervals,
    and recommended actions (continue, declare_winner, eliminate_worst).
    """
    await get_or_404(db, Agent, agent_id, workspace_id=workspace_id)

    # Get all active versions
    service = PromptVersionService()
    active_versions = await service.get_active_versions(db, agent_id)

    if not active_versions:
        return VersionComparisonResponse(
            versions=[],
            winner_id=None,
            winner_probability=None,
            recommended_action="no_versions",
            min_samples_needed=0,
        )

    # Run statistical comparison
    stats_service = BanditStatisticsService()
    comparison = stats_service.compare_versions(active_versions, winner_threshold=winner_threshold)

    # Convert to response format
    version_items = [
        VersionComparisonItem(
            version_id=v.version_id,
            version_number=v.version_number,
            is_active=v.is_active,
            is_baseline=v.is_baseline,
            arm_status=v.arm_status,
            probability_best=v.probability_best,
            credible_interval_lower=v.credible_interval[0],
            credible_interval_upper=v.credible_interval[1],
            sample_size=v.sample_size,
            booking_rate=v.booking_rate,
            mean_estimate=v.mean_estimate,
        )
        for v in comparison.versions
    ]

    return VersionComparisonResponse(
        versions=version_items,
        winner_id=comparison.winner_id,
        winner_probability=comparison.winner_probability,
        recommended_action=comparison.recommended_action,
        min_samples_needed=comparison.min_samples_needed,
    )


@router.get("/winner", response_model=WinnerDetectionResponse)
async def detect_winner(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    threshold: float = Query(0.95, ge=0.5, le=0.999),
) -> WinnerDetectionResponse:
    """Check if a statistical winner can be declared.

    A winner is declared when one version has probability > threshold
    of being the best performing version.
    """
    await get_or_404(db, Agent, agent_id, workspace_id=workspace_id)

    # Get all active versions
    service = PromptVersionService()
    active_versions = await service.get_active_versions(db, agent_id)

    if not active_versions:
        return WinnerDetectionResponse(
            winner_id=None,
            winner_probability=None,
            confidence_threshold=threshold,
            is_conclusive=False,
            message="No active versions to compare",
        )

    # Detect winner
    stats_service = BanditStatisticsService()
    result = stats_service.detect_winner(active_versions, threshold=threshold)

    return WinnerDetectionResponse(
        winner_id=result.winner_id,
        winner_probability=result.winner_probability,
        confidence_threshold=result.confidence_threshold,
        is_conclusive=result.is_conclusive,
        message=result.message,
    )
