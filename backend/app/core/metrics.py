"""Prometheus application metrics.

This module defines all custom Counters and Histograms exported via the
``/metrics`` endpoint (mounted in :mod:`app.main`). HTTP-level request /
latency metrics are handled automatically by
``prometheus-fastapi-instrumentator``; this module covers domain-specific
signals (voice, SMS, third-party integrations, background workers).

Conventions
-----------
- Counter names end in ``_total``.
- Histograms have units in the metric name (``_seconds`` or ``_ms``) and use
  buckets tuned to the expected operating range so we don't waste series
  cardinality.
- Labels are kept low-cardinality. **Never** label with raw user input,
  message bodies, phone numbers, or contact IDs — only with bounded enums
  (event type, outcome, direction, worker name) and workspace_id (which is
  bounded by the number of tenants).
- The ``workspace_id`` label values are stringified UUIDs; callers should
  pass ``str(workspace_id)`` to avoid type-driven cardinality bugs.

Helpers at the bottom of this file (``observe_*``) provide typed wrappers
and a context manager (``worker_loop_timer``) for the most common call
sites so callers don't have to repeat label boilerplate.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from prometheus_client import Counter, Histogram

# --------------------------------------------------------------------------- #
# Voice calls
# --------------------------------------------------------------------------- #

voice_calls_started_total = Counter(
    "voice_calls_started_total",
    "Outbound or inbound voice calls that have started (one event per call).",
    labelnames=("workspace_id",),
)

voice_calls_completed_total = Counter(
    "voice_calls_completed_total",
    "Voice calls that have reached a terminal state (hangup processed).",
    labelnames=("workspace_id", "outcome"),
)

voice_call_duration_seconds = Histogram(
    "voice_call_duration_seconds",
    "Duration of completed voice calls in seconds.",
    # Telephony durations span sub-second (immediate hangup / rejection) to
    # multi-minute conversations. Buckets aimed at the 5s–10m operating range.
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800),
)


# --------------------------------------------------------------------------- #
# SMS
# --------------------------------------------------------------------------- #

sms_sent_total = Counter(
    "sms_sent_total",
    "SMS messages sent or received, labelled by direction.",
    labelnames=("workspace_id", "direction"),
)

sms_bounce_total = Counter(
    "sms_bounce_total",
    "SMS bounce events classified by bounce type (hard/soft/spam_complaint).",
    labelnames=("workspace_id", "bounce_type"),
)

ai_text_response_failures_total = Counter(
    "ai_text_response_failures_total",
    (
        "Inbound texts where the AI failed to reply, labelled by reason "
        "(no_credential/generation_failed/send_failed). A rising count means "
        "leads are being nurtured with silence."
    ),
    labelnames=("workspace_id", "reason"),
)


# --------------------------------------------------------------------------- #
# Cal.com webhooks
# --------------------------------------------------------------------------- #

calcom_webhook_received_total = Counter(
    "calcom_webhook_received_total",
    "Cal.com webhooks received (post-signature-validation), labelled by trigger.",
    labelnames=("trigger",),
)

calcom_webhook_signature_invalid_total = Counter(
    "calcom_webhook_signature_invalid_total",
    "Cal.com webhook requests rejected due to invalid/missing signature or timestamp.",
)


# --------------------------------------------------------------------------- #
# Telnyx webhooks
# --------------------------------------------------------------------------- #

telnyx_webhook_received_total = Counter(
    "telnyx_webhook_received_total",
    "Telnyx webhooks received, labelled by event_type.",
    labelnames=("event_type",),
)


# --------------------------------------------------------------------------- #
# Third-party integration latencies
# --------------------------------------------------------------------------- #

# Latency in milliseconds. We use _ms histograms because these third-party
# round-trips are sub-second in the happy path and we care about p50/p95
# in tens-to-hundreds-of-ms granularity.
_LATENCY_MS_BUCKETS = (10, 25, 50, 100, 200, 400, 800, 1600, 3200, 6400)

openai_realtime_latency_ms = Histogram(
    "openai_realtime_latency_ms",
    "Round-trip latency for OpenAI Realtime API events (request → first response).",
    buckets=_LATENCY_MS_BUCKETS,
)

elevenlabs_tts_latency_ms = Histogram(
    "elevenlabs_tts_latency_ms",
    "Latency between submitting text to ElevenLabs TTS and receiving first audio chunk.",
    buckets=_LATENCY_MS_BUCKETS,
)

elevenlabs_reconnect_total = Counter(
    "elevenlabs_reconnect_total",
    "ElevenLabs WebSocket reconnect attempts, labelled by reason. "
    "``reason`` is a bounded enum: ``connection_closed`` (peer closed cleanly), "
    "``connection_closed_error`` (peer closed abnormally), ``success`` (a reconnect "
    "attempt succeeded), ``exhausted`` (max attempts hit without recovery), "
    "``circuit_open`` (skipped because the breaker rejected the probe).",
    labelnames=("reason",),
)

telnyx_api_latency_ms = Histogram(
    "telnyx_api_latency_ms",
    "Latency of Telnyx REST API calls (per request).",
    buckets=_LATENCY_MS_BUCKETS,
)


# --------------------------------------------------------------------------- #
# Background workers
# --------------------------------------------------------------------------- #

worker_loop_duration_seconds = Histogram(
    "worker_loop_duration_seconds",
    "Duration of a single worker poll cycle (one _process_items invocation).",
    labelnames=("worker",),
    # Worker cycles are typically fast (<1s) but can spike during batch work.
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 5, 10, 30, 60, 300),
)

worker_items_processed_total = Counter(
    "worker_items_processed_total",
    "Number of work items processed by a worker (incremented per item, not per cycle).",
    labelnames=("worker",),
)

worker_errors_total = Counter(
    "worker_errors_total",
    "Number of unhandled exceptions raised inside a worker poll cycle.",
    labelnames=("worker",),
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _ws_label(workspace_id: uuid.UUID | str | None) -> str:
    """Render a workspace_id for use as a metric label.

    ``None`` collapses to the literal string ``"unknown"`` so that the label
    cardinality stays bounded and we never accidentally pass a Python None
    (which Prometheus would reject) when an upstream lookup fails.
    """
    if workspace_id is None:
        return "unknown"
    return str(workspace_id)


def observe_voice_call_started(workspace_id: uuid.UUID | str | None) -> None:
    """Record one outbound or inbound voice call start."""
    voice_calls_started_total.labels(workspace_id=_ws_label(workspace_id)).inc()


def observe_voice_call_completed(
    workspace_id: uuid.UUID | str | None,
    outcome: str,
    duration_seconds: float | int | None,
) -> None:
    """Record a voice call reaching a terminal state.

    ``outcome`` should be a low-cardinality enum: ``completed``, ``failed``,
    ``no_answer``, ``rejected``, etc. ``duration_seconds`` may be ``None`` /
    ``0`` for calls that hung up before connecting; we skip the histogram
    observation in that case to avoid skewing the latency distribution with
    artificial zeros.
    """
    voice_calls_completed_total.labels(
        workspace_id=_ws_label(workspace_id),
        outcome=outcome or "unknown",
    ).inc()
    if duration_seconds is not None and duration_seconds > 0:
        voice_call_duration_seconds.observe(float(duration_seconds))


def observe_sms_sent(
    workspace_id: uuid.UUID | str | None,
    direction: str,
) -> None:
    """Record an SMS event. ``direction`` is ``inbound`` or ``outbound``."""
    sms_sent_total.labels(
        workspace_id=_ws_label(workspace_id),
        direction=direction,
    ).inc()


def observe_sms_bounce(
    workspace_id: uuid.UUID | str | None,
    bounce_type: str,
) -> None:
    """Record an SMS bounce. ``bounce_type`` is ``hard``/``soft``/``spam_complaint``."""
    sms_bounce_total.labels(
        workspace_id=_ws_label(workspace_id),
        bounce_type=bounce_type or "unknown",
    ).inc()


def observe_ai_text_response_failure(
    workspace_id: uuid.UUID | str | None,
    reason: str,
) -> None:
    """Record an inbound text the AI could not reply to.

    ``reason`` is ``no_credential`` (OpenAI creds missing/expired),
    ``generation_failed`` (LLM returned nothing / errored), or ``send_failed``
    (reply generated but the outbound provider rejected it).
    """
    ai_text_response_failures_total.labels(
        workspace_id=_ws_label(workspace_id),
        reason=reason or "unknown",
    ).inc()


def observe_calcom_webhook(trigger: str) -> None:
    """Record a successfully verified Cal.com webhook."""
    calcom_webhook_received_total.labels(trigger=trigger or "unknown").inc()


def observe_calcom_signature_invalid() -> None:
    """Record a Cal.com webhook rejected for signature/timestamp issues."""
    calcom_webhook_signature_invalid_total.inc()


def observe_telnyx_webhook(event_type: str) -> None:
    """Record a Telnyx webhook delivery."""
    telnyx_webhook_received_total.labels(event_type=event_type or "unknown").inc()


def observe_worker_item(worker: str, count: int = 1) -> None:
    """Record ``count`` items processed by ``worker`` in the current cycle."""
    if count <= 0:
        return
    worker_items_processed_total.labels(worker=worker).inc(count)


def observe_worker_error(worker: str) -> None:
    """Record an unhandled exception inside a worker poll cycle."""
    worker_errors_total.labels(worker=worker).inc()


@contextmanager
def worker_loop_timer(worker: str) -> Iterator[None]:
    """Time a single worker poll cycle and record errors.

    Usage::

        with worker_loop_timer("my_worker"):
            await self._process_items()

    The duration is always recorded (success or failure). On exception the
    error counter is incremented and the exception is re-raised so callers
    can preserve existing logging behaviour.
    """
    start = time.monotonic()
    try:
        yield
    except Exception:
        worker_errors_total.labels(worker=worker).inc()
        raise
    finally:
        worker_loop_duration_seconds.labels(worker=worker).observe(time.monotonic() - start)


@contextmanager
def latency_ms_timer(histogram: Histogram) -> Iterator[None]:
    """Time a block of code and observe the duration in milliseconds.

    Used for third-party integration latencies (OpenAI Realtime, ElevenLabs
    TTS, Telnyx REST). The histogram must be one of the ``*_latency_ms``
    histograms defined in this module.
    """
    start = time.monotonic()
    try:
        yield
    finally:
        histogram.observe((time.monotonic() - start) * 1000.0)
