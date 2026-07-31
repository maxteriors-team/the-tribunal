"""Safety and cadence tests for the first-14-days quote follow-up worker."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.core.encryption import InvalidToken
from app.schemas.quote_followup import (
    QuoteFollowupSettings,
    QuoteFollowupTouchSettings,
)
from app.services.compliance.outbound_compliance import OutboundComplianceService
from app.workers.post_estimate_followup_worker import (
    PostEstimateFollowupWorker,
    QuoteRecipient,
    due_touches,
    post_estimate_window_is_open,
    resolve_delivery_channel,
)

SENT_AT = datetime(2026, 7, 1, 15, 0, tzinfo=UTC)


def _quote(*, status: str = "sent", contact_id: int | None = 7) -> SimpleNamespace:
    workspace = SimpleNamespace(
        id=uuid.uuid4(),
        name="Maxteriors",
        settings={"timezone": "UTC"},
    )
    contact = SimpleNamespace(
        first_name="Jamie",
        last_name="Homeowner",
        email="jamie@example.com",
        phone_number="+12485550123",
        sms_consent_status="opted_in",
    )
    return SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        workspace=workspace,
        contact_id=contact_id,
        contact=contact if contact_id is not None else None,
        status=status,
        sent_at=SENT_AT,
        approved_at=None,
        declined_at=None,
        proposal_document=None,
        public_token="proposal-token",
        number="Q-1042",
        total=12_000,
        currency="USD",
        created_by_id=1,
    )


def _recipient() -> QuoteRecipient:
    return QuoteRecipient(
        first_name="Jamie",
        last_name="Homeowner",
        email="jamie@example.com",
        phone="+12485550123",
        sms_consent_status="opted_in",
    )


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar(self) -> object:
        return self.value


@pytest.mark.parametrize(
    ("now", "expected_offsets"),
    [
        (SENT_AT + timedelta(days=1) - timedelta(microseconds=1), []),
        (SENT_AT + timedelta(days=1), [1]),
        (SENT_AT + timedelta(days=7), [1, 3, 7]),
        (SENT_AT + timedelta(days=14), [1, 3, 7, 14]),
        (SENT_AT + timedelta(days=15), []),
        (SENT_AT + timedelta(days=29), []),
    ],
)
def test_cadence_boundaries_and_revival_gap(
    now: datetime,
    expected_offsets: list[int],
) -> None:
    touches = due_touches(
        QuoteFollowupSettings(),
        sent_at=SENT_AT,
        now=now,
        completed_offsets=set(),
    )
    assert [touch.offset_days for touch in touches] == expected_offsets


def test_completed_touch_is_never_due_twice() -> None:
    touches = due_touches(
        QuoteFollowupSettings(),
        sent_at=SENT_AT,
        now=SENT_AT + timedelta(days=1),
        completed_offsets={1},
    )
    assert touches == []


def test_offsets_cannot_enter_30_day_revival_window() -> None:
    with pytest.raises(ValidationError):
        QuoteFollowupTouchSettings(offset_days=30, channel="call")


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (SENT_AT, True),
        (SENT_AT + timedelta(days=14), True),
        (SENT_AT + timedelta(days=15) - timedelta(microseconds=1), True),
        (SENT_AT + timedelta(days=15), False),
    ],
)
def test_window_ownership_is_measured_from_presentation(now: datetime, expected: bool) -> None:
    """The rail the revival sequence honours: who owns this quote right now."""
    assert post_estimate_window_is_open(SENT_AT, now=now) is expected


def test_unsent_quote_is_owned_by_nobody() -> None:
    assert post_estimate_window_is_open(None, now=SENT_AT) is False


def test_high_value_sms_routes_to_human_call_but_email_stays_email() -> None:
    sms_touch = QuoteFollowupTouchSettings(offset_days=1, channel="sms")
    email_touch = QuoteFollowupTouchSettings(
        offset_days=7,
        channel="email",
        template_id=uuid.uuid4(),
    )
    assert (
        resolve_delivery_channel(
            sms_touch,
            quote_total=12_000,
            high_value_threshold=10_000,
        )
        == "call"
    )
    assert (
        resolve_delivery_channel(
            email_touch,
            quote_total=12_000,
            high_value_threshold=10_000,
        )
        == "email"
    )


@pytest.mark.parametrize(
    "reason",
    [
        "quote_approved",
        "quote_declined",
        "contact_replied",
        "contact_opted_out",
        "appointment_booked",
    ],
)
async def test_every_stop_condition_prevents_dispatch(reason: str) -> None:
    worker = PostEstimateFollowupWorker()
    worker._get_stop_reason = AsyncMock(return_value=reason)  # type: ignore[method-assign]
    worker._dispatch_touch = AsyncMock()  # type: ignore[method-assign]
    db = AsyncMock()

    await worker._process_quote(
        _quote(),  # type: ignore[arg-type]
        QuoteFollowupSettings(enabled=True),
        SENT_AT + timedelta(days=1),
        db,
    )

    worker._dispatch_touch.assert_not_awaited()


@pytest.mark.parametrize(
    ("status", "expected"),
    [("approved", "quote_approved"), ("declined", "quote_declined")],
)
async def test_terminal_quote_status_stop_reason(status: str, expected: str) -> None:
    worker = PostEstimateFollowupWorker()
    reason = await worker._get_stop_reason(
        _quote(status=status),  # type: ignore[arg-type]
        _recipient(),
        AsyncMock(),
    )
    assert reason == expected


async def test_opted_out_contact_stop_reason() -> None:
    worker = PostEstimateFollowupWorker()
    worker.opt_out_manager.check_opt_out = AsyncMock(return_value=True)
    worker._has_reply_after_quote = AsyncMock(return_value=False)  # type: ignore[method-assign]

    reason = await worker._get_stop_reason(
        _quote(),  # type: ignore[arg-type]
        _recipient(),
        AsyncMock(),
    )
    assert reason == "contact_opted_out"


async def test_inbound_reply_stop_reason() -> None:
    worker = PostEstimateFollowupWorker()
    worker.opt_out_manager.check_opt_out = AsyncMock(return_value=False)
    worker._has_reply_after_quote = AsyncMock(return_value=True)  # type: ignore[method-assign]

    reason = await worker._get_stop_reason(
        _quote(),  # type: ignore[arg-type]
        _recipient(),
        AsyncMock(),
    )
    assert reason == "contact_replied"


async def test_booked_appointment_stop_reason() -> None:
    worker = PostEstimateFollowupWorker()
    worker.opt_out_manager.check_opt_out = AsyncMock(return_value=False)
    worker._has_reply_after_quote = AsyncMock(return_value=False)  # type: ignore[method-assign]
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarResult(True))

    reason = await worker._get_stop_reason(
        _quote(),  # type: ignore[arg-type]
        _recipient(),
        db,
    )
    assert reason == "appointment_booked"


async def test_quiet_hours_defer_automated_touch_before_template_or_send() -> None:
    worker = PostEstimateFollowupWorker()
    worker.opt_out_manager.check_opt_out = AsyncMock(return_value=False)
    worker.compliance = OutboundComplianceService(worker.opt_out_manager)
    worker._load_template = AsyncMock()  # type: ignore[method-assign]
    quote = _quote()
    touch = QuoteFollowupTouchSettings(
        offset_days=1,
        channel="sms",
        template_id=uuid.uuid4(),
    )
    config = QuoteFollowupSettings(
        enabled=True,
        high_value_threshold=20_000,
        timezone="UTC",
        touches=[
            touch,
            QuoteFollowupTouchSettings(offset_days=3, channel="call"),
            QuoteFollowupTouchSettings(
                offset_days=7,
                channel="email",
                template_id=uuid.uuid4(),
            ),
        ],
    )

    result = await worker._dispatch_touch(
        quote=quote,  # type: ignore[arg-type]
        recipient=_recipient(),
        touch=touch,
        delivered_channel="sms",
        config=config,
        now=datetime(2026, 7, 2, 23, 0, tzinfo=UTC),
        db=AsyncMock(),
    )

    assert result is None
    worker._load_template.assert_not_awaited()


async def test_undecryptable_contact_skips_one_quote_without_killing_the_tick() -> None:
    """A contact under a retired key must not stall the cadence for everyone.

    The row raises while it is materialized, so eager-loading it would abort the
    whole tick before any per-quote handling — silently, since the loop logs and
    the heartbeat keeps ``/readyz`` green.
    """
    worker = PostEstimateFollowupWorker()
    worker._get_stop_reason = AsyncMock(return_value=None)  # type: ignore[method-assign]
    worker._completed_offsets = AsyncMock(return_value=set())  # type: ignore[method-assign]
    worker._dispatch_touch = AsyncMock()  # type: ignore[method-assign]
    db = AsyncMock()
    db.get = AsyncMock(side_effect=InvalidToken())

    await worker._process_quote(
        _quote(),  # type: ignore[arg-type]
        QuoteFollowupSettings(enabled=True),
        SENT_AT + timedelta(days=1),
        db,
    )

    # Materialized per quote rather than eager-joined into the broad fetch, and
    # a quote that cannot be decrypted is dropped instead of dispatched.
    db.get.assert_awaited_once()
    worker._dispatch_touch.assert_not_awaited()


async def test_quote_without_a_contact_never_queries_for_one() -> None:
    db = AsyncMock()
    contact = await PostEstimateFollowupWorker._load_contact(
        _quote(contact_id=None),  # type: ignore[arg-type]
        db,
    )

    assert contact is None
    db.get.assert_not_awaited()


async def test_processed_offset_prevents_double_message() -> None:
    worker = PostEstimateFollowupWorker()
    worker._get_stop_reason = AsyncMock(return_value=None)  # type: ignore[method-assign]
    worker._completed_offsets = AsyncMock(return_value={1})  # type: ignore[method-assign]
    worker._dispatch_touch = AsyncMock()  # type: ignore[method-assign]

    await worker._process_quote(
        _quote(),  # type: ignore[arg-type]
        QuoteFollowupSettings(enabled=True),
        SENT_AT + timedelta(days=1),
        AsyncMock(),
    )

    worker._dispatch_touch.assert_not_awaited()
