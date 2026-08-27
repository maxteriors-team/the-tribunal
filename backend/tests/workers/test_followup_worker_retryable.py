"""FollowupWorker — RetryableWorker contract."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.ai.openai_credentials import OpenAICredentialContext
from app.workers.base import BaseWorker
from app.workers.followup_worker import FollowupWorker
from app.workers.retryable import RetryableWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(FollowupWorker, RetryableWorker)
    assert issubclass(FollowupWorker, BaseWorker)


def test_retry_configuration() -> None:
    assert FollowupWorker.COMPONENT_NAME == "followup_worker"
    assert FollowupWorker.max_retries == 3
    assert FollowupWorker.backoff_base_seconds == 2.0


@pytest.mark.asyncio
async def test_followup_uses_workspace_openai_credential() -> None:
    worker = FollowupWorker()
    conversation = MagicMock(
        id=uuid4(),
        workspace_id=uuid4(),
        followup_delay_hours=1,
    )
    db = MagicMock()
    db.commit = AsyncMock()
    credential = OpenAICredentialContext(
        bearer_token="workspace-token",
        source="workspace_api_key",
    )

    with (
        patch(
            "app.workers.followup_worker.resolve_openai_credentials",
            new=AsyncMock(return_value=credential),
        ) as resolve_credential,
        patch(
            "app.workers.followup_worker.generate_followup_message",
            new=AsyncMock(return_value=None),
        ) as generate_message,
    ):
        result = await worker._process_conversation_followup(conversation, db)

    assert result is False
    resolve_credential.assert_awaited_once_with(db, conversation.workspace_id)
    generate_message.assert_awaited_once_with(
        conversation=conversation,
        db=db,
        openai_api_key=credential.bearer_token,
        credential=credential,
    )
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_quo_followup_stops_before_ai_or_sms() -> None:
    worker = FollowupWorker()
    conversation = MagicMock(id=uuid4(), source_provider="quo")
    db = MagicMock()

    with (
        patch(
            "app.workers.followup_worker.resolve_openai_credentials",
            new=AsyncMock(),
        ) as resolve_credential,
        patch("app.workers.followup_worker.get_text_message_provider") as get_provider,
    ):
        result = await worker._process_conversation_followup(conversation, db)

    assert result is True
    resolve_credential.assert_not_awaited()
    get_provider.assert_not_called()


@pytest.mark.asyncio
async def test_failed_conversation_followup_routes_to_dlq() -> None:
    worker = FollowupWorker()
    recorder = wire_worker_for_retry_test(worker)

    conversation = MagicMock(id=uuid4())
    db = MagicMock()

    async def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("followup blew up")

    item_key = f"conversation:{conversation.id}"
    await worker.execute_with_retry(fail, conversation, db, item_key=item_key)

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "followup_worker"
    assert recorder.calls[0]["item_key"] == item_key
