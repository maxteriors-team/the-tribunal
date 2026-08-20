"""Prompt version management endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DB, CurrentUser, get_workspace, require_route_capabilities
from app.api.service_errors import ServiceErrorRoute
from app.core.permissions import Capability
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
    VersionComparisonResponse,
    WinnerDetectionResponse,
)
from app.services.ai.prompt_version_lifecycle_service import PromptVersionLifecycleService

router = APIRouter(
    route_class=ServiceErrorRoute,
    dependencies=[
        Depends(require_route_capabilities(Capability.CRM_READ, Capability.WORKSPACE_MANAGE))
    ],
)


def _prompt_version_service() -> PromptVersionLifecycleService:
    """Return the prompt version lifecycle service for route adapters."""
    return PromptVersionLifecycleService()


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
    return await _prompt_version_service().list_versions(
        db,
        workspace_id,
        agent_id,
        page=page,
        page_size=page_size,
    )


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
    return await _prompt_version_service().list_active_versions(db, workspace_id, agent_id)


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
    return await _prompt_version_service().create_version_for_agent(
        db,
        workspace_id,
        agent_id,
        body,
        created_by_id=current_user.id,
    )


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
    return await _prompt_version_service().compare_versions_in_workspace(
        db,
        workspace_id,
        agent_id,
        winner_threshold=winner_threshold,
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
    return await _prompt_version_service().detect_winner_in_workspace(
        db,
        workspace_id,
        agent_id,
        threshold=threshold,
    )


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
    return await _prompt_version_service().get_version(db, workspace_id, agent_id, version_id)


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
    return await _prompt_version_service().update_version(
        db,
        workspace_id,
        agent_id,
        version_id,
        body,
    )


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
    return await _prompt_version_service().activate_version_for_agent(
        db,
        workspace_id,
        agent_id,
        version_id,
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
    return await _prompt_version_service().rollback_agent_to_version(
        db,
        workspace_id,
        agent_id,
        version_id,
        created_by_id=current_user.id,
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
    return await _prompt_version_service().get_version_stats(
        db,
        workspace_id,
        agent_id,
        version_id,
        days=days,
    )


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
    return await _prompt_version_service().activate_for_testing_in_workspace(
        db,
        workspace_id,
        agent_id,
        version_id,
    )


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
    return await _prompt_version_service().deactivate_version_in_workspace(
        db,
        workspace_id,
        agent_id,
        version_id,
    )


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
    return await _prompt_version_service().pause_version_in_workspace(
        db,
        workspace_id,
        agent_id,
        version_id,
    )


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
    return await _prompt_version_service().resume_version_in_workspace(
        db,
        workspace_id,
        agent_id,
        version_id,
    )


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
    return await _prompt_version_service().eliminate_version_in_workspace(
        db,
        workspace_id,
        agent_id,
        version_id,
    )


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
    return await _prompt_version_service().update_arm_status_in_workspace(
        db,
        workspace_id,
        agent_id,
        version_id,
        body,
    )
