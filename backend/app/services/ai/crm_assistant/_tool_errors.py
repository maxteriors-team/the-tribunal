"""Structured error results for CRM assistant tool calls.

The executor used to collapse every failure into
``{"success": False, "error": "Failed to execute <tool>"}``. A malformed
argument, a transient DB outage and a genuine bug were indistinguishable, so
the model could never tell "fix your arguments and retry" from "stop and tell
the operator" — and neither could the operator reading the reply.

Each result now carries:

- ``code``    — a stable machine-readable class the model can branch on
- ``message`` — one plain sentence, safe to show an operator
- ``hint``    — the concrete next move, or ``None`` when there isn't one

Stack traces and exception details stay in structlog. Nothing derived from an
exception string is ever put in ``message``: those can carry SQL fragments,
connection strings, or PII from a failed row.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ToolErrorCode(StrEnum):
    """Stable failure classes a model can branch on."""

    INVALID_ARGUMENT = "invalid_argument"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    NOT_PERMITTED = "not_permitted"
    UNAVAILABLE = "unavailable"
    INTERNAL = "internal"
    UNKNOWN_TOOL = "unknown_tool"


# Whether the model should try again with different arguments. ``UNAVAILABLE``
# is excluded on purpose: retrying a dependency outage in a tool loop just
# burns turns.
_RETRYABLE = frozenset({ToolErrorCode.INVALID_ARGUMENT, ToolErrorCode.NOT_FOUND})

# Validation detail is echoed to the model to enable self-correction, but
# bounded so a pathological error tree cannot flood the context window.
_MAX_DETAIL_CHARS = 600


def tool_error(
    code: ToolErrorCode,
    message: str,
    hint: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a structured tool failure result."""

    payload: dict[str, Any] = {
        "success": False,
        "code": code.value,
        "message": message,
        "retryable": code in _RETRYABLE,
    }
    if hint:
        payload["hint"] = hint
    payload.update(extra)
    return payload


def invalid_argument(message: str, hint: str | None = None, **extra: Any) -> dict[str, Any]:
    """The model sent an argument the tool cannot use."""

    return tool_error(ToolErrorCode.INVALID_ARGUMENT, message, hint, **extra)


def invalid_id(field: str, hint: str) -> dict[str, Any]:
    """An id argument was missing or not a well-formed identifier."""

    return invalid_argument(f"{field} is missing or not a valid id.", hint)


def missing_argument(field: str, hint: str | None = None) -> dict[str, Any]:
    """A required argument was omitted."""

    return invalid_argument(f"{field} is required.", hint)


def validation_failed(entity: str, detail: str) -> dict[str, Any]:
    """Schema validation rejected the arguments.

    ``detail`` is echoed back (bounded) precisely so the model can self-correct;
    it only ever describes arguments the model itself supplied.
    """

    return invalid_argument(
        f"{entity} arguments failed validation.",
        "Fix the fields named in `detail`, then call the tool again.",
        detail=detail[:_MAX_DETAIL_CHARS],
    )


def not_found(entity: str, hint: str | None = None, **extra: Any) -> dict[str, Any]:
    """The referenced record does not exist in this workspace."""

    return tool_error(
        ToolErrorCode.NOT_FOUND,
        f"{entity} not found in this workspace.",
        hint or "List or search first to get a valid id.",
        **extra,
    )


def conflict(message: str, hint: str | None = None, **extra: Any) -> dict[str, Any]:
    """The record exists but is in a state that blocks this action."""

    return tool_error(ToolErrorCode.CONFLICT, message, hint, **extra)


def not_permitted(message: str, hint: str | None = None, **extra: Any) -> dict[str, Any]:
    """Policy refused the action."""

    return tool_error(ToolErrorCode.NOT_PERMITTED, message, hint, **extra)


def unavailable(message: str, hint: str | None = None, **extra: Any) -> dict[str, Any]:
    """A dependency the tool needs is missing or down."""

    return tool_error(ToolErrorCode.UNAVAILABLE, message, hint, **extra)


def internal_error(tool_name: str) -> dict[str, Any]:
    """An unexpected exception escaped the handler.

    Deliberately says nothing about the exception — details live in structlog.
    """

    return tool_error(
        ToolErrorCode.INTERNAL,
        f"{tool_name} failed unexpectedly.",
        "Tell the operator this step failed; do not retry it automatically.",
    )


def unknown_tool(tool_name: str) -> dict[str, Any]:
    """The model invented a tool name."""

    return tool_error(
        ToolErrorCode.UNKNOWN_TOOL,
        f"There is no tool named {tool_name}.",
        "Use one of the tools provided in this request.",
    )
