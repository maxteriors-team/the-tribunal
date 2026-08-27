"""Contract tests for the retry-safe Quo manual text sender."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.quo_send_attempt import QuoSendAttempt, QuoSendAttemptState
from app.services.quo.outbound import (
    QuoMediaUnsupportedError,
    QuoOutboundSender,
    QuoSendRejectedError,
    QuoSendStatusUnknownError,
    execute_quo_send,
)


class _CommitOnlySession(AsyncSession):
    def __init__(self) -> None:
        super().__init__()
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _attempt() -> QuoSendAttempt:
    return QuoSendAttempt(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        client_request_id=uuid.uuid4(),
        state=QuoSendAttemptState.SENDING,
    )


async def test_sender_uses_exact_openphone_contract() -> None:
    api_key = "quo_contract_key"
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        assert request.url == httpx.URL("https://api.openphone.com/v1/messages")
        assert request.headers["Authorization"] == api_key
        assert json.loads(request.content) == {
            "content": "Hello from CRM",
            "from": "+14155552671",
            "to": ["+14155552672"],
        }
        return httpx.Response(200, json={"data": {"id": "MSG_accepted", "status": "queued"}})

    sender = QuoOutboundSender(api_key, transport=httpx.MockTransport(handler))
    try:
        accepted = await sender.send_text(
            content="Hello from CRM",
            from_number="+14155552671",
            to_number="+14155552672",
        )
    finally:
        await sender.close()

    assert accepted.provider_message_id == "MSG_accepted"
    assert len(requests) == 1


async def test_sender_rejects_media_before_network_io() -> None:
    requests = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={"data": {"id": "MSG_never"}})

    sender = QuoOutboundSender("quo_test_key", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(QuoMediaUnsupportedError, match="text-only"):
            await sender.send_text(
                content="caption",
                from_number="+14155552671",
                to_number="+14155552672",
                media=["https://example.test/image.jpg"],
            )
    finally:
        await sender.close()

    assert requests == 0


@pytest.mark.parametrize(
    ("status_code", "expected_state", "expected_error"),
    [
        (400, QuoSendAttemptState.FAILED, QuoSendRejectedError),
        (429, QuoSendAttemptState.UNKNOWN, QuoSendStatusUnknownError),
        (500, QuoSendAttemptState.UNKNOWN, QuoSendStatusUnknownError),
    ],
)
async def test_provider_http_outcomes_make_one_attempt_and_store_sanitized_state(
    status_code: int,
    expected_state: QuoSendAttemptState,
    expected_error: type[Exception],
) -> None:
    requests = 0
    sensitive_body = "do-not-store-this-message"

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(status_code, json={"message": sensitive_body})

    attempt = _attempt()
    db = _CommitOnlySession()
    sender = QuoOutboundSender("quo_test_key", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(expected_error) as exc_info:
            await execute_quo_send(
                db,
                attempt=attempt,
                sender=sender,
                content="Hello",
                from_number="+14155552671",
                to_number="+14155552672",
            )
    finally:
        await sender.close()

    assert requests == 1
    assert db.commits == 1
    assert attempt.state == expected_state
    assert attempt.error_class in {"provider_rejected", "rate_limited", "provider_5xx"}
    assert sensitive_body not in str(exc_info.value)


async def test_transport_error_is_unknown_and_is_never_retried() -> None:
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        raise httpx.ConnectError("private transport detail", request=request)

    attempt = _attempt()
    db = _CommitOnlySession()
    sender = QuoOutboundSender("quo_test_key", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(QuoSendStatusUnknownError):
            await execute_quo_send(
                db,
                attempt=attempt,
                sender=sender,
                content="Hello",
                from_number="+14155552671",
                to_number="+14155552672",
            )
    finally:
        await sender.close()

    assert requests == 1
    assert attempt.state == QuoSendAttemptState.UNKNOWN
    assert attempt.error_class == "transport"
