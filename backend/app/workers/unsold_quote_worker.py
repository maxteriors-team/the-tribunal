"""Unsold-quote re-engagement worker.

Works quotes that were **issued and went quiet**. Every other re-engagement
worker in this package chases someone who never got that far — the never-booked
worker chases a reply with no appointment, the no-show worker chases a missed
one — while a sent estimate sat untouched until it aged into ``expired``. That
is the warmest, most expensive lead a home-services business owns: the drive
time is spent, the roof is measured, the price is agreed, and the only thing
missing is a decision.

Qualifying quotes:
  - Belong to an active workspace with ``unsold_quotes.enabled`` turned on
  - Are ``sent`` or ``expired`` — never ``draft`` (never shown to the customer),
    never ``approved``/``declined`` (the customer already decided)
  - Have an ``issue_date`` that has aged past the next configured touch
  - Belong to a contact with a phone number who has not opted out

Cadence (default 30 / 60 / 90 days after ``issue_date``, all configurable in
``workspace.settings["unsold_quotes"]``):

  - Touch state is per **quote**, keyed on the outbound idempotency key
    ``unsold_quote:<quote_id>:<touch_index>``. The unique constraint on
    ``messages.idempotency_key`` is therefore what guarantees a quote is never
    double-worked, even across a crash mid-send.
  - The contact is also tagged ``unsold-quote-touch-N`` after each send, the
    same lifecycle-tag discipline the no-show sequence uses, so the sequence is
    visible in the CRM and segmentable.
  - The sequence stops after the final configured touch. It never restarts.

Two spam rails beyond the cadence itself. A quote that is *already* older than
several offsets (the operator switched this on for a back catalogue) still gets
one touch per gap window rather than three texts in three hours. And only the
highest-value eligible quote per contact is worked per cycle, so a customer
holding three open estimates hears from us once, about the biggest one.

Message selection is two-dimensional: the **hook** (price validity, seasonal
scheduling, financing) comes from the touch, and the **band** (standard vs
high-value) comes from the quote total against the configured threshold — a
$12,000 project and a $1,500 job are not the same conversation. Copy itself
lives in the workspace's :class:`~app.models.message_template.MessageTemplate`
library; built-in copy is only the fallback when a template is unnamed or was
deleted.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.message_template import MessageTemplate
from app.models.phone_number import PhoneNumber
from app.models.quote import Quote
from app.models.workspace import Workspace
from app.schemas.unsold_quotes import (
    UnsoldQuoteBand,
    UnsoldQuoteSettings,
    UnsoldQuoteTouch,
    default_template_body,
)
from app.services.compliance.quiet_hours import is_within_quiet_hours
from app.services.idempotency import derive_outbound_key, derive_worker_retry_key
from app.services.outbound.delivery import (
    OutboundDeliveryChannel,
    OutboundDeliveryRequest,
    OutboundDeliveryStatus,
    outbound_delivery_service,
)
from app.services.quotes.unsold_quote_config import get_unsold_quote_config
from app.services.rate_limiting.opt_out_manager import OptOutManager
from app.services.tags import TagService
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker

# Quote statuses this worker may touch. ``draft`` was never sent, and
# ``approved``/``declined`` are decisions — chasing either is a support ticket.
WORKABLE_STATUSES: tuple[str, ...] = ("sent", "expired")

MAX_QUOTES_PER_TICK = 25

# Idempotency scope for the outbound send; combined with the quote id and the
# touch index this is the per-quote, per-touch dedupe key.
IDEMPOTENCY_SCOPE = "unsold_quote"
ACTION_TYPE = "unsold_quote_followup"

# Lifecycle tag applied after each touch (1-based, matching the copy operators
# see in settings).
TOUCH_TAG_PREFIX = "unsold-quote-touch-"


def touch_tag(touch_number: int) -> str:
    """Return the lifecycle tag recorded after touch ``touch_number`` (1-based)."""
    return f"{TOUCH_TAG_PREFIX}{touch_number}"


@dataclass(frozen=True, slots=True)
class WorkspaceContext:
    """Snapshot of everything a workspace contributes to a send.

    Taken before the first commit of the cycle: mid-loop commits expire ORM
    instances, and re-reading ``workspace.name`` lazily after one would emit a
    query per quote (or raise on a detached instance).
    """

    workspace_id: uuid.UUID
    name: str
    timezone: str | None
    config: UnsoldQuoteSettings


@dataclass(frozen=True, slots=True)
class Recipient:
    """Who a touch goes to, and which workspace number it goes from."""

    contact: Contact
    phone: str
    from_number: str


@dataclass(frozen=True, slots=True)
class TouchDecision:
    """The touch a quote is due for right now."""

    index: int
    touch: UnsoldQuoteTouch

    @property
    def number(self) -> int:
        """1-based touch number, as shown to operators and used in tags."""
        return self.index + 1


def quote_age_days(issue_date: date, today: date) -> int:
    """Whole days between a quote's issue date and ``today`` (never negative)."""
    return max(0, (today - issue_date).days)


def select_due_touch(
    touches: list[UnsoldQuoteTouch],
    *,
    age_days: int,
    sent_at_by_index: dict[int, datetime],
    now: datetime,
) -> TouchDecision | None:
    """Return the touch this quote is due for, or None to leave it alone.

    The sequence only ever moves forward: the next candidate is the one after
    the highest touch already sent, so a gap (a send that failed permanently)
    cannot pin the quote on touch 1 forever, and a completed sequence never
    restarts.

    Two gates keep the cadence honest:

    * **Age.** The quote must have aged past the touch's ``day_offset``.
    * **Spacing.** At least ``day_offset`` minus the previous touch's offset
      must have passed since the previous touch actually went out. Without this,
      switching the feature on for a 200-day-old back catalogue would fire every
      configured touch within the same afternoon.
    """
    if not touches:
        return None

    next_index = max(sent_at_by_index) + 1 if sent_at_by_index else 0
    if next_index >= len(touches):
        return None  # Final touch already sent — stop.

    touch = touches[next_index]
    if age_days < touch.day_offset:
        return None

    if next_index > 0:
        previous_sent_at = sent_at_by_index.get(next_index - 1)
        if previous_sent_at is not None:
            gap_days = max(1, touch.day_offset - touches[next_index - 1].day_offset)
            if previous_sent_at.tzinfo is None:
                previous_sent_at = previous_sent_at.replace(tzinfo=UTC)
            if now - previous_sent_at < timedelta(days=gap_days):
                return None

    return TouchDecision(index=next_index, touch=touch)


def _to_decimal(value: object) -> Decimal | None:
    """Coerce a Numeric/float/str money value to Decimal, or None when unusable."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def value_band(total: object, threshold: float) -> UnsoldQuoteBand:
    """Return the copy band for a quote total against the configured threshold.

    A quote whose total cannot be read is treated as standard: the small-job
    message is the safe one to send when the number is unknown.
    """
    amount = _to_decimal(total)
    if amount is None:
        return "standard"
    return "high_value" if amount >= Decimal(str(threshold)) else "standard"


def format_money(total: object, currency: str | None) -> str:
    """Format a quote total for SMS, dropping a meaningless ``.00``."""
    amount = _to_decimal(total)
    if amount is None:
        return ""
    whole = amount == amount.to_integral_value()
    rendered = f"{amount:,.0f}" if whole else f"{amount:,.2f}"
    code = (currency or "USD").upper()
    return f"${rendered}" if code == "USD" else f"{rendered} {code}"


def quote_link(public_token: str | None) -> str:
    """Return the public proposal URL for a quote, or an empty string."""
    if not public_token:
        return ""
    return f"{settings.frontend_url.rstrip('/')}/p/quotes/{public_token}"


def render_message(template: str, replacements: dict[str, str]) -> str:
    """Substitute ``{placeholder}`` tokens case-insensitively.

    Unknown placeholders are left in place rather than blanked: a visible
    ``{quote_total}`` in a test send tells the operator their template names a
    field we do not fill, where silent removal would ship a broken sentence.
    """
    message = template
    for placeholder, value in replacements.items():
        pattern = re.compile(rf"\{{{re.escape(placeholder)}\}}", re.IGNORECASE)
        # Lambda replacement: a literal string would have backslash escapes
        # (\1, \g<0>) interpreted, and contact data is not a regex template.
        message = pattern.sub(lambda _match, value=value: value, message)  # type: ignore[misc]
    return re.sub(r"[ \t]{2,}", " ", message).strip()


class UnsoldQuoteWorker(RetryableWorker, BaseWorker):
    """Background worker that re-engages quotes issued but never decided."""

    POLL_INTERVAL_SECONDS = 3600  # once per hour; touches are day-grained
    COMPONENT_NAME = "unsold_quote_worker"
    # Per-quote SMS sends; conservative to avoid spiking shared rate budgets.
    MAX_CONCURRENCY = 5
    max_retries = 3
    backoff_base_seconds = 2.0

    def __init__(self) -> None:
        super().__init__()
        self.opt_out_manager = OptOutManager()

    async def _process_items(self) -> None:
        """Process every workspace that has unsold-quote follow-up enabled."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Workspace).where(Workspace.is_active.is_(True)))
            contexts = [
                context
                for workspace in result.scalars().all()
                if (context := self._context_for(workspace)) is not None
            ]

            if not contexts:
                return

            for context in contexts:
                await self.execute_with_retry(
                    self._process_workspace,
                    context,
                    db,
                    item_key=derive_worker_retry_key(IDEMPOTENCY_SCOPE, context.workspace_id),
                )

    def _context_for(self, workspace: Workspace) -> WorkspaceContext | None:
        """Snapshot an enabled workspace's config, or None when it is off."""
        config = get_unsold_quote_config(workspace)
        if not config.enabled or not config.active_touches():
            return None
        workspace_settings = workspace.settings or {}
        raw_timezone = workspace_settings.get("timezone")
        return WorkspaceContext(
            workspace_id=workspace.id,
            name=workspace.name,
            timezone=raw_timezone if isinstance(raw_timezone, str) else None,
            config=config,
        )

    async def _process_workspace(self, context: WorkspaceContext, db: AsyncSession) -> None:
        """Send the due touch for each qualifying quote in one workspace."""
        log = self.logger.bind(workspace_id=str(context.workspace_id))
        config = context.config
        touches = config.active_touches()
        now = datetime.now(UTC)

        if is_within_quiet_hours(
            config.quiet_hours_start,
            config.quiet_hours_end,
            timezone_name=config.timezone or context.timezone,
            now=now,
        ):
            log.info("unsold_quote_quiet_hours_skip")
            return

        cutoff = now.date() - timedelta(days=touches[0].day_offset)
        quotes = await self._due_quotes(db, context.workspace_id, cutoff)
        if not quotes:
            return

        log.info("unsold_quote_candidates", count=len(quotes))
        for quote in quotes:
            await self.execute_with_retry(
                self._process_quote,
                context,
                quote,
                now,
                db,
                item_key=derive_worker_retry_key(
                    IDEMPOTENCY_SCOPE, context.workspace_id, "quote", quote.id
                ),
            )

    async def _due_quotes(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        cutoff: date,
    ) -> list[Quote]:
        """Load quotes old enough for at least the first touch, biggest first.

        De-duplicated by contact so a customer holding several open estimates
        gets one message about the largest, not one per quote.
        """
        result = await db.execute(
            select(Quote)
            .where(
                and_(
                    Quote.workspace_id == workspace_id,
                    Quote.status.in_(WORKABLE_STATUSES),
                    Quote.contact_id.is_not(None),
                    Quote.issue_date.is_not(None),
                    Quote.issue_date <= cutoff,
                )
            )
            .order_by(Quote.total.desc(), Quote.issue_date)
            .limit(MAX_QUOTES_PER_TICK)
        )

        by_contact: dict[int, Quote] = {}
        for quote in result.scalars().all():
            contact_id = quote.contact_id
            if contact_id is None or contact_id in by_contact:
                continue
            by_contact[contact_id] = quote
        return list(by_contact.values())

    async def _process_quote(
        self,
        context: WorkspaceContext,
        quote: Quote,
        now: datetime,
        db: AsyncSession,
    ) -> None:
        """Evaluate one quote and, when a touch is due, send it."""
        log = self.logger.bind(
            workspace_id=str(context.workspace_id),
            quote_id=str(quote.id),
            quote_number=quote.number,
        )
        touches = context.config.active_touches()

        decision = await self._due_touch(quote, touches, now, db, log)
        if decision is None:
            return

        recipient = await self._resolve_recipient(context, quote, db, log)
        if recipient is None:
            return

        band = value_band(quote.total, context.config.value_threshold)
        body = await self._build_body(db, context, quote, recipient.contact, decision, band)
        if not body:
            log.warning("unsold_quote_empty_body", touch=decision.number)
            return

        result = await outbound_delivery_service.deliver(
            db,
            OutboundDeliveryRequest(
                workspace_id=context.workspace_id,
                channel=OutboundDeliveryChannel.SMS,
                to=recipient.phone,
                from_=recipient.from_number,
                body=body,
                contact=recipient.contact,
                idempotency_scope=IDEMPOTENCY_SCOPE,
                idempotency_parts=(quote.id, decision.index),
                action_type=ACTION_TYPE,
                # This customer handed over their number to receive this very
                # quote, so an explicit SMS opt-in is not required here. The
                # global opt-out list is still enforced above and inside the
                # delivery compliance gate.
                require_sms_consent=False,
            ),
        )

        if result.status is OutboundDeliveryStatus.BLOCKED:
            log.info("unsold_quote_send_blocked", reason=result.reason, touch=decision.number)
            return
        if not result.delivered:
            log.warning("unsold_quote_send_failed", reason=result.reason, touch=decision.number)
            return

        await self._tag_contact(recipient.contact, touch_tag(decision.number), db)
        await db.commit()
        self.record_items_processed()
        log.info(
            "unsold_quote_touch_sent",
            touch=decision.number,
            hook=decision.touch.hook,
            band=band,
            final_touch=decision.number == len(touches),
        )

    async def _due_touch(
        self,
        quote: Quote,
        touches: list[UnsoldQuoteTouch],
        now: datetime,
        db: AsyncSession,
        log: Any,
    ) -> TouchDecision | None:
        """Return the touch this quote is due for, re-checking its status first."""
        if quote.status not in WORKABLE_STATUSES or quote.issue_date is None:
            # Re-checked after the query: a rep may have approved or declined
            # the quote while this cycle was mid-flight.
            log.debug("unsold_quote_status_not_workable", status=quote.status)
            return None

        sent_at_by_index = await self._sent_touch_times(db, quote.id, len(touches))
        return select_due_touch(
            touches,
            age_days=quote_age_days(quote.issue_date, now.date()),
            sent_at_by_index=sent_at_by_index,
            now=now,
        )

    async def _resolve_recipient(
        self,
        context: WorkspaceContext,
        quote: Quote,
        db: AsyncSession,
        log: Any,
    ) -> Recipient | None:
        """Resolve who to text and from which number, honouring the opt-out list."""
        contact = await db.get(Contact, quote.contact_id)
        if contact is None or contact.workspace_id != context.workspace_id:
            log.warning("unsold_quote_contact_missing")
            return None

        contact_phone = contact.phone_number
        if not contact_phone:
            log.info("unsold_quote_contact_has_no_phone", contact_id=contact.id)
            return None

        # TCPA compliance — the suppression list wins over any cadence.
        if await self.opt_out_manager.check_opt_out(context.workspace_id, contact_phone, db):
            log.info("unsold_quote_skipped_opted_out", contact_id=contact.id)
            return None

        from_number = await self._resolve_from_number(db, contact.id, context.workspace_id)
        if not from_number:
            log.warning("unsold_quote_no_from_number")
            return None

        return Recipient(contact=contact, phone=contact_phone, from_number=from_number)

    async def _sent_touch_times(
        self,
        db: AsyncSession,
        quote_id: uuid.UUID,
        touch_count: int,
    ) -> dict[int, datetime]:
        """Return ``{touch_index: sent_at}`` for touches already delivered.

        Read from ``messages.idempotency_key`` rather than a column on the quote:
        that key is what the send itself is deduped on, so worker state and
        provider state cannot disagree about whether a touch went out.
        """
        keys = {
            derive_outbound_key(IDEMPOTENCY_SCOPE, quote_id, index): index
            for index in range(touch_count)
        }
        if not keys:
            return {}

        result = await db.execute(
            select(Message.idempotency_key, Message.created_at).where(
                Message.idempotency_key.in_(list(keys))
            )
        )
        return {keys[key]: created_at for key, created_at in result.all() if key in keys}

    async def _build_body(
        self,
        db: AsyncSession,
        context: WorkspaceContext,
        quote: Quote,
        contact: Contact,
        decision: TouchDecision,
        band: UnsoldQuoteBand,
    ) -> str:
        """Resolve the template for this touch/band and render it for the quote."""
        template = await self._resolve_template(db, context.workspace_id, decision.touch, band)
        issue_date = quote.issue_date
        replacements = {
            "first_name": contact.first_name or "there",
            "last_name": contact.last_name or "",
            "company_name": contact.company_name or "",
            "business_name": context.name,
            "quote_number": quote.number,
            "quote_title": quote.title or "your project",
            "quote_total": format_money(quote.total, quote.currency),
            "quote_link": quote_link(quote.public_token),
            "issue_date": issue_date.isoformat() if issue_date else "",
            "expiry_date": quote.expiry_date.isoformat() if quote.expiry_date else "",
            "days_since_quote": str(decision.touch.day_offset),
        }
        return render_message(template, replacements)

    async def _resolve_template(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        touch: UnsoldQuoteTouch,
        band: UnsoldQuoteBand,
    ) -> str:
        """Return the operator's named template body, else the built-in copy."""
        name = touch.high_value_template_name if band == "high_value" else touch.template_name
        if name:
            result = await db.execute(
                select(MessageTemplate.message_template)
                .where(
                    and_(
                        MessageTemplate.workspace_id == workspace_id,
                        MessageTemplate.name == name,
                    )
                )
                .limit(1)
            )
            body = result.scalar_one_or_none()
            if body:
                return str(body)
            self.logger.warning(
                "unsold_quote_template_not_found",
                workspace_id=str(workspace_id),
                template_name=name,
            )
        return default_template_body(touch.hook, band)

    @staticmethod
    async def _tag_contact(contact: Contact, tag: str, db: AsyncSession) -> None:
        """Apply a normalized workspace tag to a contact idempotently."""
        await TagService(db).add_tag_to_contact(
            workspace_id=contact.workspace_id,
            contact_id=contact.id,
            name=tag,
        )

    async def _resolve_from_number(
        self,
        db: AsyncSession,
        contact_id: int,
        workspace_id: uuid.UUID,
    ) -> str | None:
        """Resolve the best from-number for the SMS.

        Strategy 1: Existing conversation with this contact (reuse same number).
        Strategy 2: Any active SMS-enabled workspace phone number.
        """
        result = await db.execute(
            select(Conversation.workspace_phone)
            .where(
                and_(
                    Conversation.contact_id == contact_id,
                    Conversation.workspace_id == workspace_id,
                )
            )
            .order_by(Conversation.last_message_at.desc().nulls_last())
            .limit(1)
        )
        phone = result.scalar_one_or_none()
        if phone:
            return str(phone)

        result = await db.execute(
            select(PhoneNumber.phone_number)
            .where(
                and_(
                    PhoneNumber.workspace_id == workspace_id,
                    PhoneNumber.is_active.is_(True),
                    PhoneNumber.sms_enabled.is_(True),
                )
            )
            .order_by(PhoneNumber.created_at)
            .limit(1)
        )
        phone = result.scalar_one_or_none()
        if phone:
            return str(phone)

        return None


# Singleton registry
_registry = WorkerRegistry(UnsoldQuoteWorker)
start_unsold_quote_worker = _registry.start
stop_unsold_quote_worker = _registry.stop
get_unsold_quote_worker = _registry.get
