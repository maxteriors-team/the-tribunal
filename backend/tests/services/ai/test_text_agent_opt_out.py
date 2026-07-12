"""Tests for AI-confirmed SMS opt-out recording in the text agent.

When the AI classifier confirms a genuine STOP request, disabling AI on the one
conversation is not enough: a non-campaign lead must also land on the workspace
global opt-out list so campaigns, drips, reminders and the iMessage relay all
suppress future sends. These tests pin that behavior and its idempotency.
"""

from __future__ import annotations

import types
import uuid
from unittest.mock import AsyncMock

import pytest

from app.services.ai import text_agent
from app.services.ai.text_agent import _record_ai_confirmed_opt_out


class _Log:
    def bind(self, **_: object) -> _Log:
        return self

    def info(self, *_: object, **__: object) -> None:
        pass

    def warning(self, *_: object, **__: object) -> None:
        pass


class _FakeDB:
    """Minimal AsyncSession stand-in: resolves a contact and records commits."""

    def __init__(self, contact: object | None) -> None:
        self._contact = contact
        self.get = AsyncMock(return_value=contact)
        self.commit = AsyncMock()


def _conversation(contact_id: int | None) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        contact_id=contact_id,
        contact_phone="+15125559003",
        ai_enabled=True,
    )


def _inbound(body: str = "STOP") -> types.SimpleNamespace:
    return types.SimpleNamespace(id=uuid.uuid4(), body=body)


@pytest.fixture
def _patched_manager(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Replace the module opt-out manager; default: records a fresh opt-out."""
    add_opt_out = AsyncMock(return_value=object())
    manager = types.SimpleNamespace(add_opt_out=add_opt_out)
    monkeypatch.setattr(text_agent, "_opt_out_manager", manager)
    return add_opt_out


async def test_records_global_opt_out_and_disables_ai(
    _patched_manager: AsyncMock,
) -> None:
    contact = types.SimpleNamespace(
        sms_consent_status="unknown",
        sms_consent_source=None,
        sms_consent_collected_at=None,
        sms_consent_notes=None,
    )
    conversation = _conversation(contact_id=42)
    db = _FakeDB(contact)
    inbound = _inbound("STOP")

    await _record_ai_confirmed_opt_out(
        db=db,
        conversation=conversation,
        inbound_message=inbound,
        log=_Log(),
    )

    # AI is disabled on the thread.
    assert conversation.ai_enabled is False

    # A global opt-out was recorded for the workspace + contact phone.
    _patched_manager.assert_awaited_once()
    kwargs = _patched_manager.await_args.kwargs
    assert kwargs["workspace_id"] == conversation.workspace_id
    assert kwargs["phone_number"] == conversation.contact_phone
    assert kwargs["source_message_id"] == inbound.id
    assert kwargs["keyword"] == "STOP"

    # Contact consent is stamped for the compliance record.
    assert contact.sms_consent_status == "opted_out"
    assert contact.sms_consent_source == "sms_reply"
    assert contact.sms_consent_collected_at is not None
    assert "STOP" in contact.sms_consent_notes


async def test_idempotent_commit_when_already_opted_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # add_opt_out returns None when the number is already on the list and skips
    # its own commit, so the helper must commit the ai_enabled/consent changes.
    add_opt_out = AsyncMock(return_value=None)
    monkeypatch.setattr(
        text_agent, "_opt_out_manager", types.SimpleNamespace(add_opt_out=add_opt_out)
    )
    conversation = _conversation(contact_id=None)
    db = _FakeDB(None)

    await _record_ai_confirmed_opt_out(
        db=db,
        conversation=conversation,
        inbound_message=_inbound("stop texting me"),
        log=_Log(),
    )

    assert conversation.ai_enabled is False
    add_opt_out.assert_awaited_once()
    db.commit.assert_awaited_once()


async def test_no_contact_skips_consent_lookup(
    _patched_manager: AsyncMock,
) -> None:
    conversation = _conversation(contact_id=None)
    db = _FakeDB(None)

    await _record_ai_confirmed_opt_out(
        db=db,
        conversation=conversation,
        inbound_message=_inbound(),
        log=_Log(),
    )

    # No contact_id -> never resolve a contact, but still record the opt-out.
    db.get.assert_not_called()
    _patched_manager.assert_awaited_once()
