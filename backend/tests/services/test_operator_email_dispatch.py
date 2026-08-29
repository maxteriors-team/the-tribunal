"""Operator emails use role scoping unless payment alerts have a dedicated inbox."""

import json
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import notifications
from app.services.ai.tool_executor import VoiceToolExecutor
from app.services.payments.call_payment_service import notify_payment_operators
from app.services.payments.customer_payment_notifications import notify_customer_payment
from app.services.telephony import voicemail


@pytest.fixture
def admin_user() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        email="admin@example.com",
        notification_email=True,
        notification_new_lead=True,
    )


@pytest.fixture
def scoped_recipients(monkeypatch: pytest.MonkeyPatch, admin_user: SimpleNamespace) -> AsyncMock:
    recipients = AsyncMock(return_value=[admin_user])
    monkeypatch.setattr(
        "app.services.notification_recipients.workspace_notification_email_users",
        recipients,
    )
    monkeypatch.setattr(notifications, "workspace_notification_email_users", recipients)
    return recipients


@pytest.mark.asyncio
async def test_actionable_event_email_uses_scoped_admin_recipients(
    monkeypatch: pytest.MonkeyPatch,
    admin_user: SimpleNamespace,
    scoped_recipients: AsyncMock,
) -> None:
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(notifications, "send_event_notification_email", send)

    await notifications._send_emails(
        AsyncMock(),
        workspace_id=str(uuid.uuid4()),
        notification_type="new_lead",
        subject="New lead",
        heading="New lead",
        intro="Ada requested an estimate",
        details=None,
        dedupe_key=uuid.uuid4(),
        recipient_user_ids=None,
    )

    scoped_recipients.assert_awaited_once()
    send.assert_awaited_once()
    assert send.await_args.kwargs["to_email"] == admin_user.email


@pytest.mark.asyncio
async def test_taken_message_email_uses_scoped_admin_recipients(
    monkeypatch: pytest.MonkeyPatch,
    admin_user: SimpleNamespace,
    scoped_recipients: AsyncMock,
) -> None:
    send = AsyncMock(return_value=True)
    push = AsyncMock()
    monkeypatch.setattr(
        "app.services.email.send_taken_message_notification",
        send,
    )
    monkeypatch.setattr(
        "app.services.push_notifications.push_notification_service.send_to_workspace_members",
        push,
    )
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(name="Acme")
    message = SimpleNamespace(
        id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        caller_name="Ada",
        callback_number="+15555550100",
        reason="Estimate",
        urgency="normal",
        preferred_callback_time=None,
        message_body="Please call",
    )

    await VoiceToolExecutor(MagicMock())._notify_message_operators(
        db,
        workspace_id=uuid.uuid4(),
        phone_message=message,
    )

    scoped_recipients.assert_awaited_once()
    send.assert_awaited_once()
    assert send.await_args.kwargs["to_email"] == admin_user.email


@pytest.mark.asyncio
async def test_call_payment_email_uses_scoped_admin_recipients(
    monkeypatch: pytest.MonkeyPatch,
    admin_user: SimpleNamespace,
    scoped_recipients: AsyncMock,
) -> None:
    send = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.email.send_payment_received_notification", send)
    monkeypatch.setattr(
        "app.services.push_notifications.push_notification_service.send_to_workspace_members",
        AsyncMock(),
    )
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(name="Acme")
    payment = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        message_id=None,
        amount=Decimal("125.00"),
        currency="usd",
        description="Deposit",
        operators_notified_at=None,
    )

    await notify_payment_operators(db, payment)

    scoped_recipients.assert_awaited_once()
    send.assert_awaited_once()
    assert send.await_args.kwargs["to_email"] == admin_user.email


@pytest.mark.asyncio
async def test_call_payment_deduplicates_dedicated_recipient_on_retry(
    monkeypatch: pytest.MonkeyPatch,
    scoped_recipients: AsyncMock,
) -> None:
    send = AsyncMock(return_value=True)
    push = AsyncMock()
    monkeypatch.setattr("app.services.email.send_payment_received_notification", send)
    monkeypatch.setattr(
        "app.services.push_notifications.push_notification_service.send_to_workspace_members",
        push,
    )
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(
        name="Acme",
        settings={"payment_alerts": {"recipient_email": "maxterior@gmail.com"}},
    )
    payment = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        message_id=None,
        amount=Decimal("125.00"),
        currency="usd",
        description="Deposit",
        operators_notified_at=None,
    )

    await notify_payment_operators(db, payment)
    await notify_payment_operators(db, payment)

    scoped_recipients.assert_not_awaited()
    send.assert_awaited_once()
    assert send.await_args.kwargs["to_email"] == "maxterior@gmail.com"
    push.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_customer_payment_email_uses_scoped_admin_recipients(
    monkeypatch: pytest.MonkeyPatch,
    admin_user: SimpleNamespace,
    scoped_recipients: AsyncMock,
) -> None:
    send = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.email.send_payment_received_notification", send)
    monkeypatch.setattr(
        "app.services.push_notifications.push_notification_service.send_to_workspace_members",
        AsyncMock(),
    )
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(name="Acme")

    sent = await notify_customer_payment(
        db,
        workspace_id=uuid.uuid4(),
        amount=Decimal("125.00"),
        currency="usd",
        description="Invoice payment",
        idempotency_scope="invoice_payment",
        idempotency_id=uuid.uuid4(),
    )

    assert sent == 1
    scoped_recipients.assert_awaited_once()
    send.assert_awaited_once()
    assert send.await_args.kwargs["to_email"] == admin_user.email


@pytest.mark.asyncio
async def test_customer_payment_retry_delivers_once_per_attempt_with_stable_deduplication_key(
    monkeypatch: pytest.MonkeyPatch,
    scoped_recipients: AsyncMock,
) -> None:
    send = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.email.send_payment_received_notification", send)
    monkeypatch.setattr(
        "app.services.push_notifications.push_notification_service.send_to_workspace_members",
        AsyncMock(),
    )
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(
        name="Acme",
        settings={"payment_alerts": {"recipient_email": "maxterior@gmail.com"}},
    )
    payment_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    sent_counts = []

    for _ in range(2):
        sent_counts.append(
            await notify_customer_payment(
                db,
                workspace_id=workspace_id,
                amount=Decimal("125.00"),
                currency="usd",
                description="Invoice payment",
                idempotency_scope="invoice_payment",
                idempotency_id=payment_id,
            )
        )

    scoped_recipients.assert_not_awaited()
    assert sent_counts == [1, 1]
    assert [call.kwargs["to_email"] for call in send.await_args_list] == [
        "maxterior@gmail.com",
        "maxterior@gmail.com",
    ]
    keys = [call.kwargs["idempotency_key"] for call in send.await_args_list]
    assert keys[0] == keys[1]


@pytest.mark.asyncio
async def test_voicemail_email_uses_scoped_admin_recipients(
    monkeypatch: pytest.MonkeyPatch,
    admin_user: SimpleNamespace,
    scoped_recipients: AsyncMock,
) -> None:
    send = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.email.send_voicemail_notification", send)
    workspace = SimpleNamespace(id=uuid.uuid4(), name="Acme")
    message = SimpleNamespace(id=uuid.uuid4(), transcript=json.dumps({"text": "Call me"}))
    analysis = voicemail.VoicemailAnalysis(
        summary="Estimate request",
        intent="estimate",
        urgency="normal",
        callback_requested=True,
    )

    await voicemail._email_workspace_members(
        AsyncMock(),
        workspace=workspace,
        message=message,
        contact_phone="+15555550100",
        analysis=analysis,
        log=MagicMock(),
    )

    scoped_recipients.assert_awaited_once()
    send.assert_awaited_once()
    assert send.await_args.kwargs["to_email"] == admin_user.email
