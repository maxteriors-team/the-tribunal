"""Cal.com webhook endpoints for appointment events.

This module is a thin FastAPI router. All real work is delegated:

- :mod:`app.api.webhooks.calcom_parser` — payload parsing / contact lookup
- :mod:`app.api.webhooks.calcom_events` — lifecycle SMS + downstream dispatch
- :mod:`app.api.webhooks.calcom_handlers` — per-event state-machine handlers
"""

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, status

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
from app.services.webhook_replay import (
    SignatureClaimOutcome,
    claim_webhook_signature,
)

router = APIRouter()
logger = structlog.get_logger()

# Idempotency dedupe window. Cal.com retries failed deliveries; the side
# effects in handlers (confirmation SMS, owner email) are not safe to
# replay. 7 days covers any plausible retry horizon while keeping the
# Redis footprint bounded.
_IDEMPOTENCY_TTL_SECONDS = DEFAULT_WEBHOOK_IDEMPOTENCY_TTL_SECONDS
_IDEMPOTENCY_KEY_PREFIX = webhook_key_prefix("calcom")

# Header carrying the HMAC-SHA256 digest Cal.com computes over the raw body.
_SIGNATURE_HEADER = "x-cal-signature-256"

# ``claim_redis_idempotency_key`` reports an unreachable Redis by returning
# ``claimed=True`` with this reason (fail open) so callers can choose. This
# route chooses to fail closed — see ``_claim_webhook_delivery``.
_REDIS_UNAVAILABLE_REASON = "redis_unavailable"


def _build_idempotency_key(payload: dict[str, Any]) -> str | None:
    """Derive a stable idempotency key from a Cal.com webhook payload.

    Preference order matches the task contract:

    1. ``payload.id`` (outer) — Cal.com's own delivery id when present.
    2. ``triggerEvent + uid + createdAt`` — composite fallback. ``uid`` is
       the booking identifier (stable across retries for the same
       booking event); ``createdAt`` differentiates legitimate retries
       of distinct events for the same booking (e.g. created then
       rescheduled).

    Returns ``None`` when the payload carries no usable delivery identity. The
    caller rejects those with 400: a delivery we cannot dedupe is a delivery we
    would happily replay, and Cal.com always sends at least one of these fields.
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

    Fails CLOSED on Redis errors. The shared helper reports an unreachable
    Redis as "claimed" so each caller can pick a policy; this route picks 503.
    Letting a delivery through un-deduped means re-firing confirmation SMS and
    owner email, and the per-row handler guards do not cover every trigger. A
    503 costs us nothing: Cal.com retries, and by then Redis is usually back.

    Raises:
        HTTPException: 503 when the idempotency store is unreachable.
    """
    claim = await claim_redis_idempotency_key(
        key,
        ttl_seconds=_IDEMPOTENCY_TTL_SECONDS,
        log=log,
        redis_getter=get_redis,
        failure_event="calcom_idempotency_redis_unavailable",
    )
    if claim.reason == _REDIS_UNAVAILABLE_REASON:
        log.error("calcom_webhook_idempotency_store_unavailable", key=key)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook idempotency store unavailable",
        )
    return claim.claimed


async def _reject_replayed_signature(request: Request, log: Any) -> None:
    """Burn this delivery's signature in the durable ledger, or refuse it.

    Cal.com's HMAC authenticates the *body*, not the *delivery*: a captured
    ``(body, x-cal-signature-256)`` pair verifies forever, and the unsigned
    ``x-cal-timestamp`` header cannot fix that (see
    :func:`app.core.webhook_security.verify_calcom_webhook`). Remembering which
    signatures we already honoured is the defence that does not depend on
    attacker-supplied input.

    Must be called AFTER signature verification (so only digests we computed
    ourselves can reach the table) and BEFORE any dispatch or side effect.
    Split out as its own coroutine so tests can patch the whole check in one
    place.

    Raises:
        HTTPException: 409 if this exact signature was already accepted, 503 if
            the ledger is unreachable (fail closed — Cal.com retries).
    """
    signature = request.headers.get(_SIGNATURE_HEADER, "")
    if not signature:
        # Only reachable via ``settings.skip_webhook_verification`` (local dev):
        # in production, verification 403s an unsigned delivery long before
        # this point. Nothing to remember, so there is nothing to enforce.
        log.warning("calcom_webhook_signature_ledger_skipped_unsigned")
        return

    claim = await claim_webhook_signature("calcom", signature, log=log)

    if claim.outcome is SignatureClaimOutcome.REPLAY:
        log.warning("calcom_webhook_signature_replay_rejected")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate Cal.com webhook signature",
        )

    if claim.outcome is SignatureClaimOutcome.LEDGER_UNAVAILABLE:
        # Fail closed. Processing a delivery we cannot dedupe is precisely the
        # failure mode the ledger exists to remove, and the handlers need the
        # same database anyway.
        log.error("calcom_webhook_signature_ledger_unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook replay ledger unavailable",
        )


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

    Every delivery passes two gates before a single side effect runs:
    signature verification, then the durable replay ledger. Both fail closed.
    """
    log = logger.bind(endpoint="calcom_booking_webhook")

    try:
        await verify_calcom_webhook(request)
    except Exception as e:
        log.error("webhook_verification_failed", error=str(e))
        observe_calcom_signature_invalid()
        raise

    # Replay rejection, immediately after verification and before anything
    # observable happens. A verified signature we have already honoured is a
    # replay no matter how fresh it looks, so it never reaches parsing,
    # metrics, or dispatch.
    await _reject_replayed_signature(request, log)

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
    # downstream side effects (confirmation SMS, owner email) are not
    # safe to replay. Claim a dedupe slot in Redis before dispatching.
    # The per-row ``is_new_booking`` guard in ``handle_booking_created``
    # already prevents duplicate SMS/email on retried BOOKING_CREATED
    # events; this Redis dedupe is the explicit safety net for that and
    # for every other handler.
    idempotency_key = _build_idempotency_key(payload)
    if idempotency_key is None:
        # No delivery identity means no dedupe slot, and dispatching anyway
        # would re-run side effects on every retry. Reject instead of
        # proceeding blind; real Cal.com payloads always carry these fields, so
        # this is a malformed delivery, not a legitimate one we are dropping.
        log.warning("calcom_webhook_missing_idempotency_fields")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cal.com webhook payload is missing delivery identity fields",
        )

    claimed = await _claim_webhook_delivery(idempotency_key, log)
    if not claimed:
        log.info(
            "calcom_webhook_replay_skipped",
            idempotency_key=idempotency_key,
        )
        return {"status": "ok", "deduped": "true"}

    handler = _EVENT_DISPATCH.get(trigger)
    if handler is None:
        log.debug("unhandled_event_type")
    else:
        await handler(data, log)

    return {"status": "ok"}
