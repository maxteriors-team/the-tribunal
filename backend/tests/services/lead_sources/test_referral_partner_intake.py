"""Focused security and lifecycle tests for referral-partner public intake."""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.formparsers import MultiPartException
from starlette.requests import Request
from starlette.types import Message

from app.api.v1 import referral_partners as intake_routes
from app.api.v1.referral_partners import _logo_response, public_router, router
from app.models.referral_partner import (
    ReferralPartner,
    ReferralPartnerIntakeStatus,
    ReferralPartnerOfferType,
    ReferralPartnerType,
)
from app.models.referral_partner_intake import ReferralPartnerIntakeLink
from app.models.referral_partner_logo import (
    MAX_REFERRAL_PARTNER_LOGO_BYTES,
    ReferralPartnerLogo,
)
from app.schemas.referral_partner import PublicReferralPartnerIntakeSubmit
from app.services.lead_sources.referral_partner_intake_service import (
    ReferralPartnerIntakeNotFoundError,
    ReferralPartnerIntakeService,
    ReferralPartnerLogoTooLargeError,
    ReferralPartnerLogoValidationError,
    detect_raster_type,
    intake_token_digest,
)


def _db() -> MagicMock:
    db = MagicMock(spec=AsyncSession)
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    return db


def _scalars_result(items: list[object]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


def _partner(*, workspace_id: uuid.UUID | None = None) -> ReferralPartner:
    return ReferralPartner(
        id=uuid.uuid4(),
        workspace_id=workspace_id or uuid.uuid4(),
        name="Dana Ruiz",
        partner_type=ReferralPartnerType.REALTOR,
        is_active=True,
        intake_status=ReferralPartnerIntakeStatus.NOT_REQUESTED,
        offer_type=ReferralPartnerOfferType.NONE,
    )


def _payload(**updates: object) -> PublicReferralPartnerIntakeSubmit:
    values: dict[str, object] = {
        "name": "Dana Ruiz",
        "company": "Keller Williams",
        "email": "dana@example.com",
        "phone": "+15555550100",
        "website_url": "https://example.com",
        "business_description": "Local real estate team",
        "services": "Residential sales",
        "service_area": "Austin",
        "offer_headline": "Client credit",
        "offer_description": "$250 closing credit",
        "offer_type": "fixed_dollar_credit",
        "offer_value": "250.00",
        "offer_terms": "At closing",
    }
    values.update(updates)
    return PublicReferralPartnerIntakeSubmit.model_validate(values)


@pytest.mark.asyncio
async def test_issue_reuses_then_rotates_and_revokes_high_entropy_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db()
    service = ReferralPartnerIntakeService(db)
    partner = _partner()
    monkeypatch.setattr(service, "_scoped_partner", AsyncMock(return_value=partner))

    db.execute.return_value = _scalars_result([])
    first = await service.issue_link(partner.id, partner.workspace_id)
    first_link = db.add.call_args.args[0]
    frontend_path, first_token = first.intake_url.split("#token=", 1)
    assert frontend_path.endswith("/p/referral-partners/intake")
    assert "?" not in frontend_path
    assert "/p/referral-partners/intake/" not in first.intake_url
    decoded = base64.urlsafe_b64decode(first_token + "=" * (-len(first_token) % 4))
    assert len(decoded) == 32
    assert first_link.token_digest == hashlib.sha256(first_token.encode()).hexdigest()
    assert first_link.token == first_token

    db.execute.return_value = _scalars_result([first_link])
    reused = await service.issue_link(partner.id, partner.workspace_id)
    assert reused.intake_url == first.intake_url
    assert db.add.call_count == 1

    db.execute.return_value = _scalars_result([first_link])
    rotated = await service.issue_link(partner.id, partner.workspace_id, rotate=True)
    second_link = db.add.call_args.args[0]
    assert rotated.intake_url != first.intake_url
    assert first_link.revoked_at is not None
    assert second_link.revoked_at is None

    db.execute.return_value = _scalars_result([second_link])
    await service.revoke_link(partner.id, partner.workspace_id)
    assert second_link.revoked_at is not None
    assert partner.intake_status is ReferralPartnerIntakeStatus.REVOKED


@pytest.mark.asyncio
async def test_invalid_and_expired_tokens_share_not_found_path() -> None:
    db = _db()
    result = MagicMock()
    result.one_or_none.return_value = None
    db.execute.return_value = result
    service = ReferralPartnerIntakeService(db)

    for token in ("invalid", "expired-token"):
        with pytest.raises(ReferralPartnerIntakeNotFoundError):
            await service._resolve_token(token)

    query = db.execute.call_args.args[0]
    sql = str(query)
    assert "token_digest" in sql
    assert "revoked_at IS NULL" in sql
    assert "expires_at >" in sql
    assert "is_active IS true" in sql


@pytest.mark.asyncio
async def test_scoped_partner_query_includes_authenticated_workspace() -> None:
    db = _db()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    service = ReferralPartnerIntakeService(db)
    partner_id, workspace_id = uuid.uuid4(), uuid.uuid4()

    with pytest.raises(ReferralPartnerIntakeNotFoundError):
        await service._scoped_partner(partner_id, workspace_id)

    params = db.execute.call_args.args[0].compile().params
    assert partner_id in params.values()
    assert workspace_id in params.values()


@pytest.mark.asyncio
async def test_repeat_submit_updates_same_partner_without_creating_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db()
    service = ReferralPartnerIntakeService(db)
    partner = _partner()
    link = ReferralPartnerIntakeLink(
        workspace_id=partner.workspace_id,
        referral_partner_id=partner.id,
        token_digest=intake_token_digest("live-token"),
        token="live-token",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    monkeypatch.setattr(service, "_resolve_token", AsyncMock(return_value=(link, partner)))
    monkeypatch.setattr(service, "public_prefill", AsyncMock(return_value=MagicMock()))

    original_id = partner.id
    await service.submit("live-token", _payload(name="First Update"))
    await service.submit("live-token", _payload(name="Second Update"))

    assert partner.id == original_id
    assert partner.name == "Second Update"
    assert partner.offer_value == Decimal("250.00")
    assert db.add.call_count == 0
    assert db.flush.await_count == 2


def test_public_payload_forbids_identifiers_extra_fields_and_non_http_url() -> None:
    for forbidden in ("id", "workspace_id", "contact_id", "referral_partner_id"):
        with pytest.raises(ValidationError):
            _payload(**{forbidden: str(uuid.uuid4())})
    with pytest.raises(ValidationError):
        _payload(website_url="ftp://example.com/logo")


@pytest.mark.asyncio
async def test_logo_auth_precedes_size_and_magic_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db()
    service = ReferralPartnerIntakeService(db)
    monkeypatch.setattr(
        service,
        "_resolve_token",
        AsyncMock(side_effect=ReferralPartnerIntakeNotFoundError),
    )
    with pytest.raises(ReferralPartnerIntakeNotFoundError):
        await service.upload_logo(
            "invalid", filename="x.png", declared_type="image/png", data=b"x" * 10
        )

    monkeypatch.setattr(
        service,
        "_resolve_token",
        AsyncMock(return_value=(MagicMock(), _partner())),
    )
    with pytest.raises(ReferralPartnerLogoTooLargeError):
        await service.upload_logo(
            "live",
            filename="x.png",
            declared_type="image/png",
            data=b"x" * (MAX_REFERRAL_PARTNER_LOGO_BYTES + 1),
        )
    with pytest.raises(ReferralPartnerLogoValidationError):
        await service.upload_logo(
            "live", filename="x.png", declared_type="image/jpeg", data=b"\x89PNG\r\n\x1a\n"
        )


def test_logo_raster_magic_deferred_blob_and_nosniff_response() -> None:
    assert detect_raster_type(b"\xff\xd8\xffrest") == "image/jpeg"
    assert detect_raster_type(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert detect_raster_type(b"RIFF\x04\x00\x00\x00WEBPrest") == "image/webp"
    assert detect_raster_type(b"<svg></svg>") is None
    assert ReferralPartnerLogo.__mapper__.attrs.data.deferred is True

    logo = MagicMock(data=b"image", content_type="image/png", filename="safe.png")
    response = _logo_response(logo, public=True)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_public_rate_limit_uses_separate_ip_and_token_digest_buckets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enforce = AsyncMock()
    monkeypatch.setattr(intake_routes, "enforce_embed_rate_limit", enforce)
    request = Request(
        {"type": "http", "headers": [], "client": ("203.0.113.8", 4000), "scheme": "https"}
    )

    await intake_routes._rate_limit_public(request, "secret-capability", write=True)

    assert enforce.await_count == 2
    calls = enforce.await_args_list
    assert calls[0].kwargs["scope"].endswith(":write:ip")
    assert calls[0].kwargs["identifier"] == "203.0.113.8"
    assert calls[1].kwargs["scope"].endswith(":write:token")
    assert calls[1].kwargs["identifier"] == intake_token_digest("secret-capability")
    assert calls[1].kwargs["identifier"] != "secret-capability"


@pytest.mark.asyncio
async def test_logo_route_authenticates_before_bounded_multipart_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def rate_limit(*args: object, **kwargs: object) -> None:
        events.append("rate")

    async def read_upload(request: Request) -> tuple[str, str, bytes]:
        events.append("bounded-parse")
        return "logo.png", "image/png", b"\x89PNG\r\n\x1a\n"

    service = MagicMock()

    async def prefill(token: str) -> MagicMock:
        events.append("auth")
        return MagicMock()

    async def upload(*args: object, **kwargs: object) -> MagicMock:
        events.append("upload")
        return MagicMock()

    service.public_prefill = prefill
    service.upload_logo = upload
    monkeypatch.setattr(intake_routes, "_rate_limit_public", rate_limit)
    monkeypatch.setattr(intake_routes, "_read_logo_upload", read_upload)
    monkeypatch.setattr(intake_routes, "ReferralPartnerIntakeService", lambda db: service)

    request = Request(
        {"type": "http", "headers": [], "client": ("203.0.113.8", 4000), "scheme": "https"}
    )
    response = Response()
    db = MagicMock()
    db.info = {}
    await intake_routes.upload_public_referral_partner_logo(
        "secret-capability", request, db, response
    )

    assert events == ["rate", "auth", "bounded-parse", "upload"]
    assert db.info["app.tenancy.system"] == (
        "public referral-partner intake resolves workspace from capability"
    )
    assert response.headers["cache-control"] == "no-store,max-age=0"
    assert response.headers["pragma"] == "no-cache"


@pytest.mark.asyncio
async def test_logo_request_stream_has_hard_total_byte_cap() -> None:
    async def receive() -> Message:
        return {
            "type": "http.request",
            "body": b"x" * (intake_routes._MAX_LOGO_MULTIPART_BODY_BYTES + 1),
            "more_body": False,
        }

    request = Request(
        {"type": "http", "headers": [], "client": ("203.0.113.8", 4000)},
        receive,
    )
    with pytest.raises(MultiPartException):
        async for _ in intake_routes._bounded_logo_body(request):
            pass


def test_public_bearer_extraction_uses_uniform_not_found() -> None:
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="secret-capability")
    assert intake_routes._public_bearer_token(credentials) == "secret-capability"

    invalid_credentials = (
        None,
        HTTPAuthorizationCredentials(scheme="Basic", credentials="secret-capability"),
        HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid token"),
        HTTPAuthorizationCredentials(scheme="Bearer", credentials="x" * 129),
    )
    for invalid in invalid_credentials:
        with pytest.raises(HTTPException) as exc_info:
            intake_routes._public_bearer_token(invalid)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Referral partner intake not found"
        assert exc_info.value.headers == {
            "Cache-Control": "no-store,max-age=0",
            "Pragma": "no-cache",
        }


@pytest.mark.asyncio
async def test_sensitive_json_responses_disable_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    service = MagicMock()
    service.issue_link = AsyncMock(return_value=MagicMock())
    service.public_prefill = AsyncMock(return_value=MagicMock())
    service.submit = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(intake_routes, "ReferralPartnerIntakeService", lambda db: service)
    monkeypatch.setattr(intake_routes, "_rate_limit_public", AsyncMock())

    membership = MagicMock(workspace_id=uuid.uuid4())
    request = Request(
        {"type": "http", "headers": [], "client": ("203.0.113.8", 4000), "scheme": "https"}
    )
    responses = [Response() for _ in range(4)]
    public_db = MagicMock()
    public_db.info = {}

    await intake_routes.issue_referral_partner_intake_link(
        uuid.uuid4(), membership, MagicMock(), responses[0]
    )
    await intake_routes.rotate_referral_partner_intake_link(
        uuid.uuid4(), membership, MagicMock(), responses[1]
    )
    await intake_routes.get_public_referral_partner_intake(
        "secret-capability", request, public_db, responses[2]
    )
    await intake_routes.submit_public_referral_partner_intake(
        "secret-capability", _payload(), request, public_db, responses[3]
    )

    for response in responses:
        assert response.headers["cache-control"] == "no-store,max-age=0"
        assert response.headers["pragma"] == "no-cache"


def test_route_capability_surface_and_separate_public_router() -> None:
    private_routes = {(path.path, method) for path in router.routes for method in path.methods}
    public_routes = {
        (path.path, method) for path in public_router.routes for method in path.methods
    }
    assert {
        ("/{partner_id}/intake-link", "POST"),
        ("/{partner_id}/intake-link/rotate", "POST"),
        ("/{partner_id}/intake-link", "DELETE"),
        ("/{partner_id}/logo", "GET"),
    } <= private_routes
    assert {
        ("/intake", "GET"),
        ("/intake", "POST"),
        ("/intake/logo", "POST"),
        ("/intake/logo", "GET"),
    } == public_routes
    assert all("{token}" not in path for path, _method in public_routes)
    assert public_router.dependencies == []
