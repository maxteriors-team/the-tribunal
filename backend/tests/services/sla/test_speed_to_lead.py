"""Unit tests for the speed-to-lead SLA service.

The repo's service tests mock the DB session, so these exercise the pure
first-response maths plus the alert/metrics helpers with fabricated rows.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.sla import speed_to_lead as stl


def _workspace(settings: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), settings=settings or {})


def _conversation(**kwargs) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "first_inbound_at": None,
        "first_response_at": None,
        "first_response_seconds": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


class TestSettings:
    def test_defaults_when_unset(self) -> None:
        config = stl.get_speed_to_lead_settings(_workspace())
        assert config.enabled is True
        assert config.sla_seconds == stl.DEFAULT_SLA_SECONDS
        assert config.alert_enabled is True
        assert config.badge_enabled is False
        assert config.badge_window_days == stl.DEFAULT_BADGE_WINDOW_DAYS

    def test_reads_overrides(self) -> None:
        ws = _workspace(
            {
                stl.SETTINGS_KEY: {
                    "enabled": False,
                    "sla_seconds": 30,
                    "alert_enabled": False,
                    "badge_enabled": True,
                    "badge_window_days": 7,
                }
            }
        )
        config = stl.get_speed_to_lead_settings(ws)
        assert config.enabled is False
        assert config.sla_seconds == 30
        assert config.alert_enabled is False
        assert config.badge_enabled is True
        assert config.badge_window_days == 7

    def test_clamps_out_of_range_values(self) -> None:
        ws = _workspace({stl.SETTINGS_KEY: {"sla_seconds": 999999, "badge_window_days": 99999}})
        config = stl.get_speed_to_lead_settings(ws)
        assert config.sla_seconds == 3600
        assert config.badge_window_days == 365

    def test_invalid_types_fall_back_to_defaults(self) -> None:
        ws = _workspace({stl.SETTINGS_KEY: {"sla_seconds": "fast"}})
        config = stl.get_speed_to_lead_settings(ws)
        assert config.sla_seconds == stl.DEFAULT_SLA_SECONDS

    def test_non_dict_settings_block_is_ignored(self) -> None:
        ws = _workspace({stl.SETTINGS_KEY: "nope"})
        config = stl.get_speed_to_lead_settings(ws)
        assert config.sla_seconds == stl.DEFAULT_SLA_SECONDS


class TestMarkInboundLead:
    def test_sets_first_inbound_when_unset(self) -> None:
        conv = _conversation()
        at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        stl.mark_inbound_lead(conv, at)
        assert conv.first_inbound_at == at

    def test_is_idempotent(self) -> None:
        first = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        conv = _conversation(first_inbound_at=first)
        stl.mark_inbound_lead(conv, datetime(2026, 1, 1, 13, 0, tzinfo=UTC))
        assert conv.first_inbound_at == first


class TestRecordFirstResponse:
    def test_records_delta_seconds(self) -> None:
        anchor = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        conv = _conversation(first_inbound_at=anchor)
        seconds = stl.record_first_response(conv, anchor + timedelta(seconds=42))
        assert seconds == 42
        assert conv.first_response_seconds == 42
        assert conv.first_response_at == anchor + timedelta(seconds=42)

    def test_no_anchor_returns_none(self) -> None:
        conv = _conversation()
        assert stl.record_first_response(conv, datetime.now(UTC)) is None
        assert conv.first_response_at is None

    def test_already_responded_returns_none(self) -> None:
        anchor = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        responded = datetime(2026, 1, 1, 12, 1, tzinfo=UTC)
        conv = _conversation(first_inbound_at=anchor, first_response_at=responded)
        assert stl.record_first_response(conv, datetime.now(UTC)) is None
        assert conv.first_response_at == responded

    def test_negative_delta_is_clamped_to_zero(self) -> None:
        anchor = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        conv = _conversation(first_inbound_at=anchor)
        seconds = stl.record_first_response(conv, anchor - timedelta(seconds=5))
        assert seconds == 0

    def test_naive_anchor_is_treated_as_utc(self) -> None:
        naive_anchor = datetime(2026, 1, 1, 12, 0, 0)  # noqa: DTZ001
        conv = _conversation(first_inbound_at=naive_anchor)
        seconds = stl.record_first_response(
            conv, datetime(2026, 1, 1, 12, 0, 10, tzinfo=UTC)
        )
        assert seconds == 10


@pytest.mark.asyncio
class TestRecordAndAlert:
    async def test_no_response_skips_alert(self) -> None:
        conv = _conversation()  # no inbound anchor
        db = MagicMock()
        db.get = AsyncMock()
        log = MagicMock()
        result = await stl.record_first_response_and_maybe_alert(db, conv, datetime.now(UTC), log)
        assert result is None
        db.get.assert_not_awaited()

    async def test_within_sla_does_not_alert(self, monkeypatch: pytest.MonkeyPatch) -> None:
        anchor = datetime.now(UTC) - timedelta(seconds=10)
        conv = _conversation(first_inbound_at=anchor)
        db = MagicMock()
        db.get = AsyncMock(return_value=_workspace({stl.SETTINGS_KEY: {"sla_seconds": 60}}))

        push = AsyncMock()
        monkeypatch.setattr(
            "app.services.push_notifications.push_notification_service",
            SimpleNamespace(send_to_workspace_members=push),
        )
        seconds = await stl.record_first_response_and_maybe_alert(
            db, conv, datetime.now(UTC), MagicMock()
        )
        assert seconds is not None and seconds <= 60
        push.assert_not_awaited()

    async def test_breach_triggers_alert(self, monkeypatch: pytest.MonkeyPatch) -> None:
        anchor = datetime.now(UTC) - timedelta(seconds=120)
        conv = _conversation(first_inbound_at=anchor)
        db = MagicMock()
        db.get = AsyncMock(
            return_value=_workspace(
                {stl.SETTINGS_KEY: {"sla_seconds": 60, "alert_enabled": True}}
            )
        )

        push = AsyncMock()
        monkeypatch.setattr(
            "app.services.push_notifications.push_notification_service",
            SimpleNamespace(send_to_workspace_members=push),
        )
        seconds = await stl.record_first_response_and_maybe_alert(
            db, conv, datetime.now(UTC), MagicMock()
        )
        assert seconds is not None and seconds > 60
        push.assert_awaited_once()

    async def test_breach_with_alerts_disabled_is_silent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        anchor = datetime.now(UTC) - timedelta(seconds=120)
        conv = _conversation(first_inbound_at=anchor)
        db = MagicMock()
        db.get = AsyncMock(
            return_value=_workspace(
                {stl.SETTINGS_KEY: {"sla_seconds": 60, "alert_enabled": False}}
            )
        )
        push = AsyncMock()
        monkeypatch.setattr(
            "app.services.push_notifications.push_notification_service",
            SimpleNamespace(send_to_workspace_members=push),
        )
        await stl.record_first_response_and_maybe_alert(db, conv, datetime.now(UTC), MagicMock())
        push.assert_not_awaited()

    async def test_alert_failure_is_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        anchor = datetime.now(UTC) - timedelta(seconds=120)
        conv = _conversation(first_inbound_at=anchor)
        db = MagicMock()
        db.get = AsyncMock(return_value=_workspace({stl.SETTINGS_KEY: {"sla_seconds": 60}}))
        push = AsyncMock(side_effect=RuntimeError("boom"))
        monkeypatch.setattr(
            "app.services.push_notifications.push_notification_service",
            SimpleNamespace(send_to_workspace_members=push),
        )
        log = MagicMock()
        seconds = await stl.record_first_response_and_maybe_alert(db, conv, datetime.now(UTC), log)
        assert seconds is not None
        log.warning.assert_called()


@pytest.mark.asyncio
class TestComputeMetrics:
    async def test_aggregates_row(self) -> None:
        db = MagicMock()
        one = MagicMock(return_value=(10, 9, 14.2, 12.0, 3))
        db.execute = AsyncMock(return_value=MagicMock(one=one))
        metrics = await stl.compute_sla_metrics(
            db, uuid.uuid4(), sla_seconds=60, window_days=30
        )
        assert metrics.leads_measured == 10
        assert metrics.within_sla == 9
        assert metrics.pct_within_sla == 90.0
        assert metrics.avg_response_seconds == 14
        assert metrics.median_response_seconds == 12
        assert metrics.fastest_response_seconds == 3

    async def test_empty_window_is_null_safe(self) -> None:
        db = MagicMock()
        one = MagicMock(return_value=(0, 0, None, None, None))
        db.execute = AsyncMock(return_value=MagicMock(one=one))
        metrics = await stl.compute_sla_metrics(db, uuid.uuid4(), sla_seconds=60)
        assert metrics.leads_measured == 0
        assert metrics.pct_within_sla is None
        assert metrics.avg_response_seconds is None
