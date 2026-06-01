"""Shared context and helpers for CRM assistant tool modules."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

type ToolArguments = dict[str, Any]
type ToolResult = dict[str, Any]
type ToolHandler = Callable[[ToolArguments], Awaitable[ToolResult]]


@dataclass(slots=True, frozen=True)
class CRMToolContext:
    """Per-request dependencies shared by assistant tool handlers."""

    db: AsyncSession
    workspace_id: uuid.UUID
    user_id: int


def parse_uuid(raw_value: Any) -> uuid.UUID | None:
    """Parse a UUID argument, returning None for invalid assistant input."""

    try:
        return uuid.UUID(str(raw_value))
    except (TypeError, ValueError):
        return None


def without_confirmation(args: ToolArguments) -> ToolArguments:
    """Remove assistant confirmation flags before model/schema construction."""

    return {key: value for key, value in args.items() if key not in {"confirmed", "user_confirmed"}}
