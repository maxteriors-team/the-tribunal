"""Regression tests for contact-scoped AI assignment on text/iMessage threads."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from app.api.webhooks.mac_relay_handlers import _normalize_relay_address
from app.core.encryption import hash_phone
from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.user import User
from app.services.contacts.ai_state_service import sender_address_for_phone
from app.services.telephony import inbound_text
from app.services.telephony.inbound_text import (
    _resolve_default_agent_id,
    _resolve_existing_contact_agent_id,
    check_operator_by_phone,
)
from tests.factories import PhoneNumberFactory

ensure_default_agent_original = inbound_text.ensure_default_agent


class _ScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None


class _ExecuteResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _ScalarResult:
        return _ScalarResult(self._rows)


def test_imessage_sender_address_prefers_relay_alias() -> None:
    phone_number = PhoneNumberFactory.build(
        phone_number="+15551234567",
        imessage_enabled=True,
        mac_relay_sender_id="owner@example.com",
    )

    assert sender_address_for_phone(phone_number) == "owner@example.com"


def test_non_imessage_sender_address_uses_phone_number() -> None:
    phone_number = PhoneNumberFactory.build(
        phone_number="+15551234567",
        imessage_enabled=False,
        mac_relay_sender_id="owner@example.com",
    )

    assert sender_address_for_phone(phone_number) == "+15551234567"


def test_mac_relay_address_normalization_preserves_apple_id_email() -> None:
    assert _normalize_relay_address(" Owner@Example.COM ") == "owner@example.com"


async def test_contact_assignment_reuses_text_threads_only() -> None:
    workspace_id = uuid.uuid4()
    contact_id = 123
    voice_agent_id = uuid.uuid4()
    text_agent_id = uuid.uuid4()
    voice_conversation = Conversation(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        contact_id=contact_id,
        workspace_phone="+15550000001",
        contact_phone="+15550000002",
        channel="voice",
        assigned_agent_id=voice_agent_id,
    )
    text_conversation = Conversation(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        contact_id=contact_id,
        workspace_phone="+15550000001",
        contact_phone="+15550000002",
        channel="imessage",
        assigned_agent_id=text_agent_id,
    )

    db = MagicMock()

    async def execute(_statement: object) -> _ExecuteResult:
        ordered_rows = [voice_conversation.assigned_agent_id, text_conversation.assigned_agent_id]
        matching_rows = [
            conversation.assigned_agent_id
            for conversation in [voice_conversation, text_conversation]
            if conversation.channel in ("sms", "imessage")
            and conversation.assigned_agent_id is not None
        ]
        assert matching_rows != ordered_rows
        return _ExecuteResult(matching_rows)

    db.execute = AsyncMock(side_effect=execute)

    result = await _resolve_existing_contact_agent_id(db, workspace_id, contact_id)

    assert result == text_agent_id


async def test_resolve_default_agent_prefers_explicit_phone_number_agent() -> None:
    workspace_id = uuid.uuid4()
    explicit_agent_id = uuid.uuid4()
    db = MagicMock()

    async def execute(_statement: object) -> _ExecuteResult:
        return _ExecuteResult([explicit_agent_id])

    db.execute = AsyncMock(side_effect=execute)
    fallback = AsyncMock()
    inbound_text.ensure_default_agent = fallback  # type: ignore[assignment]
    try:
        result = await _resolve_default_agent_id(db, workspace_id, "+15550000001")
    finally:
        inbound_text.ensure_default_agent = ensure_default_agent_original

    assert result == explicit_agent_id
    fallback.assert_not_awaited()


async def test_resolve_default_agent_falls_back_to_workspace_default() -> None:
    workspace_id = uuid.uuid4()
    default_agent_id = uuid.uuid4()
    db = MagicMock()

    async def execute(_statement: object) -> _ExecuteResult:
        return _ExecuteResult([])

    db.execute = AsyncMock(side_effect=execute)
    default_agent = Agent(id=default_agent_id, workspace_id=workspace_id)
    fallback = AsyncMock(return_value=default_agent)
    inbound_text.ensure_default_agent = fallback  # type: ignore[assignment]
    try:
        result = await _resolve_default_agent_id(db, workspace_id, "+15550000001")
    finally:
        inbound_text.ensure_default_agent = ensure_default_agent_original

    assert result == default_agent_id
    assert result is not None
    fallback.assert_awaited_once_with(db, workspace_id)


async def test_operator_lookup_uses_phone_hash_variants() -> None:
    workspace_id = uuid.uuid4()
    user = User(
        id=7,
        email="operator@example.com",
        email_hash="unused",
        hashed_password="hash",
        phone_number="555-123-4567",
        phone_hash=hash_phone("5551234567"),
        is_active=True,
    )
    db = MagicMock()

    async def execute(_statement: object) -> _ExecuteResult:
        return _ExecuteResult([user])

    db.execute = AsyncMock(side_effect=execute)

    result = await check_operator_by_phone(db, "+15551234567", workspace_id)

    assert result is user
    db.execute.assert_awaited_once()
