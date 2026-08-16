"""Fast regression tests for quote delivery behavior."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.quotes import QuoteService


@pytest.mark.asyncio
async def test_explicit_quote_resend_uses_a_fresh_provider_key(monkeypatch) -> None:
    """Two deliberate email deliveries must not collapse into one Resend email."""
    workspace_id = uuid.uuid4()
    quote_id = uuid.uuid4()
    quote = SimpleNamespace(
        id=quote_id,
        proposal_document={"client": {"email": "client@example.com"}},
        public_token="quote-share-token",
        workspace=SimpleNamespace(name="Lighting Co"),
        contact=None,
    )
    service = QuoteService(AsyncMock())
    monkeypatch.setattr(service, "_load_for_send", AsyncMock(return_value=quote))
    monkeypatch.setattr(service, "_ensure_sent_state", AsyncMock())

    delivery_attempt_ids: list[uuid.UUID] = []

    async def capture_email(
        delivered_quote,
        *,
        override_email: str | None = None,
        delivery_attempt_id: uuid.UUID | None = None,
    ) -> bool:
        assert delivered_quote is quote
        assert override_email == "client@example.com"
        assert delivery_attempt_id is not None
        delivery_attempt_ids.append(delivery_attempt_id)
        return True

    monkeypatch.setattr(service, "_email_quote", capture_email)

    first = await service.deliver_quote(workspace_id, quote_id, channel="email")
    second = await service.deliver_quote(workspace_id, quote_id, channel="email")

    assert first.ok and second.ok
    assert len(delivery_attempt_ids) == 2
    assert delivery_attempt_ids[0] != delivery_attempt_ids[1]
