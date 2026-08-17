"""Regression tests for current-thread intent and cross-channel context selection."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.contact_context_snapshot import ContactTimelineItem
from app.services.ai.message_context_builder import (
    build_contact_generation_context,
    get_latest_inbound_intent,
    select_relevant_cross_channel_history,
)

NOW = datetime(2026, 8, 17, 16, 0, tzinfo=UTC)


def _timeline_item(
    *,
    body: str,
    channel: str,
    minutes_ago: int,
) -> ContactTimelineItem:
    return ContactTimelineItem(
        message_id=uuid.uuid4(),
        channel=channel,
        direction="inbound",
        occurred_at=NOW - timedelta(minutes=minutes_ago),
        status="delivered",
        content=body,
        duration_seconds=180 if channel == "voice" else None,
        is_ai=False,
        provenance=(),
    )


def test_latest_inbound_intent_ignores_newer_assistant_turn() -> None:
    messages = [
        {"role": "user", "content": "Earlier question"},
        {"role": "user", "content": "What did we discuss about gutters on the call?"},
        {"role": "assistant", "content": "Let me check."},
    ]

    assert get_latest_inbound_intent(messages) == ("What did we discuss about gutters on the call?")


def test_relevant_prior_call_survives_newer_unrelated_sms_history() -> None:
    prior_call = _timeline_item(
        body="Customer qualified for a gutter cleaning estimate after discussing downspouts.",
        channel="voice",
        minutes_ago=90,
    )
    newer_sms = tuple(
        _timeline_item(
            body=f"Unrelated driveway message {index}",
            channel="sms",
            minutes_ago=20 - index,
        )
        for index in range(10)
    )

    selected = select_relevant_cross_channel_history(
        (prior_call, *newer_sms),
        latest_inbound_intent="What did we discuss on the call about gutter downspouts?",
        limit=3,
    )

    assert prior_call in selected
    assert len(selected) == 3
    assert [item.occurred_at for item in selected] == sorted(item.occurred_at for item in selected)


@pytest.mark.asyncio
async def test_sms_contact_context_renders_live_snapshot_before_durable_memory() -> None:
    workspace_id = uuid.uuid4()
    conversation = SimpleNamespace(
        workspace_id=workspace_id,
        contact_id=44,
    )
    copied_snapshot = MagicMock()
    copied_snapshot.render.return_value = "<LIVE_CRM>quote=approved</LIVE_CRM>"
    snapshot = MagicMock(recent_timeline=())
    snapshot.model_copy.return_value = copied_snapshot
    snapshot_service = MagicMock()
    snapshot_service.get_snapshot = AsyncMock(return_value=snapshot)
    memory_service = MagicMock()
    memory_service.get_context = AsyncMock(return_value=SimpleNamespace())

    with (
        patch(
            "app.services.ai.message_context_builder.ContactContextSnapshotService",
            return_value=snapshot_service,
        ),
        patch(
            "app.services.ai.message_context_builder.ContactAIMemoryService",
            return_value=memory_service,
        ),
        patch(
            "app.services.ai.message_context_builder.render_contact_ai_memory_context",
            return_value="<DURABLE_MEMORY>quote=pending</DURABLE_MEMORY>",
        ),
    ):
        context = await build_contact_generation_context(
            conversation,
            AsyncMock(),
            messages=[{"role": "user", "content": "Was my quote accepted?"}],
        )

    assert context.latest_inbound_intent == "Was my quote accepted?"
    assert context.prompt_block.index("quote=approved") < context.prompt_block.index(
        "quote=pending"
    )
    snapshot_service.get_snapshot.assert_awaited_once_with(
        workspace_id=workspace_id,
        contact_id=44,
    )
    memory_service.get_context.assert_awaited_once_with(
        workspace_id=workspace_id,
        contact_id=44,
    )
