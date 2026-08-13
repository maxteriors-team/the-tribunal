"""Workflow cursor logic — how a multi-step automation walks its step list.

A workflow is a **flat** list of steps (``automations.actions``). Control flow is
expressed with *goto* rather than nested branch bodies, and that single decision
is what makes the engine resumable: the position of a half-finished run is one
integer (``automation_executions.step_index``), not a path into a tree. A run
that pauses on a ``wait`` for three days is restored on a later poll cycle by
reading that integer back.

Why this module is pure
-----------------------
Everything here is a function over plain values — no session, no I/O. The rules
that decide *where a customer's workflow goes next* are therefore testable
without a database, the same split already used by
:mod:`app.services.automations.conditions` and
:mod:`app.services.automations.events`. The worker owns the side effects
(sending, tagging, enrolling); this module only ever answers "which step next?".

Goto semantics
--------------
A ``branch`` step carries ``then_goto`` / ``else_goto``. Each target is:

- a **step id** present in the workflow -> jump to that step;
- :data:`GOTO_END` (``"__end__"``) -> finish the run successfully;
- ``null`` / absent -> fall through to the following step;
- **a step id that does not exist -> finish the run** and log. This is the one
  asymmetric rule and it is deliberate: after a typo'd target the *only* safe
  move is to stop. Falling through would run the steps belonging to the other
  branch, which in this product means texting a customer the message written for
  people who did the opposite thing.

Loop safety
-----------
Goto permits cycles, and a cycle that sends SMS is the single failure mode this
engine must never have. Two independent bounds, because they catch different
shapes of runaway:

- :data:`MAX_STEPS_PER_RUN` bounds one *cycle*, catching a tight loop with no
  ``wait`` in it (which would otherwise spin forever inside one poll).
- :data:`MAX_RESUMES` bounds a run's *lifetime*, catching a slow loop that does
  pass through a ``wait`` and so would otherwise resume politely, forever.

Hitting either is a **failure**, not a quiet stop: a workflow that loops is
misauthored, and silently truncating it would hide that from the operator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

__all__ = [
    "GOTO_END",
    "MAX_RESUMES",
    "MAX_STEPS_PER_RUN",
    "MAX_WAIT",
    "END_OF_WORKFLOW",
    "WorkflowStep",
    "BranchTarget",
    "normalize_steps",
    "resolve_goto",
    "branch_targets",
    "wait_duration",
    "step_at",
]

# Sentinel goto target meaning "this run is finished". A literal rather than
# ``null`` because ``null`` already means "fall through", and the two intents
# must not collapse into one.
GOTO_END = "__end__"

# Cursor value meaning "past the last step". Returned by the resolvers instead
# of ``None`` so callers compare integers and never juggle Optionals.
END_OF_WORKFLOW = -1

# Steps executed in a single poll cycle for one execution. Generous for real
# workflows (the longest hand-authored sequences in this product are ~12 steps)
# and low enough that a runaway is caught inside one cycle.
MAX_STEPS_PER_RUN = 50

# Times one execution may be resumed from a ``wait`` across its whole lifetime.
# A 30-step drip with a wait between every step resumes 30 times; 200 leaves
# generous headroom while still bounding a loop that hides behind a wait.
MAX_RESUMES = 200

# Hard ceiling on a single wait. Guards a typo'd ``{"days": 99999}`` that would
# park a customer's workflow past the heat death of the business.
MAX_WAIT = timedelta(days=365)

# Accepted duration keys on a ``wait`` step, in ascending unit size. ``hours``
# is listed for backward compatibility: it is the only key the pre-resume
# engine understood, and existing rows still carry it.
_WAIT_UNITS: tuple[tuple[str, timedelta], ...] = (
    ("minutes", timedelta(minutes=1)),
    ("hours", timedelta(hours=1)),
    ("days", timedelta(days=1)),
)

# Applied when a ``wait`` step names no duration at all. Matches the previous
# engine's ``int(config.get("hours", 1))`` so existing automations keep their
# timing exactly.
_DEFAULT_WAIT = timedelta(hours=1)


@dataclass(frozen=True)
class WorkflowStep:
    """One step of a workflow, normalized from raw JSONB.

    ``step_id`` is optional: automations authored before branching exist as
    ``[{"type": ..., "config": ...}]`` with no ids, and must keep running
    untouched. Only steps that are the *target* of a branch need an id.
    """

    index: int
    type: str
    config: dict[str, Any]
    step_id: str | None = None


@dataclass(frozen=True)
class BranchTarget:
    """Where a ``branch`` step sends the run for one of its two outcomes."""

    # Cursor to continue at: a step index, or END_OF_WORKFLOW to finish.
    index: int
    # True when the configured target named a step id that does not exist. The
    # run still ends (fail-safe), but the caller should log it as misauthored.
    dangling: bool = False


def _as_step_id(value: Any) -> str | None:
    """Coerce a raw id to a non-empty string, or ``None``."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def normalize_steps(actions: Any) -> list[WorkflowStep]:
    """Normalize ``automations.actions`` into positional :class:`WorkflowStep`s.

    ``actions`` is free-form JSONB that may have been written by an older
    client, by the CRM assistant, or by hand. Anything that is not a mapping is
    dropped rather than raising, so one malformed entry cannot take a whole
    workspace's automations offline. Types are lower-cased once here so every
    downstream comparison is a plain equality check.
    """
    if not isinstance(actions, list):
        return []

    steps: list[WorkflowStep] = []
    for raw in actions:
        if not isinstance(raw, dict):
            continue
        config = raw.get("config")
        steps.append(
            WorkflowStep(
                index=len(steps),
                type=str(raw.get("type", "")).strip().lower(),
                config=config if isinstance(config, dict) else {},
                step_id=_as_step_id(raw.get("id")),
            )
        )
    return steps


def step_at(steps: list[WorkflowStep], cursor: int) -> WorkflowStep | None:
    """The step at ``cursor``, or ``None`` when the run is finished.

    Treats any out-of-range cursor as "finished" — including a negative one and
    one past the end. A persisted ``step_index`` can outlive an edit that
    shortened the workflow, and that must end the run, not raise.
    """
    if cursor < 0 or cursor >= len(steps):
        return None
    return steps[cursor]


def resolve_goto(steps: list[WorkflowStep], target: Any, *, fallthrough: int) -> BranchTarget:
    """Resolve one configured goto target to a cursor.

    Args:
        steps: The normalized workflow.
        target: Raw ``then_goto``/``else_goto`` value.
        fallthrough: Cursor to use when ``target`` is null/absent — normally the
            index after the branch step.

    Returns:
        A :class:`BranchTarget`. ``dangling`` is True only when a non-empty id
        matched no step, in which case ``index`` is :data:`END_OF_WORKFLOW`.
    """
    resolved = _as_step_id(target)

    # Null/absent: continue in document order.
    if resolved is None:
        return BranchTarget(index=fallthrough)

    if resolved == GOTO_END:
        return BranchTarget(index=END_OF_WORKFLOW)

    for step in steps:
        if step.step_id is not None and step.step_id == resolved:
            return BranchTarget(index=step.index)

    # Named a step that is not there — stop rather than run the other branch.
    return BranchTarget(index=END_OF_WORKFLOW, dangling=True)


def branch_targets(
    steps: list[WorkflowStep],
    step: WorkflowStep,
) -> tuple[BranchTarget, BranchTarget]:
    """The ``(when_true, when_false)`` targets for a ``branch`` step."""
    fallthrough = step.index + 1
    return (
        resolve_goto(steps, step.config.get("then_goto"), fallthrough=fallthrough),
        resolve_goto(steps, step.config.get("else_goto"), fallthrough=fallthrough),
    )


def wait_duration(config: dict[str, Any] | None) -> timedelta:
    """How long a ``wait`` step pauses the run.

    Sums every recognised unit present (``minutes``/``hours``/``days``), so
    ``{"days": 1, "hours": 12}`` is 36 hours. Falls back to
    :data:`_DEFAULT_WAIT` only when no usable key is present at all — matching
    the previous engine so existing automations keep their timing.

    Negative and unparseable values contribute nothing rather than shortening
    the wait: the failure mode of a bad value must be "sends later", never
    "sends immediately to everyone".
    """
    settings = config or {}
    total = timedelta()
    found = False

    for key, unit in _WAIT_UNITS:
        if key not in settings:
            continue
        raw = settings[key]
        if isinstance(raw, bool) or raw is None:
            continue
        try:
            amount = float(raw)
        except (TypeError, ValueError):
            continue
        if amount < 0:
            # Negative is nonsense, not an instruction. Skip it entirely so the
            # no-usable-key fallback applies and the run waits the default,
            # rather than resolving to zero and sending immediately.
            continue
        if amount == 0:
            # An explicit zero *is* a real instruction ("don't wait"), so it
            # counts as a usable key even though it adds nothing.
            found = True
            continue
        total += unit * amount
        found = True

    if not found:
        return _DEFAULT_WAIT
    return min(total, MAX_WAIT)
