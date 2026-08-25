"""Tests for the NudgeDeliveryService.

Unit tests with a mocked AsyncSession. Both push and SMS delivery are routed
through ``outbound_delivery_service.deliver`` (the single outbound seam), so the
tests patch that service and the workspace SMS-number resolver rather than any
transport client directly.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, tzinfo
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.nudges.nudge_delivery import NudgeDeliveryService
from app.services.outbound.delivery import OutboundDeliveryChannel


@pytest.fixture
def delivery() -> NudgeDeliveryService:
    return NudgeDeliveryService()


def _make_nudge(
    workspace_id: uuid.UUID | None = None,
    assigned_to_user_id: int | None = None,
) -> MagicMock:
    nudge = MagicMock()
    nudge.id = uuid.uuid4()
    nudge.workspace_id = workspace_id or uuid.uuid4()
    nudge.contact_id = 1
    nudge.nudge_type = "birthday"
    nudge.title = "🎂 Alice's birthday"
    nudge.message = "Alice's birthday is in 2 days."
    nudge.status = "pending"
    nudge.assigned_to_user_id = assigned_to_user_id
    nudge.delivered_at = None
    nudge.delivered_via = None
    return nudge


def _at(instant: datetime) -> Callable[..., datetime]:
    """Build a ``datetime.now`` stand-in pinned to *instant*, honouring its tz arg.

    Quiet-hours logic reads the wall clock in the workspace zone, so the stub has
    to convert rather than return a fixed UTC value — otherwise the test passes
    for the wrong reason.
    """

    def _now(tz: tzinfo | None = None) -> datetime:
        return instant.astimezone(tz) if tz else instant

    return _now


def _make_workspace(nudge_settings: dict | None = None) -> MagicMock:
    ws = MagicMock()
    ws.id = uuid.uuid4()
    ws.settings = {
        "nudge_settings": nudge_settings
        or {
            "delivery_channels": ["sms", "push"],
        }
    }
    return ws


def _make_user(
    user_id: int = 1,
    phone_number: str | None = "+15551234567",
    notification_sms: bool = True,
    is_active: bool = True,
) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.phone_number = phone_number
    user.notification_sms = notification_sms
    user.is_active = is_active
    return user


def _scalar_result(value):
    result = MagicMock()
    result.scalars.return_value.all.return_value = value
    return result


def _scalar_one_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_membership(user: MagicMock, role: str = "owner") -> MagicMock:
    membership = MagicMock()
    membership.user = user
    membership.role = role
    return membership


def _delivery_result(delivered: bool = True) -> MagicMock:
    """Mimic the OutboundDeliveryResult returned by the outbound service."""
    result = MagicMock()
    result.delivered = delivered
    return result


def _channels_used(mock_deliver: AsyncMock) -> list[OutboundDeliveryChannel]:
    """Channels passed to each ``outbound_delivery_service.deliver`` call.

    The request is the second positional arg: ``deliver(db, request)``.
    """
    return [call.args[1].channel for call in mock_deliver.await_args_list]


def _make_phone() -> MagicMock:
    phone = MagicMock()
    phone.id = uuid.uuid4()
    phone.phone_number = "+15550000000"
    return phone


class TestDeliverToWorkspaceMembers:
    async def test_deliver_to_workspace_members(self, delivery: NudgeDeliveryService) -> None:
        """Nudge delivered via push + SMS → marked as sent."""
        ws = _make_workspace()
        nudge = _make_nudge(workspace_id=ws.id)
        membership = _make_membership(_make_user())

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(ws),  # load workspace
                _scalar_result([membership]),  # resolve target users
            ]
        )
        mock_db.commit = AsyncMock()

        with (
            patch("app.services.nudges.nudge_delivery.outbound_delivery_service") as mock_outbound,
            patch(
                "app.services.nudges.nudge_delivery.get_workspace_sms_number",
                new=AsyncMock(return_value=_make_phone()),
            ),
            patch("app.services.nudges.nudge_delivery.settings") as mock_settings,
            patch.object(NudgeDeliveryService, "_is_quiet_hours", return_value=False),
        ):
            mock_settings.telnyx_api_key = "fake-key"
            mock_outbound.deliver = AsyncMock(return_value=_delivery_result(True))

            result = await delivery.deliver_nudge(mock_db, nudge)

        assert result is True
        assert nudge.status == "sent"
        assert nudge.delivered_at is not None
        # Both channels were exercised through the outbound seam.
        channels = _channels_used(mock_outbound.deliver)
        assert OutboundDeliveryChannel.PUSH in channels
        assert OutboundDeliveryChannel.SMS in channels
        mock_db.commit.assert_awaited_once()


class TestSkipUsersWithoutPhone:
    async def test_skip_users_without_phone(self, delivery: NudgeDeliveryService) -> None:
        """User without phone_number → SMS not sent, push still works."""
        ws = _make_workspace()
        nudge = _make_nudge(workspace_id=ws.id)
        membership = _make_membership(_make_user(phone_number=None))

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(ws),
                _scalar_result([membership]),
            ]
        )
        mock_db.commit = AsyncMock()

        with (
            patch("app.services.nudges.nudge_delivery.outbound_delivery_service") as mock_outbound,
            patch(
                "app.services.nudges.nudge_delivery.get_workspace_sms_number",
                new=AsyncMock(return_value=_make_phone()),
            ),
            patch("app.services.nudges.nudge_delivery.settings") as mock_settings,
            patch.object(NudgeDeliveryService, "_is_quiet_hours", return_value=False),
        ):
            mock_settings.telnyx_api_key = "fake-key"
            mock_outbound.deliver = AsyncMock(return_value=_delivery_result(True))

            result = await delivery.deliver_nudge(mock_db, nudge)

        assert result is True
        channels = _channels_used(mock_outbound.deliver)
        # Push happened; no SMS was attempted for the phone-less user.
        assert OutboundDeliveryChannel.PUSH in channels
        assert OutboundDeliveryChannel.SMS not in channels


class TestSmsSkippedDuringQuietHours:
    async def test_sms_skipped_during_quiet_hours(self, delivery: NudgeDeliveryService) -> None:
        """Quiet hours suppress SMS; with SMS-only channel the nudge is not sent."""
        ws = _make_workspace({"delivery_channels": ["sms"]})
        nudge = _make_nudge(workspace_id=ws.id)
        membership = _make_membership(_make_user())

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(ws),
                _scalar_result([membership]),
            ]
        )
        mock_db.commit = AsyncMock()

        with (
            patch("app.services.nudges.nudge_delivery.outbound_delivery_service") as mock_outbound,
            patch("app.services.nudges.nudge_delivery.settings") as mock_settings,
            patch.object(NudgeDeliveryService, "_is_quiet_hours", return_value=True),
        ):
            mock_settings.telnyx_api_key = "fake-key"
            mock_outbound.deliver = AsyncMock(return_value=_delivery_result(True))

            result = await delivery.deliver_nudge(mock_db, nudge)

        assert result is False
        assert nudge.status == "pending"
        mock_outbound.deliver.assert_not_awaited()


class TestQuietHoursRespected:
    def test_quiet_hours_during_quiet_period(self, delivery: NudgeDeliveryService) -> None:
        """23:00 UTC falls within default quiet hours (22:00-08:00)."""
        ws = _make_workspace()
        late_night = datetime(2026, 3, 28, 23, 0, 0, tzinfo=UTC)

        with patch("app.services.nudges.nudge_delivery.datetime") as mock_dt:
            mock_dt.now.return_value = late_night
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            result = delivery._is_quiet_hours(ws)

        assert result is True

    def test_not_quiet_hours_during_day(self, delivery: NudgeDeliveryService) -> None:
        """14:00 UTC is outside quiet hours."""
        ws = _make_workspace()
        afternoon = datetime(2026, 3, 28, 14, 0, 0, tzinfo=UTC)

        with patch("app.services.nudges.nudge_delivery.datetime") as mock_dt:
            mock_dt.now.return_value = afternoon
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            result = delivery._is_quiet_hours(ws)

        assert result is False

    def test_quiet_hours_respects_workspace_timezone(self, delivery: NudgeDeliveryService) -> None:
        """Quiet hours are workspace-local wall-clock times, not UTC.

        At 11:00 UTC (= 07:00 America/New_York, EDT) an Eastern workspace is
        still inside the default 22:00-08:00 window, even though 11:00 UTC is
        outside it. Evaluating in UTC would send nudges at ~7am local... or
        worse, in the small hours for other offsets.
        """
        instant = datetime(2026, 3, 28, 11, 0, 0, tzinfo=UTC)
        ws_utc = _make_workspace()
        ws_utc.settings["timezone"] = "UTC"
        ws_eastern = _make_workspace()
        ws_eastern.settings["timezone"] = "America/New_York"

        with patch("app.services.nudges.nudge_delivery.datetime") as mock_dt:
            mock_dt.now.side_effect = _at(instant)
            mock_dt.side_effect = datetime

            assert delivery._is_quiet_hours(ws_utc) is False
            assert delivery._is_quiet_hours(ws_eastern) is True

    def test_unconfigured_workspace_uses_eastern_not_utc(
        self, delivery: NudgeDeliveryService
    ) -> None:
        """No workspace sets ``settings['timezone']``, so the fallback is the real path.

        A UTC fallback made "quiet until 08:00" expire at 03:00 Eastern, which is
        the middle of the night for the operators these nudges page.
        """
        instant = datetime(2026, 3, 28, 11, 0, 0, tzinfo=UTC)  # 07:00 EDT
        ws = _make_workspace()  # no timezone configured

        with patch("app.services.nudges.nudge_delivery.datetime") as mock_dt:
            mock_dt.now.side_effect = _at(instant)
            mock_dt.side_effect = datetime

            assert delivery._is_quiet_hours(ws) is True


class TestNudgeMarkedSent:
    async def test_nudge_marked_sent(self, delivery: NudgeDeliveryService) -> None:
        """After delivery, nudge.status == 'sent' and delivered_at is set."""
        ws = _make_workspace({"delivery_channels": ["push"]})
        nudge = _make_nudge(workspace_id=ws.id)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(ws),
                _scalar_result([_make_membership(_make_user())]),
            ]
        )
        mock_db.commit = AsyncMock()

        with patch("app.services.nudges.nudge_delivery.outbound_delivery_service") as mock_outbound:
            mock_outbound.deliver = AsyncMock(return_value=_delivery_result(True))

            await delivery.deliver_nudge(mock_db, nudge)

        assert nudge.status == "sent"
        assert nudge.delivered_at is not None
        assert "push" in nudge.delivered_via


class TestLegacyGlobalRecipients:
    async def test_sales_cannot_receive_global_nudges(self, delivery: NudgeDeliveryService) -> None:
        """Unassigned nudges exclude active roles without crm:write."""
        nudge = _make_nudge()
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=_scalar_result([_make_membership(_make_user(user_id=7), role="sales_rep")])
        )

        assert await delivery._resolve_target_users(db, nudge) == []

    async def test_manager_is_the_only_global_recipient(
        self, delivery: NudgeDeliveryService
    ) -> None:
        """Global nudges resolve only active CRM writers."""
        manager = _make_user(user_id=8)
        sales = _make_user(user_id=9)
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=_scalar_result(
                [
                    _make_membership(sales, role="sales_rep"),
                    _make_membership(manager, role="manager"),
                ]
            )
        )

        assert await delivery._resolve_target_users(db, _make_nudge()) == [manager]


class TestAssignedUserOnly:
    async def test_assigned_user_only(self, delivery: NudgeDeliveryService) -> None:
        """Nudge with assigned_to_user_id → only that user is targeted."""
        ws = _make_workspace({"delivery_channels": ["push"]})
        assigned_user = _make_user(user_id=99)
        nudge = _make_nudge(workspace_id=ws.id, assigned_to_user_id=99)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(ws),
                _scalar_one_result(assigned_user),  # resolve single assigned user
            ]
        )
        mock_db.commit = AsyncMock()

        with patch("app.services.nudges.nudge_delivery.outbound_delivery_service") as mock_outbound:
            mock_outbound.deliver = AsyncMock(return_value=_delivery_result(True))

            result = await delivery.deliver_nudge(mock_db, nudge)

        assert result is True
        mock_outbound.deliver.assert_awaited_once()
        # The single push went out scoped to the assigned user.
        request = mock_outbound.deliver.await_args.args[1]
        assert request.channel == OutboundDeliveryChannel.PUSH
        assert request.user_id == 99
        assert nudge.status == "sent"
