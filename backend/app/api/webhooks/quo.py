"""Public Quo webhook endpoint with per-integration signature verification."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Mapping
from functools import partial
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from svix.webhooks import Webhook, WebhookVerificationError

from app.api.deps import TransactionalDB
from app.models.workspace import WorkspaceIntegration
from app.services.quo.client import QuoClient
from app.services.quo.sync import QuoSyncError, QuoSyncService
from app.services.webhooks.pipeline import (
    WebhookDispatchResult,
    WebhookPipeline,
    WebhookRequestEnvelope,
)
from app.services.webhooks.quo import (
    QuoWebhookEvent,
    check_quo_idempotency,
    parse_quo_payload,
)
from app.utils.phone import normalize_phone_safe

router = APIRouter()
logger = structlog.get_logger()

QUO_MAX_BODY_BYTES = 1024 * 1024
QUO_TIMESTAMP_TOLERANCE_SECONDS = 5 * 60


def _require_signed_headers(headers: Mapping[str, str]) -> None:
    webhook_id = headers.get("webhook-id", "")
    timestamp = headers.get("webhook-timestamp", "")
    signature = headers.get("webhook-signature", "")
    if (
        not webhook_id
        or len(webhook_id) > 128
        or not timestamp
        or len(timestamp) > 20
        or not signature
        or len(signature) > 2048
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing or invalid Quo webhook headers",
        )

    try:
        signed_at = int(timestamp)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Quo webhook timestamp",
        ) from None
    if signed_at <= 0 or abs(int(time.time()) - signed_at) > QUO_TIMESTAMP_TOLERANCE_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Quo webhook timestamp",
        )


async def _verify_quo_envelope(
    request: WebhookRequestEnvelope,
    *,
    signing_key: str,
) -> dict[str, Any]:
    """Verify the exact raw bytes with Quo's Svix-compatible signing key."""
    _require_signed_headers(request.headers)
    try:
        webhook = Webhook(signing_key)
    except ValueError:
        logger.error("quo_webhook_signing_key_invalid")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Quo webhook verification unavailable",
        ) from None

    try:
        verified = webhook.verify(request.raw_body, dict(request.headers))
    except WebhookVerificationError:
        logger.warning("quo_webhook_verification_failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Quo webhook signature",
        ) from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Quo webhook payload",
        ) from None
    except ValueError:
        logger.warning("quo_webhook_verification_failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Quo webhook signature",
        ) from None

    if isinstance(verified, dict):
        return verified
    try:
        decoded = json.loads(request.raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Quo webhook payload",
        ) from None
    if not isinstance(decoded, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Quo webhook payload",
        )
    return decoded


async def _read_limited_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Content-Length",
            ) from None
        if declared_length < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Content-Length",
            )
        if declared_length > QUO_MAX_BODY_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Quo webhook payload too large",
            )

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > QUO_MAX_BODY_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Quo webhook payload too large",
            )
        body.extend(chunk)
    return bytes(body)


@router.post("/{workspace_integration_id}", include_in_schema=False)
async def receive_quo_webhook(
    workspace_integration_id: uuid.UUID,
    request: Request,
    db: TransactionalDB,
) -> dict[str, str]:
    """Verify, tenant-bind, dedupe, and dispatch one Quo delivery."""
    lookup_result = await db.execute(
        select(WorkspaceIntegration).where(
            WorkspaceIntegration.id == workspace_integration_id,
            WorkspaceIntegration.integration_type == "quo",
            WorkspaceIntegration.is_active.is_(True),
        )
    )
    integration = lookup_result.scalar_one_or_none()
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active Quo integration not found",
        )

    credentials = integration.safe_credentials()
    api_key = credentials.get("api_key") if credentials else None
    signing_key = credentials.get("webhook_signing_key") if credentials else None
    organization_id = credentials.get("organization_id") if credentials else None
    api_version = credentials.get("webhook_api_version") if credentials else None
    phone_number_id = credentials.get("phone_number_id") if credentials else None
    phone_number = credentials.get("phone_number") if credentials else None
    if (
        not isinstance(api_key, str)
        or not api_key.strip()
        or not isinstance(signing_key, str)
        or not signing_key.startswith("whsec_")
        or not isinstance(organization_id, str)
        or not organization_id.startswith("OR")
        or not isinstance(api_version, str)
        or not isinstance(phone_number_id, str)
        or not phone_number_id.strip()
        or len(phone_number_id) > 255
        or not isinstance(phone_number, str)
        or normalize_phone_safe(phone_number) != phone_number
    ):
        logger.error(
            "quo_webhook_credentials_unavailable",
            workspace_integration_id=str(workspace_integration_id),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Quo webhook verification unavailable",
        )

    async def dispatch(
        session: Any,
        event: QuoWebhookEvent,
        event_log: Any,
    ) -> WebhookDispatchResult:
        async with QuoClient(api_key) as quo_client:
            try:
                return await QuoSyncService(
                    session,
                    workspace_id=integration.workspace_id,
                    organization_id=organization_id,
                    phone_number_id=phone_number_id,
                    phone_number=phone_number,
                    client=quo_client,
                ).process(event, event_log)
            except QuoSyncError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid Quo webhook resource",
                ) from exc

    payload = await _read_limited_body(request)
    headers = dict(request.headers)
    pipeline: WebhookPipeline[dict[str, Any], QuoWebhookEvent] = WebhookPipeline(
        provider="quo",
        verifier=partial(_verify_quo_envelope, signing_key=signing_key),
        parser=partial(
            parse_quo_payload,
            expected_organization_id=organization_id,
            expected_api_version=api_version,
        ),
        idempotency_checker=check_quo_idempotency,
        dispatcher=dispatch,
    )
    pipeline_result = await pipeline.process(
        db=db,
        request=WebhookRequestEnvelope(
            provider="quo",
            raw_body=payload,
            headers=headers,
        ),
        log=logger,
    )
    return pipeline_result.response_body()
