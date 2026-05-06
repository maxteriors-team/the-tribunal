"""API dependencies."""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.api_key import APIKey
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Get the current authenticated user via API key or JWT."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    user = await _user_from_api_key(request, db)
    if user is None and token is not None:
        user = await _user_from_jwt(token, db)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Get the current active user."""
    return current_user


async def get_optional_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    """Get the current user if authenticated, None otherwise."""
    user = await _user_from_api_key(request, db)
    if user is not None:
        return user

    if token is None:
        return None

    return await _user_from_jwt(token, db)


async def _user_from_api_key(request: Request, db: AsyncSession) -> User | None:
    """Attempt to authenticate via X-API-Key header. Returns None if not present/invalid.

    On success, stashes the API key's workspace binding on ``request.state`` so
    downstream workspace-resolution dependencies can enforce that the key is only
    used against its own workspace. Without this binding, an API key issued for
    workspace A would silently grant the underlying user access to every other
    workspace they belong to (privilege escalation).
    """
    api_key_header = request.headers.get("X-API-Key")
    if not api_key_header:
        return None

    key_hash = hashlib.sha256(api_key_header.encode()).hexdigest()
    result = await db.execute(
        select(APIKey).where(APIKey.key_hash == key_hash, APIKey.is_active == True)  # noqa: E712
    )
    api_key_obj = result.scalar_one_or_none()
    if api_key_obj is None:
        return None
    if api_key_obj.expires_at and api_key_obj.expires_at < datetime.now(UTC):
        return None

    user_result = await db.execute(select(User).where(User.id == api_key_obj.user_id))
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None

    # Bind this request to the API key's workspace. Workspace-resolving deps
    # MUST consult this and reject mismatched workspace_id path params.
    request.state.api_key_workspace_id = api_key_obj.workspace_id
    return user


def _enforce_api_key_workspace(request: Request, workspace_id: uuid.UUID) -> None:
    """If auth came from an API key, require its workspace_id to match the URL.

    API keys are workspace-scoped (see :class:`app.models.api_key.APIKey`). A key
    issued for workspace A must not authorize access to workspace B, even when the
    underlying user is a member of both. Raises 403 on mismatch.
    """
    api_key_workspace_id: uuid.UUID | None = getattr(
        request.state, "api_key_workspace_id", None
    )
    if api_key_workspace_id is not None and api_key_workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key is not authorized for this workspace",
        )


async def _user_from_jwt(token: str, db: AsyncSession) -> User | None:
    """Attempt to authenticate via JWT Bearer token. Returns None if invalid."""
    payload = decode_access_token(token)
    if payload is None:
        return None

    user_id_str: str | None = payload.get("sub")
    if user_id_str is None:
        return None

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    return user


async def get_workspace(
    request: Request,
    workspace_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Workspace:
    """Get workspace and verify user has access."""
    # Enforce API-key workspace binding before consulting membership.
    _enforce_api_key_workspace(request, workspace_id)

    # Check membership
    result = await db.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == current_user.id,
            WorkspaceMembership.workspace_id == workspace_id,
        )
    )
    membership = result.scalar_one_or_none()

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found or access denied",
        )

    # Get workspace
    ws_result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace: Workspace | None = ws_result.scalar_one_or_none()

    if workspace is None or not workspace.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    return workspace


async def get_workspace_admin(
    request: Request,
    workspace_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Workspace:
    """Get workspace and verify user has admin or owner access."""
    _enforce_api_key_workspace(request, workspace_id)

    result = await db.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == current_user.id,
            WorkspaceMembership.workspace_id == workspace_id,
        )
    )
    membership = result.scalar_one_or_none()

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found or access denied",
        )

    if membership.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    ws_result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace: Workspace | None = ws_result.scalar_one_or_none()

    if workspace is None or not workspace.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    return workspace


async def get_membership(
    request: Request,
    workspace_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceMembership:
    """Get the current user's workspace membership (validates access)."""
    _enforce_api_key_workspace(request, workspace_id)

    result = await db.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == current_user.id,
            WorkspaceMembership.workspace_id == workspace_id,
        )
    )
    membership = result.scalar_one_or_none()

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found or access denied",
        )

    return membership


# Type aliases for cleaner dependency injection
CurrentUser = Annotated[User, Depends(get_current_user)]
ActiveUser = Annotated[User, Depends(get_current_active_user)]
OptionalCurrentUser = Annotated[User | None, Depends(get_optional_current_user)]
DB = Annotated[AsyncSession, Depends(get_db)]
WorkspaceAccess = Annotated[Workspace, Depends(get_workspace)]
WorkspaceAdminAccess = Annotated[Workspace, Depends(get_workspace_admin)]
CurrentMembership = Annotated[WorkspaceMembership, Depends(get_membership)]
