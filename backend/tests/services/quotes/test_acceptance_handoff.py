"""Accepting a quote over text hands off to a human — it never books a call.

Regression for a live incident. A customer approved a lighting proposal by SMS
("James this is approved, thanks so much!") and the AI agent, whose prompt is a
booking funnel with no quote awareness, replied by offering discovery-call slots
and booking one for work the customer had already bought. The operator had to
apologise and walk it back by hand.

The rule pinned here: an accepted quote pauses the AI, acknowledges without
naming a time, and pages a human to schedule the install once materials are in.
"""

from __future__ import annotations

import types
import uuid
from unittest.mock import AsyncMock

import pytest

from app.services.ai import text_agent
from app.services.quotes import acceptance_handoff
from app.services.quotes.acceptance_detector import has_potential_acceptance_keywords
from app.services.quotes.acceptance_handoff import (
    build_acknowledgement,
    hand_off_accepted_quote,
    summarize_materials,
)


class _Log:
    def bind(self, **_: object) -> _Log:
        return self

    def info(self, *_: object, **__: object) -> None:
        pass

    def warning(self, *_: object, **__: object) -> None:
        pass


class _FakeDB:
    def __init__(self, contact: object | None = None) -> None:
        self.get = AsyncMock(return_value=contact)
        self.commit = AsyncMock()


def _conversation() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        contact_id=7,
        contact_phone="+15125559003",
        workspace_phone="+15125550000",
        channel="sms",
        ai_enabled=True,
        ai_paused=False,
        ai_paused_until=None,
    )


def _contact(first_name: str = "Greg") -> types.SimpleNamespace:
    return types.SimpleNamespace(id=7, first_name=first_name, full_name=f"{first_name} Nolan")


def _quote(**overrides: object) -> types.SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "number": "Q-1042",
        "status": "sent",
        "proposal_document": {
            "fulfillment": [
                {"sku": "LED-WW-25", "qty": 12, "description": "Warm white bulbs"},
                {"sku": "CLIP-RG", "qty": 200, "description": "Ridge clips"},
            ]
        },
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


@pytest.fixture
def _sender(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Capture the outbound acknowledgement instead of texting a real customer."""
    send_message = AsyncMock()
    service = types.SimpleNamespace(send_message=send_message, close=AsyncMock())
    monkeypatch.setattr(
        "app.services.telephony.text_provider.get_text_message_provider",
        lambda *_a, **_k: service,
    )
    return send_message


@pytest.fixture
def _notifier(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    notify = AsyncMock()
    monkeypatch.setattr(acceptance_handoff, "notify_workspace_event", notify)
    return notify


# ── The acknowledgement itself ──────────────────────────────────────


def test_acknowledgement_never_offers_or_confirms_a_time() -> None:
    """The whole bug was a time appearing here. It must not come back."""
    body = build_acknowledgement(_contact())
    lowered = body.lower()
    for banned in ("am", "pm", "monday", "tuesday", "thursday", "friday", "which works"):
        assert f" {banned}" not in f" {lowered}", f"acknowledgement offered a time: {banned}"
    assert "discovery call" not in lowered
    assert "booked" not in lowered
    assert "confirmed for" not in lowered


def test_acknowledgement_promises_scheduling_once_materials_are_in() -> None:
    body = build_acknowledgement(_contact())
    assert "materials" in body.lower()
    assert "Greg" in body


def test_acknowledgement_handles_a_contact_with_no_first_name() -> None:
    assert "there" in build_acknowledgement(_contact(first_name=""))


# ── The handoff ─────────────────────────────────────────────────────


async def test_handoff_pauses_the_ai(_sender: AsyncMock, _notifier: AsyncMock) -> None:
    conversation = _conversation()
    db = _FakeDB()

    await hand_off_accepted_quote(
        db,
        conversation=conversation,
        contact=_contact(),
        quote=_quote(),
        agent_id=uuid.uuid4(),
        log=_Log(),
    )

    assert conversation.ai_paused is True
    assert conversation.ai_paused_until is None
    db.commit.assert_awaited()


async def test_handoff_texts_the_customer_once(_sender: AsyncMock, _notifier: AsyncMock) -> None:
    conversation = _conversation()

    await hand_off_accepted_quote(
        _FakeDB(),
        conversation=conversation,
        contact=_contact(),
        quote=_quote(),
        agent_id=uuid.uuid4(),
        log=_Log(),
    )

    _sender.assert_awaited_once()
    assert "materials" in _sender.await_args.kwargs["body"].lower()


async def test_handoff_pages_operators_with_the_parts_list(
    _sender: AsyncMock, _notifier: AsyncMock
) -> None:
    quote = _quote()

    await hand_off_accepted_quote(
        _FakeDB(),
        conversation=_conversation(),
        contact=_contact(),
        quote=quote,
        agent_id=uuid.uuid4(),
        log=_Log(),
    )

    kwargs = _notifier.await_args.kwargs
    assert quote.number in kwargs["title"]
    assert kwargs["email_details"] == {
        "LED-WW-25": "Qty 12 — Warm white bulbs",
        "CLIP-RG": "Qty 200 — Ridge clips",
    }
    assert kwargs["dedupe_key"] == f"quote_accepted_via_text:{quote.id}"


async def test_a_failed_text_still_pauses_the_ai(
    monkeypatch: pytest.MonkeyPatch, _notifier: AsyncMock
) -> None:
    """An agent that keeps selling into a closed deal is the worse failure."""
    service = types.SimpleNamespace(
        send_message=AsyncMock(side_effect=RuntimeError("carrier down")),
        close=AsyncMock(),
    )
    monkeypatch.setattr(
        "app.services.telephony.text_provider.get_text_message_provider",
        lambda *_a, **_k: service,
    )
    conversation = _conversation()

    await hand_off_accepted_quote(
        _FakeDB(),
        conversation=conversation,
        contact=_contact(),
        quote=_quote(),
        agent_id=uuid.uuid4(),
        log=_Log(),
    )

    assert conversation.ai_paused is True


async def test_a_failed_notification_still_leaves_the_ai_paused(
    monkeypatch: pytest.MonkeyPatch, _sender: AsyncMock
) -> None:
    monkeypatch.setattr(
        acceptance_handoff,
        "notify_workspace_event",
        AsyncMock(side_effect=RuntimeError("push down")),
    )
    conversation = _conversation()

    await hand_off_accepted_quote(
        _FakeDB(),
        conversation=conversation,
        contact=_contact(),
        quote=_quote(),
        agent_id=uuid.uuid4(),
        log=_Log(),
    )

    assert conversation.ai_paused is True


def test_a_quote_with_no_parts_summarizes_empty() -> None:
    assert summarize_materials(_quote(proposal_document={})) == {}
    assert summarize_materials(_quote(proposal_document=None)) == {}
    assert summarize_materials(_quote(proposal_document={"fulfillment": [{"sku": "  "}]})) == {}


# ── The pipeline gate ───────────────────────────────────────────────


async def test_greg_reply_is_intercepted_and_never_reaches_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end on the exact message that caused the incident."""
    conversation = _conversation()
    quote = _quote()
    handoff = AsyncMock()

    monkeypatch.setattr(text_agent, "find_outstanding_quote", AsyncMock(return_value=quote))
    monkeypatch.setattr(text_agent, "classify_quote_acceptance", AsyncMock(return_value=True))
    monkeypatch.setattr(text_agent, "build_message_context", AsyncMock(return_value=[]))
    monkeypatch.setattr(text_agent, "hand_off_accepted_quote", handoff)

    handled = await text_agent._handle_quote_acceptance(
        db=_FakeDB(_contact()),
        conversation=conversation,
        agent=types.SimpleNamespace(id=uuid.uuid4()),
        inbound_message=types.SimpleNamespace(body="James this is approved, thanks so much!"),
        credential=None,
        log=_Log(),
    )

    assert handled is True
    handoff.assert_awaited_once()


async def test_no_outstanding_quote_falls_through_to_the_normal_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(text_agent, "find_outstanding_quote", AsyncMock(return_value=None))
    classify = AsyncMock(return_value=True)
    monkeypatch.setattr(text_agent, "classify_quote_acceptance", classify)

    handled = await text_agent._handle_quote_acceptance(
        db=_FakeDB(_contact()),
        conversation=_conversation(),
        agent=types.SimpleNamespace(id=uuid.uuid4()),
        inbound_message=types.SimpleNamespace(body="sounds good"),
        credential=None,
        log=_Log(),
    )

    assert handled is False
    classify.assert_not_awaited()  # no quote => never pay for the classifier


async def test_classifier_saying_no_falls_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "Yes, that's my email" must still get a normal reply."""
    monkeypatch.setattr(text_agent, "find_outstanding_quote", AsyncMock(return_value=_quote()))
    monkeypatch.setattr(text_agent, "classify_quote_acceptance", AsyncMock(return_value=False))
    monkeypatch.setattr(text_agent, "build_message_context", AsyncMock(return_value=[]))
    handoff = AsyncMock()
    monkeypatch.setattr(text_agent, "hand_off_accepted_quote", handoff)

    handled = await text_agent._handle_quote_acceptance(
        db=_FakeDB(_contact()),
        conversation=_conversation(),
        agent=types.SimpleNamespace(id=uuid.uuid4()),
        inbound_message=types.SimpleNamespace(body="yes, that's my email"),
        credential=None,
        log=_Log(),
    )

    assert handled is False
    handoff.assert_not_awaited()


async def test_an_intercept_failure_never_leaves_the_lead_on_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        text_agent,
        "find_outstanding_quote",
        AsyncMock(side_effect=RuntimeError("db blip")),
    )

    handled = await text_agent._handle_quote_acceptance(
        db=_FakeDB(_contact()),
        conversation=_conversation(),
        agent=types.SimpleNamespace(id=uuid.uuid4()),
        inbound_message=types.SimpleNamespace(body="approved!"),
        credential=None,
        log=_Log(),
    )

    assert handled is False  # falls through to the normal reply


# ── The cheap pre-filter ────────────────────────────────────────────


@pytest.mark.parametrize(
    "message",
    [
        "James this is approved, thanks so much!",
        "Looks good, let's do it",
        "approved",
        "We're good to go",
        "Go ahead and get us on the schedule",
        "Yes",
    ],
)
def test_prefilter_catches_acceptance_phrasings(message: str) -> None:
    assert has_potential_acceptance_keywords(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "What's the warranty on the bulbs?",
        "Can you send that again? The link is broken",
        "Next week I'll be out of commission for our family reunion",
        "greg@example.net",
        "",
    ],
)
def test_prefilter_ignores_everything_else(message: str) -> None:
    assert has_potential_acceptance_keywords(message) is False
