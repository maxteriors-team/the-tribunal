"""Tests for ``app.core.circuit_breakers``.

Pins the contract every service-client wrapper depends on:

* The seven provider singletons exist with ``fail_max=5`` and
  ``reset_timeout=60`` so call-site retry tuning is uniform.
* ``ProviderCircuitBreaker.call_async`` works without tornado \u2014
  pybreaker 1.x's built-in ``call_async`` is hard-coupled to
  ``tornado.gen`` and would raise ``NameError`` otherwise.
* After ``fail_max`` consecutive failures the breaker transitions
  ``closed \u2192 open`` and subsequent calls raise the provider-specific
  ``ProviderUnavailableError`` subclass (which is a
  ``ServiceUnavailableError``) \u2014 *not* a raw
  ``pybreaker.CircuitBreakerError``.
* After ``reset_timeout`` elapses, the breaker probes via ``half-open``
  and closes on a successful trial call.
* The Prometheus gauge ``circuit_breaker_state{provider}`` tracks the
  state with the documented encoding: 0=closed, 1=half-open, 2=open.
* Non-system errors (e.g. ``ValidationError``) do not count towards the
  failure threshold \u2014 pybreaker's standard behaviour, which we preserve
  on the async path.
* The ``@with_breaker(...)`` decorator routes wrapped coroutines through
  the breaker so existing service-client methods can be wrapped without
  changing their call sites.
"""

from __future__ import annotations

import asyncio

import pybreaker
import pytest

from app.core.circuit_breakers import (
    ALL_BREAKERS,
    ElevenLabsUnavailableError,
    GooglePlacesUnavailableError,
    OpenAIUnavailableError,
    ProviderCircuitBreaker,
    ProviderUnavailableError,
    ResendUnavailableError,
    StripeUnavailableError,
    TelnyxUnavailableError,
    circuit_breaker_state,
    elevenlabs_breaker,
    googleplaces_breaker,
    openai_breaker,
    resend_breaker,
    stripe_breaker,
    telnyx_breaker,
    with_breaker,
)
from app.services.exceptions import ServiceUnavailableError

# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


def _fresh_breaker(fail_max: int = 2, reset_timeout: float = 0.05) -> ProviderCircuitBreaker:
    """A breaker with a tiny threshold and timeout for fast tests.

    Using a fresh instance per test keeps state isolated so we don't fight
    the module-level singletons (which other tests in this session may
    have tripped).
    """
    return ProviderCircuitBreaker(
        provider="test_provider",
        unavailable_exc=TelnyxUnavailableError,
        fail_max=fail_max,
        reset_timeout=reset_timeout,
    )


async def _boom() -> None:
    raise RuntimeError("upstream down")


async def _ok() -> str:
    return "ok"


def _gauge_value(provider: str) -> float:
    """Read the current value of ``circuit_breaker_state{provider}``."""
    raw: float = circuit_breaker_state.labels(provider=provider)._value.get()
    return raw


# --------------------------------------------------------------------------- #
# Singletons & configuration
# --------------------------------------------------------------------------- #


class TestProviderSingletons:
    """Every external provider has a breaker with uniform defaults."""

    def test_all_six_providers_have_a_breaker(self) -> None:
        providers = {b.provider for b in ALL_BREAKERS}
        assert providers == {
            "telnyx",
            "openai",
            "elevenlabs",
            "resend",
            "stripe",
            "googleplaces",
        }

    @pytest.mark.parametrize(
        "breaker",
        [
            telnyx_breaker,
            openai_breaker,
            elevenlabs_breaker,
            resend_breaker,
            stripe_breaker,
            googleplaces_breaker,
        ],
    )
    def test_each_breaker_uses_documented_thresholds(self, breaker: ProviderCircuitBreaker) -> None:
        assert breaker.fail_max == 5
        assert breaker.reset_timeout == 60

    def test_each_breaker_raises_provider_specific_exception(self) -> None:
        # Mapping: breaker name \u2192 expected exception subclass.
        assert telnyx_breaker._unavailable_exc is TelnyxUnavailableError
        assert openai_breaker._unavailable_exc is OpenAIUnavailableError
        assert elevenlabs_breaker._unavailable_exc is ElevenLabsUnavailableError
        assert resend_breaker._unavailable_exc is ResendUnavailableError
        assert stripe_breaker._unavailable_exc is StripeUnavailableError
        assert googleplaces_breaker._unavailable_exc is GooglePlacesUnavailableError

    def test_provider_unavailable_errors_are_service_unavailable(self) -> None:
        # Callers can degrade gracefully by catching the umbrella type.
        for exc_cls in (
            TelnyxUnavailableError,
            OpenAIUnavailableError,
            ElevenLabsUnavailableError,
            ResendUnavailableError,
            StripeUnavailableError,
            GooglePlacesUnavailableError,
        ):
            assert issubclass(exc_cls, ProviderUnavailableError)
            assert issubclass(exc_cls, ServiceUnavailableError)


# --------------------------------------------------------------------------- #
# State machine: closed \u2192 open \u2192 half-open \u2192 closed
# --------------------------------------------------------------------------- #


class TestStateMachine:
    @pytest.mark.asyncio
    async def test_closed_breaker_passes_calls_through(self) -> None:
        breaker = _fresh_breaker()
        assert breaker.current_state == pybreaker.STATE_CLOSED

        result = await breaker.call_async(_ok)

        assert result == "ok"
        assert breaker.current_state == pybreaker.STATE_CLOSED

    @pytest.mark.asyncio
    async def test_opens_after_fail_max_consecutive_failures(self) -> None:
        breaker = _fresh_breaker(fail_max=2)

        # First two failures: still closed (original RuntimeError surfaces).
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call_async(_boom)

        assert breaker.current_state == pybreaker.STATE_OPEN

    @pytest.mark.asyncio
    async def test_open_breaker_raises_domain_exception_not_circuit_error(
        self,
    ) -> None:
        breaker = _fresh_breaker(fail_max=2)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call_async(_boom)

        # Subsequent calls fail fast \u2014 the user-supplied function is NOT
        # invoked.  We track this by raising in the function and asserting
        # the *breaker's* exception bubbles instead.
        async def must_not_run() -> None:  # pragma: no cover - asserts via no call
            raise AssertionError("breaker should have short-circuited")

        with pytest.raises(TelnyxUnavailableError) as excinfo:
            await breaker.call_async(must_not_run)

        # Crucially, callers see the domain exception \u2014 never the third-party
        # ``pybreaker.CircuitBreakerError``.
        assert not isinstance(excinfo.value, pybreaker.CircuitBreakerError)
        assert isinstance(excinfo.value, ServiceUnavailableError)
        assert "circuit open" in excinfo.value.message

    @pytest.mark.asyncio
    async def test_half_open_probe_closes_on_success(self) -> None:
        breaker = _fresh_breaker(fail_max=2, reset_timeout=0.05)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call_async(_boom)
        assert breaker.current_state == pybreaker.STATE_OPEN

        await asyncio.sleep(0.07)  # let reset_timeout elapse

        # The trial call transitions open \u2192 half-open \u2192 (on success) closed.
        result = await breaker.call_async(_ok)

        assert result == "ok"
        assert breaker.current_state == pybreaker.STATE_CLOSED

    @pytest.mark.asyncio
    async def test_half_open_probe_reopens_on_failure(self) -> None:
        breaker = _fresh_breaker(fail_max=2, reset_timeout=0.05)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call_async(_boom)

        await asyncio.sleep(0.07)

        # Trial call fails \u2192 breaker should go straight back to open.
        with pytest.raises(RuntimeError):
            await breaker.call_async(_boom)

        assert breaker.current_state == pybreaker.STATE_OPEN

    @pytest.mark.asyncio
    async def test_open_state_short_circuits_before_timeout(self) -> None:
        breaker = _fresh_breaker(fail_max=2, reset_timeout=10)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call_async(_boom)

        # We've not waited for reset_timeout \u2014 every call must fail fast.
        for _ in range(3):
            with pytest.raises(TelnyxUnavailableError):
                await breaker.call_async(_ok)


# --------------------------------------------------------------------------- #
# Prometheus gauge
# --------------------------------------------------------------------------- #


class TestMetrics:
    """``circuit_breaker_state`` encodes state as 0=closed / 1=half-open / 2=open."""

    @pytest.mark.asyncio
    async def test_gauge_is_zero_when_closed(self) -> None:
        # Use a unique provider name so other tests don't pollute the gauge.
        breaker = ProviderCircuitBreaker(
            provider="metric_closed_test",
            unavailable_exc=TelnyxUnavailableError,
            fail_max=2,
            reset_timeout=10,
        )
        assert breaker.current_state == pybreaker.STATE_CLOSED
        assert _gauge_value("metric_closed_test") == 0

    @pytest.mark.asyncio
    async def test_gauge_is_two_when_open(self) -> None:
        breaker = ProviderCircuitBreaker(
            provider="metric_open_test",
            unavailable_exc=TelnyxUnavailableError,
            fail_max=2,
            reset_timeout=10,
        )
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call_async(_boom)

        assert breaker.current_state == pybreaker.STATE_OPEN
        assert _gauge_value("metric_open_test") == 2

    @pytest.mark.asyncio
    async def test_gauge_is_one_when_half_open(self) -> None:
        breaker = ProviderCircuitBreaker(
            provider="metric_half_open_test",
            unavailable_exc=TelnyxUnavailableError,
            fail_max=2,
            reset_timeout=0.05,
        )
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call_async(_boom)
        await asyncio.sleep(0.07)

        # ``half_open()`` is the public transition; calling it directly
        # avoids racing the call_async admission logic which would also
        # immediately attempt the trial call.
        breaker.half_open()

        assert breaker.current_state == pybreaker.STATE_HALF_OPEN
        assert _gauge_value("metric_half_open_test") == 1

    @pytest.mark.asyncio
    async def test_gauge_returns_to_zero_after_recovery(self) -> None:
        breaker = ProviderCircuitBreaker(
            provider="metric_recovery_test",
            unavailable_exc=TelnyxUnavailableError,
            fail_max=2,
            reset_timeout=0.05,
        )
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call_async(_boom)
        assert _gauge_value("metric_recovery_test") == 2

        await asyncio.sleep(0.07)
        await breaker.call_async(_ok)

        assert breaker.current_state == pybreaker.STATE_CLOSED
        assert _gauge_value("metric_recovery_test") == 0


# --------------------------------------------------------------------------- #
# Failure-counting semantics
# --------------------------------------------------------------------------- #


class TestFailureCountingSemantics:
    """Excluded exceptions don't trip the breaker."""

    @pytest.mark.asyncio
    async def test_a_successful_call_resets_the_failure_counter(self) -> None:
        breaker = _fresh_breaker(fail_max=3)

        with pytest.raises(RuntimeError):
            await breaker.call_async(_boom)
        with pytest.raises(RuntimeError):
            await breaker.call_async(_boom)
        assert breaker.fail_counter == 2

        # Success: counter resets \u2014 we should be able to fail 3 more times
        # before tripping, not 1.
        await breaker.call_async(_ok)
        assert breaker.fail_counter == 0

        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call_async(_boom)
        assert breaker.current_state == pybreaker.STATE_CLOSED

    @pytest.mark.asyncio
    async def test_excluded_exceptions_do_not_count_as_failures(self) -> None:
        # pybreaker treats user-registered excluded exceptions as "business
        # logic" errors that propagate without affecting breaker state.
        class BusinessError(Exception):
            pass

        breaker = _fresh_breaker(fail_max=2)
        breaker.add_excluded_exception(BusinessError)

        async def business_failure() -> None:
            raise BusinessError("invalid input")

        for _ in range(5):
            with pytest.raises(BusinessError):
                await breaker.call_async(business_failure)

        # Counter never incremented; breaker still closed.
        assert breaker.current_state == pybreaker.STATE_CLOSED
        assert breaker.fail_counter == 0


# --------------------------------------------------------------------------- #
# Decorator helper
# --------------------------------------------------------------------------- #


class TestWithBreakerDecorator:
    @pytest.mark.asyncio
    async def test_decorator_routes_calls_through_the_breaker(self) -> None:
        breaker = _fresh_breaker(fail_max=2)
        call_count = 0

        @with_breaker(breaker)
        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("nope")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                await flaky()

        assert call_count == 2
        assert breaker.current_state == pybreaker.STATE_OPEN

        # Once open, the decorator should fail fast \u2014 the underlying
        # function must NOT be called a third time.
        with pytest.raises(TelnyxUnavailableError):
            await flaky()
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_decorator_preserves_function_metadata(self) -> None:
        breaker = _fresh_breaker()

        @with_breaker(breaker)
        async def my_action(x: int, y: int) -> int:
            """Add two numbers."""
            return x + y

        assert my_action.__name__ == "my_action"
        assert my_action.__doc__ == "Add two numbers."
        assert await my_action(2, 3) == 5

    @pytest.mark.asyncio
    async def test_decorator_forwards_args_and_kwargs(self) -> None:
        breaker = _fresh_breaker()

        @with_breaker(breaker)
        async def add(x: int, *, multiplier: int = 1) -> int:
            return x * multiplier

        assert await add(5, multiplier=3) == 15
