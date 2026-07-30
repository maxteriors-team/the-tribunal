"""Condition triggers — automations that watch a workspace-level number.

An *event* trigger fires on something that happened to a contact; a *polling*
trigger fires on a contact who matches a shape. A **condition** trigger fires on
the state of the *business*: no contact caused it, so it is evaluated once per
automation per poll cycle instead of once per contact, and its actions run with
no contact attached (like a contactless event — see
:meth:`app.workers.automation_worker.AutomationWorker._run_actions`).

There is one today: ``backlog_below_threshold``, which closes the loop between
the fuel gauge (:meth:`app.services.reporting.capacity_service.CapacityService.compute_backlog`)
and the marketing machine. When weeks-of-booked-work falls under the owner's
threshold, demand generation fires by itself — start a reactivation drip, launch
a campaign — instead of waiting for the owner to notice a dry pipeline six weeks
too late.

Two rules make that safe to point at an entire customer database:

- **The cooldown is mandatory.** A thin backlog *stays* thin for weeks while the
  worker re-evaluates every 60 seconds, so one fire must silence the automation
  for ``cooldown_days`` — tracked on ``Automation.last_triggered_at``, which
  :meth:`AutomationWorker._run_actions` already stamps on every successful run.
  A missing or nonsensical value falls back to
  :data:`DEFAULT_BACKLOG_COOLDOWN_DAYS` rather than to zero: "no cooldown" would
  text every past customer every minute of a slow month.
- **Unknown is not zero.** ``backlog_weeks`` is ``None`` when the workspace never
  entered a crew capacity. That is an *unreadable* gauge, not an empty tank, so
  the condition is skipped silently. Reading it as ``0`` would make every
  workspace that skipped the capacity setting fire every campaign it owns.

:func:`evaluate_backlog_condition` is a pure function over plain values, so both
rules are testable without a database — the same split as
:func:`app.services.reporting.capacity_service.assemble_backlog` and
:func:`app.services.automations.events.lead_created_event_matches`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

# Trigger identifier stored verbatim in ``automations.trigger_type`` and matched
# case-insensitively by the worker (same convention as the event triggers).
CONDITION_BACKLOG_BELOW_THRESHOLD = "backlog_below_threshold"

# Condition triggers the worker evaluates against workspace state rather than
# against ``contacts`` (polling) or ``automation_events`` (event drain).
AUTOMATION_CONDITION_TRIGGERS: frozenset[str] = frozenset({CONDITION_BACKLOG_BELOW_THRESHOLD})

# Four weeks of booked work is the usual "start marketing now" line for home
# services: shorter than the sales cycle that has to refill it, long enough that
# a single rainy week does not trip it.
DEFAULT_BACKLOG_THRESHOLD_WEEKS = 4.0

# Two weeks between blasts to the same audience. Used whenever ``cooldown_days``
# is missing or non-positive, because an uncapped re-fire is the one failure mode
# this trigger must never have.
DEFAULT_BACKLOG_COOLDOWN_DAYS = 14

# Decision reasons (logged, never shown to a contact).
REASON_FIRE = "below_threshold"
REASON_CAPACITY_UNKNOWN = "capacity_unknown"
REASON_BACKLOG_HEALTHY = "backlog_at_or_above_threshold"
REASON_COOLING_DOWN = "cooling_down"


@dataclass(frozen=True)
class BacklogConditionDecision:
    """Why a ``backlog_below_threshold`` automation did or did not fire.

    Carries the resolved settings and the cooldown expiry alongside the verdict
    so the worker can log one line that explains itself without re-deriving
    anything.
    """

    should_fire: bool
    reason: str
    backlog_weeks: float | None
    threshold_weeks: float
    cooldown_days: int
    cooldown_until: datetime | None = None


def _as_float(value: Any) -> float | None:
    """Coerce a JSONB value to a positive float, or ``None`` if it isn't one.

    ``trigger_config`` is a free-form blob: a hand-written row or an older client
    can hold ``"4"`` instead of ``4``. Anything unparseable, zero or negative is
    rejected here so the caller can apply its documented default.
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def backlog_threshold_weeks(trigger_config: dict[str, Any] | None) -> float:
    """Weeks-of-work below which the automation should fire.

    Falls back to :data:`DEFAULT_BACKLOG_THRESHOLD_WEEKS` for a missing or
    non-positive value: a zero threshold can never be met, which would leave an
    automation the owner switched on quietly inert.
    """
    return _as_float((trigger_config or {}).get("threshold_weeks")) or (
        DEFAULT_BACKLOG_THRESHOLD_WEEKS
    )


def backlog_cooldown_days(trigger_config: dict[str, Any] | None) -> int:
    """Days of silence after a fire, never zero.

    Falls back to :data:`DEFAULT_BACKLOG_COOLDOWN_DAYS` when unset or
    nonsensical. Rounded down to whole days, with a floor of one, so a fractional
    or hostile value can never collapse the cooldown to nothing.
    """
    days = _as_float((trigger_config or {}).get("cooldown_days"))
    if days is None:
        return DEFAULT_BACKLOG_COOLDOWN_DAYS
    return max(1, int(days))


def _as_utc(moment: datetime) -> datetime:
    """Treat a naive timestamp as UTC so cooldown maths never raises."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def evaluate_backlog_condition(
    trigger_config: dict[str, Any] | None,
    *,
    backlog_weeks: float | None,
    last_triggered_at: datetime | None,
    now: datetime | None = None,
) -> BacklogConditionDecision:
    """Decide whether a thin backlog should fire demand generation (pure).

    Args:
        trigger_config: The automation's ``trigger_config``; reads
            ``threshold_weeks`` and ``cooldown_days``, both defaulted.
        backlog_weeks: ``BacklogReport.backlog_weeks`` — ``None`` means the
            workspace has no crew capacity set and the gauge is unreadable.
        last_triggered_at: ``Automation.last_triggered_at``; the cooldown clock.
        now: Evaluation instant (defaults to now, UTC).

    Returns:
        A :class:`BacklogConditionDecision`. ``should_fire`` is True only when
        capacity is known, the backlog is strictly below the threshold, and the
        cooldown has expired.
    """
    moment = _as_utc(now or datetime.now(UTC))
    threshold = backlog_threshold_weeks(trigger_config)
    cooldown_days = backlog_cooldown_days(trigger_config)
    cooldown_until = (
        None
        if last_triggered_at is None
        else _as_utc(last_triggered_at) + timedelta(days=cooldown_days)
    )

    def decide(*, should_fire: bool, reason: str) -> BacklogConditionDecision:
        return BacklogConditionDecision(
            should_fire=should_fire,
            reason=reason,
            backlog_weeks=backlog_weeks,
            threshold_weeks=threshold,
            cooldown_days=cooldown_days,
            cooldown_until=cooldown_until,
        )

    # Unknown capacity is not an empty backlog — skip rather than fire blind.
    if backlog_weeks is None:
        return decide(should_fire=False, reason=REASON_CAPACITY_UNKNOWN)

    # Strictly below: a backlog exactly at the threshold is still healthy, and
    # matches ``BacklogReport.below_alert_threshold`` (``weeks < threshold``).
    if backlog_weeks >= threshold:
        return decide(should_fire=False, reason=REASON_BACKLOG_HEALTHY)

    if cooldown_until is not None and moment < cooldown_until:
        return decide(should_fire=False, reason=REASON_COOLING_DOWN)

    return decide(should_fire=True, reason=REASON_FIRE)
