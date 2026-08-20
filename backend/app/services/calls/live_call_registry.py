"""In-process registry of live voice calls for operator supervision.

This module gives operators a way to *listen*, *whisper*, and *barge in* on a
live Telnyx<->AI call. The voice bridge (``app/websockets/voice_bridge.py``)
registers a :class:`LiveCall` for the duration of each call and feeds it the
audio it is already relaying in both directions. The supervisor WebSocket
(``app/websockets/call_supervisor.py``) looks the call up by id, subscribes to
its audio fan-out, and issues control actions back to it.

Concurrency model
-----------------
A single backend process owns each Telnyx WebSocket, so the registry is
deliberately **in-process** (a module-level singleton). This matches the
project's "all workers run inside the single ``backend-api`` process" note: a
supervisor can only attach to a call that is being relayed by the *same*
process. The per-workspace concurrency cap is already enforced in Redis by
``connection_limits``, so a cross-replica roster is out of scope here.

All writes to the Telnyx WebSocket (AI audio *and* operator barge-in audio)
are funnelled through :meth:`LiveCall.send_to_telnyx_mulaw` under a per-call
lock so frames from the relay loop and the supervisor task never interleave.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import time
import uuid
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

try:  # Python 3.13 removed the stdlib ``audioop`` module.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="'audioop' is deprecated and slated for removal in Python 3.13",
            category=DeprecationWarning,
        )
        import audioop
except ModuleNotFoundError:  # pragma: no cover - exercised only on 3.13+
    import audioop_lts as audioop  # type: ignore[no-redef]

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = structlog.get_logger()

# Fan-out queue depth per supervisor. ~50 frames/sec of 20ms µ-law, so 150 is
# ~3s of buffered audio. On overflow we drop the oldest frame rather than block
# the audio relay — a lagging operator socket must never add latency to the
# live caller<->AI path.
_SUBSCRIBER_QUEUE_MAXSIZE = 150

# Hard cap on simultaneous supervisors per call. Keeps fan-out cost bounded.
_MAX_SUPERVISORS_PER_CALL = 5


@dataclass(frozen=True)
class LiveCallInfo:
    """Serializable snapshot of a live call for the roster API."""

    call_id: str
    workspace_id: str
    direction: str
    agent_name: str | None
    contact_name: str | None
    contact_phone: str | None
    started_at: float
    supervisor_count: int
    barged: bool

    def as_dict(self) -> dict[str, Any]:
        """Render for the JSON roster response."""
        from datetime import UTC, datetime

        return {
            "call_id": self.call_id,
            "workspace_id": self.workspace_id,
            "direction": self.direction,
            "agent_name": self.agent_name,
            "contact_name": self.contact_name,
            "contact_phone": self.contact_phone,
            "started_at": datetime.fromtimestamp(self.started_at, tz=UTC).isoformat(),
            "duration_seconds": max(0, int(time.time() - self.started_at)),
            "supervisor_count": self.supervisor_count,
            "barged": self.barged,
        }


class LiveCall:
    """Live-call presence + audio fan-out + operator control for one call.

    Audio published to the registry is always µ-law 8kHz (the Telnyx wire
    format). Supervisor sockets are responsible for transcoding for the
    browser. Barge-in audio arriving from a supervisor is converted to µ-law
    here before being written to Telnyx.
    """

    def __init__(
        self,
        *,
        call_id: str,
        workspace_id: str,
        telnyx_ws: WebSocket,
        voice_session: Any,
        direction: str,
        agent_name: str | None = None,
        contact_name: str | None = None,
        contact_phone: str | None = None,
        log: Any | None = None,
    ) -> None:
        self.call_id = call_id
        self.workspace_id = str(workspace_id)
        self.direction = direction
        self.agent_name = agent_name
        self.contact_name = contact_name
        self.contact_phone = contact_phone
        self.started_at = time.time()

        self._telnyx_ws = telnyx_ws
        self._voice_session = voice_session
        self._log = (log or logger).bind(component="live_call", call_id=call_id)

        self._send_lock = asyncio.Lock()
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

        # Barge-in / take-over state. ``ai_muted`` is read by the relay loop on
        # every provider audio chunk; when True the AI's audio is dropped and
        # the operator drives the call instead.
        self.ai_muted: bool = False
        self.barged_by: int | None = None

    # ------------------------------------------------------------------
    # Telnyx writes (serialized)
    # ------------------------------------------------------------------
    async def send_to_telnyx_mulaw(self, mulaw: bytes) -> None:
        """Write a µ-law audio frame to the Telnyx media stream.

        Funnels every outbound frame (AI *and* operator barge-in) through one
        lock so concurrent senders never interleave bytes on the socket.
        """
        if not mulaw:
            return
        payload = base64.b64encode(mulaw).decode("utf-8")
        message = json.dumps({"event": "media", "media": {"payload": payload}})
        async with self._send_lock:
            await self._telnyx_ws.send_text(message)

    # ------------------------------------------------------------------
    # Audio fan-out to supervisors
    # ------------------------------------------------------------------
    def add_subscriber(self) -> asyncio.Queue[dict[str, Any]] | None:
        """Register a supervisor audio queue. Returns None if the call is full."""
        if len(self._subscribers) >= _MAX_SUPERVISORS_PER_CALL:
            return None
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_MAXSIZE)
        self._subscribers.add(queue)
        self._log.info("supervisor_subscribed", supervisor_count=len(self._subscribers))
        return queue

    def remove_subscriber(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Deregister a supervisor audio queue."""
        self._subscribers.discard(queue)
        self._log.info("supervisor_unsubscribed", supervisor_count=len(self._subscribers))

    @property
    def supervisor_count(self) -> int:
        """Number of operators currently attached to this call."""
        return len(self._subscribers)

    def publish(self, track: str, mulaw: bytes) -> None:
        """Fan a µ-law frame out to every subscriber.

        Non-blocking: a full queue means the operator's socket is lagging, so
        we drop the oldest frame to make room rather than apply backpressure to
        the live audio relay.
        """
        if not self._subscribers or not mulaw:
            return
        for queue in self._subscribers:
            self._offer(queue, {"track": track, "mulaw": mulaw})

    @staticmethod
    def _offer(queue: asyncio.Queue[dict[str, Any]], item: dict[str, Any]) -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            # Lagging subscriber: drop the oldest frame to make room. Both ops
            # may still race other producers, so suppress and move on rather
            # than block the live audio relay.
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(item)

    # ------------------------------------------------------------------
    # Operator controls
    # ------------------------------------------------------------------
    async def whisper(self, text: str) -> bool:
        """Inject private operator guidance into the AI session.

        The guidance steers the AI's *next* response; it is not spoken aloud
        and the caller never hears it. Returns False if the underlying provider
        session does not support guidance injection.
        """
        text = (text or "").strip()
        if not text:
            return False
        inject = getattr(self._voice_session, "inject_operator_guidance", None)
        if inject is None:
            self._log.warning("whisper_unsupported_by_provider")
            return False
        try:
            await inject(text)
        except Exception as exc:  # never let a whisper break the call
            self._log.warning("whisper_failed", error=str(exc))
            return False
        self._log.info("operator_whisper", chars=len(text))
        return True

    async def start_barge(self, operator_user_id: int) -> None:
        """Take over the call: mute the AI and stop any in-flight AI response."""
        self.ai_muted = True
        self.barged_by = operator_user_id
        # Stop the AI mid-utterance so the caller hears the operator promptly.
        cancel = getattr(self._voice_session, "cancel_response", None)
        if cancel is not None:
            try:
                await cancel()
            except Exception as exc:
                self._log.warning("barge_cancel_response_failed", error=str(exc))
        self._log.info("operator_barge_start", operator_user_id=operator_user_id)

    async def stop_barge(self) -> None:
        """Hand control back to the AI."""
        if not self.ai_muted:
            return
        self.ai_muted = False
        self.barged_by = None
        self._log.info("operator_barge_stop")

    async def send_barge_audio_pcm16(self, pcm16_16k: bytes) -> None:
        """Forward operator microphone audio (PCM16 16kHz) to the caller.

        No-op unless the operator currently holds the call via :meth:`start_barge`.
        """
        if not self.ai_muted or not pcm16_16k:
            return
        # PCM16 16kHz -> 8kHz, then encode µ-law for Telnyx.
        pcm_8k, _ = audioop.ratecv(pcm16_16k, 2, 1, 16000, 8000, None)
        mulaw = audioop.lin2ulaw(pcm_8k, 2)
        await self.send_to_telnyx_mulaw(mulaw)

    # ------------------------------------------------------------------
    # Roster snapshot
    # ------------------------------------------------------------------
    def info(self) -> LiveCallInfo:
        """Return a serializable snapshot for the roster API."""
        return LiveCallInfo(
            call_id=self.call_id,
            workspace_id=self.workspace_id,
            direction=self.direction,
            agent_name=self.agent_name,
            contact_name=self.contact_name,
            contact_phone=self.contact_phone,
            started_at=self.started_at,
            supervisor_count=self.supervisor_count,
            barged=self.ai_muted,
        )


class LiveCallRegistry:
    """Process-wide map of active calls keyed by Telnyx call-control id."""

    def __init__(self) -> None:
        self._calls: dict[str, LiveCall] = {}

    def register(self, live_call: LiveCall) -> None:
        """Add a call to the roster."""
        self._calls[live_call.call_id] = live_call
        logger.info(
            "live_call_registered",
            call_id=live_call.call_id,
            workspace_id=live_call.workspace_id,
            active_calls=len(self._calls),
        )

    def unregister(self, call_id: str) -> None:
        """Remove a call from the roster (idempotent)."""
        if self._calls.pop(call_id, None) is not None:
            logger.info(
                "live_call_unregistered",
                call_id=call_id,
                active_calls=len(self._calls),
            )

    def get(self, call_id: str, workspace_id: str | uuid.UUID | None = None) -> LiveCall | None:
        """Look up a live call, optionally enforcing workspace scope.

        Returns None if the call is unknown OR if ``workspace_id`` is supplied
        and does not match the call's workspace (cross-tenant access guard).
        """
        live_call = self._calls.get(call_id)
        if live_call is None:
            return None
        if workspace_id is not None and live_call.workspace_id != str(workspace_id):
            return None
        return live_call

    def list_for_workspace(self, workspace_id: str | uuid.UUID) -> list[LiveCallInfo]:
        """Return roster snapshots for all live calls in a workspace."""
        target = str(workspace_id)
        return [call.info() for call in self._calls.values() if call.workspace_id == target]


# Module-level singleton. The voice bridge and supervisor socket share it.
_registry = LiveCallRegistry()


def get_live_call_registry() -> LiveCallRegistry:
    """Return the process-wide live-call registry singleton."""
    return _registry
