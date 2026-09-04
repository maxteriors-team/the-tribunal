"""Referral-partner endpoints: roster CRUD plus the production scoreboard.

Mounted under a workspace. Reads are available to any workspace member; writes
are gated to managers and up (:data:`app.api.deps.WorkspaceManager`), because the
partner roster is relationship data an owner curates — the same posture crews and
technicians get in :mod:`app.api.v1.field_service`.

Writes run on the transactional session so a failed name-uniqueness or
cross-tenant contact check rolls back cleanly, and ``ServiceErrorRoute`` maps the
service layer's typed errors onto HTTP responses at the boundary.
"""

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.api.deps import (
    DB,
    CanWriteCRM,
    TransactionalDB,
    WorkspaceAccess,
    WorkspaceManager,
    require_capability,
)
from app.api.service_errors import ServiceErrorRoute
from app.core.config import settings
from app.core.permissions import Capability
from app.core.utils import get_client_ip
from app.models.referral_partner import ReferralPartnerType
from app.models.referral_partner_logo import (
    MAX_REFERRAL_PARTNER_LOGO_BYTES,
    ReferralPartnerLogo,
)
from app.schemas.referral_partner import (
    DEFAULT_QUIET_AFTER_DAYS,
    PublicReferralPartnerIntake,
    PublicReferralPartnerIntakeSubmit,
    ReferralPartnerCreate,
    ReferralPartnerIntakeLinkResponse,
    ReferralPartnerListResponse,
    ReferralPartnerLogoResponse,
    ReferralPartnerResponse,
    ReferralPartnerScoreboardResponse,
    ReferralPartnerUpdate,
)
from app.services.lead_sources.referral_partner_intake_service import (
    ReferralPartnerIntakeNotFoundError,
    ReferralPartnerIntakeService,
    ReferralPartnerLogoTooLargeError,
    ReferralPartnerLogoValidationError,
    intake_token_digest,
)
from app.services.lead_sources.referral_partner_service import ReferralPartnerService
from app.services.rate_limiting.embed_limiter import enforce_embed_rate_limit

# Partner records carry a name, email, phone and an optional link to the CRM
# contact the partner already is — customer PII by another name — and the
# scoreboard ranks who sends business. ``crm:read`` is the floor, the same gate
# ``/contacts`` uses. Writes are already dispatcher-gated per route via
# ``WorkspaceManager``.
router = APIRouter(
    route_class=ServiceErrorRoute,
    dependencies=[Depends(require_capability(Capability.CRM_READ))],
)
public_router = APIRouter()
_public_bearer = HTTPBearer(auto_error=False)

_PUBLIC_READ_PER_IP = 120
_PUBLIC_READ_PER_TOKEN = 60
_PUBLIC_WRITE_PER_IP = 30
_PUBLIC_WRITE_PER_TOKEN = 15
_PUBLIC_RATE_WINDOW_SECONDS = 3600
_MAX_LOGO_MULTIPART_OVERHEAD_BYTES = 64 * 1024
_MAX_LOGO_MULTIPART_BODY_BYTES = (
    MAX_REFERRAL_PARTNER_LOGO_BYTES + _MAX_LOGO_MULTIPART_OVERHEAD_BYTES
)
_LOGO_UPLOAD_OPENAPI = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}


def _raise_intake_not_found() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Referral partner intake not found"
    )


def _public_bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_public_bearer)],
) -> str:
    """Extract the capability without ever placing it in a request URL."""
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        _raise_intake_not_found()
    return credentials.credentials


PublicIntakeToken = Annotated[str, Depends(_public_bearer_token)]


def _set_no_store(response: Response) -> None:
    """Prevent browser and intermediary storage of capability-backed JSON."""
    response.headers["Cache-Control"] = "no-store,max-age=0"
    response.headers["Pragma"] = "no-cache"


async def _rate_limit_public(request: Request, token: str, *, write: bool) -> None:
    client_ip = get_client_ip(request, settings.trusted_proxies)
    digest = intake_token_digest(token)
    kind = "write" if write else "read"
    await enforce_embed_rate_limit(
        scope=f"referral_partner_intake:{kind}:ip",
        identifier=client_ip,
        limit=_PUBLIC_WRITE_PER_IP if write else _PUBLIC_READ_PER_IP,
        window_seconds=_PUBLIC_RATE_WINDOW_SECONDS,
    )
    await enforce_embed_rate_limit(
        scope=f"referral_partner_intake:{kind}:token",
        identifier=digest,
        limit=_PUBLIC_WRITE_PER_TOKEN if write else _PUBLIC_READ_PER_TOKEN,
        window_seconds=_PUBLIC_RATE_WINDOW_SECONDS,
    )


class _LogoBodyTooLarge(MultiPartException):
    pass


async def _bounded_logo_body(request: Request) -> AsyncGenerator[bytes, None]:
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_LOGO_MULTIPART_BODY_BYTES:
            raise _LogoBodyTooLarge("Logo upload exceeds the request size limit")
        yield chunk


async def _read_logo_upload(request: Request) -> tuple[str | None, str | None, bytes]:
    """Parse one multipart file after auth while bounding bytes read from ASGI."""
    parser = MultiPartParser(
        request.headers,
        _bounded_logo_body(request),
        max_files=1,
        max_fields=0,
        max_part_size=MAX_REFERRAL_PARTNER_LOGO_BYTES + 1,
    )
    try:
        form = await parser.parse()
    except _LogoBodyTooLarge as exc:
        raise ReferralPartnerLogoTooLargeError(str(exc)) from exc
    except MultiPartException as exc:
        raise ReferralPartnerLogoValidationError("A single logo file is required") from exc

    try:
        items = form.multi_items()
        if len(items) != 1 or items[0][0] != "file" or not isinstance(items[0][1], UploadFile):
            raise ReferralPartnerLogoValidationError("A single logo file is required")
        upload = items[0][1]
        data = await upload.read(MAX_REFERRAL_PARTNER_LOGO_BYTES + 1)
        return upload.filename, upload.content_type, data
    finally:
        await form.close()


def _logo_response(logo: ReferralPartnerLogo, *, public: bool) -> Response:
    return Response(
        content=logo.data,
        media_type=logo.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{logo.filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600" if not public else "private, no-store",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("", response_model=ReferralPartnerListResponse)
async def list_referral_partners(
    workspace: WorkspaceAccess,
    db: DB,
    is_active: bool | None = None,
    partner_type: ReferralPartnerType | None = None,
) -> ReferralPartnerListResponse:
    """List referral partners, optionally filtered by active state or type."""
    service = ReferralPartnerService(db)
    return await service.list(workspace.id, is_active=is_active, partner_type=partner_type)


@router.post("", response_model=ReferralPartnerResponse, status_code=201)
async def create_referral_partner(
    payload: ReferralPartnerCreate,
    membership: WorkspaceManager,
    db: TransactionalDB,
) -> ReferralPartnerResponse:
    """Add a referral partner to the roster."""
    service = ReferralPartnerService(db)
    return await service.create(membership.workspace_id, payload.model_dump())


# Registered before `/{partner_id}` so FastAPI matches the static "scoreboard"
# path instead of trying to parse it as a UUID.
@router.get("/scoreboard", response_model=ReferralPartnerScoreboardResponse)
async def get_referral_partner_scoreboard(
    workspace: WorkspaceAccess,
    db: DB,
    quiet_after_days: int = Query(
        DEFAULT_QUIET_AFTER_DAYS,
        ge=1,
        le=3650,
        description="A partner is 'gone quiet' after this many days with no referral.",
    ),
    gone_quiet_only: bool = Query(
        False,
        description=(
            "Return only partners with at least one historical referral and "
            "nothing inside the window — the call list."
        ),
    ),
    is_active: bool | None = None,
    partner_type: ReferralPartnerType | None = None,
) -> ReferralPartnerScoreboardResponse:
    """Per-partner referrals, close rate, and revenue, ranked by revenue."""
    service = ReferralPartnerService(db)
    return await service.scoreboard(
        workspace.id,
        quiet_after_days=quiet_after_days,
        gone_quiet_only=gone_quiet_only,
        is_active=is_active,
        partner_type=partner_type,
    )


@router.post("/{partner_id}/intake-link", response_model=ReferralPartnerIntakeLinkResponse)
async def issue_referral_partner_intake_link(
    partner_id: uuid.UUID,
    membership: CanWriteCRM,
    db: TransactionalDB,
    response: Response,
) -> ReferralPartnerIntakeLinkResponse:
    """Create or reuse a copyable public intake link for this scoped partner."""
    try:
        result = await ReferralPartnerIntakeService(db).issue_link(
            partner_id, membership.workspace_id
        )
    except ReferralPartnerIntakeNotFoundError:
        _raise_intake_not_found()
    _set_no_store(response)
    return result


@router.post("/{partner_id}/intake-link/rotate", response_model=ReferralPartnerIntakeLinkResponse)
async def rotate_referral_partner_intake_link(
    partner_id: uuid.UUID,
    membership: CanWriteCRM,
    db: TransactionalDB,
    response: Response,
) -> ReferralPartnerIntakeLinkResponse:
    """Revoke existing capabilities and return a newly generated intake link."""
    try:
        result = await ReferralPartnerIntakeService(db).issue_link(
            partner_id, membership.workspace_id, rotate=True
        )
    except ReferralPartnerIntakeNotFoundError:
        _raise_intake_not_found()
    _set_no_store(response)
    return result


@router.delete("/{partner_id}/intake-link", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_referral_partner_intake_link(
    partner_id: uuid.UUID, membership: CanWriteCRM, db: TransactionalDB
) -> None:
    """Revoke every public intake capability for this scoped partner."""
    try:
        await ReferralPartnerIntakeService(db).revoke_link(partner_id, membership.workspace_id)
    except ReferralPartnerIntakeNotFoundError:
        _raise_intake_not_found()


@router.get("/{partner_id}/logo")
async def download_referral_partner_logo(
    partner_id: uuid.UUID, workspace: WorkspaceAccess, db: DB
) -> Response:
    """Download a scoped partner's validated raster logo."""
    try:
        logo = await ReferralPartnerIntakeService(db).authenticated_logo(partner_id, workspace.id)
    except ReferralPartnerIntakeNotFoundError:
        _raise_intake_not_found()
    return _logo_response(logo, public=False)


@router.get("/{partner_id}", response_model=ReferralPartnerResponse)
async def get_referral_partner(
    partner_id: uuid.UUID,
    workspace: WorkspaceAccess,
    db: DB,
) -> ReferralPartnerResponse:
    """Get a single referral partner."""
    service = ReferralPartnerService(db)
    return await service.get(partner_id, workspace.id)


@router.put("/{partner_id}", response_model=ReferralPartnerResponse)
async def update_referral_partner(
    partner_id: uuid.UUID,
    payload: ReferralPartnerUpdate,
    membership: WorkspaceManager,
    db: TransactionalDB,
) -> ReferralPartnerResponse:
    """Update a referral partner."""
    service = ReferralPartnerService(db)
    return await service.update(
        partner_id, membership.workspace_id, payload.model_dump(exclude_unset=True)
    )


@router.delete("/{partner_id}", status_code=204)
async def delete_referral_partner(
    partner_id: uuid.UUID,
    membership: WorkspaceManager,
    db: TransactionalDB,
) -> None:
    """Delete a referral partner. Their referred leads and jobs keep their history."""
    service = ReferralPartnerService(db)
    await service.delete(partner_id, membership.workspace_id)


# This router is mounted separately from the workspace router. It intentionally
# has no CRM_READ dependency, never accepts a client-supplied workspace ID, and
# receives its capability only in Authorization so access logs cannot capture it.
@public_router.get("/intake", response_model=PublicReferralPartnerIntake)
async def get_public_referral_partner_intake(
    token: PublicIntakeToken, request: Request, db: DB, response: Response
) -> PublicReferralPartnerIntake:
    """Return safe editable prefill data for a live bearer capability."""
    await _rate_limit_public(request, token, write=False)
    try:
        result = await ReferralPartnerIntakeService(db).public_prefill(token)
    except ReferralPartnerIntakeNotFoundError:
        _raise_intake_not_found()
    _set_no_store(response)
    return result


@public_router.post("/intake", response_model=PublicReferralPartnerIntake)
async def submit_public_referral_partner_intake(
    token: PublicIntakeToken,
    payload: PublicReferralPartnerIntakeSubmit,
    request: Request,
    db: TransactionalDB,
    response: Response,
) -> PublicReferralPartnerIntake:
    """Update the capability's existing partner; never creates a CRM entity."""
    await _rate_limit_public(request, token, write=True)
    try:
        result = await ReferralPartnerIntakeService(db).submit(token, payload)
    except ReferralPartnerIntakeNotFoundError:
        _raise_intake_not_found()
    _set_no_store(response)
    return result


@public_router.post(
    "/intake/logo",
    response_model=ReferralPartnerLogoResponse,
    status_code=201,
    openapi_extra=_LOGO_UPLOAD_OPENAPI,
)
async def upload_public_referral_partner_logo(
    token: PublicIntakeToken, request: Request, db: TransactionalDB
) -> ReferralPartnerLogoResponse:
    """Replace this partner's logo after bearer auth and strict raster validation."""
    await _rate_limit_public(request, token, write=True)
    service = ReferralPartnerIntakeService(db)
    try:
        # No FastAPI body parameter: bearer auth completes before multipart parsing.
        await service.public_prefill(token)
    except ReferralPartnerIntakeNotFoundError:
        _raise_intake_not_found()

    try:
        filename, declared_type, data = await _read_logo_upload(request)
        return await service.upload_logo(
            token,
            filename=filename,
            declared_type=declared_type,
            data=data,
        )
    except ReferralPartnerIntakeNotFoundError:
        _raise_intake_not_found()
    except ReferralPartnerLogoTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)) from exc
    except ReferralPartnerLogoValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@public_router.get("/intake/logo")
async def download_public_referral_partner_logo(
    token: PublicIntakeToken, request: Request, db: DB
) -> Response:
    """Serve validated raster bytes only while the bearer capability is live."""
    await _rate_limit_public(request, token, write=False)
    try:
        logo = await ReferralPartnerIntakeService(db).public_logo(token)
    except ReferralPartnerIntakeNotFoundError:
        _raise_intake_not_found()
    return _logo_response(logo, public=True)
