"""Fail-closed, workspace-scoped inbound readiness checks."""

import uuid
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.models.phone_number import PhoneNumberProvider
from app.services.telephony import inbound_call_readiness as readiness_module
from app.services.telephony.inbound_call_readiness import evaluate_inbound_call_readiness

pytestmark = pytest.mark.asyncio


class _Result:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


def _agent(workspace_id: uuid.UUID, **overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "workspace_id": workspace_id,
        "is_active": True,
        "channel_mode": "voice",
        "voice_provider": "openai",
        "voice_id": "alloy",
        "transfer_destination_number": "+12025550124",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _phone(workspace_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        workspace_id=workspace_id,
        provider=PhoneNumberProvider.TELNYX,
        is_active=True,
        voice_enabled=True,
        telnyx_phone_number_id="provider-number-id",
    )


def _configure_runtime(monkeypatch: pytest.MonkeyPatch, workspace_id: uuid.UUID) -> None:
    monkeypatch.setattr(settings, "inbound_voice_pilot_workspace_ids", {workspace_id})
    monkeypatch.setattr(settings, "telnyx_api_key", "test-key")
    monkeypatch.setattr(settings, "api_base_url", "https://api.example.com")
    monkeypatch.setattr(settings, "telnyx_public_key", "test-public-key")
    monkeypatch.setattr(settings, "telnyx_connection_id", "connection-id")


async def test_ready_requires_every_workspace_and_provider_prerequisite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    agent = _agent(workspace_id)
    db = SimpleNamespace(execute=AsyncMock(return_value=_Result(agent)))
    credentials = AsyncMock(return_value=SimpleNamespace(source="workspace_api_key"))
    monkeypatch.setattr(readiness_module, "resolve_openai_credentials", credentials)
    _configure_runtime(monkeypatch, workspace_id)

    readiness = await evaluate_inbound_call_readiness(
        cast(Any, db),
        workspace_id=workspace_id,
        phone_number=cast(Any, _phone(workspace_id)),
        assigned_agent_id=agent.id,
        fallback_number="+12025550123",
        transfer_destination_number=None,
    )

    assert readiness.ready is True
    assert all(check.ready for check in readiness.checks)
    credentials.assert_awaited_once_with(db, workspace_id, require_fresh=True)


async def test_foreign_agent_is_bounded_to_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    workspace_id = uuid.uuid4()
    db = SimpleNamespace(execute=AsyncMock(return_value=_Result(None)))
    monkeypatch.setattr(
        readiness_module,
        "resolve_openai_credentials",
        AsyncMock(return_value=SimpleNamespace(source="workspace_api_key")),
    )
    _configure_runtime(monkeypatch, workspace_id)

    readiness = await evaluate_inbound_call_readiness(
        cast(Any, db),
        workspace_id=workspace_id,
        phone_number=cast(Any, _phone(workspace_id)),
        assigned_agent_id=uuid.uuid4(),
        fallback_number="+12025550123",
        transfer_destination_number="+12025550124",
    )

    checks = {check.code: check for check in readiness.checks}
    assert readiness.ready is False
    assert checks["agent"].ready is False
    assert checks["agent"].message == "Choose an active voice-capable agent in this workspace."


async def test_non_openai_agent_and_non_e164_destinations_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    agent = _agent(
        workspace_id,
        voice_provider="elevenlabs",
        transfer_destination_number="2025550124",
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=_Result(agent)))
    monkeypatch.setattr(
        readiness_module,
        "resolve_openai_credentials",
        AsyncMock(return_value=SimpleNamespace(source="workspace_api_key")),
    )
    _configure_runtime(monkeypatch, workspace_id)

    readiness = await evaluate_inbound_call_readiness(
        cast(Any, db),
        workspace_id=workspace_id,
        phone_number=cast(Any, _phone(workspace_id)),
        assigned_agent_id=agent.id,
        fallback_number="2025550123",
        transfer_destination_number=None,
    )

    checks = {check.code: check.ready for check in readiness.checks}
    assert checks["agent_provider"] is False
    assert checks["fallback_number"] is False
    assert checks["transfer_destination"] is False
    assert readiness.ready is False


async def test_global_openai_credentials_cannot_activate_the_workspace_pilot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    agent = _agent(workspace_id)
    db = SimpleNamespace(execute=AsyncMock(return_value=_Result(agent)))
    monkeypatch.setattr(
        readiness_module,
        "resolve_openai_credentials",
        AsyncMock(return_value=SimpleNamespace(source="env_api_key")),
    )
    _configure_runtime(monkeypatch, workspace_id)

    readiness = await evaluate_inbound_call_readiness(
        cast(Any, db),
        workspace_id=workspace_id,
        phone_number=cast(Any, _phone(workspace_id)),
        assigned_agent_id=agent.id,
        fallback_number="+12025550123",
        transfer_destination_number="+12025550124",
    )

    checks = {check.code: check.ready for check in readiness.checks}
    assert checks["openai_credentials"] is False
    assert readiness.ready is False


@pytest.mark.parametrize(
    "api_base_url",
    [
        "http://localhost:8000",
        "https://localhost",
        "https://127.0.0.1",
        "https://10.0.0.1",
        "https://[fd00::1]",
        "https://api.internal",
        "https://user:password@api.example.com",
        "https://api.example.com?token=secret",
    ],
)
async def test_non_public_stream_url_cannot_activate_provider_routing(
    monkeypatch: pytest.MonkeyPatch,
    api_base_url: str,
) -> None:
    workspace_id = uuid.uuid4()
    agent = _agent(workspace_id)
    db = SimpleNamespace(execute=AsyncMock(return_value=_Result(agent)))
    monkeypatch.setattr(
        readiness_module,
        "resolve_openai_credentials",
        AsyncMock(return_value=SimpleNamespace(source="workspace_api_key")),
    )
    _configure_runtime(monkeypatch, workspace_id)
    monkeypatch.setattr(settings, "api_base_url", api_base_url)

    readiness = await evaluate_inbound_call_readiness(
        cast(Any, db),
        workspace_id=workspace_id,
        phone_number=cast(Any, _phone(workspace_id)),
        assigned_agent_id=agent.id,
        fallback_number="+12025550123",
        transfer_destination_number="+12025550124",
    )

    checks = {check.code: check.ready for check in readiness.checks}
    assert checks["telnyx_runtime"] is False
    assert readiness.ready is False
