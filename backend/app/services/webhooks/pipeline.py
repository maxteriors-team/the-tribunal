"""Reusable webhook processing pipeline primitives.

The pipeline enforces the common inbound-provider shape:

1. verify the provider signature / trust boundary;
2. parse the verified payload into an internal event DTO;
3. run an idempotency check before side effects;
4. dispatch to a domain service that persists state and runs side effects;
5. emit a structured audit result.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal, Protocol, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

WebhookTerminalStatus = Literal["processed", "ignored", "duplicate"]

VerifiedPayloadT = TypeVar("VerifiedPayloadT")
EventT = TypeVar("EventT", bound="WebhookEventDTO")


class WebhookEventDTO(Protocol):
    """Provider-neutral attributes every parsed webhook event exposes."""

    @property
    def provider(self) -> str:
        """Webhook provider name, e.g. ``resend`` or ``telnyx``."""

    @property
    def event_type(self) -> str:
        """Provider event type after parsing."""

    @property
    def event_id(self) -> str | None:
        """Provider delivery/event id when available."""

    @property
    def idempotency_key(self) -> str | None:
        """Stable key used by the idempotency checker."""


@dataclass(frozen=True, slots=True)
class WebhookRequestEnvelope:
    """Raw HTTP request data passed into a provider verifier."""

    provider: str
    raw_body: bytes
    headers: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class WebhookIdempotencyDecision:
    """Decision returned by a provider-specific idempotency checker."""

    should_process: bool
    reason: str | None = None

    @classmethod
    def process(cls, reason: str | None = None) -> WebhookIdempotencyDecision:
        """Allow the event to continue to domain dispatch."""
        return cls(should_process=True, reason=reason)

    @classmethod
    def duplicate(cls, reason: str = "duplicate") -> WebhookIdempotencyDecision:
        """Skip domain dispatch because this event was already processed."""
        return cls(should_process=False, reason=reason)


@dataclass(frozen=True, slots=True)
class WebhookDispatchResult:
    """Terminal result returned by a domain webhook service."""

    status: WebhookTerminalStatus
    reason: str | None = None

    @classmethod
    def processed(cls, reason: str | None = None) -> WebhookDispatchResult:
        return cls(status="processed", reason=reason)

    @classmethod
    def ignored(cls, reason: str) -> WebhookDispatchResult:
        return cls(status="ignored", reason=reason)

    @classmethod
    def duplicate(cls, reason: str = "duplicate") -> WebhookDispatchResult:
        return cls(status="duplicate", reason=reason)


@dataclass(frozen=True, slots=True)
class WebhookProcessingResult:
    """Result exposed to routers/tests after the pipeline finishes."""

    provider: str
    event_type: str
    event_id: str | None
    idempotency_key: str | None
    status: WebhookTerminalStatus
    duration_ms: int
    reason: str | None = None

    def response_body(self) -> dict[str, str]:
        """HTTP response body suitable for webhook providers.

        Providers only require a 2xx to stop retrying. The extra fields are
        stable and useful for tests or manual probes.
        """
        body = {"status": "ok"}
        if self.status == "duplicate":
            body["deduped"] = "true"
        if self.reason:
            body["reason"] = self.reason
        return body


Verifier = Callable[[WebhookRequestEnvelope], Awaitable[VerifiedPayloadT]]
Parser = Callable[[VerifiedPayloadT, WebhookRequestEnvelope], EventT]
IdempotencyChecker = Callable[[AsyncSession, EventT, Any], Awaitable[WebhookIdempotencyDecision]]
Dispatcher = Callable[[AsyncSession, EventT, Any], Awaitable[WebhookDispatchResult]]
AuditSink = Callable[[AsyncSession, EventT, WebhookProcessingResult, Any], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class WebhookPipeline[VerifiedPayloadT, EventT: WebhookEventDTO]:
    """Composable webhook pipeline for provider adapters."""

    provider: str
    verifier: Verifier[VerifiedPayloadT]
    parser: Parser[VerifiedPayloadT, EventT]
    idempotency_checker: IdempotencyChecker[EventT]
    dispatcher: Dispatcher[EventT]
    audit_sink: AuditSink[EventT] | None = None

    async def process(
        self,
        *,
        db: AsyncSession,
        request: WebhookRequestEnvelope,
        log: Any,
    ) -> WebhookProcessingResult:
        """Run the full verification → parse → dedupe → dispatch flow."""
        started_at = perf_counter()
        verified_payload = await self.verifier(request)
        event = self.parser(verified_payload, request)
        bound_log = log.bind(
            provider=event.provider,
            event_type=event.event_type,
            event_id=event.event_id,
            idempotency_key=event.idempotency_key,
        )
        bound_log.info("webhook_pipeline_received")

        decision = await self.idempotency_checker(db, event, bound_log)
        if not decision.should_process:
            result = self._result(
                event=event,
                started_at=started_at,
                status="duplicate",
                reason=decision.reason,
            )
            await self._audit(db, event, result, bound_log)
            bound_log.info(
                "webhook_pipeline_duplicate_skipped",
                duration_ms=result.duration_ms,
                reason=result.reason,
            )
            return result

        try:
            dispatch_result = await self.dispatcher(db, event, bound_log)
        except Exception as exc:
            duration_ms = _elapsed_ms(started_at)
            bound_log.exception(
                "webhook_pipeline_dispatch_failed",
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise

        result = self._result(
            event=event,
            started_at=started_at,
            status=dispatch_result.status,
            reason=dispatch_result.reason,
        )
        await self._audit(db, event, result, bound_log)
        bound_log.info(
            "webhook_pipeline_completed",
            status=result.status,
            duration_ms=result.duration_ms,
            reason=result.reason,
        )
        return result

    def _result(
        self,
        *,
        event: EventT,
        started_at: float,
        status: WebhookTerminalStatus,
        reason: str | None,
    ) -> WebhookProcessingResult:
        return WebhookProcessingResult(
            provider=self.provider,
            event_type=event.event_type,
            event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            status=status,
            duration_ms=_elapsed_ms(started_at),
            reason=reason,
        )

    async def _audit(
        self,
        db: AsyncSession,
        event: EventT,
        result: WebhookProcessingResult,
        log: Any,
    ) -> None:
        """Emit the optional provider-specific audit side channel."""
        if self.audit_sink is None:
            return
        await self.audit_sink(db, event, result, log)


def _elapsed_ms(started_at: float) -> int:
    return int(max(0.0, (perf_counter() - started_at) * 1000))
