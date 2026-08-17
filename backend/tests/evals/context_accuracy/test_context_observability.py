"""Privacy and determinism tests for production AI observability."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.ai.context_observability import (
    ContextChunk,
    build_context_event,
    observe_human_correction,
    observe_model_route,
    observe_tool_call,
    pseudonymous_ref,
)


class CapturingLog:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def info(self, name: str, **values: Any) -> None:
        self.events.append((name, values))


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for child in value.values() for key in _all_keys(child)}
    if isinstance(value, list):
        return {key for child in value for key in _all_keys(child)}
    return set()


def test_context_event_has_source_freshness_and_tokens_without_text_or_raw_ids() -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    raw_source_id = "contact-row-raw-123"
    raw_invocation_id = "conversation-raw-456"
    sensitive_text = "[CONTACT] wrote secret-body@example.invalid and [PHONE_RAW]."

    event = build_context_event(
        surface="sms",
        invocation_id=raw_invocation_id,
        chunks=(
            ContextChunk(
                source_type="contact_snapshot",
                source_ids=(raw_source_id,),
                text=sensitive_text,
                observed_at=now - timedelta(minutes=2),
                record_updated_at=now - timedelta(days=45),
            ),
        ),
        model="configured-model",
        temperature=0.0,
        now=now,
        hash_key="test-only-observability-key",
    )
    serialized = json.dumps(event, sort_keys=True)

    assert sensitive_text not in serialized
    assert "secret-body@example.invalid" not in serialized
    assert raw_source_id not in serialized
    assert raw_invocation_id not in serialized
    assert event["context_token_count"] > 0
    assert event["context_sources"][0]["freshness"] == "stale"
    assert event["context_sources"][0]["token_count"] > 0
    assert not {"body", "message_body", "text", "arguments", "result"}.intersection(
        _all_keys(event)
    )


def test_pseudonymous_refs_are_stable_and_type_separated() -> None:
    first = pseudonymous_ref("contact", "123", hash_key="test-key")
    second = pseudonymous_ref("contact", "123", hash_key="test-key")
    different_type = pseudonymous_ref("workspace", "123", hash_key="test-key")

    assert first == second
    assert first != different_type
    assert first.startswith("ctx_")
    assert "123" not in first


def test_tool_route_and_human_correction_events_accept_metadata_only() -> None:
    log = CapturingLog()
    common_key = "test-only-observability-key"

    tool_event = observe_tool_call(
        log,
        surface="voice",
        invocation_id="raw-call-id",
        tool_call_id="raw-tool-id",
        tool_name="book_appointment",
        status="completed",
        success=True,
        hash_key=common_key,
    )
    correction_event = observe_human_correction(
        log,
        workspace_id="raw-workspace-id",
        contact_id="raw-contact-id",
        operator_id="raw-operator-id",
        correction_id="raw-correction-id",
        correction_kind="fact",
        action="replaced",
        hash_key=common_key,
    )
    route_event = observe_model_route(
        log,
        invocation_id="raw-conversation-id",
        mode="shadow",
        recommended_tier="strong",
        recommended_model="strong-model",
        recommended_temperature=0.0,
        selected_model="cheap-model",
        selected_temperature=0.7,
        reason_codes=("pricing_or_quote",),
        hash_key=common_key,
    )
    serialized = json.dumps([tool_event, correction_event, route_event], sort_keys=True)

    assert [name for name, _ in log.events] == [
        "ai_tool_call_observed",
        "ai_human_correction_observed",
        "ai_model_route_observed",
    ]
    assert "raw-call-id" not in serialized
    assert "raw-tool-id" not in serialized
    assert "raw-contact-id" not in serialized
    assert "raw-correction-id" not in serialized
    assert "pricing_or_quote" in serialized
    assert not {"body", "message_body", "arguments", "result"}.intersection(
        _all_keys([tool_event, correction_event, route_event])
    )


def test_tool_name_is_allowlisted_before_logging() -> None:
    log = CapturingLog()
    unsafe_name = "book for secret-body@example.invalid"

    event = observe_tool_call(
        log,
        surface="sms",
        invocation_id="invocation",
        tool_call_id="tool-call",
        tool_name=unsafe_name,
        status="requested",
        hash_key="test-only-observability-key",
    )

    assert event["tool_name"] == "invalid_tool_name"
    assert unsafe_name not in json.dumps(event)
