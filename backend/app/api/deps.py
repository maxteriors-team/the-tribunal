"""API dependencies."""

import hashlib
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Capability, role_can
from app.core.roles import WorkspaceRole
from app.core.security import decode_access_token
from app.db.session import get_db, transaction_boundary
from app.models.api_key import APIKey
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

_ACCESS_COOKIE_NAME = "access_token"


def _extract_jwt(request: Request, header_token: str | None) -> str | None:
    """Resolve the JWT for this request.

    Prefers the httpOnly ``access_token`` cookie (XSS-resistant — JS cannot
    read it). Falls back to the ``Authorization: Bearer ...`` header so
    server-to-server callers, native clients, and the existing test suite
    continue to work.
    """
    cookie_token = request.cookies.get(_ACCESS_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    return header_token


def _bind_identity_to_logs(
    *,
    user_id: int | None = None,
    workspace_id: uuid.UUID | None = None,
) -> None:
    """Attach the resolved identity to structlog's per-request contextvars.

    The request-scoped ``request_id`` is bound earlier by
    :class:`app.main.RequestIDMiddleware`; this helper adds ``user_id`` and,
    when known, ``workspace_id`` so every subsequent log line in this request
    carries the full ``(request_id, workspace_id, user_id)`` triple.

    Values are bound only when present so we never emit ``user_id=None`` keys
    that would clutter logs for anonymous endpoints.
    """
    fields: dict[str, object] = {}
    if user_id is not None:
        fields["user_id"] = user_id
    if workspace_id is not None:
        fields["workspace_id"] = str(workspace_id)
    if fields:
        structlog.contextvars.bind_contextvars(**fields)


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
    if user is None:
        jwt_token = _extract_jwt(request, token)
        if jwt_token is not None:
            user = await _user_from_jwt(jwt_token, db)
    if user is None:
        raise credentials_exception

    # Bind the resolved user (and the API-key-scoped workspace, if any) to
    # structlog contextvars so the rest of the request's log lines are
    # automatically tagged. The middleware already bound ``request_id``.
    api_key_workspace_id: uuid.UUID | None = getattr(request.state, "api_key_workspace_id", None)
    _bind_identity_to_logs(user_id=user.id, workspace_id=api_key_workspace_id)
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
    if user is None:
        jwt_token = _extract_jwt(request, token)
        if jwt_token is not None:
            user = await _user_from_jwt(jwt_token, db)

    if user is not None:
        api_key_workspace_id: uuid.UUID | None = getattr(
            request.state, "api_key_workspace_id", None
        )
        _bind_identity_to_logs(user_id=user.id, workspace_id=api_key_workspace_id)
    return user


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
    api_key_workspace_id: uuid.UUID | None = getattr(request.state, "api_key_workspace_id", None)
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

    _bind_identity_to_logs(workspace_id=workspace.id)
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

    _bind_identity_to_logs(workspace_id=workspace.id)
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

    _bind_identity_to_logs(workspace_id=workspace_id)
    return membership


def require_workspace_roles(
    *allowed: WorkspaceRole,
) -> Callable[[WorkspaceMembership], Awaitable[WorkspaceMembership]]:
    """Build a dependency that requires the caller to hold one of ``allowed``.

    Resolves the current user's membership via :func:`get_membership` (which
    already enforces workspace access and the API-key workspace binding), then
    rejects with 403 when the membership role is not in the allow-list. An
    explicit allow-list is used rather than a rank threshold so peer roles of
    equal rank (e.g. ``dispatcher`` and ``sales_rep``) never leak into each
    other's endpoints.
    """
    allowed_values = {role.value for role in allowed}

    async def _require(
        membership: Annotated[WorkspaceMembership, Depends(get_membership)],
    ) -> WorkspaceMembership:
        if membership.role not in allowed_values:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return membership

    return _require


def require_capability(
    *required: Capability,
) -> Callable[[WorkspaceMembership], Awaitable[WorkspaceMembership]]:
    """Build a dependency that requires the caller's role to hold every capability.

    Resolves the membership via :func:`get_membership` (which already enforces
    workspace access and the API-key workspace binding), maps the role to its
    tier via :mod:`app.core.permissions`, and rejects with 403 unless the role is
    granted **all** of ``required``. Unknown/legacy role strings resolve to the
    lowest tier (fail-closed), so a corrupt value never escalates.
    """

    async def _require(
        membership: Annotated[WorkspaceMembership, Depends(get_membership)],
    ) -> WorkspaceMembership:
        if not all(role_can(membership.role, cap) for cap in required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return membership

    return _require


async def get_transactional_db(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AsyncGenerator[AsyncSession, None]:
    """Provide a request transaction boundary for migrated mutating routes."""
    async with transaction_boundary(db):
        yield db


# Type aliases for cleaner dependency injection
CurrentUser = Annotated[User, Depends(get_current_user)]
ActiveUser = Annotated[User, Depends(get_current_active_user)]
OptionalCurrentUser = Annotated[User | None, Depends(get_optional_current_user)]
DB = Annotated[AsyncSession, Depends(get_db)]
TransactionalDB = Annotated[
    AsyncSession,
    Depends(get_transactional_db, scope="function"),
]
WorkspaceAccess = Annotated[Workspace, Depends(get_workspace)]
WorkspaceAdminAccess = Annotated[Workspace, Depends(get_workspace_admin)]
CurrentMembership = Annotated[WorkspaceMembership, Depends(get_membership)]

# Role-gated membership dependencies for field-service / sales surfaces. Each
# resolves (and returns) the caller's membership, raising 403 when the role is
# not permitted. Owners and admins are always included.
WorkspaceManager = Annotated[
    WorkspaceMembership,
    Depends(
        require_workspace_roles(
            WorkspaceRole.OWNER,
            WorkspaceRole.ADMIN,
            WorkspaceRole.MANAGER,
        )
    ),
]
WorkspaceDispatcher = Annotated[
    WorkspaceMembership,
    Depends(
        require_workspace_roles(
            WorkspaceRole.OWNER,
            WorkspaceRole.ADMIN,
            WorkspaceRole.MANAGER,
            WorkspaceRole.DISPATCHER,
        )
    ),
]

# Capability-gated membership dependencies (preferred for new endpoints). Each
# resolves (and returns) the caller's membership, raising 403 when the role's
# tier lacks the capability. See :mod:`app.core.permissions` for the matrix.
CanReadCRM = Annotated[WorkspaceMembership, Depends(require_capability(Capability.CRM_READ))]
CanWriteCRM = Annotated[WorkspaceMembership, Depends(require_capability(Capability.CRM_WRITE))]
CanWritePipelineOwn = Annotated[
    WorkspaceMembership, Depends(require_capability(Capability.PIPELINE_WRITE_OWN))
]
CanSendComms = Annotated[WorkspaceMembership, Depends(require_capability(Capability.COMMS_SEND))]
CanManageComms = Annotated[
    WorkspaceMembership, Depends(require_capability(Capability.COMMS_MANAGE))
]
CanReadBilling = Annotated[
    WorkspaceMembership, Depends(require_capability(Capability.BILLING_READ))
]
CanWriteBilling = Annotated[
    WorkspaceMembership, Depends(require_capability(Capability.BILLING_WRITE))
]
CanViewReports = Annotated[
    WorkspaceMembership, Depends(require_capability(Capability.REPORTS_VIEW))
]
CanManageMembers = Annotated[
    WorkspaceMembership, Depends(require_capability(Capability.MEMBERS_MANAGE))
]
