"""Abuse controls for manual appointment reminder SMS sends."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.services.rate_limiting.appointment_reminder_limiter import (
    enforce_appointment_reminder_rate_limit,
)

pytestmark = pytest.mark.asyncio


async def test_checks_user_and_workspace_windows() -> None:
    check = AsyncMock(return_value=(True, 1))

    with patch(
        "app.services.rate_limiting.appointment_reminder_limiter._check_and_increment",
        check,
    ):
        await enforce_appointment_reminder_rate_limit(uuid.uuid4(), 42)

    assert check.await_count == 3
    keys = [call.args[0] for call in check.await_args_list]
    assert ":user:42:hour:" in keys[0]
    assert ":hour:" in keys[1]
    assert ":day:" in keys[2]


async def test_rejects_when_a_window_is_exhausted() -> None:
    check = AsyncMock(return_value=(False, 26))

    with (
        patch(
            "app.services.rate_limiting.appointment_reminder_limiter._check_and_increment",
            check,
        ),
        pytest.raises(HTTPException) as excinfo,
    ):
        await enforce_appointment_reminder_rate_limit(uuid.uuid4(), 42)

    assert excinfo.value.status_code == 429
    assert excinfo.value.headers is not None
    assert int(excinfo.value.headers["Retry-After"]) > 0


async def test_fails_closed_when_redis_is_unavailable() -> None:
    check = AsyncMock(side_effect=ConnectionError("redis unavailable"))

    with (
        patch(
            "app.services.rate_limiting.appointment_reminder_limiter._check_and_increment",
            check,
        ),
        pytest.raises(HTTPException) as excinfo,
    ):
        await enforce_appointment_reminder_rate_limit(uuid.uuid4(), 42)

    assert excinfo.value.status_code == 503
    assert excinfo.value.detail == "Reminder sending is temporarily unavailable"
