"""Circuit breakers for external providers.

This module instantiates one :class:`pybreaker.CircuitBreaker` per external
dependency (Telnyx, Cal.com, OpenAI, ElevenLabs, Resend, Stripe, Google
Places). Service clients route their outbound entry methods through the
matching breaker so that, after ``fail_max`` consecutive failures, further
calls fail-fast with a domain-specific exception until ``reset_timeout``
elapses and the breaker transitions to ``half-open`` to probe recovery.

Conventions
-----------

- All breakers share the same defaults (``fail_max=5``, ``reset_timeout=60``)
  so failure semantics are uniform across providers and so the metric is
  trivially comparable across labels.
- The breaker's name (``provider``) is the only label on the exported
  ``circuit_breaker_state`` gauge — bounded cardinality.
- When the breaker is *open*, calls raise the breaker's configured
  ``ProviderUnavailableError`` (a subclass of
  :class:`app.services.exceptions.ServiceUnavailableError`) so callers can
  catch a single domain exception and degrade gracefully rather than
  branching on a third-party type (``pybreaker.CircuitBreakerError``).
- The mapping from pybreaker state name → gauge value lives in
  ``_STATE_TO_VALUE`` and is the single source of truth for the metric.

Usage
-----

Wrap an async client method via ``call_async``::

    from app.core.circuit_breakers import telnyx_breaker

    async def send_sms(...):
        return await telnyx_breaker.call_async(self._post_message, payload)

If the breaker is open the call raises ``TelnyxUnavailableError`` (a
``ServiceUnavailableError`` subclass) — never a raw
``CircuitBreakerError``.
"""

from __future__ import annotations

import contextlib
import functools
from collections.abc import Awaitable, Callable
from typing import Any, Final, TypeVar

import pybreaker
import structlog
from prometheus_client import Gauge

from app.services.exceptions import ServiceUnavailableError

T = TypeVar("T")

logger = structlog.get_logger(__name__)


# --------------------------------------------------------------------------- #
# Domain exceptions
# --------------------------------------------------------------------------- #


class ProviderUnavailableError(ServiceUnavailableError):
    """Raised when an external provider's circuit breaker is open.

    Subclasses identify the specific provider so callers can catch either
    the umbrella :class:`ServiceUnavailableError` (degrade everything) or
    the provider-specific subclass (degrade just one path).
    """

    provider: str = "unknown"

    def __init__(self, detail: str | None = None) -> None:
        message = f"{self.provider} is temporarily unavailable (circuit open)"
        super().__init__(message, detail=detail)


class TelnyxUnavailableError(ProviderUnavailableError):
    provider = "telnyx"


class CalComUnavailableError(ProviderUnavailableError):
    provider = "calcom"


class OpenAIUnavailableError(ProviderUnavailableError):
    provider = "openai"


class ElevenLabsUnavailableError(ProviderUnavailableError):
    provider = "elevenlabs"


class ResendUnavailableError(ProviderUnavailableError):
    provider = "resend"


class StripeUnavailableError(ProviderUnavailableError):
    provider = "stripe"


class GooglePlacesUnavailableError(ProviderUnavailableError):
    provider = "googleplaces"


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #


circuit_breaker_state: Final[Gauge] = Gauge(
    "circuit_breaker_state",
    "Current state of an external-provider circuit breaker (0=closed, 1=half-open, 2=open).",
    labelnames=("provider",),
)


# pybreaker exposes ``pybreaker.STATE_CLOSED`` etc. as the string names that
# each state's ``.name`` returns. We map by those names so the mapping stays
# correct if pybreaker ever renumbers internal integer constants.
_STATE_TO_VALUE: Final[dict[str, int]] = {
    pybreaker.STATE_CLOSED: 0,
    pybreaker.STATE_HALF_OPEN: 1,
    pybreaker.STATE_OPEN: 2,
}


def _record_state(provider: str, state_name: str) -> None:
    """Push the breaker's current state to the Prometheus gauge."""
    value = _STATE_TO_VALUE.get(state_name)
    if value is None:
        # Defensive: unknown state name (future pybreaker version). Skip the
        # write rather than crash — the breaker itself still works.
        logger.warning(
            "circuit_breaker_unknown_state",
            provider=provider,
            state=state_name,
        )
        return
    circuit_breaker_state.labels(provider=provider).set(value)


# --------------------------------------------------------------------------- #
# Listener: bridges pybreaker state changes to metrics + structured logging
# and translates ``CircuitBreakerError`` into the provider's domain exception.
# --------------------------------------------------------------------------- #


class _ProviderBreakerListener(pybreaker.CircuitBreakerListener):
    """Listener that records every state change to the gauge and logs."""

    def __init__(self, provider: str) -> None:
        self._provider = provider

    def state_change(
        self,
        cb: pybreaker.CircuitBreaker,
        old_state: pybreaker.CircuitBreakerState | None,
        new_state: pybreaker.CircuitBreakerState,
    ) -> None:
        _record_state(self._provider, new_state.name)
        logger.info(
            "circuit_breaker_state_change",
            provider=self._provider,
            old_state=old_state.name if old_state is not None else None,
            new_state=new_state.name,
            fail_counter=cb.fail_counter,
        )

    def failure(
        self,
        cb: pybreaker.CircuitBreaker,
        exc: BaseException,
    ) -> None:
        logger.warning(
            "circuit_breaker_failure",
            provider=self._provider,
            fail_counter=cb.fail_counter,
            fail_max=cb.fail_max,
            exc_type=type(exc).__name__,
        )


# --------------------------------------------------------------------------- #
# Provider-specific breaker subclass that swaps ``CircuitBreakerError``
# for the domain exception. We override ``call_async`` and ``call`` so the
# adaptation runs on every code path callers might use.
# --------------------------------------------------------------------------- #


class ProviderCircuitBreaker(pybreaker.CircuitBreaker):
    """A pybreaker breaker bound to a specific provider's domain exception.

    On *open* state, instead of raising ``pybreaker.CircuitBreakerError`` we
    raise the configured :class:`ProviderUnavailableError` subclass so call
    sites can catch a single, stable, framework-free exception type.
    """

    def __init__(
        self,
        *,
        provider: str,
        unavailable_exc: type[ProviderUnavailableError],
        fail_max: int = 5,
        reset_timeout: float = 60,
    ) -> None:
        super().__init__(
            fail_max=fail_max,
            reset_timeout=reset_timeout,
            name=provider,
            listeners=[_ProviderBreakerListener(provider)],
        )
        self._provider = provider
        self._unavailable_exc = unavailable_exc
        # Seed the gauge so scrapers see ``closed`` from boot, not a missing
        # series until the first state change.
        _record_state(provider, self.current_state)

    @property
    def provider(self) -> str:
        return self._provider

    def _translate(self, exc: pybreaker.CircuitBreakerError) -> ProviderUnavailableError:
        return self._unavailable_exc(detail=str(exc))

    async def call_async(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Run an ``async`` ``func`` through this breaker.

        Reimplemented (rather than delegating to ``super().call_async``)
        because pybreaker 1.x's built-in ``call_async`` is hard-coupled to
        ``tornado.gen`` and raises ``NameError`` if tornado isn't
        importable. We replicate the sync ``CircuitBreakerState.call`` flow
        but with native ``await`` for the user's coroutine.
        """
        # ---- 1. Admission control (open state may reject or probe) ------
        # ``CircuitOpenState.before_call`` *recurses* back into
        # ``self.call`` (sync) after the reset timeout — we can't use it
        # for async. Replicate its logic directly here.
        with self._lock:
            self._async_admit()
            for listener in self.listeners:
                listener.before_call(self, func, *args, **kwargs)

        # ---- 2. Execute the awaitable outside the lock ------------------
        # Serializing every external request through one mutex is
        # unacceptable on hot paths (voice/SMS). The state-storage updates
        # in steps 1 & 3 are the only critical sections.
        try:
            ret = await func(*args, **kwargs)
        except BaseException as exc:
            with self._lock:
                self._async_on_failure(exc)
            raise
        else:
            with self._lock:
                self._async_on_success()
            return ret

    def _async_admit(self) -> None:
        """Open-state admission check for the async path. Must hold ``_lock``.

        Mirrors ``CircuitOpenState.before_call`` but, on timeout-elapsed,
        flips the breaker to ``half-open`` *without* recursing into the
        sync ``call`` path. The actual trial invocation happens in
        :meth:`call_async`'s ``await`` step.
        """
        from datetime import UTC, datetime, timedelta

        state_name = self.current_state
        if state_name == pybreaker.STATE_OPEN:
            timeout = timedelta(seconds=self.reset_timeout)
            opened_at = self._state_storage.opened_at
            if opened_at and datetime.now(UTC) < opened_at + timeout:
                raise self._unavailable_exc(
                    detail="Timeout not elapsed yet, circuit breaker still open"
                )
            # Probe: transition to half-open. The pending ``await`` is the
            # trial call.
            self.half_open()

    def _async_on_failure(self, exc: BaseException) -> None:
        """Bookkeeping for a failed async call. Must hold ``_lock``.

        Mirrors ``CircuitBreakerState._handle_error(reraise=False)`` —
        we re-raise in the caller so the original traceback is preserved.
        """
        if self.is_system_error(exc):
            self._inc_counter()
            for listener in self.listeners:
                listener.failure(self, exc)
            # ``state.on_failure`` may itself raise CircuitBreakerError
            # when the threshold trips. We swallow that here because the
            # caller is about to raise the *original* exception, which is
            # the more informative signal.
            with contextlib.suppress(pybreaker.CircuitBreakerError):
                self.state.on_failure(exc)
        else:
            # Non-system error (e.g. ValidationError) — pybreaker treats
            # it as success for breaker-state purposes.
            self._async_on_success()

    def _async_on_success(self) -> None:
        """Bookkeeping for a successful async call. Must hold ``_lock``.

        Mirrors ``CircuitBreakerState._handle_success``. Re-reads ``state``
        because an in-flight call may have started in ``half-open``.
        """
        self._state_storage.reset_counter()
        self.state.on_success()
        for listener in self.listeners:
            listener.success(self)

    def call(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        try:
            return super().call(func, *args, **kwargs)
        except pybreaker.CircuitBreakerError as exc:
            raise self._translate(exc) from exc


# --------------------------------------------------------------------------- #
# Per-provider singletons
# --------------------------------------------------------------------------- #


_FAIL_MAX: Final[int] = 5
_RESET_TIMEOUT: Final[float] = 60


def _make(provider: str, exc: type[ProviderUnavailableError]) -> ProviderCircuitBreaker:
    return ProviderCircuitBreaker(
        provider=provider,
        unavailable_exc=exc,
        fail_max=_FAIL_MAX,
        reset_timeout=_RESET_TIMEOUT,
    )


telnyx_breaker: Final[ProviderCircuitBreaker] = _make("telnyx", TelnyxUnavailableError)
calcom_breaker: Final[ProviderCircuitBreaker] = _make("calcom", CalComUnavailableError)
openai_breaker: Final[ProviderCircuitBreaker] = _make("openai", OpenAIUnavailableError)
elevenlabs_breaker: Final[ProviderCircuitBreaker] = _make("elevenlabs", ElevenLabsUnavailableError)
resend_breaker: Final[ProviderCircuitBreaker] = _make("resend", ResendUnavailableError)
stripe_breaker: Final[ProviderCircuitBreaker] = _make("stripe", StripeUnavailableError)
googleplaces_breaker: Final[ProviderCircuitBreaker] = _make(
    "googleplaces", GooglePlacesUnavailableError
)


ALL_BREAKERS: Final[tuple[ProviderCircuitBreaker, ...]] = (
    telnyx_breaker,
    calcom_breaker,
    openai_breaker,
    elevenlabs_breaker,
    resend_breaker,
    stripe_breaker,
    googleplaces_breaker,
)


# --------------------------------------------------------------------------- #
# Decorator helper
# --------------------------------------------------------------------------- #


def with_breaker(
    breaker: ProviderCircuitBreaker,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator that routes an ``async`` callable through ``breaker``.

    Apply as the *outermost* decorator so retries (e.g. ``tenacity``)
    happen inside one breaker probe — a single user-level call counts as
    one attempt regardless of how many transient retries it absorbed.

        @with_breaker(telnyx_breaker)
        @_telnyx_retry
        async def _post_message(self, payload): ...
    """

    def decorator(
        func: Callable[..., Awaitable[T]],
    ) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            result: T = await breaker.call_async(func, *args, **kwargs)
            return result

        return wrapper

    return decorator


__all__ = [
    "ALL_BREAKERS",
    "CalComUnavailableError",
    "ElevenLabsUnavailableError",
    "GooglePlacesUnavailableError",
    "OpenAIUnavailableError",
    "ProviderCircuitBreaker",
    "ProviderUnavailableError",
    "ResendUnavailableError",
    "StripeUnavailableError",
    "TelnyxUnavailableError",
    "calcom_breaker",
    "circuit_breaker_state",
    "elevenlabs_breaker",
    "googleplaces_breaker",
    "openai_breaker",
    "resend_breaker",
    "stripe_breaker",
    "telnyx_breaker",
    "with_breaker",
]
