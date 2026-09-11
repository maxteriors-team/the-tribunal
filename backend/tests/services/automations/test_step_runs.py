"""The per-step ledger, and the suppression rule it exists to make possible.

``unsold_quote_worker`` stops a sequence when the customer has replied since the
last touch. That rule needs two things the engine did not have: a record of when
each touch actually went out, and a way to ask a question about the *run* rather
than about a record.

These tests pin both, plus the distinction that makes the rule correct rather
than merely present — a step that declined to send is not a touch, so it must
not move the last-touch clock and silence the next real message.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.automation import Automation
from app.models.automation_execution import AutomationExecution
from app.models.automation_step_run import (
    OUTCOME_SENT,
    OUTCOME_SKIPPED,
)
from app.models.contact import Contact
from app.models.conversation import (
    Conversation,
    Message,
    MessageChannel,
    MessageDirection,
    MessageStatus,
)
from app.models.workspace import Workspace
from app.services.automations.branching import (
    run_rules_match,
    split_run_scoped_rules,
)
from app.services.automations.step_runs import (
    DEFAULT_FRESH_REPLY_WINDOW_DAYS,
    last_touch_at,
    record_step_run,
    replied_since_last_touch,
    touch_count,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Each test owns its own connections; a pooled one belongs to a dead loop."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _fixture(db) -> tuple[Workspace, Contact, Automation, AutomationExecution]:
    ws = Workspace(
        id=uuid.uuid4(),
        name="Ledger",
        slug=f"ledger-{uuid.uuid4().hex[:8]}",
    )
    db.add(ws)
    await db.flush()

    phone = f"+1313555{uuid.uuid4().int % 10000:04d}"
    contact = Contact(
        workspace_id=ws.id,
        first_name="Robin",
        phone_number=phone,
        phone_hash=hash_phone(phone),
    )
    db.add(contact)
    await db.flush()

    automation = Automation(
        workspace_id=ws.id,
        name="Quote revival",
        trigger_type="quote_sent",
        trigger_config={},
        actions=[],
    )
    db.add(automation)
    await db.flush()

    execution = AutomationExecution(
        automation_id=automation.id,
        contact_id=contact.id,
        subject_type="contact",
        subject_id=str(contact.id),
        status="pending",
    )
    db.add(execution)
    await db.flush()
    return ws, contact, automation, execution


async def _inbound(db, *, workspace_id: uuid.UUID, contact: Contact, at: datetime) -> None:
    convo = Conversation(
        workspace_id=workspace_id,
        contact_id=contact.id,
        contact_phone_hash=hash_phone(contact.phone_number),
    )
    db.add(convo)
    await db.flush()
    msg = Message(
        conversation_id=convo.id,
        idempotency_key=uuid.uuid4(),
        direction=MessageDirection.INBOUND,
        channel=MessageChannel.SMS,
        status=MessageStatus.DELIVERED,
        is_ai=False,
        body="Sounds good, call me",
        created_at=at,
    )
    db.add(msg)
    await db.flush()


# --- The ledger itself --------------------------------------------------------


async def test_only_a_delivered_step_moves_the_last_touch_clock() -> None:
    """A skipped step is not a touch.

    If a message suppressed for consent counted as a touch, it would push the
    last-touch clock forward and suppress the *next* message too — a sequence
    silently muting itself.
    """
    async with AsyncSessionLocal() as db:
        ws, contact, automation, execution = await _fixture(db)

        assert await last_touch_at(db, execution.id) is None

        await record_step_run(
            db,
            workspace_id=ws.id,
            execution_id=execution.id,
            automation_id=automation.id,
            contact_id=contact.id,
            step_index=0,
            step_type="send_sms",
            outcome=OUTCOME_SKIPPED,
            reason="no_sms_consent",
        )
        await db.flush()
        assert await last_touch_at(db, execution.id) is None
        assert await touch_count(db, execution.id) == 0

        await record_step_run(
            db,
            workspace_id=ws.id,
            execution_id=execution.id,
            automation_id=automation.id,
            contact_id=contact.id,
            step_index=1,
            step_type="send_sms",
            outcome=OUTCOME_SENT,
        )
        await db.flush()
        assert await last_touch_at(db, execution.id) is not None
        assert await touch_count(db, execution.id) == 1

        await db.rollback()


async def test_a_revisited_step_appends_rather_than_overwrites() -> None:
    """A goto loop revisiting a step is evidence, not a duplicate to collapse."""
    async with AsyncSessionLocal() as db:
        ws, contact, automation, execution = await _fixture(db)

        for _ in range(3):
            await record_step_run(
                db,
                workspace_id=ws.id,
                execution_id=execution.id,
                automation_id=automation.id,
                contact_id=contact.id,
                step_index=2,
                step_type="send_sms",
                outcome=OUTCOME_SENT,
            )
        await db.flush()

        assert await touch_count(db, execution.id) == 3
        await db.rollback()


# --- The rule this was built for ---------------------------------------------


async def test_a_reply_after_our_last_touch_stops_the_sequence() -> None:
    """Stop reason 5, ported from `unsold_quote_worker`."""
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        ws, contact, automation, execution = await _fixture(db)

        await record_step_run(
            db,
            workspace_id=ws.id,
            execution_id=execution.id,
            automation_id=automation.id,
            contact_id=contact.id,
            step_index=0,
            step_type="send_sms",
            outcome=OUTCOME_SENT,
        )
        await db.flush()

        # Nothing inbound yet — the ladder may continue.
        assert not await replied_since_last_touch(
            db,
            workspace_id=ws.id,
            execution_id=execution.id,
            contact_id=contact.id,
            contact_phone=contact.phone_number,
            now=now,
        )

        await _inbound(db, workspace_id=ws.id, contact=contact, at=now + timedelta(minutes=5))

        # They answered our nudge. A human takes it from here.
        assert await replied_since_last_touch(
            db,
            workspace_id=ws.id,
            execution_id=execution.id,
            contact_id=contact.id,
            contact_phone=contact.phone_number,
            now=now,
        )

        await db.rollback()


async def test_old_history_before_the_first_touch_does_not_block() -> None:
    """The detail that makes the rule correct rather than merely present.

    With no touch recorded there is no clock to measure from, so the rule falls
    back to a short recent window. Without that, an old quote carrying months of
    unrelated conversation would look like a live one and never be revived.
    """
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        ws, contact, automation, execution = await _fixture(db)

        stale = now - timedelta(days=DEFAULT_FRESH_REPLY_WINDOW_DAYS + 60)
        await _inbound(db, workspace_id=ws.id, contact=contact, at=stale)

        assert not await replied_since_last_touch(
            db,
            workspace_id=ws.id,
            execution_id=execution.id,
            contact_id=contact.id,
            contact_phone=contact.phone_number,
            now=now,
        )

        # But a genuinely recent one does block, still with no touch recorded.
        await _inbound(
            db,
            workspace_id=ws.id,
            contact=contact,
            at=now - timedelta(days=2),
        )
        assert await replied_since_last_touch(
            db,
            workspace_id=ws.id,
            execution_id=execution.id,
            contact_id=contact.id,
            contact_phone=contact.phone_number,
            now=now,
        )

        await db.rollback()


# --- Wiring it into a branch condition ---------------------------------------


async def test_run_scoped_rules_are_split_from_record_rules() -> None:
    """A condition may mix both kinds; each half goes to the engine that knows it."""
    rules = [
        {"field": "status", "operator": "in", "value": ["sent"]},
        {"field": "replied_since_last_touch", "operator": "eq", "value": False},
    ]
    run_rules, subject_rules = split_run_scoped_rules(rules)
    assert [r["field"] for r in run_rules] == ["replied_since_last_touch"]
    assert [r["field"] for r in subject_rules] == ["status"]


async def test_a_branch_can_ask_whether_they_replied_since_our_last_touch() -> None:
    """The end-to-end shape a workflow definition would actually store."""
    now = datetime.now(UTC)
    rules = [{"field": "replied_since_last_touch", "operator": "eq", "value": False}]

    async with AsyncSessionLocal() as db:
        ws, contact, automation, execution = await _fixture(db)
        await record_step_run(
            db,
            workspace_id=ws.id,
            execution_id=execution.id,
            automation_id=automation.id,
            contact_id=contact.id,
            step_index=0,
            step_type="send_sms",
            outcome=OUTCOME_SENT,
        )
        await db.flush()

        # Silence: the condition "they have not replied" holds, ladder continues.
        assert await run_rules_match(
            db,
            rules,
            logic="and",
            workspace_id=ws.id,
            execution_id=execution.id,
            contact_id=contact.id,
            contact_phone=contact.phone_number,
        )

        await _inbound(db, workspace_id=ws.id, contact=contact, at=now + timedelta(minutes=1))

        # They replied: the condition fails and the branch takes the else-path.
        assert not await run_rules_match(
            db,
            rules,
            logic="and",
            workspace_id=ws.id,
            execution_id=execution.id,
            contact_id=contact.id,
            contact_phone=contact.phone_number,
        )

        await db.rollback()


async def test_a_string_false_from_jsonb_is_not_read_as_true() -> None:
    """A UI that writes ``"false"`` must not invert a suppression rule."""
    async with AsyncSessionLocal() as db:
        ws, contact, automation, execution = await _fixture(db)

        # No touches, no replies -> replied_since_last_touch is False.
        for written in (False, "false", "False"):
            assert await run_rules_match(
                db,
                [{"field": "replied_since_last_touch", "operator": "eq", "value": written}],
                logic="and",
                workspace_id=ws.id,
                execution_id=execution.id,
                contact_id=contact.id,
                contact_phone=contact.phone_number,
            ), f"{written!r} should compare equal to False"

        await db.rollback()


async def test_touch_count_supports_a_max_touches_ceiling() -> None:
    """``max_touches`` from the worker, as an ordinary branch condition."""
    async with AsyncSessionLocal() as db:
        ws, contact, automation, execution = await _fixture(db)

        rules = [{"field": "touch_count", "operator": "lt", "value": 3}]

        for sent in range(3):
            assert await run_rules_match(
                db,
                rules,
                logic="and",
                workspace_id=ws.id,
                execution_id=execution.id,
                contact_id=contact.id,
            ), f"under the ceiling at {sent} touches"
            await record_step_run(
                db,
                workspace_id=ws.id,
                execution_id=execution.id,
                automation_id=automation.id,
                contact_id=contact.id,
                step_index=sent,
                step_type="send_sms",
                outcome=OUTCOME_SENT,
            )
            await db.flush()

        assert not await run_rules_match(
            db,
            rules,
            logic="and",
            workspace_id=ws.id,
            execution_id=execution.id,
            contact_id=contact.id,
        ), "the third touch closes the ladder"

        await db.rollback()
