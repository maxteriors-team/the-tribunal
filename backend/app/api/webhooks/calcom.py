"""Cal.com webhook endpoints for appointment events.

This module is a thin FastAPI router. All real work is delegated:

- :mod:`app.api.webhooks.calcom_parser` — payload parsing / contact lookup
- :mod:`app.api.webhooks.calcom_events` — lifecycle SMS + downstream dispatch
- :mod:`app.api.webhooks.calcom_handlers` — per-event state-machine handlers
"""

from typing import Any

import structlog
from fastapi import APIRouter, Request

from app.api.webhooks.calcom_handlers import (
    handle_booking_cancelled,
    handle_booking_created,
    handle_booking_rescheduled,
    handle_meeting_ended,
)
from app.core.metrics import (
    observe_calcom_signature_invalid,
    observe_calcom_webhook,
)
from app.core.webhook_security import verify_calcom_webhook
from app.db.redis import get_redis
from app.services.idempotency import (
    DEFAULT_WEBHOOK_IDEMPOTENCY_TTL_SECONDS,
    claim_redis_idempotency_key,
    derive_webhook_delivery_key,
    webhook_key_prefix,
)

router = APIRouter()
logger = structlog.get_logger()

# Idempotency dedupe window. Cal.com retries failed deliveries; the side
# effects in handlers (confirmation SMS, realtor email) are not safe to
# replay. 7 days covers any plausible retry horizon while keeping the
# Redis footprint bounded.
_IDEMPOTENCY_TTL_SECONDS = DEFAULT_WEBHOOK_IDEMPOTENCY_TTL_SECONDS
_IDEMPOTENCY_KEY_PREFIX = webhook_key_prefix("calcom")


def _build_idempotency_key(payload: dict[str, Any]) -> str | None:
    """Derive a stable idempotency key from a Cal.com webhook payload.

    Preference order matches the task contract:

    1. ``payload.id`` (outer) — Cal.com's own delivery id when present.
    2. ``triggerEvent + uid + createdAt`` — composite fallback. ``uid`` is
       the booking identifier (stable across retries for the same
       booking event); ``createdAt`` differentiates legitimate retries
       of distinct events for the same booking (e.g. created then
       rescheduled).

    Returns ``None`` if we can't build any meaningful key — caller must
    fail open in that case rather than block traffic.
    """
    delivery_id = payload.get("id")
    if delivery_id:
        return derive_webhook_delivery_key("calcom", delivery_id)

    trigger = payload.get("trigger") or payload.get("triggerEvent") or ""
    data = payload.get("data") or payload.get("payload") or {}
    # For flat-payload events (MEETING_ENDED) the booking fields live at
    # the top level alongside ``triggerEvent``.
    uid = data.get("uid") if isinstance(data, dict) else None
    if not uid:
        uid = payload.get("uid", "")
    created_at = payload.get("createdAt", "")

    if not (trigger and uid):
        return None
    if created_at:
        return derive_webhook_delivery_key("calcom", trigger, uid, created_at)
    return derive_webhook_delivery_key("calcom", trigger, uid)


async def _claim_webhook_delivery(key: str, log: Any) -> bool:
    """Atomically reserve a webhook delivery slot.

    Uses ``SET key 1 NX EX 604800``. Returns ``True`` when the caller
    won the race and should process the webhook; ``False`` when a prior
    delivery already claimed the slot (replay — skip side effects).

    Fails open on Redis errors: the handlers' own per-row guards
    (``is_new_booking`` etc.) remain the primary defense; the Redis
    check is an explicit safety net layered on top. A Redis outage
    must not silently drop legitimate webhooks.
    """
    claim = await claim_redis_idempotency_key(
        key,
        ttl_seconds=_IDEMPOTENCY_TTL_SECONDS,
        log=log,
        redis_getter=get_redis,
        failure_event="calcom_idempotency_redis_unavailable",
    )
    return claim.claimed


# Dispatch table keyed by Cal.com ``trigger`` field.
# Using a dict avoids a long if/elif chain (ruff PLR0911/PLR0912) and keeps
# the router trivially extensible.
_EVENT_DISPATCH: dict[str, Any] = {
    "BOOKING_CREATED": handle_booking_created,
    "BOOKING_RESCHEDULED": handle_booking_rescheduled,
    "BOOKING_CANCELLED": handle_booking_cancelled,
    "MEETING_ENDED": handle_meeting_ended,
}


@router.post("/booking")
async def calcom_booking_webhook(request: Request) -> dict[str, str]:
    """Handle Cal.com booking events.

    Cal.com sends webhooks for:
    - ``BOOKING_CREATED``: New booking created
    - ``BOOKING_RESCHEDULED``: Booking rescheduled
    - ``BOOKING_CANCELLED``: Booking cancelled
    - ``MEETING_ENDED``: Meeting completed (or marked no-show)

    All webhooks are signature-verified before processing.
    """
    log = logger.bind(endpoint="calcom_booking_webhook")

    try:
        await verify_calcom_webhook(request)
    except Exception as e:
        log.error("webhook_verification_failed", error=str(e))
        observe_calcom_signature_invalid()
        raise

    try:
        payload = await request.json()
    except Exception as e:
        log.error("invalid_json_payload", error=str(e))
        return {"status": "error", "message": "Invalid JSON"}

    trigger = payload.get("trigger", "")
    data = payload.get("data", {})

    log = log.bind(event_type=trigger)
    log.info("webhook_received")
    observe_calcom_webhook(trigger)

    # Idempotency check: Cal.com retries failed deliveries, and the
    # downstream side effects (confirmation SMS, realtor email) are not
    # safe to replay. Claim a dedupe slot in Redis before dispatching.
    # The per-row ``is_new_booking`` guard in ``handle_booking_created``
    # already prevents duplicate SMS/email on retried BOOKING_CREATED
    # events; this Redis dedupe is the explicit safety net for that and
    # for every other handler.
    idempotency_key = _build_idempotency_key(payload)
    if idempotency_key is not None:
        claimed = await _claim_webhook_delivery(idempotency_key, log)
        if not claimed:
            log.info(
                "calcom_webhook_replay_skipped",
                idempotency_key=idempotency_key,
            )
            return {"status": "ok", "deduped": "true"}
    else:
        log.warning("calcom_webhook_missing_idempotency_fields")

    handler = _EVENT_DISPATCH.get(trigger)
    if handler is None:
        log.debug("unhandled_event_type")
    else:
        await handler(data, log)

    return {"status": "ok"}
