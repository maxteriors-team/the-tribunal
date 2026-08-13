"""Postgres-backed replay rejection for signed provider webhooks.

Why this exists
---------------

An HMAC-over-body signature proves the *payload* came from a provider. It says
nothing about *when*, and it never expires: a captured ``(body, signature)`` pair
can verify forever when the provider does not sign a timestamp.

The only defense that does not rely on attacker-supplied input is remembering
what we have already accepted. :func:`claim_webhook_signature` does that in
Postgres, atomically, via ``INSERT ... ON CONFLICT DO NOTHING`` against the
``(provider, signature)`` UNIQUE constraint on
:class:`~app.models.webhook_signature.SeenWebhookSignature`.

Design notes
------------

* **Fail closed.** If the ledger cannot be reached we return
  :attr:`SignatureClaimOutcome.LEDGER_UNAVAILABLE` and the caller must refuse
  the delivery (503) so the provider retries. Processing a webhook we cannot
  dedupe is exactly the failure mode this module exists to remove — and the
  handlers need the same database anyway, so "let it through" would not have
  worked regardless.
* **Claim before dispatch.** The row is committed *before* the handlers run, so
  a crash mid-handler still burns the delivery. That matches the pre-existing
  Redis claim semantics: a provider retry of a delivery we already began is
  refused rather than replayed.
* **Only verified signatures land here.** Callers must run signature
  verification first, so an unauthenticated attacker cannot stuff the table.
* **Bounded retention.** Rows older than :data:`SIGNATURE_RETENTION_DAYS` are
  swept by :mod:`app.workers.webhook_signature_cleanup_worker`. A pair captured
  today and replayed after the window would be accepted again; rotate the
  webhook secret if a capture is ever suspected.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.webhook_signature import SeenWebhookSignature

# How long an accepted signature stays un-replayable. Deliberately much longer
# than the 7-day provider retry horizon used by the Redis delivery dedupe: this
# window is a security boundary, not a retry window. Bounded so the table (a few
# hundred bytes per booking webhook) cannot grow without limit.
SIGNATURE_RETENTION_DAYS = 30

SessionFactory = Callable[[], AsyncSession]


class SignatureClaimOutcome(StrEnum):
    """Result of trying to record a webhook signature as seen."""

    CLAIMED = "claimed"
    REPLAY = "replay"
    LEDGER_UNAVAILABLE = "ledger_unavailable"


@dataclass(frozen=True, slots=True)
class SignatureClaim:
    """Outcome of :func:`claim_webhook_signature`."""

    outcome: SignatureClaimOutcome

    @property
    def claimed(self) -> bool:
        """True only when this delivery is the first to present the signature."""
        return self.outcome is SignatureClaimOutcome.CLAIMED


async def claim_webhook_signature(
    provider: str,
    signature: str,
    *,
    log: Any,
    session_factory: SessionFactory = AsyncSessionLocal,
) -> SignatureClaim:
    """Record ``signature`` for ``provider``, reporting whether it was new.

    Args:
        provider: Short provider slug, e.g. ``"resend"``.
        signature: The verbatim signature header value. Callers MUST have
            verified it cryptographically first.
        log: Bound structlog logger.
        session_factory: Session factory override (tests).

    Returns:
        A :class:`SignatureClaim`. ``CLAIMED`` means first sighting (proceed),
        ``REPLAY`` means we already honoured this exact signature (refuse), and
        ``LEDGER_UNAVAILABLE`` means the check could not run (refuse, 503).

    Raises:
        ValueError: If ``provider`` or ``signature`` is empty. Not reachable
            from request handling — verification rejects unsigned requests long
            before this point — so an empty value is a programming error, not an
            attacker-controlled condition to be papered over.
    """
    provider_slug = provider.strip().lower()
    normalized = signature.strip()
    if not provider_slug:
        msg = "webhook replay provider must be non-empty"
        raise ValueError(msg)
    if not normalized:
        msg = "webhook replay signature must be non-empty"
        raise ValueError(msg)

    # ON CONFLICT DO NOTHING + RETURNING is a single atomic round trip: two
    # concurrent deliveries of the same signature cannot both see "new".
    statement = (
        pg_insert(SeenWebhookSignature)
        .values(
            id=uuid.uuid4(),
            provider=provider_slug,
            signature=normalized,
            created_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["provider", "signature"])
        .returning(SeenWebhookSignature.id)
    )

    try:
        async with session_factory() as db:
            result = await db.execute(statement)
            inserted = result.scalar_one_or_none()
            await db.commit()
    except Exception as exc:
        # Fail closed: the caller turns this into a 503 so the provider retries.
        log.error(
            "webhook_signature_ledger_unavailable",
            provider=provider_slug,
            error=str(exc),
        )
        return SignatureClaim(SignatureClaimOutcome.LEDGER_UNAVAILABLE)

    if inserted is None:
        return SignatureClaim(SignatureClaimOutcome.REPLAY)
    return SignatureClaim(SignatureClaimOutcome.CLAIMED)
