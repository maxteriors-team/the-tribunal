"""Authenticated OpenAI Realtime token endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import DB, CurrentUser, get_workspace
from app.core.config import settings
from app.models.workspace import Workspace
from app.services.agents import AgentService
from app.services.ai.openai_credentials import OpenAICredentialError, resolve_openai_credentials
from app.services.ai.openai_realtime_config import (
    build_client_secret_request,
    build_realtime_session_config,
    extract_realtime_client_secret_value,
)
from app.services.ai.voice_tools import get_tools_from_agent_config

router = APIRouter()
logger = structlog.get_logger()


class RealtimeTokenRequest(BaseModel):
    """Optional test-session overrides for a Realtime client secret."""

    voice: str | None = None
    instructions: str | None = None
    turn_detection_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    silence_duration_ms: int | None = Field(default=None, ge=100, le=5000)
    initial_greeting: str | None = None


class RealtimeTokenResponse(BaseModel):
    """Realtime client secret response."""

    client_secret: dict[str, str]
    model: str
    agent: dict[str, str | None]
    tools: list[dict[str, object]]


@router.post("/token/{agent_id}", response_model=RealtimeTokenResponse)
async def create_realtime_token(
    agent_id: uuid.UUID,
    body: RealtimeTokenRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    workspace_id: uuid.UUID = Query(...),
) -> RealtimeTokenResponse:
    """Create an authenticated OpenAI Realtime client secret for voice testing."""
    del current_user, workspace

    agent = await AgentService(db).get_agent(workspace_id, agent_id)
    tools = get_tools_from_agent_config(
        agent,
        enable_booking=bool(agent.calcom_event_type_id),
    )
    instructions = body.instructions or agent.system_prompt

    try:
        credential_context = await resolve_openai_credentials(db, workspace_id)
    except OpenAICredentialError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice service not configured",
        ) from None

    session_config = build_realtime_session_config(
        instructions=instructions,
        voice=body.voice or agent.voice_id,
        turn_detection_mode=agent.turn_detection_mode,
        turn_detection_threshold=body.turn_detection_threshold
        if body.turn_detection_threshold is not None
        else agent.turn_detection_threshold,
        silence_duration_ms=body.silence_duration_ms
        if body.silence_duration_ms is not None
        else agent.silence_duration_ms,
        idle_timeout_ms=settings.openai_realtime_idle_timeout_ms,
        language=agent.language,
        tools=tools,
    )
    client_secret_body = build_client_secret_request(session=session_config)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.openai.com/v1/realtime/client_secrets",
            headers={
                **credential_context.openai_headers(),
                "Content-Type": "application/json",
            },
            json=client_secret_body,
            timeout=30.0,
        )

    if response.status_code != httpx.codes.OK:
        logger.error(
            "openai_realtime_token_error",
            status=response.status_code,
            credential_source=credential_context.source,
            agent_id=str(agent_id),
            workspace_id=str(workspace_id),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to create voice session",
        )

    try:
        session_data = response.json()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to create voice session",
        ) from None

    return RealtimeTokenResponse(
        client_secret={"value": extract_realtime_client_secret_value(session_data) or ""},
        model=session_config["model"],
        agent={
            "id": str(agent.id),
            "name": agent.name,
            "voice": body.voice or agent.voice_id,
            "language": agent.language,
            "initial_greeting": body.initial_greeting or agent.initial_greeting,
        },
        tools=[dict(tool) for tool in tools if tool.get("type") == "function"],
    )


@router.get("/token/{agent_id}", response_model=RealtimeTokenResponse)
async def get_realtime_token_compat(
    agent_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    workspace_id: uuid.UUID = Query(...),
) -> RealtimeTokenResponse:
    """Temporary GET compatibility wrapper for older voice-test callers."""
    return await create_realtime_token(
        agent_id=agent_id,
        workspace_id=workspace_id,
        body=RealtimeTokenRequest(),
        current_user=current_user,
        db=db,
        workspace=workspace,
    )
