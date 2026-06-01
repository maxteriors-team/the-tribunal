"""Credential storage helpers for realtor onboarding integrations."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_json, encrypt_json
from app.db.scope import apply_workspace_scope
from app.models.workspace import WorkspaceIntegration

logger = structlog.get_logger()

CALCOM_INTEGRATION_TYPE = "calcom"
FOLLOWUPBOSS_INTEGRATION_TYPE = "followupboss"


async def upsert_workspace_integration_credentials(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    integration_type: str,
    credentials: dict[str, Any],
) -> WorkspaceIntegration:
    """Create or reactivate a workspace integration with encrypted credentials."""
    result = await db.execute(
        apply_workspace_scope(
            select(WorkspaceIntegration),
            WorkspaceIntegration,
            workspace_id,
        ).where(WorkspaceIntegration.integration_type == integration_type)
    )
    existing = result.scalar_one_or_none()
    encrypted_credentials = encrypt_json(credentials)

    if existing is not None:
        existing.encrypted_credentials = encrypted_credentials
        existing.is_active = True
        return existing

    integration = WorkspaceIntegration(
        workspace_id=workspace_id,
        integration_type=integration_type,
        encrypted_credentials=encrypted_credentials,
        is_active=True,
    )
    db.add(integration)
    return integration


async def store_calcom_credentials(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    api_key: str,
) -> WorkspaceIntegration:
    """Store or update the Cal.com API key for a workspace."""
    return await upsert_workspace_integration_credentials(
        db=db,
        workspace_id=workspace_id,
        integration_type=CALCOM_INTEGRATION_TYPE,
        credentials={"api_key": api_key},
    )


async def store_followupboss_credentials(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    api_key: str,
) -> WorkspaceIntegration:
    """Store or update the Follow Up Boss API key for a workspace."""
    return await upsert_workspace_integration_credentials(
        db=db,
        workspace_id=workspace_id,
        integration_type=FOLLOWUPBOSS_INTEGRATION_TYPE,
        credentials={"api_key": api_key},
    )


async def get_workspace_calcom_api_key(
    workspace_id: uuid.UUID,
    db: AsyncSession,
) -> str | None:
    """Return the active stored Cal.com API key for a workspace, if present."""
    result = await db.execute(
        apply_workspace_scope(
            select(WorkspaceIntegration),
            WorkspaceIntegration,
            workspace_id,
        ).where(
            WorkspaceIntegration.integration_type == CALCOM_INTEGRATION_TYPE,
            WorkspaceIntegration.is_active.is_(True),
        )
    )
    integration = result.scalar_one_or_none()
    if integration is None:
        return None

    try:
        credentials = decrypt_json(integration.encrypted_credentials)
    except Exception as exc:  # pragma: no cover - defensive corrupt-row guard
        logger.warning(
            "calcom_credentials_decrypt_failed",
            workspace_id=str(workspace_id),
            error=str(exc),
        )
        return None

    api_key = credentials.get("api_key")
    return api_key if isinstance(api_key, str) and api_key else None
