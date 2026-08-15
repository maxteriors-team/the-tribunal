"""Verified Meta Lead Ads (``leadgen``) webhook ingestion."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from app.api.deps import DB
from app.core.config import settings
from app.services.lead_sources.meta_lead_ads_service import (
    MetaLeadAdsError,
    MetaLeadAdsValidationError,
    process_meta_lead,
)

logger = structlog.get_logger()
router = APIRouter()


@router.get("/leadgen")
async def verify_meta_leadgen_webhook(
    mode: str | None = Query(default=None, alias="hub.mode"),
    verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> Response:
    """Complete Meta's callback verification challenge."""
    configured = settings.meta_lead_ads_verify_token
    if (
        mode != "subscribe"
        or not configured
        or not verify_token
        or not hmac.compare_digest(verify_token, configured)
        or challenge is None
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verification failed")
    return Response(content=challenge, media_type="text/plain")


async def _bounded_body(request: Request) -> bytes:
    limit = settings.meta_lead_ads_max_webhook_bytes
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Webhook payload too large",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _verify_signature(body: bytes, signature_header: str | None) -> None:
    secret = settings.meta_lead_ads_app_secret
    if not secret:
        logger.error("meta_lead_webhook_disabled", reason="app_secret_not_configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Meta Lead Ads webhook is not configured",
        )
    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing signature")
    supplied = signature_header.removeprefix("sha256=").strip().lower()
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")


def _lead_events(payload: dict[str, Any]) -> list[tuple[str, str]]:
    if payload.get("object") != "page":
        return []
    events: list[tuple[str, str]] = []
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return events
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_page_id = str(entry.get("id") or "").strip()
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict) or change.get("field") != "leadgen":
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            page_id = str(value.get("page_id") or entry_page_id).strip()
            leadgen_id = str(value.get("leadgen_id") or "").strip()
            if page_id and leadgen_id:
                events.append((page_id, leadgen_id))
    # Preserve provider order while suppressing duplicate changes in one delivery.
    return list(dict.fromkeys(events))


@router.post("/leadgen")
async def ingest_meta_leadgen_webhook(request: Request, db: DB) -> dict[str, int | bool]:
    """Fetch and idempotently persist every verified ``leadgen`` change."""
    body = await _bounded_body(request)
    _verify_signature(body, request.headers.get("x-hub-signature-256"))
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")

    events = _lead_events(parsed)
    processed = 0
    ignored = 0
    for page_id, leadgen_id in events:
        try:
            result = await process_meta_lead(db, page_id=page_id, leadgen_id=leadgen_id)
            await db.commit()
        except MetaLeadAdsValidationError:
            # A malformed or disconnected lead cannot be fixed by provider replay.
            await db.rollback()
            ignored += 1
            continue
        except MetaLeadAdsError as exc:
            await db.rollback()
            logger.warning("meta_lead_processing_retryable_failure", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Meta lead processing temporarily failed",
            ) from exc
        except Exception:
            await db.rollback()
            logger.exception("meta_lead_processing_failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Meta lead processing temporarily failed",
            ) from None

        if result.status == "ignored":
            ignored += 1
        else:
            processed += 1

    return {"received": True, "processed": processed, "ignored": ignored}
