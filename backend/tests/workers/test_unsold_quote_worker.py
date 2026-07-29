"""Unsold-quote re-engagement worker tests.

The expensive failures for this worker are all *sends that should not have
happened*: chasing a quote the customer already approved, texting someone on the
suppression list, re-sending a touch that already went out, firing the whole
30/60/90 sequence in one afternoon against a back catalogue, or waking a
customer at 2am. Each of those has a test here.

DB-free: the cadence decision is a pure function, and the send path runs against
a mocked session with the delivery service, tag service and opt-out manager
patched, matching the other worker unit tests in this package.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.quote import Quote
from app.schemas.unsold_quotes import (
    DEFAULT_TEMPLATE_BODIES,
    UnsoldQuoteSettings,
    UnsoldQuoteTouch,
    default_template_body,
)
from app.services.outbound.delivery import (
    OutboundDeliveryChannel,
    OutboundDeliveryResult,
    OutboundDeliveryStatus,
)
from app.workers.base import BaseWorker
from app.workers.retryable import RetryableWorker
from app.workers.unsold_quote_worker import (
    WORKABLE_STATUSES,
    TouchDecision,
    UnsoldQuoteWorker,
    WorkspaceContext,
    format_money,
    quote_age_days,
    render_message,
    select_due_touch,
    touch_tag,
    value_band,
)
from tests.factories import ContactFactory

WORKSPACE_ID = uuid.uuid4()
NOW = datetime(2026, 7, 29, 15, 0, tzinfo=UTC)

DEFAULT_TOUCHES = [
    UnsoldQuoteTouch(day_offset=30, hook="price_validity"),
    UnsoldQuoteTouch(day_offset=60, hook="seasonal"),
    UnsoldQuoteTouch(day_offset=90, hook="financing"),
]


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _config(**overrides: object) -> UnsoldQuoteSettings:
    base: dict[str, object] = {"enabled": True, "touches": DEFAULT_TOUCHES}
    base.update(overrides)
    return UnsoldQuoteSettings(**base)  # type: ignore[arg-type]


def _context(config: UnsoldQuoteSettings | None = None) -> WorkspaceContext:
    return WorkspaceContext(
        workspace_id=WORKSPACE_ID,
        name="Maxteriors",
        timezone="America/Detroit",
        config=config or _config(),
    )


def _quote(*, days_old: int = 31, status: str = "sent", total: str = "1500.00") -> Quote:
    return Quote(
        id=uuid.uuid4(),
        workspace_id=WORKSPACE_ID,
        contact_id=42,
        number="QUO-000123",
        title="Gutter cleaning",
        status=status,
        total=Decimal(total),
        currency="USD",
        issue_date=NOW.date() - timedelta(days=days_old),
        public_token="tok-123",
    )


def _contact() -> object:
    return ContactFactory.build(
        id=42,
        workspace_id=WORKSPACE_ID,
        first_name="Dana",
        last_name="Reed",
        phone_number="+15125550143",
    )


def _sent_result() -> OutboundDeliveryResult:
    return OutboundDeliveryResult(
        channel=OutboundDeliveryChannel.SMS,
        status=OutboundDeliveryStatus.SENT,
        message=MagicMock(id=uuid.uuid4()),
    )


def _worker(*, opted_out: bool = False, sent_touches: dict[int, datetime] | None = None):
    worker = UnsoldQuoteWorker()
    worker.opt_out_manager.check_opt_out = AsyncMock(return_value=opted_out)  # type: ignore[method-assign]
    worker._sent_touch_times = AsyncMock(return_value=sent_touches or {})  # type: ignore[method-assign]
    worker._resolve_from_number = AsyncMock(return_value="+15125550100")  # type: ignore[method-assign]
    return worker


def _quotes_result(quotes: list[Quote]) -> MagicMock:
    """A ``db.execute`` result whose ``.scalars().all()`` yields ``quotes``."""
    return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=quotes))))


def _db(contact: object) -> MagicMock:
    db = MagicMock()
    db.get = AsyncMock(return_value=contact)
    db.commit = AsyncMock()
    db.execute = AsyncMock()
    return db


# --------------------------------------------------------------------------- #
# Worker contract
# --------------------------------------------------------------------------- #
def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(UnsoldQuoteWorker, RetryableWorker)
    assert issubclass(UnsoldQuoteWorker, BaseWorker)


def test_retry_configuration() -> None:
    assert UnsoldQuoteWorker.COMPONENT_NAME == "unsold_quote_worker"
    assert UnsoldQuoteWorker.max_retries == 3
    assert UnsoldQuoteWorker.backoff_base_seconds == 2.0


def test_only_sent_and_expired_quotes_are_workable() -> None:
    """Draft was never shown; approved/declined are decisions already made."""
    assert set(WORKABLE_STATUSES) == {"sent", "expired"}


# --------------------------------------------------------------------------- #
# Cadence (pure)
# --------------------------------------------------------------------------- #
def test_first_touch_waits_for_its_day_offset() -> None:
    assert select_due_touch(DEFAULT_TOUCHES, age_days=29, sent_at_by_index={}, now=NOW) is None

    due = select_due_touch(DEFAULT_TOUCHES, age_days=30, sent_at_by_index={}, now=NOW)
    assert due is not None
    assert due.number == 1
    assert due.touch.hook == "price_validity"


def test_second_touch_waits_for_both_age_and_spacing() -> None:
    """A day-31 quote texted today does not get day 60's message tomorrow."""
    just_sent = {0: NOW - timedelta(hours=2)}
    assert (
        select_due_touch(DEFAULT_TOUCHES, age_days=95, sent_at_by_index=just_sent, now=NOW) is None
    )

    long_ago = {0: NOW - timedelta(days=30)}
    due = select_due_touch(DEFAULT_TOUCHES, age_days=95, sent_at_by_index=long_ago, now=NOW)
    assert due is not None
    assert due.number == 2
    assert due.touch.hook == "seasonal"


def test_back_catalogue_gets_one_touch_not_the_whole_sequence() -> None:
    """Switching this on for a 200-day-old quote sends touch 1, then waits."""
    first = select_due_touch(DEFAULT_TOUCHES, age_days=200, sent_at_by_index={}, now=NOW)
    assert first is not None and first.number == 1

    after_first = select_due_touch(
        DEFAULT_TOUCHES, age_days=200, sent_at_by_index={0: NOW}, now=NOW
    )
    assert after_first is None


def test_sequence_stops_after_the_final_touch() -> None:
    all_sent = {index: NOW - timedelta(days=40) for index in range(3)}
    assert (
        select_due_touch(DEFAULT_TOUCHES, age_days=400, sent_at_by_index=all_sent, now=NOW) is None
    )


def test_cadence_moves_forward_past_a_gap() -> None:
    """A touch that never landed cannot pin the quote on touch 1 forever."""
    due = select_due_touch(
        DEFAULT_TOUCHES,
        age_days=200,
        sent_at_by_index={1: NOW - timedelta(days=45)},
        now=NOW,
    )
    assert due is not None
    assert due.number == 3


def test_max_touches_shortens_the_sequence_without_losing_copy() -> None:
    config = _config(max_touches=2)
    assert len(config.touches) == 3
    assert config.day_offsets == [30, 60]
    assert (
        select_due_touch(
            config.active_touches(),
            age_days=400,
            sent_at_by_index={0: NOW - timedelta(days=90), 1: NOW - timedelta(days=40)},
            now=NOW,
        )
        is None
    )


def test_no_configured_touches_never_fires() -> None:
    assert select_due_touch([], age_days=999, sent_at_by_index={}, now=NOW) is None


def test_quote_age_never_goes_negative() -> None:
    assert quote_age_days(date(2026, 8, 30), date(2026, 7, 29)) == 0
    assert quote_age_days(date(2026, 6, 29), date(2026, 7, 29)) == 30


# --------------------------------------------------------------------------- #
# Value segmentation and rendering (pure)
# --------------------------------------------------------------------------- #
def test_value_band_splits_on_the_configured_threshold() -> None:
    assert value_band(Decimal("1500"), 5000.0) == "standard"
    assert value_band(Decimal("5000"), 5000.0) == "high_value"
    assert value_band(Decimal("12000"), 5000.0) == "high_value"
    # A raised threshold moves the line without a code change.
    assert value_band(Decimal("12000"), 15000.0) == "standard"


def test_unreadable_total_falls_back_to_the_small_job_message() -> None:
    assert value_band(None, 5000.0) == "standard"
    assert value_band("not-a-number", 5000.0) == "standard"


def test_money_formats_for_sms() -> None:
    assert format_money(Decimal("12000.00"), "USD") == "$12,000"
    assert format_money(Decimal("1499.50"), "USD") == "$1,499.50"
    assert format_money(Decimal("900"), "CAD") == "900 CAD"
    assert format_money(None, "USD") == ""


def test_render_substitutes_placeholders_and_tidies_gaps() -> None:
    body = render_message(
        "Hi {first_name}, {quote_number} for {quote_total}. {quote_link}",
        {
            "first_name": "Dana",
            "quote_number": "QUO-000123",
            "quote_total": "$12,000",
            "quote_link": "",
        },
    )
    assert body == "Hi Dana, QUO-000123 for $12,000."


def test_render_leaves_unknown_placeholders_visible() -> None:
    """A visible token tells the operator their template names a field we don't fill."""
    assert render_message("Hi {nickname}", {"first_name": "Dana"}) == "Hi {nickname}"


def test_default_copy_exists_for_every_hook_and_band() -> None:
    for hook in ("price_validity", "seasonal", "financing"):
        for band in ("standard", "high_value"):
            assert DEFAULT_TEMPLATE_BODIES[(hook, band)]
    # An unknown hook still sends something rather than an empty text.
    assert default_template_body("mystery", "high_value")


# --------------------------------------------------------------------------- #
# Send path
# --------------------------------------------------------------------------- #
async def test_due_quote_is_texted_and_tagged() -> None:
    worker = _worker()
    contact = _contact()
    db = _db(contact)

    with (
        patch(
            "app.workers.unsold_quote_worker.outbound_delivery_service.deliver",
            AsyncMock(return_value=_sent_result()),
        ) as deliver,
        patch("app.workers.unsold_quote_worker.TagService") as tag_service,
    ):
        tag_service.return_value.add_tag_to_contact = AsyncMock()
        await worker._process_quote(_context(), _quote(), NOW, db)

    deliver.assert_awaited_once()
    request = deliver.await_args.args[1]
    assert request.to == "+15125550143"
    assert request.action_type == "unsold_quote_followup"
    assert request.idempotency_scope == "unsold_quote"
    # Touch index rides in the key, so touch 1 and touch 2 never collide.
    assert request.idempotency_parts[1] == 0
    assert "Dana" in request.body

    tag_service.return_value.add_tag_to_contact.assert_awaited_once()
    assert tag_service.return_value.add_tag_to_contact.await_args.kwargs["name"] == (touch_tag(1))
    db.commit.assert_awaited_once()


async def test_decided_and_draft_quotes_are_never_worked() -> None:
    for status in ("draft", "approved", "declined"):
        worker = _worker()
        db = _db(_contact())
        with patch(
            "app.workers.unsold_quote_worker.outbound_delivery_service.deliver",
            AsyncMock(),
        ) as deliver:
            await worker._process_quote(_context(), _quote(status=status), NOW, db)
        assert deliver.await_count == 0, status
        assert db.commit.await_count == 0, status


async def test_opted_out_contact_is_skipped_without_a_tag() -> None:
    worker = _worker(opted_out=True)
    db = _db(_contact())

    with (
        patch(
            "app.workers.unsold_quote_worker.outbound_delivery_service.deliver",
            AsyncMock(),
        ) as deliver,
        patch("app.workers.unsold_quote_worker.TagService") as tag_service,
    ):
        tag_service.return_value.add_tag_to_contact = AsyncMock()
        await worker._process_quote(_context(), _quote(), NOW, db)

    assert deliver.await_count == 0
    assert tag_service.return_value.add_tag_to_contact.await_count == 0


async def test_already_sent_touch_is_not_repeated() -> None:
    """The per-quote idempotency key is what stops a quote being double-worked."""
    worker = _worker(sent_touches={0: NOW - timedelta(hours=6)})
    db = _db(_contact())

    with patch(
        "app.workers.unsold_quote_worker.outbound_delivery_service.deliver",
        AsyncMock(),
    ) as deliver:
        await worker._process_quote(_context(), _quote(days_old=31), NOW, db)

    assert deliver.await_count == 0


async def test_quote_younger_than_the_first_offset_is_left_alone() -> None:
    worker = _worker()
    db = _db(_contact())

    with patch(
        "app.workers.unsold_quote_worker.outbound_delivery_service.deliver",
        AsyncMock(),
    ) as deliver:
        await worker._process_quote(_context(), _quote(days_old=10), NOW, db)

    assert deliver.await_count == 0


async def test_high_value_quote_gets_the_high_value_copy() -> None:
    worker = _worker()
    db = _db(_contact())

    with (
        patch(
            "app.workers.unsold_quote_worker.outbound_delivery_service.deliver",
            AsyncMock(return_value=_sent_result()),
        ) as deliver,
        patch("app.workers.unsold_quote_worker.TagService") as tag_service,
    ):
        tag_service.return_value.add_tag_to_contact = AsyncMock()
        await worker._process_quote(_context(), _quote(total="12000.00"), NOW, db)

    body = deliver.await_args.args[1].body
    assert "$12,000" in body
    assert body.startswith("Hi Dana, checking in on your $12,000 estimate")


async def test_blocked_delivery_leaves_the_touch_unrecorded() -> None:
    """A blocked send must not tag: the touch never reached the customer."""
    worker = _worker()
    db = _db(_contact())
    blocked = OutboundDeliveryResult(
        channel=OutboundDeliveryChannel.SMS,
        status=OutboundDeliveryStatus.BLOCKED,
        reason="global_opt_out",
    )

    with (
        patch(
            "app.workers.unsold_quote_worker.outbound_delivery_service.deliver",
            AsyncMock(return_value=blocked),
        ),
        patch("app.workers.unsold_quote_worker.TagService") as tag_service,
    ):
        tag_service.return_value.add_tag_to_contact = AsyncMock()
        await worker._process_quote(_context(), _quote(), NOW, db)

    assert tag_service.return_value.add_tag_to_contact.await_count == 0
    assert db.commit.await_count == 0


async def test_contact_without_a_phone_is_skipped() -> None:
    worker = _worker()
    contact = ContactFactory.build(
        id=42, workspace_id=WORKSPACE_ID, first_name="Dana", phone_number=None, phone_hash=None
    )
    db = _db(contact)

    with patch(
        "app.workers.unsold_quote_worker.outbound_delivery_service.deliver",
        AsyncMock(),
    ) as deliver:
        await worker._process_quote(_context(), _quote(), NOW, db)

    assert deliver.await_count == 0


# --------------------------------------------------------------------------- #
# Template resolution
# --------------------------------------------------------------------------- #
async def test_named_message_template_is_used_when_it_resolves() -> None:
    worker = _worker()
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value="Custom {first_name}!"))
    )

    body = await worker._resolve_template(
        db,
        WORKSPACE_ID,
        UnsoldQuoteTouch(day_offset=30, hook="seasonal", template_name="Spring nudge"),
        "standard",
    )

    assert body == "Custom {first_name}!"


async def test_deleted_template_falls_back_to_built_in_copy() -> None:
    """A deleted template must not silently switch the sequence off."""
    worker = _worker()
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

    body = await worker._resolve_template(
        db,
        WORKSPACE_ID,
        UnsoldQuoteTouch(day_offset=90, hook="financing", template_name="Gone"),
        "standard",
    )

    assert body == default_template_body("financing", "standard")


# --------------------------------------------------------------------------- #
# Workspace pass: quiet hours and candidate selection
# --------------------------------------------------------------------------- #
async def test_quiet_hours_stop_the_workspace_pass() -> None:
    """22:00 in Detroit is inside the default 21:00-08:00 window."""
    worker = _worker()
    db = MagicMock()
    db.execute = AsyncMock(return_value=_quotes_result([]))

    await worker._process_workspace(_context(), db)

    assert db.execute.await_count == 1  # 15:00 UTC = 11:00 local: allowed

    db.execute.reset_mock()
    with patch("app.workers.unsold_quote_worker.datetime") as clock:
        clock.now.return_value = datetime(2026, 7, 30, 2, 0, tzinfo=UTC)  # 22:00 local
        await worker._process_workspace(_context(), db)

    assert db.execute.await_count == 0


async def test_quiet_hours_can_be_switched_off() -> None:
    worker = _worker()
    db = MagicMock()
    db.execute = AsyncMock(return_value=_quotes_result([]))
    context = _context(_config(quiet_hours_start=None, quiet_hours_end=None))

    with patch("app.workers.unsold_quote_worker.datetime") as clock:
        clock.now.return_value = datetime(2026, 7, 30, 2, 0, tzinfo=UTC)
        await worker._process_workspace(context, db)

    assert db.execute.await_count == 1


async def test_one_quote_per_contact_per_cycle() -> None:
    """A customer holding three estimates hears about the biggest one only."""
    worker = _worker()
    big = _quote(total="12000.00")
    small = _quote(total="900.00")
    db = MagicMock()
    db.execute = AsyncMock(return_value=_quotes_result([big, small]))

    quotes = await worker._due_quotes(db, WORKSPACE_ID, NOW.date() - timedelta(days=30))

    assert quotes == [big]


def test_disabled_workspace_produces_no_context() -> None:
    worker = UnsoldQuoteWorker()
    workspace = SimpleNamespace(id=WORKSPACE_ID, name="Maxteriors", settings={})

    assert worker._context_for(workspace) is None  # type: ignore[arg-type]

    enabled = SimpleNamespace(
        id=WORKSPACE_ID,
        name="Maxteriors",
        settings={"unsold_quotes": {"enabled": True}, "timezone": "America/Detroit"},
    )
    context = worker._context_for(enabled)  # type: ignore[arg-type]
    assert context is not None
    assert context.timezone == "America/Detroit"
    assert context.config.day_offsets == [30, 60, 90]


def test_touch_decision_number_is_one_based() -> None:
    decision = TouchDecision(index=2, touch=DEFAULT_TOUCHES[2])
    assert decision.number == 3
    assert touch_tag(decision.number) == "unsold-quote-touch-3"
