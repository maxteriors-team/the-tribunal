"""Unsold-quote revival worker (30/60/90 days).

Quotes that were issued and then went quiet are the warmest recoverable revenue
a home-services business has: the lead is already paid for and the work is
already scoped. Nothing else in the system works them — ``never_booked_worker``
targets contacts who replied but never booked, ``noshow_reengagement_worker``
targets no-shows, and ``post_estimate_followup_worker`` stops at day 14.

This worker is anchored to the quote's **issue date** (the date printed on the
document, which is what "your price is still good until…" refers to), falling
back to ``sent_at`` when a quote carries no issue date.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import Date, and_, cast, exists, func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from app.core.encryption import InvalidToken, hash_phone
from app.db.session import AsyncSessionLocal
from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageDirection, MessageStatus
from app.models.human_nudge import HumanNudge
from app.models.message_template import MessageTemplate
from app.models.phone_number import PhoneNumber
from app.models.quote import UNSOLD_QUOTE_STATUSES, Quote
from app.models.quote_followup_touch import SEQUENCE_UNSOLD_REVIVAL, QuoteFollowupTouch
from app.models.workspace import Workspace
from app.schemas.quote_revival import (
    REVIVAL_MAX_OFFSET_DAYS,
    QuoteRevivalSettings,
    QuoteRevivalTouchSettings,
)
from app.services.calendar.reminder_service import resolve_from_number
from app.services.compliance.outbound_compliance import (
    DirectOutboundComplianceRequest,
    OutboundComplianceService,
)
from app.services.email import send_automation_email
from app.services.idempotency import derive_outbound_key, derive_worker_retry_key
from app.services.quotes.pricing_config import get_pricing_config
from app.services.quotes.proposal_pricing import financing_is_offered
from app.services.quotes.revival_config import (
    SETTINGS_KEY as REVIVAL_SETTINGS_KEY,
)
from app.services.quotes.revival_config import (
    get_quote_revival_config,
)
from app.services.rate_limiting.number_pool import NumberPoolManager
from app.services.rate_limiting.opt_out_manager import OptOutManager
from app.services.tags import TagService
from app.services.telephony.text_provider import get_text_message_provider
from app.utils.phone import normalize_phone_safe
from app.utils.timezones import workspace_timezone_name
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.post_estimate_followup_worker import (
    ACTIVE_WINDOW_DAYS as POST_ESTIMATE_WINDOW_DAYS,
)
from app.workers.post_estimate_followup_worker import (
    QuoteRecipient,
    post_estimate_window_is_open,
    render_quote_followup_template,
    resolve_quote_recipient,
)
from app.workers.retryable import RetryableWorker

# Rows per keyset page; the tick pages until the due set is exhausted.
QUOTE_PAGE_SIZE = 100
# Absolute per-tick ceiling so a pathological dataset cannot spin forever.
MAX_QUOTES_PER_TICK = 5_000
# Only these two statuses mean "issued and undecided". ``draft`` was never
# presented; ``approved``/``declined`` are settled outcomes. Defined on the model
# so pre-booking audience selection shares one definition of "unsold".
REVIVABLE_STATUSES = UNSOLD_QUOTE_STATUSES
# A quote whose anchor is older than this is out of scope for every workspace,
# so the broad fetch stays bounded regardless of per-workspace configuration.
MAX_QUOTE_AGE_DAYS = REVIVAL_MAX_OFFSET_DAYS + 1
# The configured ``offset_days`` floor is not enough to keep the two quote
# sequences apart: revival counts from the document's issue date while the
# first-14-days cadence counts from ``sent_at``, and a back-dated quote is
# already "30 days old" the day it is presented. This rail is measured from
# presentation, so a quote the other sequence still owns is never touched.
POST_ESTIMATE_WINDOW_STOP_REASON = "post_estimate_window_open"
# With no revival touch recorded yet, an inbound message inside this window
# means a live conversation the worker must not interrupt.
FRESH_REPLY_WINDOW_DAYS = 14
# Applied to the contact for operator segmentation only. The ledger — not this
# tag — is the dedupe gate, because a contact can hold several open quotes and a
# contact-scoped tag would silently starve every quote after the first.
REVIVED_TAG = "unsold-quote-revived"


@dataclass(frozen=True, slots=True)
class RevivalDeliveryResult:
    """Outcome persisted in the shared quote follow-up ledger."""

    outcome: str
    reason: str | None = None
    message_id: uuid.UUID | None = None
    human_nudge_id: uuid.UUID | None = None


def resolve_anchor(quote: Quote) -> datetime | None:
    """Return the instant the revival clock starts for this quote.

    ``issue_date`` is the customer-visible document date and the thing price
    validity is measured against, so it wins when present. A quote issued in the
    future has not aged at all and is skipped by the caller.
    """
    if quote.issue_date is not None:
        return datetime.combine(quote.issue_date, time.min, tzinfo=UTC)
    return quote.sent_at


def due_touches(
    config: QuoteRevivalSettings,
    *,
    anchor: datetime,
    now: datetime,
    completed_offsets: set[int],
) -> list[QuoteRevivalTouchSettings]:
    """Return unprocessed touches that have come due, oldest first.

    ``max_touches`` is applied against the configured ladder rather than against
    what already ran, so lowering it stops the sequence early instead of
    re-opening touches an operator has already retired.
    """
    if now < anchor:
        return []
    allowed = config.touches[: config.max_touches]
    if len(completed_offsets) >= config.max_touches:
        return []
    return [
        touch
        for touch in allowed
        if touch.offset_days not in completed_offsets
        and anchor + timedelta(days=touch.offset_days) <= now
    ]


def eligibility_stop_reason(quote: Quote, *, now: datetime) -> str | None:
    """Return why this quote is out of scope, judged from its own columns alone.

    DB-free and cheap, so it runs before any opt-out, conversation, or
    appointment lookup. The window rail lives here rather than in the offset
    validator because the two sequences count from different anchors.
    """
    if quote.status in {"approved", "declined"}:
        return f"quote_{quote.status}"
    if quote.status not in REVIVABLE_STATUSES:
        return "quote_not_revivable"
    if post_estimate_window_is_open(quote.sent_at, now=now):
        return POST_ESTIMATE_WINDOW_STOP_REASON
    return None


def resolve_template_id(
    touch: QuoteRevivalTouchSettings,
    *,
    quote_total: float,
    high_value_threshold: float,
) -> uuid.UUID | None:
    """Pick the high-value approach for big quotes, with a routine fallback."""
    if quote_total >= high_value_threshold and touch.high_value_template_id is not None:
        return touch.high_value_template_id
    return touch.template_id


class UnsoldQuoteWorker(RetryableWorker, BaseWorker):
    """Work issued-but-undecided quotes on a configurable long-range ladder."""

    POLL_INTERVAL_SECONDS = 3600  # hourly; this cadence moves in days, not minutes
    COMPONENT_NAME = "unsold_quote_worker"
    MAX_CONCURRENCY = 5
    max_retries = 3
    backoff_base_seconds = 2.0

    def __init__(self) -> None:
        super().__init__()
        self.opt_out_manager = OptOutManager()
        self.compliance = OutboundComplianceService(self.opt_out_manager)
        self.number_pool = NumberPoolManager()

    async def _process_items(self) -> None:
        """Load aged, undecided quotes and process the newest due touch for each."""
        now = datetime.now(UTC)
        # ``expired`` is only stamped lazily by the quote service, so age is
        # computed from the dates rather than trusted from the status column.
        anchor_expr = func.coalesce(Quote.issue_date, cast(Quote.sent_at, Date))
        processed = 0
        cursor: tuple[date, uuid.UUID] | None = None

        async with AsyncSessionLocal() as db:
            while processed < MAX_QUOTES_PER_TICK:
                # Only the workspace is eager-loaded. Contact columns are
                # encrypted, and a single row written under a retired key raises
                # while the result set is materialized — which would abort the
                # whole tick before any per-quote error handling could contain it.
                statement = (
                    select(Quote)
                    .join(Quote.workspace)
                    .options(contains_eager(Quote.workspace))
                    .where(
                        and_(
                            Quote.status.in_(REVIVABLE_STATUSES),
                            Quote.sent_at.is_not(None),
                            # Presented long enough ago that the first-14-days
                            # cadence has finished with it, whatever it is dated.
                            Quote.sent_at <= now - timedelta(days=POST_ESTIMATE_WINDOW_DAYS),
                            anchor_expr.is_not(None),
                            anchor_expr <= now.date(),
                            anchor_expr > now.date() - timedelta(days=MAX_QUOTE_AGE_DAYS),
                            # Disabled workspaces are discarded below anyway;
                            # excluding them in SQL stops them consuming pages.
                            # Text comparison, not a boolean cast: a cast raises
                            # on a hand-edited value, and this predicate spans
                            # every workspace, so one bad row would kill the
                            # fetch for all of them.
                            Workspace.settings[REVIVAL_SETTINGS_KEY]["enabled"].astext == "true",
                        )
                    )
                    .order_by(anchor_expr, Quote.id)
                    .limit(QUOTE_PAGE_SIZE)
                )
                if cursor is not None:
                    statement = statement.where(tuple_(anchor_expr, Quote.id) > cursor)

                quotes = list((await db.execute(statement)).unique().scalars().all())
                if not quotes:
                    return

                for quote in quotes:
                    config = get_quote_revival_config(quote.workspace)
                    if not config.enabled:
                        continue
                    await self.execute_with_retry(
                        self._process_quote,
                        quote,
                        config,
                        now,
                        db,
                        item_key=derive_worker_retry_key("unsold_quote_revival", quote.id),
                    )

                last = quotes[-1]
                last_anchor = last.issue_date or (
                    last.sent_at.date() if last.sent_at is not None else None
                )
                if last_anchor is None:
                    return
                cursor = (last_anchor, last.id)
                processed += len(quotes)
                if len(quotes) < QUOTE_PAGE_SIZE:
                    return

        self.logger.warning(
            "Unsold-quote tick hit its ceiling; some due quotes went unworked",
            processed=processed,
            ceiling=MAX_QUOTES_PER_TICK,
        )

    async def _process_quote(
        self,
        quote: Quote,
        config: QuoteRevivalSettings,
        now: datetime,
        db: AsyncSession,
    ) -> None:
        """Stop, dedupe, and execute at most one customer-facing touch."""
        log = self.logger.bind(quote_id=str(quote.id), workspace_id=str(quote.workspace_id))
        anchor = resolve_anchor(quote)
        if anchor is None or anchor > now:
            return

        try:
            contact = await self._load_contact(quote, db)
        except InvalidToken:
            # Encrypted under a key this deployment no longer holds. Retrying
            # cannot help, so skip this quote loudly and keep the tick alive.
            log.warning("Skipping quote whose contact cannot be decrypted")
            return
        recipient = resolve_quote_recipient(quote, contact=contact)

        stop_reason = await self._get_stop_reason(quote, recipient, now, db)
        if stop_reason:
            log.info("Unsold-quote revival halted", reason=stop_reason)
            return

        completed_offsets = await self._completed_offsets(quote.id, db)
        pending = due_touches(
            config,
            anchor=anchor,
            now=now,
            completed_offsets=completed_offsets,
        )
        if not pending:
            return

        # After downtime several offsets can be due at once. Record the older
        # ones as superseded and send only the newest so nobody gets a burst.
        for stale_touch in pending[:-1]:
            await self._record_touch(
                quote=quote,
                touch=stale_touch,
                template_id=None,
                result=RevivalDeliveryResult(
                    outcome="skipped_stale",
                    reason="newer_touch_due",
                ),
                now=now,
                db=db,
            )
        if len(pending) > 1:
            await db.commit()

        # Re-read the decision columns immediately before the side effect: a
        # stale broad-fetch row must never message a quote that just closed.
        await db.refresh(quote, attribute_names=["status", "approved_at", "declined_at"])
        stop_reason = await self._get_stop_reason(quote, recipient, now, db)
        if stop_reason:
            log.info("Unsold-quote revival halted before dispatch", reason=stop_reason)
            return

        touch = pending[-1]
        template_id = resolve_template_id(
            touch,
            quote_total=float(quote.total or 0),
            high_value_threshold=config.high_value_threshold,
        )
        result = await self._dispatch_touch(
            quote=quote,
            recipient=recipient,
            touch=touch,
            template_id=template_id,
            config=config,
            now=now,
            db=db,
        )
        if result is None:
            return

        await self._record_touch(
            quote=quote,
            touch=touch,
            template_id=template_id,
            result=result,
            now=now,
            db=db,
        )
        if quote.contact_id is not None:
            await TagService(db).add_tag_to_contact(
                workspace_id=quote.workspace_id,
                contact_id=quote.contact_id,
                name=REVIVED_TAG,
            )
        await db.commit()
        self.record_items_processed()
        log.info(
            "Unsold-quote revival touch processed",
            offset_days=touch.offset_days,
            channel=touch.channel,
            outcome=result.outcome,
        )

    async def _get_stop_reason(
        self,
        quote: Quote,
        recipient: QuoteRecipient,
        now: datetime,
        db: AsyncSession,
    ) -> str | None:
        """Return the first reason this quote must be left alone."""
        eligibility_reason = eligibility_stop_reason(quote, now=now)
        if eligibility_reason:
            return eligibility_reason

        if recipient.phone and await self.opt_out_manager.check_opt_out(
            quote.workspace_id, recipient.phone, db
        ):
            return "contact_opted_out"

        if await self._has_recent_reply(quote, recipient, now, db):
            return "contact_replied"

        if quote.contact_id is not None:
            appointment_result = await db.execute(
                select(
                    exists().where(
                        and_(
                            Appointment.workspace_id == quote.workspace_id,
                            Appointment.contact_id == quote.contact_id,
                            Appointment.status == AppointmentStatus.SCHEDULED,
                        )
                    )
                )
            )
            if bool(appointment_result.scalar()):
                return "appointment_booked"
        return None

    async def _has_recent_reply(
        self,
        quote: Quote,
        recipient: QuoteRecipient,
        now: datetime,
        db: AsyncSession,
    ) -> bool:
        """Detect a live conversation this sequence must not talk over.

        Measured from the last revival touch when there is one — a reply to our
        own nudge means a human should take it from here. Before the first
        touch, an old quote may legitimately have months of unrelated history,
        so only genuinely recent inbound traffic blocks the sequence.
        """
        last_touch_at = await db.scalar(
            select(func.max(QuoteFollowupTouch.processed_at)).where(
                QuoteFollowupTouch.quote_id == quote.id,
                QuoteFollowupTouch.sequence_key == SEQUENCE_UNSOLD_REVIVAL,
            )
        )
        cutoff = last_touch_at or now - timedelta(days=FRESH_REPLY_WINDOW_DAYS)

        conversation_identity = []
        if quote.contact_id is not None:
            conversation_identity.append(Conversation.contact_id == quote.contact_id)
        if recipient.phone:
            conversation_identity.append(
                Conversation.contact_phone_hash == hash_phone(recipient.phone)
            )
        if not conversation_identity:
            return False

        result = await db.execute(
            select(
                exists().where(
                    and_(
                        Message.conversation_id == Conversation.id,
                        Conversation.workspace_id == quote.workspace_id,
                        or_(*conversation_identity),
                        Message.direction == MessageDirection.INBOUND,
                        Message.created_at >= cutoff,
                    )
                )
            )
        )
        return bool(result.scalar())

    async def _dispatch_touch(
        self,
        *,
        quote: Quote,
        recipient: QuoteRecipient,
        touch: QuoteRevivalTouchSettings,
        template_id: uuid.UUID | None,
        config: QuoteRevivalSettings,
        now: datetime,
        db: AsyncSession,
    ) -> RevivalDeliveryResult | None:
        """Run one call-task, SMS, or email touch; ``None`` means retry later."""
        if touch.channel == "call":
            return await self._create_call_task(quote, recipient, touch, config, now, db)

        compliance_result = await self.compliance.evaluate_direct(
            DirectOutboundComplianceRequest(
                workspace_id=quote.workspace_id,
                contact_id=quote.contact_id,
                phone_number=recipient.phone,
                sms_consent_status=recipient.sms_consent_status,
                channel=touch.channel,
                action_type="unsold_quote_revival",
                now=now,
                quiet_hours_start=config.quiet_hours_start,
                quiet_hours_end=config.quiet_hours_end,
                timezone=config.timezone or workspace_timezone_name(quote.workspace),
            ),
            db,
        )
        if not compliance_result.allowed:
            self.logger.info(
                "Unsold-quote touch deferred by compliance",
                quote_id=str(quote.id),
                offset_days=touch.offset_days,
                reason=compliance_result.reason,
            )
            return None

        template = await self._load_template(quote.workspace_id, template_id, db)
        if template is None:
            self.logger.warning(
                "Unsold-quote touch missing saved template",
                quote_id=str(quote.id),
                offset_days=touch.offset_days,
            )
            return None
        body = render_revival_template(
            template.message_template,
            quote=quote,
            recipient=recipient,
            now=now,
        )

        if touch.channel == "sms":
            return await self._send_sms(quote, recipient, touch, body, db)
        if touch.channel == "email":
            return await self._send_email(quote, recipient, touch, body)
        raise ValueError(f"Unsupported quote revival channel: {touch.channel}")

    async def _send_sms(
        self,
        quote: Quote,
        recipient: QuoteRecipient,
        touch: QuoteRevivalTouchSettings,
        body: str,
        db: AsyncSession,
    ) -> RevivalDeliveryResult | None:
        """Send one compliant, idempotent SMS from the contact's familiar number."""
        if not recipient.phone:
            return None
        to_number = normalize_phone_safe(recipient.phone)
        if not to_number:
            self.logger.warning("Revival phone is not valid E.164", quote_id=str(quote.id))
            return None

        from_number = await self._resolve_sms_number(quote, db)
        if not from_number:
            self.logger.warning("No SMS sender for unsold-quote revival", quote_id=str(quote.id))
            return None
        if not await self._reserve_sender(from_number, quote, db):
            # No ledger row, so the touch stays due and retries on a later tick.
            return None

        sms = get_text_message_provider()
        try:
            message = await sms.send_message(
                to_number=to_number,
                from_number=from_number,
                body=body,
                db=db,
                workspace_id=quote.workspace_id,
                idempotency_key=derive_outbound_key(
                    "unsold_quote_revival_sms",
                    quote.id,
                    touch.offset_days,
                ),
            )
        finally:
            await sms.close()

        if message.status in {MessageStatus.FAILED, MessageStatus.FAILED.value}:
            return RevivalDeliveryResult(
                outcome="failed",
                reason="provider_failed",
                message_id=message.id,
            )
        return RevivalDeliveryResult(outcome="sent", message_id=message.id)

    async def _send_email(
        self,
        quote: Quote,
        recipient: QuoteRecipient,
        touch: QuoteRevivalTouchSettings,
        body: str,
    ) -> RevivalDeliveryResult | None:
        """Send one idempotent template-based revival email."""
        if not recipient.email:
            self.logger.warning("Revival touch has no email destination", quote_id=str(quote.id))
            return None
        workspace_name = quote.workspace.name if quote.workspace else "our team"
        sent = await send_automation_email(
            to_email=recipient.email,
            subject=f"Your quote {quote.number} from {workspace_name}",
            body=body,
            idempotency_key=derive_outbound_key(
                "unsold_quote_revival_email",
                quote.id,
                touch.offset_days,
            ),
        )
        return RevivalDeliveryResult(outcome="sent") if sent else None

    async def _create_call_task(
        self,
        quote: Quote,
        recipient: QuoteRecipient,
        touch: QuoteRevivalTouchSettings,
        config: QuoteRevivalSettings,
        now: datetime,
        db: AsyncSession,
    ) -> RevivalDeliveryResult | None:
        """Create a visible HumanNudge prompting a real operator conversation."""
        if not recipient.phone:
            self.logger.warning("Revival call task has no phone", quote_id=str(quote.id))
            return None

        dedup_key = f"unsold-quote-revival:{quote.id}:{touch.offset_days}"
        result = await db.execute(
            select(HumanNudge).where(HumanNudge.dedup_key == dedup_key).limit(1)
        )
        nudge = result.scalar_one_or_none()
        if nudge is None:
            display_name = (
                " ".join(
                    part for part in (recipient.first_name, recipient.last_name) if part
                ).strip()
                or "the customer"
            )
            total = f"{float(quote.total or 0):,.2f} {quote.currency.upper()}"
            # Only suggest financing where the workspace actually offers it —
            # clearing every eligible category is how financing is switched off,
            # and telling a rep to pitch a product that no longer exists burns
            # the one revival call this quote gets.
            levers = "re-price, re-schedule, or walk through financing"
            if not financing_is_offered(get_pricing_config(quote.workspace)):
                levers = "re-price or re-schedule"
            nudge = HumanNudge(
                workspace_id=quote.workspace_id,
                contact_id=quote.contact_id,
                nudge_type="unsold_quote_revival",
                title=f"Revive quote {quote.number} with {display_name}",
                message=(
                    f"Quote {quote.number} for {total} has been open {touch.offset_days} days "
                    f"with no decision. Call {recipient.phone} — offer to {levers}."
                ),
                suggested_action="call",
                priority="high"
                if float(quote.total or 0) >= config.high_value_threshold
                else "medium",
                due_date=now,
                status="pending",
                assigned_to_user_id=quote.created_by_id,
                dedup_key=dedup_key,
            )
            db.add(nudge)
            await db.flush()

        return RevivalDeliveryResult(outcome="task_created", human_nudge_id=nudge.id)

    async def _resolve_sms_number(self, quote: Quote, db: AsyncSession) -> str | None:
        """Reuse a conversation sender, then fall back to any workspace SMS number."""
        if quote.contact_id is not None:
            from_number = await resolve_from_number(db, quote.contact_id, quote.workspace_id, None)
            if from_number:
                return from_number

        result = await db.execute(
            select(PhoneNumber.phone_number)
            .where(
                and_(
                    PhoneNumber.workspace_id == quote.workspace_id,
                    PhoneNumber.is_active.is_(True),
                    PhoneNumber.sms_enabled.is_(True),
                )
            )
            .order_by(PhoneNumber.created_at)
            .limit(1)
        )
        phone = result.scalar_one_or_none()
        return str(phone) if phone else None

    async def _reserve_sender(self, from_number: str, quote: Quote, db: AsyncSession) -> bool:
        """Consume this number's send allowance, mirroring the campaign worker.

        A 366-day revival window can hold far more due quotes than the
        first-14-days cadence, so an uncapped tick here is the larger burst risk
        of the two.
        """
        result = await db.execute(
            select(PhoneNumber).where(
                and_(
                    PhoneNumber.workspace_id == quote.workspace_id,
                    PhoneNumber.phone_number == from_number,
                )
            )
        )
        phone = result.scalar_one_or_none()
        if phone is None:
            # A thread can legitimately reference a sender this workspace no
            # longer tracks. Refusing would silently disable revival for those
            # contacts, which is a worse failure than an uncapped send we can see.
            self.logger.warning(
                "Revival sender is not a tracked number; sending uncapped",
                quote_id=str(quote.id),
            )
            return True

        if not await self.number_pool.reserve_number_for_send(phone, db):
            self.logger.info(
                "Revival touch deferred; sender at capacity",
                quote_id=str(quote.id),
                phone_number_id=str(phone.id),
            )
            return False
        return True

    @staticmethod
    async def _load_contact(quote: Quote, db: AsyncSession) -> Contact | None:
        """Materialize the encrypted contact row for exactly one quote."""
        if quote.contact_id is None:
            return None
        return await db.get(Contact, quote.contact_id)

    @staticmethod
    async def _load_template(
        workspace_id: uuid.UUID,
        template_id: uuid.UUID | None,
        db: AsyncSession,
    ) -> MessageTemplate | None:
        """Load a saved MessageTemplate only from the quote's workspace."""
        if template_id is None:
            return None
        result = await db.execute(
            select(MessageTemplate).where(
                MessageTemplate.id == template_id,
                MessageTemplate.workspace_id == workspace_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _completed_offsets(quote_id: uuid.UUID, db: AsyncSession) -> set[int]:
        """Read only revival rows; the post-estimate cadence shares this table."""
        result = await db.execute(
            select(QuoteFollowupTouch.offset_days).where(
                QuoteFollowupTouch.quote_id == quote_id,
                QuoteFollowupTouch.sequence_key == SEQUENCE_UNSOLD_REVIVAL,
            )
        )
        return set(result.scalars().all())

    @staticmethod
    async def _record_touch(
        *,
        quote: Quote,
        touch: QuoteRevivalTouchSettings,
        template_id: uuid.UUID | None,
        result: RevivalDeliveryResult,
        now: datetime,
        db: AsyncSession,
    ) -> None:
        """Insert one ledger row without duplicating a concurrent/retried touch."""
        statement = (
            pg_insert(QuoteFollowupTouch)
            .values(
                id=uuid.uuid4(),
                workspace_id=quote.workspace_id,
                quote_id=quote.id,
                sequence_key=SEQUENCE_UNSOLD_REVIVAL,
                offset_days=touch.offset_days,
                configured_channel=touch.channel,
                delivered_channel=touch.channel,
                outcome=result.outcome,
                reason=result.reason,
                message_template_id=template_id,
                message_id=result.message_id,
                human_nudge_id=result.human_nudge_id,
                processed_at=now,
                created_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_quote_followup_touches_quote_sequence_offset")
        )
        await db.execute(statement)


def render_revival_template(
    template: str,
    *,
    quote: Quote,
    recipient: QuoteRecipient,
    now: datetime,
) -> str:
    """Render revival placeholders on top of the shared quote placeholders.

    The extra fields exist so an operator can write price-validity and
    seasonal-urgency copy in a saved template instead of asking for new code.
    """
    rendered = render_quote_followup_template(template, quote=quote, recipient=recipient)
    anchor = resolve_anchor(quote)
    days_since = max((now - anchor).days, 0) if anchor is not None else 0
    expiry = quote.expiry_date.isoformat() if quote.expiry_date else ""
    for placeholder, value in (
        ("days_since_quote", str(days_since)),
        ("expiry_date", expiry),
    ):
        rendered = rendered.replace(f"{{{placeholder}}}", value)
    return rendered


_registry = WorkerRegistry(UnsoldQuoteWorker)
start_unsold_quote_worker = _registry.start
stop_unsold_quote_worker = _registry.stop
get_unsold_quote_worker = _registry.get
