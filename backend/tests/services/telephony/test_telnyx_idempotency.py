"""Service-level tests for idempotent outbound sends.

These tests live next to ``test_telnyx.py`` and cover only the
crash-safety contract introduced with the ``idempotency_key`` column:

- ``TelnyxSMSService._post_message`` forwards the key as the
  ``X-Idempotency-Key`` HTTP header.
- ``TelnyxSMSService.send_message`` short-circuits and returns the
  existing Message row when a non-QUEUED row already exists for the
  key (the prior attempt reached Telnyx).
- ``TelnyxSMSService.send_message`` *resumes* the prior attempt when
  the existing row is still QUEUED (the prior attempt wrote the row
  but never reached Telnyx) \u2014 it must reuse the same row id, not
  create a duplicate.
- ``TelnyxVoiceService.initiate_call`` forwards the key both as
  ``client_state`` (base64) on the JSON payload and as the
  ``X-Idempotency-Key`` header, and short-circuits on a pre-existing
  non-QUEUED row.
"""

from __future__ import annotations

import base64
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.models.conversation import MessageStatus
from app.services.telephony.telnyx import TelnyxSMSService
from app.services.telephony.telnyx_voice import TelnyxVoiceService

# ---------------------------------------------------------------------------
# SMS: header forwarding on the low-level POST
# ---------------------------------------------------------------------------


class TestPostMessageHeader:
    """``_post_message`` must forward ``X-Idempotency-Key`` when given."""

    async def test_header_included_when_key_provided(self) -> None:
        svc = TelnyxSMSService(api_key="k")
        key = uuid.uuid4()

        seen_requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_requests.append(request)
            return httpx.Response(200, json={"data": {"id": "m1"}})

        svc._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=svc.BASE_URL,
        )

        try:
            await svc._post_message(
                {"to": "+1", "from": "+2", "text": "hi", "type": "SMS"},
                idempotency_key=key,
            )
        finally:
            await svc.close()

        assert seen_requests[0].headers["X-Idempotency-Key"] == str(key)

    async def test_header_omitted_when_no_key(self) -> None:
        svc = TelnyxSMSService(api_key="k")

        seen_requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_requests.append(request)
            return httpx.Response(200, json={"data": {"id": "m1"}})

        svc._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=svc.BASE_URL,
        )

        try:
            await svc._post_message(
                {"to": "+1", "from": "+2", "text": "hi", "type": "SMS"},
            )
        finally:
            await svc.close()

        assert "X-Idempotency-Key" not in seen_requests[0].headers


# ---------------------------------------------------------------------------
# SMS: send_message dedupe behavior
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_with_existing(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Build a db mock whose first execute() returns a given Message row."""

    def _make(existing: Any) -> Any:
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=existing)
        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db

    return _make


class TestSendMessageDedupe:
    """``send_message`` short-circuits or resumes based on the existing row."""

    async def test_returns_existing_sent_message_unchanged(
        self, mock_db_with_existing: Any
    ) -> None:
        svc = TelnyxSMSService(api_key="k")
        key = uuid.uuid4()
        existing = MagicMock(
            id=uuid.uuid4(),
            status=MessageStatus.SENT,
            idempotency_key=key,
        )
        db = mock_db_with_existing(existing)

        # The service must NOT hit Telnyx \u2014 we'd fail loudly if it tried.
        with patch.object(svc, "_post_message", AsyncMock(side_effect=AssertionError("unreached"))):
            result = await svc.send_message(
                to_number="+12025551234",
                from_number="+12025556789",
                body="hi",
                db=db,
                workspace_id=uuid.uuid4(),
                idempotency_key=key,
            )

        assert result is existing

    async def test_resumes_queued_row_without_creating_duplicate(
        self, mock_db_with_existing: Any
    ) -> None:
        svc = TelnyxSMSService(api_key="k")
        key = uuid.uuid4()
        queued_id = uuid.uuid4()
        # The row exists but the prior attempt crashed before reaching
        # Telnyx. send_message must reuse this row, not insert a new one.
        existing = MagicMock(
            id=queued_id,
            status=MessageStatus.QUEUED,
            idempotency_key=key,
            conversation_id=uuid.uuid4(),
            body="hi",
        )
        db = mock_db_with_existing(existing)

        post_mock = AsyncMock(return_value={"data": {"id": "telnyx-m1"}})
        conversation = MagicMock(
            id=existing.conversation_id,
            contact_id=None,
            last_message_preview=None,
            last_message_at=None,
            last_message_direction=None,
        )
        with (
            patch.object(
                svc,
                "_get_or_create_conversation",
                AsyncMock(return_value=conversation),
            ),
            patch.object(svc, "_post_message", post_mock),
            patch(
                "app.services.telephony.telnyx.shorten_urls_in_text",
                AsyncMock(side_effect=lambda body, **kw: body),
            ),
        ):
            result = await svc.send_message(
                to_number="+12025551234",
                from_number="+12025556789",
                body="hi",
                db=db,
                workspace_id=uuid.uuid4(),
                idempotency_key=key,
            )

            # Reused the same Message row, no duplicate insert.
            assert result is existing
            db.add.assert_not_called()
            assert conversation.last_message_direction == "outbound"
            # Telnyx received the same key as header.
            post_mock.assert_awaited_once()
            forwarded = post_mock.call_args.kwargs["idempotency_key"]
            assert forwarded == key


# ---------------------------------------------------------------------------
# Voice: client_state + header forwarding + dedupe
# ---------------------------------------------------------------------------


class TestVoiceInitiateCallIdempotency:
    """``initiate_call`` forwards the key via client_state + header, and dedupes."""

    async def test_returns_existing_non_queued_call_unchanged(self) -> None:
        svc = TelnyxVoiceService(api_key="k")
        key = uuid.uuid4()
        existing = MagicMock(
            id=uuid.uuid4(),
            status=MessageStatus.RINGING,
            idempotency_key=key,
        )

        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=existing)
        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar)
        db.commit = AsyncMock()

        # If the service reaches the Telnyx HTTP path on a dedupe-hit
        # we want a loud failure.
        fake_client = MagicMock()
        fake_client.post = AsyncMock(side_effect=AssertionError("unreached"))
        svc._client = fake_client

        result = await svc.initiate_call(
            to_number="+12025551234",
            from_number="+12025556789",
            connection_id="conn-1",
            webhook_url="http://x",
            db=db,
            workspace_id=uuid.uuid4(),
            idempotency_key=key,
        )

        assert result is existing

    async def test_fresh_call_sends_client_state_and_header(self) -> None:
        svc = TelnyxVoiceService(api_key="k")
        key = uuid.uuid4()

        # No existing row \u2014 db.execute returns scalar_one_or_none=None.
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=None)
        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        # Fake the HTTP layer.
        response = MagicMock(status_code=200, text="")
        response.json = MagicMock(return_value={"data": {"id": "c1", "call_control_id": "cc1"}})
        fake_client = MagicMock()
        fake_client.post = AsyncMock(return_value=response)
        svc._client = fake_client

        with patch.object(
            svc,
            "_get_or_create_conversation",
            AsyncMock(
                return_value=MagicMock(
                    id=uuid.uuid4(),
                    channel="sms",
                    last_message_preview=None,
                    last_message_at=None,
                    assigned_agent_id=None,
                    ai_enabled=False,
                )
            ),
        ):
            await svc.initiate_call(
                to_number="+12025551234",
                from_number="+12025556789",
                connection_id="conn-1",
                webhook_url="http://x",
                db=db,
                workspace_id=uuid.uuid4(),
                idempotency_key=key,
            )

        fake_client.post.assert_awaited_once()
        kwargs = fake_client.post.call_args.kwargs
        # ``client_state`` is the base64 of the key string.
        expected_b64 = base64.b64encode(str(key).encode("ascii")).decode("ascii")
        assert kwargs["json"]["client_state"] == expected_b64
        # ``X-Idempotency-Key`` header carries the raw UUID.
        assert kwargs["headers"] == {"X-Idempotency-Key": str(key)}
