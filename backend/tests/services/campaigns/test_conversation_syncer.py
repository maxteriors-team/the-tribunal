"""Campaign settings never enable automation on imported conversations."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.campaigns.conversation_syncer import CampaignConversationSyncer


@pytest.mark.asyncio
async def test_imported_conversation_skips_campaign_agent_and_ai_sync() -> None:
    conversation = SimpleNamespace(
        id=uuid4(),
        source_provider="legacy_import",
        assigned_agent_id=None,
        ai_enabled=False,
    )
    db = MagicMock()
    db.execute = AsyncMock()

    changed = await CampaignConversationSyncer().sync_conversation(db, conversation)

    assert changed is False
    db.execute.assert_not_awaited()
    assert conversation.assigned_agent_id is None
    assert conversation.ai_enabled is False
