"""Unit tests for :mod:`app.core.logging` redaction processor."""

from __future__ import annotations

import pytest

from app.core.logging import (
    REDACTED,
    SENSITIVE_KEYS,
    _build_processors,
    configure_logging,
    redact_sensitive_keys,
)

# Keys mandated by the task spec — kept here so this test fails if anyone
# silently drops one from SENSITIVE_KEYS.
REQUIRED_KEYS: tuple[str, ...] = (
    "phone",
    "phone_number",
    "email",
    "full_name",
    "password",
    "token",
    "secret",
    "authorization",
    "api_key",
    "webhook_secret",
)


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_top_level_key_is_redacted(key: str) -> None:
    event = {"event": "user_action", key: "sensitive-value-123"}

    result = redact_sensitive_keys(None, "info", event)

    assert result[key] == REDACTED
    assert result["event"] == "user_action"


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_nested_mapping_key_is_redacted(key: str) -> None:
    event = {
        "event": "request",
        "payload": {"id": 7, key: "leak"},
    }

    result = redact_sensitive_keys(None, "info", event)

    assert result["payload"][key] == REDACTED
    assert result["payload"]["id"] == 7


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_key_in_list_of_dicts_is_redacted(key: str) -> None:
    event = {"contacts": [{key: "x"}, {key: "y", "name": "Jane"}]}

    result = redact_sensitive_keys(None, "info", event)

    assert result["contacts"][0][key] == REDACTED
    assert result["contacts"][1][key] == REDACTED
    assert result["contacts"][1]["name"] == "Jane"


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_case_insensitive_match(key: str) -> None:
    event = {key.upper(): "v", key.title(): "v"}

    result = redact_sensitive_keys(None, "info", event)

    assert result[key.upper()] == REDACTED
    assert result[key.title()] == REDACTED


def test_non_sensitive_keys_pass_through() -> None:
    event = {
        "event": "ping",
        "user_id": 42,
        "phone_country_code": "+1",  # not in the deny-list
        "metadata": {"region": "us-east"},
    }

    result = redact_sensitive_keys(None, "info", event)

    assert result == {
        "event": "ping",
        "user_id": 42,
        "phone_country_code": "+1",
        "metadata": {"region": "us-east"},
    }


def test_deeply_nested_redaction() -> None:
    event = {
        "outer": {
            "middle": {
                "inner": {"password": "hunter2", "ok": True},
            },
        },
    }

    result = redact_sensitive_keys(None, "info", event)

    assert result["outer"]["middle"]["inner"]["password"] == REDACTED
    assert result["outer"]["middle"]["inner"]["ok"] is True


def test_all_required_keys_present_in_module() -> None:
    missing = set(REQUIRED_KEYS) - SENSITIVE_KEYS
    assert not missing, f"SENSITIVE_KEYS is missing: {missing}"


def test_processor_is_wired_into_pipeline() -> None:
    processors = _build_processors()
    assert redact_sensitive_keys in processors


def test_configure_logging_is_idempotent() -> None:
    # Two calls must not raise; structlog replaces config atomically.
    configure_logging()
    configure_logging()


def test_returns_same_event_dict_object() -> None:
    # structlog expects processors to return the (possibly-mutated) event dict.
    event = {"password": "x"}
    result = redact_sensitive_keys(None, "info", event)
    assert result is event
