"""Tests for ``TelnyxSMSService.update_message_status`` delivery-status mapping.

These cover the real (unmocked) status-mapping path, which the webhook-handler
tests stub out. Regression guard for the crash where a Telnyx ``delivery_failed``
/ ``sending_failed`` / unknown status raised ``ValueError`` (the default of
``dict.get(status, MessageStatus(status))`` is evaluated eagerly), returning
HTTP 500 and making Telnyx retry the delivery webhook forever.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from app.models.conversation import MessageStatus
from app.services.telephony.telnyx import TelnyxSMSService


def _db_returning(message: Any) -> Any:
    scalar = MagicMock()
    scalar.scalar_one_or_none = MagicMock(return_value=message)
    db = MagicMock()
    db.execute = AsyncMock(return_value=scalar)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _message(status: MessageStatus = MessageStatus.SENT) -> Any:
    msg = MagicMock()
    msg.id = uuid.uuid4()
    msg.status = status
    msg.delivered_at = None
    msg.error_code = None
    msg.error_message = None
    return msg


class TestUpdateMessageStatusMapping:
    async def test_delivery_failed_maps_to_failed_without_crashing(self) -> None:
        svc = TelnyxSMSService(api_key="k")
        msg = _message(MessageStatus.SENT)
        db = _db_returning(msg)

        result, previous = await svc.update_message_status(
            db=db,
            provider_message_id="m1",
            status="delivery_failed",
            error_code="40010",
            error_message="undeliverable",
        )

        assert result is msg
        assert previous == MessageStatus.SENT
        assert msg.status == MessageStatus.FAILED
        assert msg.error_code == "40010"
        db.commit.assert_awaited_once()

    async def test_sending_failed_maps_to_failed(self) -> None:
        svc = TelnyxSMSService(api_key="k")
        msg = _message(MessageStatus.SENDING)
        db = _db_returning(msg)

        _result, _previous = await svc.update_message_status(
            db=db, provider_message_id="m1", status="sending_failed"
        )

        assert msg.status == MessageStatus.FAILED
        db.commit.assert_awaited_once()

    async def test_unknown_status_is_noop_not_crash(self) -> None:
        svc = TelnyxSMSService(api_key="k")
        msg = _message(MessageStatus.SENT)
        db = _db_returning(msg)

        # Telnyx also sends statuses we don't model (expired,
        # delivery_unconfirmed). These must be ignored, never raise.
        result, previous = await svc.update_message_status(
            db=db, provider_message_id="m1", status="expired"
        )

        assert result is msg
        assert previous == MessageStatus.SENT
        assert msg.status == MessageStatus.SENT  # unchanged
        db.commit.assert_not_awaited()

    async def test_sent_advances_to_delivered_and_sets_timestamp(self) -> None:
        svc = TelnyxSMSService(api_key="k")
        msg = _message(MessageStatus.SENT)
        db = _db_returning(msg)

        await svc.update_message_status(db=db, provider_message_id="m1", status="delivered")

        assert msg.status == MessageStatus.DELIVERED
        assert msg.delivered_at is not None
        db.commit.assert_awaited_once()

    async def test_late_sent_does_not_regress_delivered(self) -> None:
        # An out-of-order / redelivered `message.sent` after `delivered` must
        # not downgrade the row (which would also double-count campaign stats).
        svc = TelnyxSMSService(api_key="k")
        msg = _message(MessageStatus.DELIVERED)
        db = _db_returning(msg)

        result, previous = await svc.update_message_status(
            db=db, provider_message_id="m1", status="sent"
        )

        assert msg.status == MessageStatus.DELIVERED
        assert previous == MessageStatus.DELIVERED
        db.commit.assert_not_awaited()

    async def test_missing_message_returns_none(self) -> None:
        svc = TelnyxSMSService(api_key="k")
        db = _db_returning(None)

        result, previous = await svc.update_message_status(
            db=db, provider_message_id="missing", status="delivered"
        )

        assert result is None
        assert previous is None
