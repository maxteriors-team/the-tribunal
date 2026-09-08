"""Shared context and helpers for CRM assistant tool modules."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

type ToolArguments = dict[str, Any]
type ToolResult = dict[str, Any]
type ToolHandler = Callable[[ToolArguments], Awaitable[ToolResult]]


@dataclass(slots=True, frozen=True)
class CRMToolContext:
    """Per-request dependencies shared by assistant tool handlers.

    ``role`` is the caller's workspace role string, carried so the tool layer can
    apply the same capability matrix the HTTP routes use. It is set from the
    resolved :class:`~app.models.workspace.WorkspaceMembership`, never from
    model output or a tool payload, so the assistant cannot claim a role it does
    not hold.
    """

    db: AsyncSession
    workspace_id: uuid.UUID
    user_id: int
    role: str


def parse_uuid(raw_value: Any) -> uuid.UUID | None:
    """Parse a UUID argument, returning None for invalid assistant input."""

    try:
        return uuid.UUID(str(raw_value))
    except (TypeError, ValueError):
        return None


def parse_date(raw_value: Any) -> date | None | Literal[False]:
    """Parse an ISO ``YYYY-MM-DD`` argument from model output.

    Three outcomes, because "absent" and "malformed" must not collapse into one:
    the date, ``None`` when the argument was omitted, and ``False`` when it was
    supplied but unusable. Callers turn ``False`` into an explicit error instead
    of silently reporting on a default window the operator never asked for.
    """

    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        return False
    try:
        return date.fromisoformat(raw_value)
    except ValueError:
        return False


def without_confirmation(args: ToolArguments) -> ToolArguments:
    """Remove assistant confirmation flags before model/schema construction."""

    return {key: value for key, value in args.items() if key not in {"confirmed", "user_confirmed"}}
