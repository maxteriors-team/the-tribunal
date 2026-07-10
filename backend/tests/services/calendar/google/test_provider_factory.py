"""Tests for get_calendar_provider selection between Google and Cal.com."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.services.calendar import factory as factory_module
from app.services.calendar.calcom import CalComCalendarProvider
from app.services.calendar.google.provider import GoogleCalendarProvider


@pytest.mark.asyncio
async def test_falls_back_to_calcom_when_google_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(factory_module, "google_oauth_configured", lambda: False)
    provider = await factory_module.get_calendar_provider(
        event_type_id=555,
        workspace_id=uuid.uuid4(),
    )
    assert isinstance(provider, CalComCalendarProvider)
    await provider.close()


@pytest.mark.asyncio
async def test_falls_back_to_calcom_when_no_connection(monkeypatch) -> None:
    monkeypatch.setattr(factory_module, "google_oauth_configured", lambda: True)

    async def _no_id(_db, _ws):
        return None

    monkeypatch.setattr(factory_module, "_google_calendar_id", _no_id)
    provider = await factory_module.get_calendar_provider(
        event_type_id=555,
        workspace_id=uuid.uuid4(),
    )
    assert isinstance(provider, CalComCalendarProvider)
    await provider.close()


@pytest.mark.asyncio
async def test_selects_google_when_connection_present(monkeypatch) -> None:
    monkeypatch.setattr(factory_module, "google_oauth_configured", lambda: True)

    async def _has_id(_db, _ws):
        return "primary"

    monkeypatch.setattr(factory_module, "_google_calendar_id", _has_id)
    monkeypatch.setattr(factory_module, "make_token_provider", lambda _ws: (lambda: None))

    agent = SimpleNamespace(schedule_config={"timezone": "America/Chicago"})
    provider = await factory_module.get_calendar_provider(
        event_type_id=555,
        agent=agent,
        workspace_id=uuid.uuid4(),
    )
    assert isinstance(provider, GoogleCalendarProvider)
    await provider.close()
