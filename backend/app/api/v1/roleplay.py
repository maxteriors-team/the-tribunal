"""Practice-arena (roleplay) endpoints.

Lets operators rehearse a configured AI agent (or a human rep) against synthetic
prospect personas and get a scored rehearsal report before the agent talks to
real leads. Distinct from the internal IVR navigation harness.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import DB, CurrentUser, get_workspace, require_route_capabilities
from app.core.permissions import Capability
from app.models.workspace import Workspace
from app.schemas.roleplay import (
    CreateRehearsalRequest,
    HumanTurnRequest,
    ProspectPersonaCreate,
    ProspectPersonaResponse,
    ProspectPersonaUpdate,
    RehearsalRunResponse,
    RehearsalRunSummary,
)
from app.services.ai.roleplay import RoleplayService
from app.services.exceptions import NotFoundError, ValidationError

router = APIRouter(
    dependencies=[Depends(require_route_capabilities(Capability.CRM_READ, Capability.CRM_READ))]
)


# === Personas ===


@router.get("/personas", response_model=list[ProspectPersonaResponse])
async def list_personas(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> list[ProspectPersonaResponse]:
    """List built-in templates plus this workspace's custom personas."""
    personas = await RoleplayService(db).list_personas(workspace_id)
    return [ProspectPersonaResponse.model_validate(p) for p in personas]


@router.post(
    "/personas",
    response_model=ProspectPersonaResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_persona(
    workspace_id: uuid.UUID,
    persona_in: ProspectPersonaCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> ProspectPersonaResponse:
    """Create a custom prospect persona."""
    try:
        persona = await RoleplayService(db).create_persona(workspace_id, persona_in.model_dump())
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return ProspectPersonaResponse.model_validate(persona)


@router.get("/personas/{persona_id}", response_model=ProspectPersonaResponse)
async def get_persona(
    workspace_id: uuid.UUID,
    persona_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> ProspectPersonaResponse:
    """Get a persona by ID."""
    try:
        persona = await RoleplayService(db).get_persona(persona_id, workspace_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    return ProspectPersonaResponse.model_validate(persona)


@router.put("/personas/{persona_id}", response_model=ProspectPersonaResponse)
async def update_persona(
    workspace_id: uuid.UUID,
    persona_id: uuid.UUID,
    persona_in: ProspectPersonaUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> ProspectPersonaResponse:
    """Update a custom persona (built-ins are read-only)."""
    try:
        persona = await RoleplayService(db).update_persona(
            persona_id, workspace_id, persona_in.model_dump(exclude_unset=True)
        )
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return ProspectPersonaResponse.model_validate(persona)


@router.delete("/personas/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_persona(
    workspace_id: uuid.UUID,
    persona_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Delete a custom persona."""
    try:
        await RoleplayService(db).delete_persona(persona_id, workspace_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


# === Rehearsal runs ===


@router.get("/runs", response_model=list[RehearsalRunSummary])
async def list_runs(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    agent_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> list[RehearsalRunSummary]:
    """List rehearsal runs (newest first)."""
    runs = await RoleplayService(db).list_runs(workspace_id, agent_id=agent_id, limit=limit)
    return [RehearsalRunSummary.model_validate(r) for r in runs]


@router.post("/runs", response_model=RehearsalRunResponse, status_code=status.HTTP_201_CREATED)
async def create_run(
    workspace_id: uuid.UUID,
    run_in: CreateRehearsalRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> RehearsalRunResponse:
    """Start a rehearsal.

    For ``rehearsee == "ai"`` the full conversation is simulated and scored
    inline before responding. For ``rehearsee == "human"`` the run is returned
    with the prospect's opening line so a rep can reply via ``/runs/{id}/turn``.
    """
    try:
        run = await RoleplayService(db).create_run(
            workspace_id,
            agent_id=run_in.agent_id,
            persona_id=run_in.persona_id,
            rehearsee=run_in.rehearsee,
            channel=run_in.channel,
            max_turns=run_in.max_turns,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return RehearsalRunResponse.model_validate(run)


@router.get("/runs/{run_id}", response_model=RehearsalRunResponse)
async def get_run(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> RehearsalRunResponse:
    """Get a rehearsal run with transcript and report."""
    try:
        run = await RoleplayService(db).get_run(run_id, workspace_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    return RehearsalRunResponse.model_validate(run)


@router.post("/runs/{run_id}/turn", response_model=RehearsalRunResponse)
async def advance_human_turn(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    turn_in: HumanTurnRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> RehearsalRunResponse:
    """Submit a human rep's reply and get the prospect's response."""
    try:
        run = await RoleplayService(db).advance_human_turn(run_id, workspace_id, turn_in.message)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return RehearsalRunResponse.model_validate(run)


@router.post("/runs/{run_id}/score", response_model=RehearsalRunResponse)
async def score_run(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> RehearsalRunResponse:
    """Score a rehearsal and finalize the report."""
    try:
        run = await RoleplayService(db).score_run(run_id, workspace_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return RehearsalRunResponse.model_validate(run)


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Delete a rehearsal run."""
    try:
        await RoleplayService(db).delete_run(run_id, workspace_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
