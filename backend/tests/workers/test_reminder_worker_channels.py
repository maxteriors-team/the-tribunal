"""Reminder channel selection and per-channel dedupe.

The dedupe columns are the whole point: an SMS reminder firing at an offset must
not suppress the email reminder at that same offset, and neither may fire twice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.workers.reminder_worker import (
    _AGENTLESS_DEFAULT_OFFSETS,
    ReminderWorker,
    _agentless_offsets,
    _channels_for,
)

NOW = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)


def _agent(**overrides):
    fields = {
        "id": 1,
        "reminder_enabled": True,
        "reminder_offsets": [60],
        "reminder_channels": ["sms"],
        "reminder_template": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _workspace(**overrides):
    fields = {"id": 7, "name": "Sparkle Exteriors", "settings": {"timezone": "America/New_York"}}
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _appointment(agent=None, workspace=None, **overrides):
    fields = {
        "id": 42,
        "agent": agent,
        "workspace": workspace or _workspace(),
        "contact": SimpleNamespace(
            id=3, email="dana@example.com", full_name="Dana Reyes", first_name="Dana"
        ),
        "scheduled_at": NOW + timedelta(minutes=30),
        "created_at": NOW - timedelta(days=1),
        "reminders_sent": [],
        "reminders_sent_email": [],
        "reminder_sent_at": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


class TestChannelSelection:
    def test_defaults_to_sms(self) -> None:
        assert _channels_for(None) == ("sms",)
        assert _channels_for(_agent(reminder_channels=[])) == ("sms",)

    def test_honours_both_channels(self) -> None:
        assert _channels_for(_agent(reminder_channels=["sms", "email"])) == ("sms", "email")

    def test_drops_unknown_channels_rather_than_dispatching_them(self) -> None:
        assert _channels_for(_agent(reminder_channels=["carrier_pigeon", "email"])) == ("email",)
        assert _channels_for(_agent(reminder_channels=["carrier_pigeon"])) == ("sms",)


class TestAgentlessOffsets:
    def test_falls_back_when_workspace_has_no_preference(self) -> None:
        assert _agentless_offsets(_workspace()) == _AGENTLESS_DEFAULT_OFFSETS
        assert _agentless_offsets(None) == _AGENTLESS_DEFAULT_OFFSETS

    def test_reads_the_workspace_default(self) -> None:
        ws = _workspace(settings={"reminder_defaults": {"offsets": [1440, 120]}})
        assert _agentless_offsets(ws) == [1440, 120]

    @pytest.mark.parametrize(
        "blob",
        [
            {"reminder_defaults": {"offsets": "1440"}},
            {"reminder_defaults": {"offsets": [0, -5, "x"]}},
            {"reminder_defaults": []},
        ],
    )
    def test_ignores_unusable_configuration(self, blob) -> None:
        assert _agentless_offsets(_workspace(settings=blob)) == _AGENTLESS_DEFAULT_OFFSETS


class TestDueCollection:
    def _due(self, appt):
        return ReminderWorker()._collect_due_reminders([appt], NOW)

    def test_sms_only_agent_yields_one_send(self) -> None:
        appt = _appointment(_agent())
        assert self._due(appt) == [(appt, 60, "sms")]

    def test_both_channels_yield_one_send_each(self) -> None:
        appt = _appointment(_agent(reminder_channels=["sms", "email"]))
        assert self._due(appt) == [(appt, 60, "sms"), (appt, 60, "email")]

    def test_sent_sms_does_not_suppress_the_email(self) -> None:
        appt = _appointment(
            _agent(reminder_channels=["sms", "email"]),
            reminders_sent=[60],
        )
        assert self._due(appt) == [(appt, 60, "email")]

    def test_sent_email_does_not_suppress_the_sms(self) -> None:
        appt = _appointment(
            _agent(reminder_channels=["sms", "email"]),
            reminders_sent_email=[60],
        )
        assert self._due(appt) == [(appt, 60, "sms")]

    def test_nothing_re_fires_once_both_channels_are_recorded(self) -> None:
        appt = _appointment(
            _agent(reminder_channels=["sms", "email"]),
            reminders_sent=[60],
            reminders_sent_email=[60],
        )
        assert self._due(appt) == []

    def test_disabled_reminders_yield_nothing(self) -> None:
        appt = _appointment(_agent(reminder_enabled=False, reminder_channels=["sms", "email"]))
        assert self._due(appt) == []

    def test_touchpoint_older_than_the_booking_is_skipped(self) -> None:
        """A booking made 10 minutes ago must not "remind" about itself."""
        appt = _appointment(_agent(), created_at=NOW - timedelta(minutes=10))
        assert self._due(appt) == []

    def test_agentless_appointment_uses_the_workspace_default(self) -> None:
        ws = _workspace(settings={"reminder_defaults": {"offsets": [30]}})
        appt = _appointment(None, workspace=ws)
        assert self._due(appt) == [(appt, 30, "sms")]


@pytest.mark.asyncio
class TestEmailSend:
    async def test_records_the_offset_against_the_email_column(self, monkeypatch) -> None:
        sent = AsyncMock(return_value=True)
        monkeypatch.setattr("app.workers.reminder_worker.send_appointment_reminder_email", sent)
        worker = ReminderWorker()
        appt = _appointment(_agent(reminder_channels=["email"]))
        db = AsyncMock()

        await worker._send_reminder_email(appt, 60, db)

        assert sent.await_count == 1
        assert sent.await_args.kwargs["to_email"] == "dana@example.com"
        assert appt.reminders_sent_email == [60]
        # The SMS column is untouched, so an SMS reminder can still fire.
        assert appt.reminders_sent == []

    async def test_provider_rejection_leaves_the_offset_unsent_for_retry(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "app.workers.reminder_worker.send_appointment_reminder_email",
            AsyncMock(return_value=False),
        )
        worker = ReminderWorker()
        appt = _appointment(_agent(reminder_channels=["email"]))

        await worker._send_reminder_email(appt, 60, AsyncMock())

        assert appt.reminders_sent_email == []

    async def test_contact_without_an_email_is_marked_not_retried(self, monkeypatch) -> None:
        sent = AsyncMock(return_value=True)
        monkeypatch.setattr("app.workers.reminder_worker.send_appointment_reminder_email", sent)
        worker = ReminderWorker()
        appt = _appointment(_agent(reminder_channels=["email"]))
        appt.contact.email = None

        await worker._send_reminder_email(appt, 60, AsyncMock())

        assert sent.await_count == 0
        assert appt.reminders_sent_email == [60]
