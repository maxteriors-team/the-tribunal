"""Ring logged-in operators' browsers on an inbound call; first accept wins.

An inbound call normally goes straight to the AI agent (or the fallback number).
When a workspace turns on ``PhoneNumber.inbound_ring_operators``, we first give
the humans a chance: every available, non-busy operator whose dashboard holds a
registered browser headset is dialed over internal SIP, and whoever accepts
first is bridged to the caller. The losing headsets are hung up immediately.

**Falling through is the whole safety story.** Nobody available, every dial
refused, nobody accepting before the ring timeout — each of those must land the
caller back in the existing AI/fallback path, never in silence. So
:func:`ring_operators` returns ``False`` for "I did not take responsibility for
this call", and the webhook caller then runs exactly what it ran before.

State lives in Redis under *every* leg id (caller + each operator leg), because
Telnyx webhooks land on any replica and the accept can arrive anywhere. The
claim that decides the winner is a single Redis ``SET NX`` — two operators
hitting Accept in the same millisecond cannot both win.

No call recording is started here. A human-answered call stays unrecorded unless
a workspace explicitly opts in, and any recording is preceded by a spoken notice
(:mod:`app.services.telephony.recording_notice`).
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.redis import get_redis
from app.models.user import User
from app.models.workspace import WorkspaceMembership
from app.services.telephony.operator_presence import (
    clear_busy,
    list_idle_available,
    mark_busy,
)

if TYPE_CHECKING:
    from app.services.telephony.telnyx_voice import TelnyxVoiceService

logger = structlog.get_logger()

_PENDING_PREFIX = "voice:operatorring:pending:"
_CLAIM_PREFIX = "voice:operatorring:claim:"
_PENDING_TTL_SECONDS = 300  # A ring resolves in well under a minute.

# Echoed by Telnyx on every webhook for an operator leg, so a leg stays
# recognisable even if the Redis state is gone.
OPERATOR_RING_CLIENT_STATE_PREFIX = "operator_ring"
_MAX_CLIENT_STATE_LENGTH = 256

# How long the headsets ring before the caller falls through to AI/fallback.
RING_TIMEOUT_SECONDS = 20

# What the webhook layer must do after a leg in an operator ring hung up.
RingHangupOutcome = Literal["not_ours", "handled", "exhausted"]

# Cap on simultaneously rung headsets: every leg is billable, and a workspace
# with fifty idle dashboards must not turn one inbound call into fifty legs.
MAX_OPERATORS_RUNG = 5


@dataclass(frozen=True, slots=True)
class PendingOperatorRing:
    """State linking the inbound caller leg to the operator legs we dialed."""

    caller_call_control_id: str
    operator_legs: dict[str, int]  # operator leg ccid -> user id
    message_id: str
    workspace_id: str
    created_at: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "caller_call_control_id": self.caller_call_control_id,
                "operator_legs": self.operator_legs,
                "message_id": self.message_id,
                "workspace_id": self.workspace_id,
                "created_at": self.created_at,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> PendingOperatorRing:
        data = json.loads(raw)
        return cls(
            caller_call_control_id=data["caller_call_control_id"],
            operator_legs={str(k): int(v) for k, v in (data.get("operator_legs") or {}).items()},
            message_id=data["message_id"],
            workspace_id=data["workspace_id"],
            created_at=data.get("created_at", ""),
        )

    def other_operator_legs(self, winner_call_control_id: str) -> list[str]:
        """Return every operator leg except the winner's."""
        return [ccid for ccid in self.operator_legs if ccid != winner_call_control_id]


def make_operator_ring_client_state(message_id: Any) -> str:
    """Return base64 ``client_state`` marking a leg as an operator ring leg."""
    raw = f"{OPERATOR_RING_CLIENT_STATE_PREFIX}:{message_id}"
    return base64.b64encode(raw.encode("ascii")).decode("ascii")


def decode_operator_ring_client_state(raw: object) -> str | None:
    """Return the message id in an operator-ring ``client_state``, if it is one.

    ``client_state`` comes back from the provider and is therefore untrusted:
    anything that is not our own marker returns ``None``.
    """
    if not isinstance(raw, str) or not raw or len(raw) > _MAX_CLIENT_STATE_LENGTH:
        return None
    try:
        decoded = base64.b64decode(raw, validate=True).decode("ascii")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    prefix = f"{OPERATOR_RING_CLIENT_STATE_PREFIX}:"
    if not decoded.startswith(prefix):
        return None
    return decoded[len(prefix) :] or None


def _keys_for(pending: PendingOperatorRing) -> list[str]:
    keys = [_PENDING_PREFIX + pending.caller_call_control_id]
    keys.extend(_PENDING_PREFIX + ccid for ccid in pending.operator_legs)
    return keys


async def store_pending_ring(pending: PendingOperatorRing) -> None:
    """Persist ring state under the caller leg and every operator leg."""
    try:
        client = await get_redis()
        payload = pending.to_json()
        for key in _keys_for(pending):
            await client.set(key, payload, ex=_PENDING_TTL_SECONDS)
    except Exception as exc:  # pragma: no cover - Redis best-effort
        logger.warning("store_pending_operator_ring_failed", error=str(exc))


async def peek_pending_ring(call_control_id: str) -> PendingOperatorRing | None:
    """Read ring state for any participating leg without deleting it."""
    try:
        client = await get_redis()
        raw = await client.get(_PENDING_PREFIX + call_control_id)
        return PendingOperatorRing.from_json(raw) if raw is not None else None
    except Exception as exc:  # pragma: no cover - Redis best-effort
        logger.warning("peek_pending_operator_ring_failed", error=str(exc))
        return None


async def pop_pending_ring(call_control_id: str) -> PendingOperatorRing | None:
    """Fetch ring state for any leg and delete it for every leg."""
    try:
        client = await get_redis()
        raw = await client.get(_PENDING_PREFIX + call_control_id)
        if raw is None:
            return None
        pending = PendingOperatorRing.from_json(raw)
        for key in _keys_for(pending):
            await client.delete(key)
        await client.delete(_CLAIM_PREFIX + pending.caller_call_control_id)
        return pending
    except Exception as exc:  # pragma: no cover - Redis best-effort
        logger.warning("pop_pending_operator_ring_failed", error=str(exc))
        return None


async def claim_call(caller_call_control_id: str, operator_call_control_id: str) -> bool:
    """Atomically decide the single winning operator leg.

    ``SET NX`` is the whole race resolution: the first accept writes the key and
    is bridged, every later accept fails the write and is hung up. If Redis is
    unreachable we refuse the claim — dropping one accepted call is recoverable,
    bridging two operators onto one caller is not.
    """
    try:
        client = await get_redis()
        claimed = await client.set(
            _CLAIM_PREFIX + caller_call_control_id,
            operator_call_control_id,
            nx=True,
            ex=_PENDING_TTL_SECONDS,
        )
        return bool(claimed)
    except Exception as exc:  # pragma: no cover - Redis best-effort
        logger.warning("operator_ring_claim_failed", error=str(exc))
        return False


async def is_claimed(caller_call_control_id: str) -> bool:
    """True once some operator has won this call.

    Distinguishes "the headsets rang out" (fall through to AI) from "a human
    took it and the conversation ended" (do nothing). On a Redis failure we
    report claimed, so a lost lookup can never re-answer a finished call with
    the AI agent.
    """
    try:
        client = await get_redis()
        return bool(await client.exists(_CLAIM_PREFIX + caller_call_control_id))
    except Exception as exc:  # pragma: no cover - Redis best-effort
        logger.warning("operator_ring_claim_lookup_failed", error=str(exc))
        return True


async def ring_operators(
    *,
    db: AsyncSession,
    voice_service: TelnyxVoiceService,
    workspace_id: uuid.UUID,
    message_id: uuid.UUID,
    caller_call_control_id: str,
    from_number: str,
    connection_id: str,
    webhook_url: str,
    log: Any,
) -> bool:
    """Ring available operators' browsers. True when this call is now theirs.

    Returns ``False`` when nobody could be rung, so the caller falls through to
    the existing AI-answering / fallback behaviour unchanged.
    """
    user_ids = await list_idle_available(str(workspace_id))
    if not user_ids:
        log.info("operator_ring_no_one_available")
        return False

    # Only operators with a provisioned browser identity can be rung, and
    # membership is joined in SQL so another tenant's user can never be dialed
    # even if a stray presence key names them.
    result = await db.execute(
        select(User.id, User.telnyx_sip_username)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .where(
            User.id.in_(user_ids),
            WorkspaceMembership.workspace_id == workspace_id,
            User.telnyx_sip_username.is_not(None),
            User.is_active.is_(True),
        )
        .limit(MAX_OPERATORS_RUNG)
    )
    candidates = [(int(row[0]), str(row[1])) for row in result.all()]
    if not candidates:
        log.info("operator_ring_no_registered_headsets")
        return False

    client_state = make_operator_ring_client_state(message_id)
    operator_legs: dict[str, int] = {}
    for user_id, sip_username in candidates:
        leg_ccid = await voice_service.dial_browser_leg(
            sip_username=sip_username,
            from_number=from_number,
            connection_id=connection_id,
            webhook_url=webhook_url,
            client_state=client_state,
            command_id=f"operator-ring-{message_id}-{user_id}",
            timeout_secs=RING_TIMEOUT_SECONDS,
        )
        if leg_ccid:
            operator_legs[leg_ccid] = user_id

    if not operator_legs:
        log.warning("operator_ring_all_dials_failed")
        return False

    await store_pending_ring(
        PendingOperatorRing(
            caller_call_control_id=caller_call_control_id,
            operator_legs=operator_legs,
            message_id=str(message_id),
            workspace_id=str(workspace_id),
            created_at=datetime.now(UTC).isoformat(),
        )
    )
    log.info("operator_ring_started", operators_rung=len(operator_legs))
    return True


async def handle_operator_leg_answered(
    call_control_id: str,
    voice_service: TelnyxVoiceService,
    log: Any,
) -> bool:
    """Bridge the winning operator to the caller; hang up the losing headsets.

    Returns True when ``call_control_id`` was an operator ring leg, so the
    normal AI-streaming path short-circuits.
    """
    from app.db.session import AsyncSessionLocal
    from app.models.conversation import Message, MessageStatus

    pending = await peek_pending_ring(call_control_id)
    if pending is None or call_control_id not in pending.operator_legs:
        return False

    if not await claim_call(pending.caller_call_control_id, call_control_id):
        # Someone else accepted first. Drop this headset without touching the
        # caller leg, which is already being bridged to the winner.
        log.info("operator_ring_lost_race")
        await voice_service.hangup_call(call_control_id)
        return True

    user_id = pending.operator_legs[call_control_id]
    bridged = await voice_service.bridge_calls(
        call_control_id=call_control_id,
        other_call_control_id=pending.caller_call_control_id,
    )
    if not bridged:
        log.error("operator_ring_bridge_failed")
        await voice_service.hangup_call(call_control_id)
        return True

    await mark_busy(pending.workspace_id, user_id)
    for loser_ccid in pending.other_operator_legs(call_control_id):
        await voice_service.hangup_call(loser_ccid)

    async with AsyncSessionLocal() as db:
        message = await db.get(Message, uuid.UUID(pending.message_id))
        if message is not None:
            message.status = MessageStatus.ANSWERED
            await db.commit()

    log.info("operator_ring_bridged", message_id=pending.message_id)
    return True


async def handle_operator_leg_hangup(
    call_control_id: str,
    voice_service: TelnyxVoiceService,
    log: Any,
) -> RingHangupOutcome:
    """Clean up when a ringing/bridged operator leg or the caller leg ends.

    Returns ``"not_ours"`` when the leg is unrelated to an operator ring, and
    ``"exhausted"`` when every headset has now gone without anyone accepting —
    the caller is still holding, so the webhook layer must fall through to the
    normal AI/fallback answering rather than leave them in silence.
    """
    pending = await peek_pending_ring(call_control_id)
    if pending is None:
        return "not_ours"

    if call_control_id == pending.caller_call_control_id:
        # Caller gave up while the headsets were still ringing: stop ringing
        # every one of them, then drop the state.
        await pop_pending_ring(call_control_id)
        for leg_ccid in pending.operator_legs:
            await voice_service.hangup_call(leg_ccid)
        for user_id in set(pending.operator_legs.values()):
            await clear_busy(pending.workspace_id, user_id)
        log.info("operator_ring_caller_hung_up")
        return "handled"

    ended_user_id = pending.operator_legs.get(call_control_id)
    if ended_user_id is not None:
        await clear_busy(pending.workspace_id, ended_user_id)

    surviving = await _surviving_operator_legs(pending, call_control_id)
    if surviving:
        log.info("operator_ring_leg_hung_up", remaining=len(surviving))
        return "handled"

    # Last headset gone. Either a human took the call and it is over, or the
    # ring timed out and the caller is still waiting on us.
    claimed = await is_claimed(pending.caller_call_control_id)
    await pop_pending_ring(call_control_id)
    if claimed:
        log.info("operator_ring_call_completed")
        return "handled"
    log.info("operator_ring_unanswered_falling_through")
    return "exhausted"


async def _surviving_operator_legs(
    pending: PendingOperatorRing,
    ended_call_control_id: str,
) -> list[str]:
    """Return operator legs whose per-leg state key still exists.

    Each leg deletes its own key as it ends, so the keys that remain are the
    headsets still ringing. Redis is the only cross-replica view of that:
    hangups for sibling legs can be processed by different backend processes.
    """
    try:
        client = await get_redis()
        await client.delete(_PENDING_PREFIX + ended_call_control_id)
        surviving = []
        for leg_ccid in pending.other_operator_legs(ended_call_control_id):
            if await client.exists(_PENDING_PREFIX + leg_ccid):
                surviving.append(leg_ccid)
        return surviving
    except Exception as exc:  # pragma: no cover - Redis best-effort
        logger.warning("operator_ring_surviving_lookup_failed", error=str(exc))
        return []
