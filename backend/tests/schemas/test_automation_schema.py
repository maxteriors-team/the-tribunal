"""Automation action configuration schema tests."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.automation import AutomationActionSchema


def test_send_sms_agent_id_is_typed_and_json_safe() -> None:
    agent_id = uuid.uuid4()

    action = AutomationActionSchema(
        type="send_sms",
        config={"message": "Hi", "agent_id": str(agent_id), "require_consent": True},
    )

    assert action.config == {
        "message": "Hi",
        "agent_id": str(agent_id),
        "require_consent": True,
    }


def test_send_sms_rejects_invalid_agent_id() -> None:
    with pytest.raises(ValidationError):
        AutomationActionSchema(
            type="send_sms",
            config={"message": "Hi", "agent_id": "not-a-uuid"},
        )
