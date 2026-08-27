"""Regression tests for per-conversation AI response debouncing."""

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from app.services.ai import text_agent


class _SessionContext:
    async def __aenter__(self) -> AsyncMock:
        return AsyncMock()

    async def __aexit__(self, *_args: object) -> None:
        return None


async def test_replaced_debounce_task_cannot_release_its_replacement() -> None:
    conversation_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    process = AsyncMock()
    real_sleep = asyncio.sleep
    delays = {delay: asyncio.Event() for delay in (0.1, 0.05, 0.01)}

    async def controlled_sleep(delay: float) -> None:
        await delays[delay].wait()

    text_agent._pending_responses.clear()
    try:
        with (
            patch("app.db.session.AsyncSessionLocal", return_value=_SessionContext()),
            patch("app.services.ai.text_agent.process_inbound_with_ai", process),
            patch("app.services.ai.text_agent.asyncio.sleep", controlled_sleep),
        ):
            await text_agent.schedule_ai_response(conversation_id, workspace_id, delay_ms=100)
            await real_sleep(0)  # Start the first task before replacing it.
            await text_agent.schedule_ai_response(conversation_id, workspace_id, delay_ms=50)
            await real_sleep(0)  # Let the cancelled task run its finally block.
            await text_agent.schedule_ai_response(conversation_id, workspace_id, delay_ms=10)
            await real_sleep(0)
            for delay in delays.values():
                delay.set()
            await real_sleep(0)
            await real_sleep(0)

        assert process.await_count == 1
    finally:
        remaining = list(text_agent._pending_responses.values())
        for task in remaining:
            task.cancel()
        await asyncio.gather(*remaining, return_exceptions=True)
        text_agent._pending_responses.clear()
