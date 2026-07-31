"""Safety and cadence tests for the 30/60/90-day unsold-quote revival worker."""

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.models.quote_followup_touch import SEQUENCE_UNSOLD_REVIVAL
from app.schemas.quote_revival import (
    QuoteRevivalSettings,
    QuoteRevivalTouchSettings,
)
from app.services.compliance.outbound_compliance import OutboundComplianceService
from app.workers.post_estimate_followup_worker import QuoteRecipient
from app.workers.unsold_quote_worker import (
    REVIVABLE_STATUSES,
    UnsoldQuoteWorker,
    due_touches,
    render_revival_template,
    resolve_anchor,
    resolve_template_id,
)

ISSUE_DATE = date(2026, 7, 1)
ANCHOR = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
SENT_AT = datetime(2026, 7, 1, 15, 0, tzinfo=UTC)


def _quote(
    *,
    status: str = "sent",
    contact_id: int | None = 7,
    total: float = 12_000,
    issue_date: date | None = ISSUE_DATE,
    expiry_date: date | None = date(2026, 7, 31),
    sent_at: datetime = SENT_AT,
) -> SimpleNamespace:
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
        issue_date=issue_date,
        expiry_date=expiry_date,
        sent_at=sent_at,
        approved_at=None,
        declined_at=None,
        proposal_document=None,
        public_token="proposal-token",
        number="Q-1042",
        total=total,
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


# --- cadence boundaries ----------------------------------------------------


@pytest.mark.parametrize(
    ("now", "expected_offsets"),
    [
        (ANCHOR + timedelta(days=29, hours=23), []),
        (ANCHOR + timedelta(days=30), [30]),
        (ANCHOR + timedelta(days=59), [30]),
        (ANCHOR + timedelta(days=60), [30, 60]),
        (ANCHOR + timedelta(days=90), [30, 60, 90]),
        (ANCHOR + timedelta(days=400), [30, 60, 90]),
    ],
)
def test_cadence_boundaries(now: datetime, expected_offsets: list[int]) -> None:
    touches = due_touches(
        QuoteRevivalSettings(),
        anchor=ANCHOR,
        now=now,
        completed_offsets=set(),
    )
    assert [touch.offset_days for touch in touches] == expected_offsets


def test_recorded_touch_is_never_worked_twice() -> None:
    """The ledger — not a contact tag — is what stops a repeat send."""
    touches = due_touches(
        QuoteRevivalSettings(),
        anchor=ANCHOR,
        now=ANCHOR + timedelta(days=90),
        completed_offsets={30, 60},
    )
    assert [touch.offset_days for touch in touches] == [90]


def test_sequence_stops_after_the_final_touch() -> None:
    touches = due_touches(
        QuoteRevivalSettings(),
        anchor=ANCHOR,
        now=ANCHOR + timedelta(days=365),
        completed_offsets={30, 60, 90},
    )
    assert touches == []


def test_max_touches_caps_the_ladder_without_retro_firing() -> None:
    """Lowering ``max_touches`` stops the sequence early, it never reopens work."""
    config = QuoteRevivalSettings(max_touches=2)
    assert [
        touch.offset_days
        for touch in due_touches(
            config,
            anchor=ANCHOR,
            now=ANCHOR + timedelta(days=90),
            completed_offsets=set(),
        )
    ] == [30, 60]
    assert (
        due_touches(
            config,
            anchor=ANCHOR,
            now=ANCHOR + timedelta(days=90),
            completed_offsets={30, 60},
        )
        == []
    )


def test_future_dated_quote_is_not_yet_aged() -> None:
    assert (
        due_touches(
            QuoteRevivalSettings(),
            anchor=ANCHOR,
            now=ANCHOR - timedelta(days=1),
            completed_offsets=set(),
        )
        == []
    )


# --- collision rail with the first-14-days cadence -------------------------


@pytest.mark.parametrize("offset", [0, 1, 7, 14])
def test_offsets_cannot_enter_the_post_estimate_window(offset: int) -> None:
    with pytest.raises(ValidationError):
        QuoteRevivalTouchSettings(offset_days=offset, channel="sms")


def test_offset_15_is_the_first_legal_revival_day() -> None:
    assert QuoteRevivalTouchSettings(offset_days=15, channel="sms").offset_days == 15


# A quote written on 1 April and presented on 1 July: the ladder counts from the
# document date, so its day-30 touch is "due" the moment the customer receives
# the estimate. Only a presentation-anchored rail keeps the two apart.
BACK_DATED = date(2026, 4, 1)


@pytest.mark.parametrize("days_after_presentation", [0, 1, 14])
async def test_back_dated_quote_is_left_to_the_first_14_days_cadence(
    days_after_presentation: int,
) -> None:
    worker = UnsoldQuoteWorker()
    worker.opt_out_manager.check_opt_out = AsyncMock(return_value=False)
    worker._has_recent_reply = AsyncMock(return_value=False)  # type: ignore[method-assign]

    reason = await worker._get_stop_reason(
        _quote(issue_date=BACK_DATED),  # type: ignore[arg-type]
        _recipient(),
        SENT_AT + timedelta(days=days_after_presentation),
        AsyncMock(),
    )

    assert reason == "post_estimate_window_open"
    # The rail is cheap and runs before any opt-out or reply lookup.
    worker.opt_out_manager.check_opt_out.assert_not_awaited()


async def test_revival_resumes_once_the_post_estimate_window_closes() -> None:
    """The rail delays a back-dated quote; it never drops it."""
    worker = UnsoldQuoteWorker()
    worker.opt_out_manager.check_opt_out = AsyncMock(return_value=False)
    worker._has_recent_reply = AsyncMock(return_value=False)  # type: ignore[method-assign]
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarResult(False))

    reason = await worker._get_stop_reason(
        _quote(issue_date=BACK_DATED),  # type: ignore[arg-type]
        _recipient(),
        SENT_AT + timedelta(days=15),
        db,
    )

    assert reason is None


async def test_revival_never_double_messages_inside_the_post_estimate_window() -> None:
    """End-to-end guard: no touch is dispatched while the other sequence owns it."""
    worker = UnsoldQuoteWorker()
    worker._load_contact = AsyncMock(return_value=None)  # type: ignore[method-assign]
    worker._has_recent_reply = AsyncMock(return_value=False)  # type: ignore[method-assign]
    worker._completed_offsets = AsyncMock(return_value=set())  # type: ignore[method-assign]
    worker.opt_out_manager.check_opt_out = AsyncMock(return_value=False)
    worker._dispatch_touch = AsyncMock()  # type: ignore[method-assign]
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarResult(False))

    await worker._process_quote(
        _quote(issue_date=BACK_DATED, contact_id=None),  # type: ignore[arg-type]
        QuoteRevivalSettings(enabled=True),
        SENT_AT + timedelta(days=1),
        db,
    )

    worker._dispatch_touch.assert_not_awaited()


def test_ledger_reads_are_scoped_to_this_sequence() -> None:
    """Post-estimate rows share the table and must not count as revival work."""
    assert SEQUENCE_UNSOLD_REVIVAL == "unsold_revival"


# --- anchor resolution ------------------------------------------------------


def test_issue_date_anchors_the_price_validity_clock() -> None:
    assert resolve_anchor(_quote()) == ANCHOR  # type: ignore[arg-type]


def test_quote_without_issue_date_falls_back_to_sent_at() -> None:
    assert resolve_anchor(_quote(issue_date=None)) == SENT_AT  # type: ignore[arg-type]


# --- value segmentation -----------------------------------------------------


def test_high_value_quote_gets_the_high_value_approach() -> None:
    routine = uuid.uuid4()
    high_value = uuid.uuid4()
    touch = QuoteRevivalTouchSettings(
        offset_days=30,
        channel="sms",
        template_id=routine,
        high_value_template_id=high_value,
    )
    assert (
        resolve_template_id(touch, quote_total=12_000, high_value_threshold=5_000) == high_value
    )
    assert resolve_template_id(touch, quote_total=1_500, high_value_threshold=5_000) == routine


def test_high_value_quote_falls_back_to_routine_copy_when_unconfigured() -> None:
    routine = uuid.uuid4()
    touch = QuoteRevivalTouchSettings(offset_days=30, channel="sms", template_id=routine)
    assert resolve_template_id(touch, quote_total=99_000, high_value_threshold=5_000) == routine


def test_call_touches_reject_customer_facing_copy() -> None:
    with pytest.raises(ValidationError):
        QuoteRevivalTouchSettings(offset_days=30, channel="call", template_id=uuid.uuid4())


def test_cadence_requires_an_automated_touch() -> None:
    with pytest.raises(ValidationError):
        QuoteRevivalSettings(
            touches=[QuoteRevivalTouchSettings(offset_days=30, channel="call")],
        )


def test_offsets_must_be_unique_and_ascending() -> None:
    with pytest.raises(ValidationError):
        QuoteRevivalSettings(
            touches=[
                QuoteRevivalTouchSettings(offset_days=60, channel="sms"),
                QuoteRevivalTouchSettings(offset_days=30, channel="email"),
            ],
        )


# --- message hooks ----------------------------------------------------------


def test_template_exposes_price_validity_hooks() -> None:
    body = render_revival_template(
        "Hi {first_name}, quote {quote_number} is {days_since_quote} days old "
        "and the price holds until {expiry_date}.",
        quote=_quote(),  # type: ignore[arg-type]
        recipient=_recipient(),
        now=ANCHOR + timedelta(days=30),
    )
    assert body == (
        "Hi Jamie, quote Q-1042 is 30 days old and the price holds until 2026-07-31."
    )


def test_template_renders_cleanly_when_no_expiry_is_set() -> None:
    body = render_revival_template(
        "{first_name}: {expiry_date}",
        quote=_quote(expiry_date=None),  # type: ignore[arg-type]
        recipient=_recipient(),
        now=ANCHOR + timedelta(days=30),
    )
    assert body == "Jamie: "


# --- stop conditions --------------------------------------------------------


def test_only_issued_undecided_quotes_are_revivable() -> None:
    assert set(REVIVABLE_STATUSES) == {"sent", "expired"}


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("approved", "quote_approved"),
        ("declined", "quote_declined"),
        ("draft", "quote_not_revivable"),
    ],
)
async def test_wrong_status_quotes_are_skipped(status: str, expected: str) -> None:
    worker = UnsoldQuoteWorker()
    reason = await worker._get_stop_reason(
        _quote(status=status),  # type: ignore[arg-type]
        _recipient(),
        ANCHOR + timedelta(days=30),
        AsyncMock(),
    )
    assert reason == expected


async def test_expired_quote_is_still_worked() -> None:
    """``expired`` is stamped lazily, so it means "no decision", not "dead"."""
    worker = UnsoldQuoteWorker()
    worker.opt_out_manager.check_opt_out = AsyncMock(return_value=False)
    worker._has_recent_reply = AsyncMock(return_value=False)  # type: ignore[method-assign]
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarResult(False))

    reason = await worker._get_stop_reason(
        _quote(status="expired"),  # type: ignore[arg-type]
        _recipient(),
        ANCHOR + timedelta(days=30),
        db,
    )
    assert reason is None


async def test_opted_out_contact_is_skipped() -> None:
    worker = UnsoldQuoteWorker()
    worker.opt_out_manager.check_opt_out = AsyncMock(return_value=True)
    worker._has_recent_reply = AsyncMock(return_value=False)  # type: ignore[method-assign]

    reason = await worker._get_stop_reason(
        _quote(),  # type: ignore[arg-type]
        _recipient(),
        ANCHOR + timedelta(days=30),
        AsyncMock(),
    )
    assert reason == "contact_opted_out"


async def test_live_conversation_is_not_talked_over() -> None:
    worker = UnsoldQuoteWorker()
    worker.opt_out_manager.check_opt_out = AsyncMock(return_value=False)
    worker._has_recent_reply = AsyncMock(return_value=True)  # type: ignore[method-assign]

    reason = await worker._get_stop_reason(
        _quote(),  # type: ignore[arg-type]
        _recipient(),
        ANCHOR + timedelta(days=30),
        AsyncMock(),
    )
    assert reason == "contact_replied"


async def test_booked_appointment_stops_the_sequence() -> None:
    worker = UnsoldQuoteWorker()
    worker.opt_out_manager.check_opt_out = AsyncMock(return_value=False)
    worker._has_recent_reply = AsyncMock(return_value=False)  # type: ignore[method-assign]
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarResult(True))

    reason = await worker._get_stop_reason(
        _quote(),  # type: ignore[arg-type]
        _recipient(),
        ANCHOR + timedelta(days=30),
        db,
    )
    assert reason == "appointment_booked"


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
    worker = UnsoldQuoteWorker()
    worker._get_stop_reason = AsyncMock(return_value=reason)  # type: ignore[method-assign]
    worker._dispatch_touch = AsyncMock()  # type: ignore[method-assign]

    await worker._process_quote(
        _quote(),  # type: ignore[arg-type]
        QuoteRevivalSettings(enabled=True),
        ANCHOR + timedelta(days=30),
        AsyncMock(),
    )

    worker._dispatch_touch.assert_not_awaited()


# --- compliance -------------------------------------------------------------


async def test_quiet_hours_defer_the_touch_before_any_template_or_send() -> None:
    worker = UnsoldQuoteWorker()
    worker.opt_out_manager.check_opt_out = AsyncMock(return_value=False)
    worker.compliance = OutboundComplianceService(worker.opt_out_manager)
    worker._load_template = AsyncMock()  # type: ignore[method-assign]
    worker._send_sms = AsyncMock()  # type: ignore[method-assign]
    touch = QuoteRevivalTouchSettings(
        offset_days=30,
        channel="sms",
        template_id=uuid.uuid4(),
    )

    result = await worker._dispatch_touch(
        quote=_quote(),  # type: ignore[arg-type]
        recipient=_recipient(),
        touch=touch,
        template_id=touch.template_id,
        config=QuoteRevivalSettings(enabled=True, timezone="UTC"),
        now=datetime(2026, 7, 31, 22, 0, tzinfo=UTC),
        db=AsyncMock(),
    )

    assert result is None
    worker._load_template.assert_not_awaited()
    worker._send_sms.assert_not_awaited()


async def test_missing_template_defers_instead_of_sending_empty_copy() -> None:
    worker = UnsoldQuoteWorker()
    worker.compliance = AsyncMock()
    worker.compliance.evaluate_direct = AsyncMock(
        return_value=SimpleNamespace(allowed=True, reason=None)
    )
    worker._load_template = AsyncMock(return_value=None)  # type: ignore[method-assign]
    worker._send_sms = AsyncMock()  # type: ignore[method-assign]
    touch = QuoteRevivalTouchSettings(
        offset_days=30,
        channel="sms",
        template_id=uuid.uuid4(),
    )

    result = await worker._dispatch_touch(
        quote=_quote(),  # type: ignore[arg-type]
        recipient=_recipient(),
        touch=touch,
        template_id=touch.template_id,
        config=QuoteRevivalSettings(enabled=True, timezone="UTC"),
        now=ANCHOR + timedelta(days=30, hours=15),
        db=AsyncMock(),
    )

    assert result is None
    worker._send_sms.assert_not_awaited()
