"""First-14-days follow-up worker for sent quotes.

The sequence is anchored to ``Quote.sent_at`` and intentionally ends after the
calendar day for offset 14. That leaves a clean gap before the separate 30/60/90
unsold-quote revival window.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, exists, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from app.core.config import settings
from app.core.encryption import InvalidToken, hash_phone
from app.db.session import system_session
from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageDirection, MessageStatus
from app.models.human_nudge import HumanNudge
from app.models.message_template import MessageTemplate
from app.models.phone_number import PhoneNumber
from app.models.quote import Quote
from app.models.quote_followup_touch import SEQUENCE_POST_ESTIMATE, QuoteFollowupTouch
from app.models.workspace import Workspace
from app.schemas.quote_followup import (
    POST_ESTIMATE_MAX_OFFSET_DAYS,
    QuoteFollowupSettings,
    QuoteFollowupTouchSettings,
)
from app.services.calendar.reminder_service import resolve_from_number
from app.services.compliance.outbound_compliance import (
    DirectOutboundComplianceRequest,
    OutboundComplianceService,
)
from app.services.email import send_automation_email
from app.services.idempotency import derive_outbound_key, derive_worker_retry_key
from app.services.quotes.followup_config import SETTINGS_KEY, get_quote_followup_config
from app.services.rate_limiting.number_pool import NumberPoolManager
from app.services.rate_limiting.opt_out_manager import OptOutManager
from app.services.telephony.text_provider import get_text_message_provider
from app.utils.phone import normalize_phone_safe
from app.utils.timezones import workspace_timezone_name
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker

# Rows fetched per keyset page. The tick keeps paging until the due set is
# exhausted, so this is a memory bound, not a work ceiling.
QUOTE_PAGE_SIZE = 100
# Absolute per-tick ceiling, purely so a pathological dataset cannot spin
# forever. Crossing it is logged loudly because it means quotes went unworked.
MAX_QUOTES_PER_TICK = 5_000
# Offset 14 remains eligible through its calendar-day window, then this worker
# permanently leaves the quote alone. The next known revival window begins day 30.
ACTIVE_WINDOW_DAYS = POST_ESTIMATE_MAX_OFFSET_DAYS + 1


@dataclass(frozen=True, slots=True)
class QuoteRecipient:
    """Resolved customer fields from a linked contact or proposal snapshot."""

    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    sms_consent_status: str | None


@dataclass(frozen=True, slots=True)
class TouchDeliveryResult:
    """Outcome persisted in the quote follow-up execution ledger."""

    outcome: str
    reason: str | None = None
    message_id: uuid.UUID | None = None
    human_nudge_id: uuid.UUID | None = None


def post_estimate_window_is_open(sent_at: datetime | None, *, now: datetime) -> bool:
    """Return whether this cadence still owns the quote and no other may touch it.

    Measured from ``sent_at`` — the moment the customer actually received the
    estimate — because the long-range revival sequence is anchored to the
    document's ``issue_date``, which legitimately predates presentation (a quote
    written on-site and sent later, or a pre-booking hold converted months on).
    Comparing the two ladders by configured offset alone is not enough: the
    offsets are counted from different instants, so the rail has to live here.
    """
    if sent_at is None:
        return False
    return now < sent_at + timedelta(days=ACTIVE_WINDOW_DAYS)


def due_touches(
    config: QuoteFollowupSettings,
    *,
    sent_at: datetime,
    now: datetime,
    completed_offsets: set[int],
) -> list[QuoteFollowupTouchSettings]:
    """Return unprocessed touches due now, oldest to newest.

    The upper bound is exclusive at day 15: an offset-14 touch may run during
    its calendar-day window, but this worker can never drift toward day 30.
    """
    if now < sent_at or now >= sent_at + timedelta(days=ACTIVE_WINDOW_DAYS):
        return []
    return [
        touch
        for touch in config.touches
        if touch.offset_days not in completed_offsets
        and sent_at + timedelta(days=touch.offset_days) <= now
    ]


def resolve_quote_recipient(quote: Quote, *, contact: Contact | None) -> QuoteRecipient:
    """Resolve snapshot-first destinations consistently with quote delivery.

    The proposal snapshot wins over the linked contact because that is the
    address the client actually received the quote at; a quote can also carry a
    snapshot with no contact row at all.

    ``contact`` is passed in rather than read off ``quote.contact`` so callers
    stay in control of when the encrypted contact row is materialized.
    """
    client = (quote.proposal_document or {}).get("client") or {}

    def text_value(key: str, contact_value: str | None) -> str:
        raw = client.get(key)
        return str(raw).strip() if raw else (contact_value or "").strip()

    email = text_value("email", contact.email if contact else None) or None
    phone = text_value("phone", contact.phone_number if contact else None) or None
    return QuoteRecipient(
        first_name=text_value("first_name", contact.first_name if contact else None),
        last_name=text_value("last_name", contact.last_name if contact else None),
        email=email,
        phone=phone,
        sms_consent_status=contact.sms_consent_status if contact else None,
    )


def resolve_delivery_channel(
    touch: QuoteFollowupTouchSettings,
    *,
    quote_total: float,
    high_value_threshold: float,
) -> str:
    """Promote high-value SMS touches to human calls; preserve email and calls."""
    if touch.channel == "sms" and quote_total >= high_value_threshold:
        return "call"
    return touch.channel


def render_quote_followup_template(
    template: str,
    *,
    quote: Quote,
    recipient: QuoteRecipient,
) -> str:
    """Render supported saved-template placeholders without evaluating code."""
    proposal_url = (
        f"{settings.frontend_url.rstrip('/')}/p/quotes/{quote.public_token}"
        if quote.public_token
        else ""
    )
    workspace_name = quote.workspace.name if quote.workspace else "our team"
    replacements = {
        "first_name": recipient.first_name,
        "last_name": recipient.last_name,
        "quote_number": quote.number,
        "quote_total": f"{float(quote.total or 0):,.2f} {quote.currency.upper()}",
        "proposal_url": proposal_url,
        "company_name": workspace_name,
    }
    rendered = template
    for placeholder, value in replacements.items():
        rendered = rendered.replace(f"{{{placeholder}}}", value)
    return rendered


class PostEstimateFollowupWorker(RetryableWorker, BaseWorker):
    """Execute configured quote touches and create human call tasks."""

    POLL_INTERVAL_SECONDS = 300
    COMPONENT_NAME = "post_estimate_followup_worker"
    MAX_CONCURRENCY = 5
    max_retries = 3
    backoff_base_seconds = 2.0

    def __init__(self) -> None:
        super().__init__()
        self.opt_out_manager = OptOutManager()
        self.compliance = OutboundComplianceService(self.opt_out_manager)
        self.number_pool = NumberPoolManager()

    async def _process_items(self) -> None:
        """Work every due quote in the window, oldest first, in keyset pages.

        A single ``LIMIT`` here would silently starve the newest quotes: ordered
        by ``sent_at`` ascending, a one-day-old quote sits behind every older one
        in the window, so on a busy workspace its day-1 and day-3 touches — the
        highest-value touches in the whole cadence — would never run.
        """
        now = datetime.now(UTC)
        processed = 0
        cursor: tuple[datetime, uuid.UUID] | None = None

        async with system_session("post_estimate_followup_worker sweeps every workspace") as db:
            while processed < MAX_QUOTES_PER_TICK:
                # Only the workspace is eager-loaded. Contact columns are
                # encrypted, and one row written under a retired key raises while
                # the result set is materialized — which would abort the whole
                # tick before any per-quote error handling could contain it.
                statement = (
                    select(Quote)
                    .join(Quote.workspace)
                    .options(contains_eager(Quote.workspace))
                    .where(
                        and_(
                            Quote.status == "sent",
                            Quote.sent_at.is_not(None),
                            Quote.sent_at <= now,
                            Quote.sent_at > now - timedelta(days=ACTIVE_WINDOW_DAYS),
                            # Disabled workspaces are discarded below anyway;
                            # excluding them in SQL stops them consuming pages.
                            # ``enabled`` defaults to False, so a workspace with
                            # no config block is correctly out of scope.
                            #
                            # Compared as text rather than cast to boolean: a
                            # cast raises on a hand-edited value like "yes", and
                            # because this predicate spans every workspace, one
                            # bad row would kill the fetch for all of them. The
                            # validated PUT endpoint only ever writes a real JSON
                            # boolean, so anything else is out of contract and
                            # correctly reads as not-enabled.
                            Workspace.settings[SETTINGS_KEY]["enabled"].astext == "true",
                        )
                    )
                    .order_by(Quote.sent_at, Quote.id)
                    .limit(QUOTE_PAGE_SIZE)
                )
                if cursor is not None:
                    statement = statement.where(tuple_(Quote.sent_at, Quote.id) > cursor)

                quotes = list((await db.execute(statement)).unique().scalars().all())
                if not quotes:
                    return

                for quote in quotes:
                    config = get_quote_followup_config(quote.workspace)
                    if not config.enabled or quote.sent_at is None:
                        continue
                    await self.execute_with_retry(
                        self._process_quote,
                        quote,
                        config,
                        now,
                        db,
                        item_key=derive_worker_retry_key("post_estimate_followup", quote.id),
                    )

                last = quotes[-1]
                if last.sent_at is None:
                    return
                cursor = (last.sent_at, last.id)
                processed += len(quotes)
                if len(quotes) < QUOTE_PAGE_SIZE:
                    return

        self.logger.warning(
            "Post-estimate tick hit its ceiling; some due quotes went unworked",
            processed=processed,
            ceiling=MAX_QUOTES_PER_TICK,
        )

    async def _process_quote(
        self,
        quote: Quote,
        config: QuoteFollowupSettings,
        now: datetime,
        db: AsyncSession,
    ) -> None:
        """Stop, dedupe, and execute at most one customer-facing touch."""
        log = self.logger.bind(quote_id=str(quote.id), workspace_id=str(quote.workspace_id))
        sent_at = quote.sent_at
        if sent_at is None:
            return

        try:
            contact = await self._load_contact(quote, db)
        except InvalidToken:
            # Encrypted under a key this deployment no longer holds. Retrying
            # cannot help, so skip this quote loudly and keep the tick alive.
            log.warning("Skipping quote whose contact cannot be decrypted")
            return
        recipient = resolve_quote_recipient(quote, contact=contact)

        stop_reason = await self._get_stop_reason(quote, recipient, db)
        if stop_reason:
            log.info("Post-estimate sequence halted", reason=stop_reason)
            return

        completed_offsets = await self._completed_offsets(quote.id, db)
        pending = due_touches(
            config,
            sent_at=sent_at,
            now=now,
            completed_offsets=completed_offsets,
        )
        if not pending:
            return

        # Never burst old messages after downtime. Record superseded offsets and
        # execute only the newest due touch.
        for stale_touch in pending[:-1]:
            stale_channel = resolve_delivery_channel(
                stale_touch,
                quote_total=float(quote.total or 0),
                high_value_threshold=config.high_value_threshold,
            )
            await self._record_touch(
                quote=quote,
                touch=stale_touch,
                delivered_channel=stale_channel,
                result=TouchDeliveryResult(
                    outcome="skipped_stale",
                    reason="newer_touch_due",
                ),
                now=now,
                db=db,
            )
        if len(pending) > 1:
            await db.commit()

        # Re-read terminal status and every external stop signal immediately
        # before the side effect; a stale broad-fetch result must not message a win.
        await db.refresh(quote, attribute_names=["status", "approved_at", "declined_at"])
        stop_reason = await self._get_stop_reason(quote, recipient, db)
        if stop_reason:
            log.info("Post-estimate sequence halted before dispatch", reason=stop_reason)
            return

        touch = pending[-1]
        delivered_channel = resolve_delivery_channel(
            touch,
            quote_total=float(quote.total or 0),
            high_value_threshold=config.high_value_threshold,
        )
        result = await self._dispatch_touch(
            quote=quote,
            recipient=recipient,
            touch=touch,
            delivered_channel=delivered_channel,
            config=config,
            now=now,
            db=db,
        )
        if result is None:
            return

        await self._record_touch(
            quote=quote,
            touch=touch,
            delivered_channel=delivered_channel,
            result=result,
            now=now,
            db=db,
        )
        await db.commit()
        self.record_items_processed()
        log.info(
            "Post-estimate touch processed",
            offset_days=touch.offset_days,
            configured_channel=touch.channel,
            delivered_channel=delivered_channel,
            outcome=result.outcome,
        )

    async def _get_stop_reason(
        self,
        quote: Quote,
        recipient: QuoteRecipient,
        db: AsyncSession,
    ) -> str | None:
        """Return the first relationship-safe reason this sequence must halt."""
        if quote.status in {"approved", "declined"}:
            return f"quote_{quote.status}"
        if quote.status != "sent":
            return "quote_not_open"

        if recipient.phone and await self.opt_out_manager.check_opt_out(
            quote.workspace_id, recipient.phone, db
        ):
            return "contact_opted_out"

        if quote.sent_at is not None and await self._has_reply_after_quote(quote, recipient, db):
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

    async def _has_reply_after_quote(
        self,
        quote: Quote,
        recipient: QuoteRecipient,
        db: AsyncSession,
    ) -> bool:
        """Find any inbound message after presentation, including snapshot-only quotes."""
        if quote.sent_at is None:
            return False

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
                        Message.created_at >= quote.sent_at,
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
        touch: QuoteFollowupTouchSettings,
        delivered_channel: str,
        config: QuoteFollowupSettings,
        now: datetime,
        db: AsyncSession,
    ) -> TouchDeliveryResult | None:
        """Run one call-task, SMS, or email touch; ``None`` means retry later."""
        if delivered_channel == "call":
            return await self._create_call_task(quote, recipient, touch, now, db)

        compliance_result = await self.compliance.evaluate_direct(
            DirectOutboundComplianceRequest(
                workspace_id=quote.workspace_id,
                contact_id=quote.contact_id,
                phone_number=recipient.phone,
                sms_consent_status=recipient.sms_consent_status,
                channel=delivered_channel,
                action_type="post_estimate_followup",
                now=now,
                quiet_hours_start=config.quiet_hours_start,
                quiet_hours_end=config.quiet_hours_end,
                timezone=config.timezone or workspace_timezone_name(quote.workspace),
            ),
            db,
        )
        if not compliance_result.allowed:
            self.logger.info(
                "Post-estimate touch deferred by compliance",
                quote_id=str(quote.id),
                offset_days=touch.offset_days,
                reason=compliance_result.reason,
            )
            return None

        template = await self._load_template(quote.workspace_id, touch.template_id, db)
        if template is None:
            self.logger.warning(
                "Post-estimate touch missing saved template",
                quote_id=str(quote.id),
                offset_days=touch.offset_days,
            )
            return None
        body = render_quote_followup_template(
            template.message_template,
            quote=quote,
            recipient=recipient,
        )

        if delivered_channel == "sms":
            return await self._send_sms(quote, recipient, touch, body, db)
        if delivered_channel == "email":
            return await self._send_email(quote, recipient, touch, body)
        raise ValueError(f"Unsupported quote follow-up channel: {delivered_channel}")

    async def _send_sms(
        self,
        quote: Quote,
        recipient: QuoteRecipient,
        touch: QuoteFollowupTouchSettings,
        body: str,
        db: AsyncSession,
    ) -> TouchDeliveryResult | None:
        """Send one compliant, idempotent SMS from the contact's familiar number."""
        if not recipient.phone:
            return None
        to_number = normalize_phone_safe(recipient.phone)
        if not to_number:
            self.logger.warning("Quote follow-up phone is not valid E.164", quote_id=str(quote.id))
            return None

        from_number = await self._resolve_sms_number(quote, db)
        if not from_number:
            self.logger.warning("No SMS sender for quote follow-up", quote_id=str(quote.id))
            return None
        if not await self._reserve_sender(from_number, quote, db):
            # Returning None writes no ledger row, so the touch stays due and is
            # retried on a later tick rather than being silently consumed.
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
                    "post_estimate_followup_sms",
                    quote.id,
                    touch.offset_days,
                ),
            )
        finally:
            await sms.close()

        if message.status in {MessageStatus.FAILED, MessageStatus.FAILED.value}:
            return TouchDeliveryResult(
                outcome="failed",
                reason="provider_failed",
                message_id=message.id,
            )
        return TouchDeliveryResult(outcome="sent", message_id=message.id)

    async def _send_email(
        self,
        quote: Quote,
        recipient: QuoteRecipient,
        touch: QuoteFollowupTouchSettings,
        body: str,
    ) -> TouchDeliveryResult | None:
        """Send one idempotent template-based estimate follow-up email."""
        if not recipient.email:
            self.logger.warning("Quote follow-up has no email destination", quote_id=str(quote.id))
            return None
        workspace_name = quote.workspace.name if quote.workspace else "our team"
        sent = await send_automation_email(
            to_email=recipient.email,
            subject=f"Following up on quote {quote.number} from {workspace_name}",
            body=body,
            idempotency_key=derive_outbound_key(
                "post_estimate_followup_email",
                quote.id,
                touch.offset_days,
            ),
        )
        return TouchDeliveryResult(outcome="sent") if sent else None

    async def _create_call_task(
        self,
        quote: Quote,
        recipient: QuoteRecipient,
        touch: QuoteFollowupTouchSettings,
        now: datetime,
        db: AsyncSession,
    ) -> TouchDeliveryResult | None:
        """Create a visible HumanNudge prompting a real operator conversation."""
        if not recipient.phone:
            self.logger.warning("Quote follow-up call task has no phone", quote_id=str(quote.id))
            return None

        dedup_key = f"post-estimate-followup:{quote.id}:{touch.offset_days}"
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
            nudge = HumanNudge(
                workspace_id=quote.workspace_id,
                contact_id=quote.contact_id,
                nudge_type="quote_follow_up",
                title=f"Call {display_name} about quote {quote.number}",
                message=(
                    f"Quote {quote.number} for {total} is still open. Call {recipient.phone} "
                    "for a real conversation before sending another automated message."
                ),
                suggested_action="call",
                priority="high"
                if float(quote.total or 0)
                >= get_quote_followup_config(quote.workspace).high_value_threshold
                else "medium",
                due_date=now,
                status="pending",
                assigned_to_user_id=quote.assigned_user_id or quote.created_by_id,
                dedup_key=dedup_key,
            )
            db.add(nudge)
            await db.flush()

        return TouchDeliveryResult(
            outcome="task_created",
            reason="high_value_routing" if touch.channel == "sms" else None,
            human_nudge_id=nudge.id,
        )

    async def _resolve_sms_number(self, quote: Quote, db: AsyncSession) -> str | None:
        """Reuse a conversation sender, then fall back to any workspace SMS number."""
        if quote.contact_id is not None:
            from_number = await resolve_from_number(
                db,
                quote.contact_id,
                quote.workspace_id,
                None,
            )
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

    async def _reserve_sender(self, from_number: str, quote: Quote, db: AsyncSession) -> bool:
        """Consume this number's send allowance, mirroring the campaign worker.

        Enabling the cadence on a workspace with a backlog of in-window quotes
        would otherwise send one message per quote on the first tick, from a
        single number, ignoring its per-second/hourly/daily limits and warming
        schedule. The customer-facing harm is small; the carrier-reputation harm
        is not, and it degrades deliverability for every other message that
        number sends.
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
            # longer tracks. Refusing would silently disable follow-up for those
            # contacts, which is a worse failure than an uncapped send we can see.
            self.logger.warning(
                "Quote follow-up sender is not a tracked number; sending uncapped",
                quote_id=str(quote.id),
            )
            return True

        if not await self.number_pool.reserve_number_for_send(phone, db):
            self.logger.info(
                "Quote follow-up deferred; sender at capacity",
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
    async def _completed_offsets(quote_id: uuid.UUID, db: AsyncSession) -> set[int]:
        """Read only this sequence's rows; revival shares the ledger table."""
        result = await db.execute(
            select(QuoteFollowupTouch.offset_days).where(
                QuoteFollowupTouch.quote_id == quote_id,
                QuoteFollowupTouch.sequence_key == SEQUENCE_POST_ESTIMATE,
            )
        )
        return set(result.scalars().all())

    @staticmethod
    async def _record_touch(
        *,
        quote: Quote,
        touch: QuoteFollowupTouchSettings,
        delivered_channel: str,
        result: TouchDeliveryResult,
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
                sequence_key=SEQUENCE_POST_ESTIMATE,
                offset_days=touch.offset_days,
                configured_channel=touch.channel,
                delivered_channel=delivered_channel,
                outcome=result.outcome,
                reason=result.reason,
                message_template_id=touch.template_id,
                message_id=result.message_id,
                human_nudge_id=result.human_nudge_id,
                processed_at=now,
                created_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_quote_followup_touches_quote_sequence_offset")
        )
        await db.execute(statement)


_registry = WorkerRegistry(PostEstimateFollowupWorker)
start_post_estimate_followup_worker = _registry.start
stop_post_estimate_followup_worker = _registry.stop
get_post_estimate_followup_worker = _registry.get
