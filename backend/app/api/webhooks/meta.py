"""Verified Meta webhook ingestion for Lead Ads (``leadgen``) and DMs (``messages``).

Both surfaces share one app secret, one signature scheme and one body cap; only
the payload shape differs. ``leadgen`` arrives as ``entry[].changes[]`` with a
``field``, while Messenger and Instagram Direct arrive as ``entry[].messaging[]``
with no ``field`` at all — ``messages`` is the *subscription* name, not something
that appears in the body.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from app.api.deps import DB
from app.core.config import settings
from app.models.conversation import MessageChannel
from app.services.lead_sources.meta_lead_ads_service import (
    MetaLeadAdsError,
    MetaLeadAdsValidationError,
    process_meta_lead,
)
from app.services.lead_sources.meta_messenger_service import (
    MetaMessageEvent,
    process_meta_message,
)

# Meta caps a DM at 1000 characters; anything longer than this is not a message
# we failed to parse, it is someone probing what we will store.
_MAX_MESSAGE_CHARS = 2000

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


def _message_events(payload: dict[str, Any]) -> list[MetaMessageEvent]:
    """Extract inbound user DMs from one Messenger/Instagram delivery.

    Everything that is not a person typing to us is dropped here rather than
    deeper in the stack:

    * ``is_echo`` — Meta mirrors our *own* sends back to us. Ingesting one would
      persist our reply as an inbound message and schedule the AI to answer
      itself, forever.
    * ``delivery`` / ``read`` / ``reaction`` / ``messaging_postbacks`` — receipts
      and taps, not content.
    * empty or attachment-only messages — nothing to reply to, and we do not
      fetch Meta-hosted media.

    ``object`` distinguishes the two products: ``page`` is Messenger, and
    ``instagram`` is Instagram Direct, where ``entry[].id`` is the Instagram
    account ID rather than a Page ID.
    """
    channel = {
        "page": MessageChannel.MESSENGER,
        "instagram": MessageChannel.INSTAGRAM,
    }.get(str(payload.get("object") or ""))
    if channel is None:
        return []

    entries = payload.get("entry")
    if not isinstance(entries, list):
        return []

    events: list[MetaMessageEvent] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id") or "").strip()
        messaging = entry.get("messaging")
        if not isinstance(messaging, list):
            continue
        for item in messaging:
            if not isinstance(item, dict):
                continue
            message = item.get("message")
            if not isinstance(message, dict) or message.get("is_echo"):
                continue
            sender = item.get("sender")
            recipient = item.get("recipient")
            if not isinstance(sender, dict) or not isinstance(recipient, dict):
                continue
            psid = str(sender.get("id") or "").strip()
            # Trust the entry's own id over the payload's recipient: the entry is
            # what Meta signed the delivery for, so a forged recipient cannot
            # redirect a message into another workspace's Page.
            account_id = entry_id or str(recipient.get("id") or "").strip()
            message_id = str(message.get("mid") or "").strip()
            text = str(message.get("text") or "").strip()[:_MAX_MESSAGE_CHARS]
            if not psid or not account_id or not message_id or not text:
                continue
            # A PSID is the person; echoing our own Page back at ourselves would
            # open a thread the business is talking to itself in.
            if psid == account_id:
                continue
            if message_id in seen:
                continue
            seen.add(message_id)
            events.append(
                MetaMessageEvent(
                    account_id=account_id,
                    psid=psid,
                    message_id=message_id,
                    text=text,
                    channel=channel,
                    sent_at_ms=_timestamp_ms(item.get("timestamp")),
                )
            )
    return events


def _timestamp_ms(value: Any) -> int | None:
    """Return Meta's epoch-millisecond timestamp, or ``None`` when unusable."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@router.get("/messages")
async def verify_meta_messages_webhook(
    mode: str | None = Query(default=None, alias="hub.mode"),
    verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> Response:
    """Complete Meta's callback verification challenge for the DM subscription."""
    return await verify_meta_leadgen_webhook(
        mode=mode, verify_token=verify_token, challenge=challenge
    )


@router.post("/messages")
async def ingest_meta_messages_webhook(request: Request, db: DB) -> dict[str, int | bool]:
    """Persist every verified inbound Messenger/Instagram DM in this delivery."""
    parsed = await _verified_payload(request)

    processed = 0
    ignored = 0
    for event in _message_events(parsed):
        try:
            created = await process_meta_message(db, event=event)
            await db.commit()
        except MetaLeadAdsValidationError:
            # An unmapped Page or disconnected integration: replaying the
            # delivery cannot fix it, so absorb it instead of making Meta retry.
            await db.rollback()
            ignored += 1
            continue
        except MetaLeadAdsError as exc:
            await db.rollback()
            logger.warning("meta_message_retryable_failure", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Meta message processing temporarily failed",
            ) from exc
        except Exception:
            await db.rollback()
            logger.exception("meta_message_processing_failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Meta message processing temporarily failed",
            ) from None
        processed += 1 if created else 0
        ignored += 0 if created else 1

    return {"received": True, "processed": processed, "ignored": ignored}


async def _verified_payload(request: Request) -> dict[str, Any]:
    """Return the signed, size-bounded JSON object body of a Meta delivery."""
    body = await _bounded_body(request)
    _verify_signature(body, request.headers.get("x-hub-signature-256"))
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")
    return parsed


@router.post("/leadgen")
async def ingest_meta_leadgen_webhook(request: Request, db: DB) -> dict[str, int | bool]:
    """Fetch and idempotently persist every verified ``leadgen`` change."""
    parsed = await _verified_payload(request)

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
