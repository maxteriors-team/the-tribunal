"""API Key management endpoints."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_workspace
from app.db.session import get_db
from app.models.api_key import APIKey
from app.models.workspace import Workspace
from app.schemas.api_key import APIKeyCreate, APIKeyCreated, APIKeyResponse

router = APIRouter()


def _hash_api_key(key: str) -> str:
    """Hash an API key using SHA-256."""
    return hashlib.sha256(key.encode()).hexdigest()


@router.post("/", response_model=APIKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: APIKeyCreate,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Create a new API key. The plaintext key is only shown once."""
    # Generate a secure random key
    raw_key = f"trib_{secrets.token_urlsafe(32)}"
    key_prefix = raw_key[:8]
    key_hash = _hash_api_key(raw_key)

    expires_at = None
    if body.expires_in_days:
        expires_at = datetime.now(UTC) + timedelta(days=body.expires_in_days)

    api_key = APIKey(
        workspace_id=workspace.id,
        user_id=current_user.id,
        name=body.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        expires_at=expires_at,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return {
        "id": api_key.id,
        "name": api_key.name,
        "key": raw_key,
        "key_prefix": key_prefix,
    }


@router.get("/", response_model=list[APIKeyResponse])
async def list_api_keys(
    workspace: Annotated[Workspace, Depends(get_workspace)],
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[APIKey]:
    """List all API keys for this workspace (redacted)."""
    result = await db.execute(
        select(APIKey).where(APIKey.workspace_id == workspace.id).order_by(APIKey.created_at.desc())
    )
    return list(result.scalars().all())


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: uuid.UUID,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Revoke (deactivate) an API key."""
    result = await db.execute(
        select(APIKey).where(
            APIKey.id == key_id,
            APIKey.workspace_id == workspace.id,
        )
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

    api_key.is_active = False
    await db.commit()
