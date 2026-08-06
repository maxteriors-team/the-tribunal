"""Save a customer's card once; charge it later while they are not present.

Everything else in this product takes payment through a one-off hosted Checkout
link — the customer re-enters their card each time and nothing is retained. This
module is the other shape: the customer authorises us once, and afterwards a
deposit, a recurring-job invoice, or an operator pressing a button can move money
without them being at a keyboard.

Three properties are non-negotiable and are enforced here rather than by
convention:

**The card number never reaches this application.** The customer types it into a
Stripe-hosted iframe; the server only ever sees a ``pm_...`` handle and the
display metadata Stripe returns. Nothing in this file accepts, forwards, or
persists a PAN.

**Consent is recorded, not asserted.** Stripe requires the customer's written
agreement — covering that we may initiate payments for them, the timing and
frequency, how the amount is determined, and the cancellation policy — and
requires us to keep a record of it. That record is written from the request that
created the SetupIntent (server-observed IP and user agent, plus the version of
the wording they were shown), carried through Stripe metadata, and persisted onto
the saved card. A client cannot fabricate it by sending ``consented: true``.

**A hard decline is never retried on a timer.** Re-authorising a real person's
card on a loop is how a business earns card-network penalties. A decline is
recorded, the operator is told once, and the loop stops there. Only
``authentication_required`` is recoverable, because that PaymentIntent's client
secret can be handed back to the customer to finish.

Stripe objects live on the **platform** account. That is step 1 of Stripe's own
Connect path (save on the platform, clone to a connected account at charge time),
so nothing here has to be unwound when Connect lands — see
:mod:`app.services.payments.stripe_client` for the seam.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import stripe
import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.models.card_charge_attempt import (
    CHARGE_STATUS_DECLINED,
    CHARGE_STATUS_ERROR,
    CHARGE_STATUS_REQUIRES_ACTION,
    CHARGE_STATUS_SUCCEEDED,
    CardChargeAttempt,
)
from app.models.contact import Contact
from app.models.contact_card_setup_token import (
    CARD_SETUP_TOKEN_TTL_HOURS,
    ContactCardSetupToken,
    default_card_setup_expiry,
    generate_card_setup_token,
)
from app.models.contact_payment_method import (
    PAYMENT_METHOD_STATUS_ACTIVE,
    PAYMENT_METHOD_STATUS_REMOVED,
    ContactPaymentMethod,
)
from app.services.exceptions import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from app.services.payments.stripe_client import (
    is_payment_configured,
    stripe_client,
    to_minor_units,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Consent (the "written agreement" Stripe requires us to retain)
# ---------------------------------------------------------------------------

# Bump this whenever CARD_ON_FILE_MANDATE_TEXT changes in a way that alters what
# the customer is agreeing to. Every saved card stores the version it was taken
# under, so changing the wording later never rewrites what someone actually
# agreed to — and an old card can be identified as needing re-consent.
CARD_ON_FILE_MANDATE_VERSION = "2026-08-05.v1"

# Covers the four terms Stripe requires for off-session charging (agreement to
# initiate payments, anticipated timing and frequency, how the amount is
# determined, cancellation policy) **and** states that the authorisation extends
# to connected accounts on the platform. That last clause ships on day one on
# purpose: it cannot be added to already-saved cards without re-asking every
# customer, so leaving it out would make Stripe Connect a re-consent migration.
CARD_ON_FILE_MANDATE_TEXT = (
    "I authorize this business, and the payment platform it uses (including "
    "accounts connected to that platform), to store this payment method and to "
    "charge it when I am not present.\n\n"
    "When it is charged: for a deposit when I accept a quote or booking; for the "
    "balance of an invoice on or after its due date; for each visit of any "
    "recurring service I have agreed to; and for a missed-appointment fee where "
    "that fee has been disclosed to me in advance. These are not scheduled "
    "subscription payments — each charge follows work I have requested or an "
    "appointment I have booked.\n\n"
    "How much is charged: the amount shown on the quote, invoice, or fee notice "
    "for that specific job. Nothing is charged beyond the amount owed on a "
    "document I have been sent.\n\n"
    "Cancelling: I can withdraw this authorization at any time by contacting the "
    "business, which removes the stored card and stops all future automatic "
    "charges. Withdrawing it does not cancel work already completed or amounts "
    "already owed, which remain payable by other means."
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

# Outcomes of an off-session charge. Conflating the first three is the classic
# and expensive bug: "needs authentication" is recoverable, a hard decline is
# not, and neither is a success.
CHARGE_OUTCOME_SUCCEEDED = CHARGE_STATUS_SUCCEEDED
CHARGE_OUTCOME_REQUIRES_ACTION = CHARGE_STATUS_REQUIRES_ACTION
CHARGE_OUTCOME_DECLINED = CHARGE_STATUS_DECLINED
CHARGE_OUTCOME_ERROR = CHARGE_STATUS_ERROR
CHARGE_OUTCOME_NO_CARD = "no_card_on_file"
CHARGE_OUTCOME_SKIPPED_NO_AUTOMATION = "skipped_no_automation"


@dataclass(slots=True)
class SetupIntentResult:
    """A SetupIntent ready for the customer's browser to confirm.

    ``client_secret`` is scoped to one customer's card entry. It must never be
    logged, put in a URL, or returned to anyone but that customer.
    """

    client_secret: str
    setup_intent_id: str
    publishable_key: str


@dataclass(slots=True)
class ChargeResult:
    """Typed outcome of an off-session charge attempt.

    Returned rather than raised for every *expected* outcome — including "this
    contact has no card on file" — so callers (workers especially) branch on
    data instead of on exception types.
    """

    status: str
    amount: float
    currency: str
    attempt_id: uuid.UUID | None = None
    payment_intent_id: str | None = None
    # Only populated for ``requires_action``: the declined PaymentIntent's secret
    # is reusable, so the customer can be sent a link to authenticate. Treated as
    # a credential — never logged.
    client_secret: str | None = None
    decline_code: str | None = None
    message: str | None = None
    # Where to send the customer to finish a ``requires_action`` payment. A page
    # URL, never a secret: the customer authenticates through the same hosted
    # Stripe Checkout the public invoice page already opens.
    recovery_url: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == CHARGE_OUTCOME_SUCCEEDED


# ---------------------------------------------------------------------------
# Stripe Customer
# ---------------------------------------------------------------------------


async def ensure_stripe_customer(db: AsyncSession, contact: Contact) -> str:
    """Return this contact's Stripe Customer id, creating it on first use.

    One Customer per contact, reused across every card they save — calling this
    twice must not mint a second Customer, or a card saved today would be
    invisible to a charge tomorrow.
    """
    if not is_payment_configured():
        raise ServiceUnavailableError("Stripe is not configured for payments")

    if contact.stripe_customer_id:
        return contact.stripe_customer_id

    client = stripe_client()
    params: dict[str, Any] = {
        "name": contact.full_name,
        "metadata": {
            "contact_id": str(contact.id),
            "workspace_id": str(contact.workspace_id),
        },
    }
    # Email/phone are Fernet-encrypted at rest here but are plain values in
    # memory; Stripe needs them to send receipts and to help the operator
    # recognise the customer in the dashboard.
    if contact.email:
        params["email"] = contact.email
    if contact.phone_number:
        params["phone"] = contact.phone_number

    customer = client.customers.create(params=params)  # type: ignore[arg-type]
    contact.stripe_customer_id = customer.id
    await db.commit()

    logger.info(
        "stripe_customer_created",
        contact_id=contact.id,
        workspace_id=str(contact.workspace_id),
        customer_id=customer.id,
    )
    return customer.id


# ---------------------------------------------------------------------------
# Card-setup links (expiring, single-use)
# ---------------------------------------------------------------------------


async def mint_card_setup_token(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    contact_id: int,
    created_by_id: int | None = None,
) -> ContactCardSetupToken:
    """Issue a fresh card-setup link for a contact.

    Any outstanding unused links for the same contact are burned first. An
    operator re-sending the link means "the last one didn't work"; leaving the
    old one live would multiply the number of URLs that can open a card form for
    one customer.
    """
    contact = await db.get(Contact, contact_id)
    if contact is None or contact.workspace_id != workspace_id:
        raise NotFoundError("Contact not found")

    outstanding = await db.execute(
        select(ContactCardSetupToken).where(
            ContactCardSetupToken.contact_id == contact_id,
            ContactCardSetupToken.used_at.is_(None),
        )
    )
    now = datetime.now(UTC)
    for stale in outstanding.scalars().all():
        stale.used_at = now

    token = ContactCardSetupToken(
        workspace_id=workspace_id,
        contact_id=contact_id,
        token=generate_card_setup_token(),
        expires_at=default_card_setup_expiry(),
        created_by_id=created_by_id,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)

    logger.info(
        "card_setup_link_minted",
        contact_id=contact_id,
        workspace_id=str(workspace_id),
        expires_at=token.expires_at.isoformat(),
        ttl_hours=CARD_SETUP_TOKEN_TTL_HOURS,
    )
    return token


async def resolve_card_setup_token(db: AsyncSession, token: str) -> ContactCardSetupToken:
    """Load a usable card-setup token, or raise.

    An unknown token is a :class:`NotFoundError` and a spent or lapsed one is a
    :class:`ConflictError` — different states deserve different copy, since
    "this link has expired, ask for a new one" is actionable and "not found" is
    not. Both are refused **before** any Stripe call.
    """
    result = await db.execute(
        select(ContactCardSetupToken)
        .where(ContactCardSetupToken.token == token)
        # Eager: the public page reads the contact immediately, and a lazy load
        # under asyncio is a sync-IO error, not a slow query.
        .options(selectinload(ContactCardSetupToken.contact))
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise NotFoundError("This card setup link is not valid.")
    if not record.is_usable:
        raise ConflictError("This card setup link has expired. Ask the business to send a new one.")
    return record


async def burn_card_setup_token(db: AsyncSession, token: ContactCardSetupToken) -> None:
    """Mark a setup token spent. Called once a SetupIntent exists for it."""
    token.used_at = datetime.now(UTC)
    await db.commit()


# ---------------------------------------------------------------------------
# Saving a card
# ---------------------------------------------------------------------------


async def create_setup_intent(
    db: AsyncSession,
    contact: Contact,
    *,
    consent_accepted: bool,
    client_ip: str | None,
    user_agent: str | None,
) -> SetupIntentResult:
    """Create a SetupIntent so the customer can save a card for future charges.

    ``consent_accepted`` is checked **before** any Stripe call: refusing early
    means an unconsented request costs nothing and creates no billable object.
    The mandate details travel on the SetupIntent's metadata so that
    :func:`save_payment_method_from_setup_intent` — which runs later, from a
    webhook, with no access to the original request — can persist the record of
    what was agreed, when, and from where.

    ``usage="off_session"`` tells Stripe the card is being set up to be charged
    while the customer is away, which is what makes later off-session
    confirmation legitimate rather than a surprise re-authorisation.
    """
    if not consent_accepted:
        raise ValidationError("The card-on-file terms must be accepted before a card can be saved.")
    if not is_payment_configured():
        raise ServiceUnavailableError("Stripe is not configured for payments")

    customer_id = await ensure_stripe_customer(db, contact)
    client = stripe_client()

    accepted_at = datetime.now(UTC)
    intent = client.setup_intents.create(
        params={
            "customer": customer_id,
            "usage": "off_session",
            "payment_method_types": ["card"],
            "metadata": {
                "kind": "card_on_file",
                "contact_id": str(contact.id),
                "workspace_id": str(contact.workspace_id),
                "mandate_version": CARD_ON_FILE_MANDATE_VERSION,
                "mandate_accepted_at": accepted_at.isoformat(),
                # Server-observed. Truncated to the column widths so a hostile
                # user agent cannot overflow the insert later.
                "mandate_ip": (client_ip or "")[:45],
                "mandate_user_agent": (user_agent or "")[:512],
            },
        }
    )
    if not intent.client_secret:
        raise ServiceUnavailableError("Could not start card setup. Please try again.")

    # Deliberately logs the SetupIntent *id* and never the client secret.
    logger.info(
        "card_setup_intent_created",
        contact_id=contact.id,
        workspace_id=str(contact.workspace_id),
        setup_intent_id=intent.id,
        mandate_version=CARD_ON_FILE_MANDATE_VERSION,
    )
    from app.core.config import settings

    return SetupIntentResult(
        client_secret=intent.client_secret,
        setup_intent_id=intent.id,
        publishable_key=settings.stripe_publishable_key,
    )


def _card_display_fields(payment_method: Any) -> dict[str, Any]:
    """Extract brand / last4 / expiry from a Stripe PaymentMethod.

    Display metadata only. Stripe never returns a full card number, and this
    function is written so that even if it did, nothing but these four fields
    would ever be read out of it.
    """
    card = getattr(payment_method, "card", None)
    if card is None and isinstance(payment_method, dict):
        card = payment_method.get("card")
    if card is None:
        return {"brand": None, "last4": None, "exp_month": None, "exp_year": None}

    def _field(name: str) -> Any:
        if isinstance(card, dict):
            return card.get(name)
        return getattr(card, name, None)

    exp_month = _field("exp_month")
    exp_year = _field("exp_year")
    last4 = _field("last4")
    return {
        "brand": str(_field("brand"))[:20] if _field("brand") else None,
        # Hard-truncated to four characters: this column is display-only and
        # must be structurally incapable of holding a card number.
        "last4": str(last4)[-4:] if last4 else None,
        "exp_month": int(exp_month) if exp_month is not None else None,
        "exp_year": int(exp_year) if exp_year is not None else None,
    }


async def save_payment_method_from_setup_intent(
    db: AsyncSession,
    setup_intent: dict[str, Any],
) -> ContactPaymentMethod | None:
    """Persist the card a completed SetupIntent set up. Idempotent.

    Driven by the ``setup_intent.succeeded`` webhook, which Stripe retries on any
    perceived failure — so the second delivery of the same event must find the
    row already there and change nothing. Idempotency is keyed on the unique
    ``stripe_payment_method_id``.

    Returns ``None`` (rather than raising) when the event is not ours or its
    contact has since been deleted: a webhook that raises is a webhook Stripe
    retries forever.
    """
    metadata = setup_intent.get("metadata") or {}
    payment_method_id = setup_intent.get("payment_method")
    if not isinstance(payment_method_id, str) or not payment_method_id:
        logger.warning(
            "card_setup_webhook_no_payment_method",
            setup_intent_id=setup_intent.get("id"),
        )
        return None
    if metadata.get("kind") != "card_on_file":
        # Some other SetupIntent (a future flow, or the Stripe dashboard). Not ours.
        return None

    existing = await db.execute(
        select(ContactPaymentMethod).where(
            ContactPaymentMethod.stripe_payment_method_id == payment_method_id
        )
    )
    saved = existing.scalar_one_or_none()
    if saved is not None:
        logger.info(
            "card_setup_webhook_replay_ignored",
            payment_method_id=payment_method_id,
            contact_payment_method_id=str(saved.id),
        )
        return saved

    resolved = await _resolve_setup_owner(db, setup_intent, metadata)
    if resolved is None:
        return None
    contact, customer_id = resolved

    display = _card_display_fields(_retrieve_payment_method(payment_method_id))

    # First card a contact saves becomes their default: a workspace with one
    # card on file must never have to pick one before charging.
    has_default = await db.execute(
        select(ContactPaymentMethod.id).where(
            ContactPaymentMethod.contact_id == contact.id,
            ContactPaymentMethod.status == PAYMENT_METHOD_STATUS_ACTIVE,
            ContactPaymentMethod.is_default.is_(True),
        )
    )
    is_default = has_default.scalar_one_or_none() is None

    method = ContactPaymentMethod(
        workspace_id=contact.workspace_id,
        contact_id=contact.id,
        stripe_payment_method_id=payment_method_id,
        stripe_customer_id=customer_id,
        is_default=is_default,
        status=PAYMENT_METHOD_STATUS_ACTIVE,
        mandate_text_version=str(metadata.get("mandate_version") or CARD_ON_FILE_MANDATE_VERSION),
        mandate_accepted_at=_parse_timestamp(metadata.get("mandate_accepted_at")),
        mandate_ip=(metadata.get("mandate_ip") or None),
        mandate_user_agent=(metadata.get("mandate_user_agent") or None),
        **display,
    )
    db.add(method)
    try:
        await db.commit()
    except IntegrityError:
        # Two deliveries of the same event raced past the SELECT above. The
        # unique constraint on stripe_payment_method_id is the real guard; fall
        # back to whichever insert won.
        await db.rollback()
        replay = await db.execute(
            select(ContactPaymentMethod).where(
                ContactPaymentMethod.stripe_payment_method_id == payment_method_id
            )
        )
        return replay.scalar_one_or_none()

    logger.info(
        "card_on_file_saved",
        contact_id=contact.id,
        workspace_id=str(contact.workspace_id),
        payment_method_id=payment_method_id,
        brand=display["brand"],
        mandate_version=method.mandate_text_version,
    )
    return method


async def _resolve_setup_owner(
    db: AsyncSession,
    setup_intent: dict[str, Any],
    metadata: dict[str, Any],
) -> tuple[Contact, str] | None:
    """Resolve the contact and Stripe Customer a completed SetupIntent belongs to.

    Returns ``None`` when either is unresolvable, which is a dead-letter case for
    the webhook rather than an error: the contact may have been deleted between
    the customer saving their card and Stripe telling us about it.
    """
    contact = await _resolve_contact(db, metadata)
    if contact is None:
        logger.warning(
            "card_setup_webhook_no_contact",
            setup_intent_id=setup_intent.get("id"),
            contact_id=metadata.get("contact_id"),
        )
        return None

    customer_id = setup_intent.get("customer")
    if not isinstance(customer_id, str) or not customer_id:
        customer_id = contact.stripe_customer_id or ""
    if not customer_id:
        logger.warning("card_setup_webhook_no_customer", setup_intent_id=setup_intent.get("id"))
        return None
    return contact, customer_id


def _retrieve_payment_method(payment_method_id: str) -> Any:
    """Fetch a PaymentMethod for its display metadata. Never raises."""
    try:
        return stripe_client().payment_methods.retrieve(payment_method_id)
    except stripe.StripeError as exc:
        # A saved card with no brand/last4 is still chargeable; losing the label
        # is far better than dropping the card because a read timed out.
        logger.warning(
            "card_payment_method_retrieve_failed",
            payment_method_id=payment_method_id,
            error=str(exc),
        )
        return None


async def _resolve_contact(db: AsyncSession, metadata: dict[str, Any]) -> Contact | None:
    """Resolve the contact a SetupIntent belongs to from its metadata."""
    raw_id = metadata.get("contact_id")
    if not raw_id:
        return None
    try:
        contact_id = int(raw_id)
    except (TypeError, ValueError):
        return None
    return await db.get(Contact, contact_id)


def _parse_timestamp(value: Any) -> datetime:
    """Parse an ISO timestamp from Stripe metadata, defaulting to now."""
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return datetime.now(UTC)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Reading / managing saved cards
# ---------------------------------------------------------------------------


async def list_payment_methods(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    contact_id: int,
) -> list[ContactPaymentMethod]:
    """List a contact's active saved cards, default first."""
    result = await db.execute(
        select(ContactPaymentMethod)
        .where(
            ContactPaymentMethod.workspace_id == workspace_id,
            ContactPaymentMethod.contact_id == contact_id,
            ContactPaymentMethod.status == PAYMENT_METHOD_STATUS_ACTIVE,
        )
        .order_by(
            ContactPaymentMethod.is_default.desc(),
            ContactPaymentMethod.created_at.desc(),
        )
    )
    return list(result.scalars().all())


async def get_default_payment_method(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    contact_id: int,
) -> ContactPaymentMethod | None:
    """Return the card to charge for this contact, or ``None``.

    Falls back to the most recently saved active card when no default is flagged,
    so a data hiccup degrades to "charge their newest card" rather than "this
    customer silently has no card".
    """
    methods = await list_payment_methods(db, workspace_id=workspace_id, contact_id=contact_id)
    return methods[0] if methods else None


async def _get_owned_method(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    contact_id: int,
    payment_method_id: uuid.UUID,
) -> ContactPaymentMethod:
    """Load a saved card, enforcing tenant + contact ownership.

    A foreign card 404s exactly like a missing one, so workspace A can never
    discover — let alone charge — workspace B's saved card.
    """
    result = await db.execute(
        select(ContactPaymentMethod).where(
            ContactPaymentMethod.id == payment_method_id,
            ContactPaymentMethod.workspace_id == workspace_id,
            ContactPaymentMethod.contact_id == contact_id,
        )
    )
    method = result.scalar_one_or_none()
    if method is None:
        raise NotFoundError("Payment method not found")
    return method


async def set_default_payment_method(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    contact_id: int,
    payment_method_id: uuid.UUID,
) -> ContactPaymentMethod:
    """Make one saved card the default, clearing the previous one."""
    method = await _get_owned_method(
        db,
        workspace_id=workspace_id,
        contact_id=contact_id,
        payment_method_id=payment_method_id,
    )
    if method.status != PAYMENT_METHOD_STATUS_ACTIVE:
        raise ConflictError("That card is no longer active")

    others = await db.execute(
        select(ContactPaymentMethod).where(
            ContactPaymentMethod.contact_id == contact_id,
            ContactPaymentMethod.id != method.id,
            ContactPaymentMethod.is_default.is_(True),
        )
    )
    # Cleared before the new default is set: the partial unique index permits
    # exactly one default active card per contact, so the order matters.
    for other in others.scalars().all():
        other.is_default = False
    await db.flush()
    method.is_default = True
    await db.commit()
    return method


async def remove_payment_method(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    contact_id: int,
    payment_method_id: uuid.UUID,
) -> ContactPaymentMethod:
    """Detach a saved card at Stripe and mark it removed here.

    A soft delete: the row survives because charge attempts reference it and
    those are the evidence trail for money already taken. Stripe detachment is
    best-effort — if it fails, the card is still unusable through this product,
    which is the property that matters to the customer who asked us to forget it.
    """
    method = await _get_owned_method(
        db,
        workspace_id=workspace_id,
        contact_id=contact_id,
        payment_method_id=payment_method_id,
    )
    if method.status == PAYMENT_METHOD_STATUS_REMOVED:
        return method

    if is_payment_configured():
        try:
            stripe_client().payment_methods.detach(method.stripe_payment_method_id)
        except stripe.StripeError as exc:
            logger.warning(
                "card_detach_failed",
                payment_method_id=method.stripe_payment_method_id,
                error=str(exc),
            )

    was_default = method.is_default
    method.status = PAYMENT_METHOD_STATUS_REMOVED
    method.is_default = False
    method.removed_at = datetime.now(UTC)
    await db.flush()

    # Promote the next card so removing the default does not silently leave the
    # contact unchargeable while still showing cards on file.
    if was_default:
        remaining = await list_payment_methods(db, workspace_id=workspace_id, contact_id=contact_id)
        if remaining:
            remaining[0].is_default = True
    await db.commit()

    logger.info(
        "card_on_file_removed",
        contact_id=contact_id,
        workspace_id=str(workspace_id),
        payment_method_id=method.stripe_payment_method_id,
    )
    return method


# ---------------------------------------------------------------------------
# Charging a saved card off-session
# ---------------------------------------------------------------------------


async def charge_saved_card(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    contact_id: int,
    amount: float,
    currency: str,
    description: str,
    trigger: str,
    idempotency_key: str,
    automated: bool,
    invoice_id: uuid.UUID | None = None,
    payment_method_id: uuid.UUID | None = None,
) -> ChargeResult:
    """Charge a contact's saved card while they are not present.

    Returns a :class:`ChargeResult` for every expected outcome and raises only
    for programmer error (a non-positive amount) or an unconfigured Stripe. A
    worker iterating a list of customers must not have its loop broken by one
    customer who never saved a card.

    ``automated`` distinguishes a worker or trigger from an operator pressing a
    button. Automated charges honour the ``no-automation`` contact tag — a
    customer flagged for human-only handling must never be silently charged by a
    background job — while an explicit operator action is unaffected, matching
    that tag's documented meaning (it mutes automation, not the human).

    ``idempotency_key`` is the safety rail and is used twice: to short-circuit on
    an attempt already recorded here, and as Stripe's own idempotency key so a
    retry that gets past us still cannot mint a second PaymentIntent.

    A hard decline is recorded and reported, and **no retry is scheduled**.
    """
    if amount <= 0:
        raise ValidationError("Charge amount must be greater than zero")
    if not is_payment_configured():
        raise ServiceUnavailableError("Stripe is not configured for payments")

    # Replay guard first: cheaper than Stripe and correct even if Stripe is down.
    replay = await _find_attempt(db, idempotency_key)
    if replay is not None:
        return _result_from_attempt(replay)

    if automated:
        from app.services.automations.opt_out import automation_suppressed

        if await automation_suppressed(db, workspace_id, contact_id):
            logger.info(
                "card_charge_skipped_no_automation",
                contact_id=contact_id,
                workspace_id=str(workspace_id),
                trigger=trigger,
            )
            return ChargeResult(
                status=CHARGE_OUTCOME_SKIPPED_NO_AUTOMATION,
                amount=amount,
                currency=currency,
                message="This contact is tagged no-automation, so automatic charges are off.",
            )

    if payment_method_id is not None:
        method: ContactPaymentMethod | None = await _get_owned_method(
            db,
            workspace_id=workspace_id,
            contact_id=contact_id,
            payment_method_id=payment_method_id,
        )
        if method is not None and method.status != PAYMENT_METHOD_STATUS_ACTIVE:
            method = None
    else:
        method = await get_default_payment_method(
            db, workspace_id=workspace_id, contact_id=contact_id
        )

    if method is None:
        return ChargeResult(
            status=CHARGE_OUTCOME_NO_CARD,
            amount=amount,
            currency=currency,
            message="No card on file for this contact.",
        )

    return await _confirm_off_session(
        db,
        method=method,
        amount=amount,
        currency=currency,
        description=description,
        trigger=trigger,
        idempotency_key=idempotency_key,
        invoice_id=invoice_id,
    )


async def _confirm_off_session(
    db: AsyncSession,
    *,
    method: ContactPaymentMethod,
    amount: float,
    currency: str,
    description: str,
    trigger: str,
    idempotency_key: str,
    invoice_id: uuid.UUID | None,
) -> ChargeResult:
    """Confirm a PaymentIntent against a saved card and record the outcome.

    Split from :func:`charge_saved_card` so the eligibility checks (replay,
    opt-out, card present) and the money-moving call read as separate concerns:
    everything above decides *whether* to charge, everything here deals with what
    Stripe answered.
    """
    workspace_id = method.workspace_id
    contact_id = method.contact_id
    client = stripe_client()
    params: dict[str, Any] = {
        "amount": to_minor_units(amount, currency),
        "currency": currency.lower(),
        "customer": method.stripe_customer_id,
        "payment_method": method.stripe_payment_method_id,
        # The two flags that make this a merchant-initiated transaction rather
        # than an abandoned checkout: confirm now, and tell Stripe the customer
        # is not here to authenticate.
        "off_session": True,
        "confirm": True,
        "description": description,
        "metadata": {
            "kind": "card_on_file",
            "trigger": trigger,
            "contact_id": str(contact_id),
            "workspace_id": str(workspace_id),
            "idempotency_key": idempotency_key,
            **({"invoice_id": str(invoice_id)} if invoice_id else {}),
        },
    }

    attempt_kwargs: dict[str, Any] = {
        "workspace_id": workspace_id,
        "contact_id": contact_id,
        "payment_method_id": method.id,
        "amount": amount,
        "currency": currency,
        "idempotency_key": idempotency_key,
        "trigger": trigger,
        "invoice_id": invoice_id,
    }

    try:
        intent = client.payment_intents.create(
            params=params,  # type: ignore[arg-type]
            options={"idempotency_key": idempotency_key},
        )
    except stripe.CardError as exc:
        return await _record_card_error(db, exc, **attempt_kwargs)
    except stripe.StripeError as exc:
        # Not a card decline: a rate limit, an API outage, a bad request. The
        # money did not move, but we may not know that for certain, so the row is
        # written as ``error`` and the webhook reconciler can correct it.
        logger.warning(
            "card_charge_stripe_error",
            contact_id=contact_id,
            workspace_id=str(workspace_id),
            trigger=trigger,
            error=str(exc),
        )
        attempt = await _record_attempt(
            db,
            status=CHARGE_STATUS_ERROR,
            failure_message=str(exc.user_message or exc),
            **attempt_kwargs,
        )
        return _result_from_attempt(attempt)

    status_value = str(getattr(intent, "status", "") or "")
    if status_value != "succeeded":
        # Reached when Stripe accepts the confirmation but the intent still needs
        # something (rare for off_session, which normally raises instead).
        attempt = await _record_attempt(
            db,
            status=CHARGE_STATUS_REQUIRES_ACTION,
            stripe_payment_intent_id=intent.id,
            failure_message=f"PaymentIntent is {status_value}",
            **attempt_kwargs,
        )
        return ChargeResult(
            status=CHARGE_OUTCOME_REQUIRES_ACTION,
            amount=amount,
            currency=currency,
            attempt_id=attempt.id,
            payment_intent_id=intent.id,
            client_secret=getattr(intent, "client_secret", None),
            message="This payment needs the customer to confirm it.",
            recovery_url=await recovery_url_for_invoice(db, invoice_id),
        )

    attempt = await _record_attempt(
        db,
        status=CHARGE_STATUS_SUCCEEDED,
        stripe_payment_intent_id=intent.id,
        **attempt_kwargs,
    )
    logger.info(
        "card_charge_succeeded",
        contact_id=contact_id,
        workspace_id=str(workspace_id),
        trigger=trigger,
        amount=amount,
        currency=currency,
        payment_intent_id=intent.id,
    )
    return ChargeResult(
        status=CHARGE_OUTCOME_SUCCEEDED,
        amount=amount,
        currency=currency,
        attempt_id=attempt.id,
        payment_intent_id=intent.id,
    )


async def _record_card_error(
    db: AsyncSession,
    exc: stripe.CardError,
    **attempt_kwargs: Any,
) -> ChargeResult:
    """Turn a Stripe ``CardError`` into a recorded attempt and a typed result.

    The fork that matters: ``authentication_required`` means the customer can
    still complete this payment — the failed PaymentIntent's client secret is
    reusable, so we hand back a recovery path instead of writing the money off.
    Every other code is a hard decline: recorded, reported once, not retried.
    """
    error = getattr(exc, "error", None)
    code = str(getattr(error, "code", None) or getattr(exc, "code", None) or "")
    decline_code = getattr(error, "decline_code", None)
    intent = getattr(error, "payment_intent", None)
    intent_id = _intent_field(intent, "id")
    message = str(exc.user_message or exc)

    if code == "authentication_required":
        attempt = await _record_attempt(
            db,
            status=CHARGE_STATUS_REQUIRES_ACTION,
            stripe_payment_intent_id=intent_id,
            decline_code=code,
            failure_message=message,
            **attempt_kwargs,
        )
        logger.info(
            "card_charge_requires_authentication",
            contact_id=attempt_kwargs.get("contact_id"),
            trigger=attempt_kwargs.get("trigger"),
            payment_intent_id=intent_id,
        )
        return ChargeResult(
            status=CHARGE_OUTCOME_REQUIRES_ACTION,
            amount=float(attempt_kwargs["amount"]),
            currency=str(attempt_kwargs["currency"]),
            attempt_id=attempt.id,
            payment_intent_id=intent_id,
            client_secret=_intent_field(intent, "client_secret"),
            decline_code=code,
            message=message,
            recovery_url=await recovery_url_for_invoice(db, attempt_kwargs.get("invoice_id")),
        )

    attempt = await _record_attempt(
        db,
        status=CHARGE_STATUS_DECLINED,
        stripe_payment_intent_id=intent_id,
        decline_code=str(decline_code or code or "card_declined")[:64],
        failure_message=message,
        **attempt_kwargs,
    )
    logger.warning(
        "card_charge_declined",
        contact_id=attempt_kwargs.get("contact_id"),
        workspace_id=str(attempt_kwargs.get("workspace_id")),
        trigger=attempt_kwargs.get("trigger"),
        decline_code=attempt.decline_code,
    )
    # Told once, here, at the single point a hard decline is recorded — and then
    # nothing further happens. No retry is scheduled by design.
    await notify_charge_declined(db, attempt)
    return _result_from_attempt(attempt)


async def recovery_url_for_invoice(
    db: AsyncSession,
    invoice_id: uuid.UUID | None,
) -> str | None:
    """Return where to send a customer whose charge needs authentication.

    ``authentication_required`` is not a lost sale: the customer only has to
    complete 3-D Secure. Rather than inventing a second payment surface, this
    points at their existing public invoice page, whose Pay button opens a fresh
    hosted Checkout Session where the bank prompt happens on Stripe's own domain.

    Returns ``None`` when the charge has no invoice behind it (a bare deposit or
    fee), in which case the operator has to reach out — which the decline notice
    says.
    """
    if invoice_id is None:
        return None
    from app.core.config import settings
    from app.models.invoice import Invoice

    invoice = await db.get(Invoice, invoice_id)
    if invoice is None or not invoice.public_token:
        return None
    return f"{settings.frontend_url.rstrip('/')}/p/invoices/{invoice.public_token}"


def _intent_field(intent: Any, name: str) -> str | None:
    """Read a field off the PaymentIntent attached to a CardError."""
    if intent is None:
        return None
    value = intent.get(name) if isinstance(intent, dict) else getattr(intent, name, None)
    return str(value) if value else None


async def _find_attempt(db: AsyncSession, idempotency_key: str) -> CardChargeAttempt | None:
    result = await db.execute(
        select(CardChargeAttempt).where(CardChargeAttempt.idempotency_key == idempotency_key)
    )
    return result.scalar_one_or_none()


async def _record_attempt(
    db: AsyncSession,
    *,
    status: str,
    workspace_id: uuid.UUID,
    contact_id: int,
    payment_method_id: uuid.UUID | None,
    amount: float,
    currency: str,
    idempotency_key: str,
    trigger: str,
    invoice_id: uuid.UUID | None = None,
    stripe_payment_intent_id: str | None = None,
    decline_code: str | None = None,
    failure_message: str | None = None,
) -> CardChargeAttempt:
    """Write the attempt row. Survives a racing duplicate by reusing the winner."""
    attempt = CardChargeAttempt(
        workspace_id=workspace_id,
        contact_id=contact_id,
        payment_method_id=payment_method_id,
        stripe_payment_intent_id=stripe_payment_intent_id,
        amount=amount,
        currency=currency,
        status=status,
        decline_code=decline_code,
        failure_message=failure_message,
        idempotency_key=idempotency_key,
        trigger=trigger,
        invoice_id=invoice_id,
    )
    db.add(attempt)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await _find_attempt(db, idempotency_key)
        if existing is None:  # pragma: no cover - only reachable on a non-unique failure
            raise
        return existing
    return attempt


def _result_from_attempt(attempt: CardChargeAttempt) -> ChargeResult:
    """Project a persisted attempt back onto its typed result.

    Note the deliberate absence of ``client_secret``: it is never persisted, so a
    replayed ``requires_action`` cannot resurrect one. The recovery link is
    issued at the moment of the original failure or not at all.
    """
    return ChargeResult(
        status=attempt.status,
        amount=float(attempt.amount),
        currency=attempt.currency,
        attempt_id=attempt.id,
        payment_intent_id=attempt.stripe_payment_intent_id,
        decline_code=attempt.decline_code,
        message=attempt.failure_message,
    )


async def notify_charge_declined(db: AsyncSession, attempt: CardChargeAttempt) -> None:
    """Tell the workspace a card on file was declined (push + email, once).

    Best-effort and never raises: this runs inside a webhook and inside worker
    loops, and a mail outage must not turn a recorded decline into an exception
    that gets retried. The per-attempt idempotency key means a replay of the same
    attempt cannot send a second email.
    """
    from app.models.user import User
    from app.models.workspace import Workspace, WorkspaceMembership
    from app.services.email import send_event_notification_email
    from app.services.idempotency import derive_outbound_key
    from app.services.push_notifications import push_notification_service

    amount_str = f"{float(attempt.amount):.2f} {attempt.currency.upper()}"
    contact = await db.get(Contact, attempt.contact_id)
    who = contact.full_name if contact else "a customer"

    try:
        await push_notification_service.send_to_workspace_members(
            db=db,
            workspace_id=str(attempt.workspace_id),
            title="Card on file declined",
            body=f"{amount_str} for {who} was declined"[:300],
            data={"type": "payment", "screen": "/(tabs)/invoices"},
            notification_type="payment",
            channel_id="alerts",
        )
    except Exception as exc:  # pragma: no cover - best-effort push
        logger.warning("card_decline_push_failed", error=str(exc))

    try:
        workspace = await db.get(Workspace, attempt.workspace_id)
        members = await db.execute(
            select(User)
            .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
            .where(WorkspaceMembership.workspace_id == attempt.workspace_id)
        )
        for user in members.scalars().all():
            if not user.notification_email or not user.email:
                continue
            await send_event_notification_email(
                to_email=user.email,
                subject=f"Card declined — {amount_str}",
                heading="A saved card was declined",
                intro=(
                    f"We tried to charge {who}'s card on file for {amount_str} and it was "
                    "declined. Nothing was charged and no automatic retry is scheduled — "
                    "reach out to the customer or take payment another way."
                ),
                details={
                    "Customer": who,
                    "Amount": amount_str,
                    "Reason": attempt.decline_code or "declined",
                    "Workspace": workspace.name if workspace else "",
                },
                idempotency_key=derive_outbound_key("card_decline_email", attempt.id, user.id),
            )
    except Exception as exc:  # pragma: no cover - best-effort email
        logger.warning("card_decline_email_failed", error=str(exc))


async def reconcile_failed_payment_intent(
    db: AsyncSession,
    payment_intent: dict[str, Any],
) -> CardChargeAttempt | None:
    """Reconcile a ``payment_intent.payment_failed`` event onto an attempt row.

    Covers the case the synchronous path cannot: the network dropped between
    Stripe charging and us hearing the answer, so no row (or an ``error`` row)
    exists for a charge that really did fail. Resolves by the idempotency key we
    put in metadata, falling back to the PaymentIntent id.

    Idempotent — an attempt already recorded as declined is left untouched.
    """
    metadata = payment_intent.get("metadata") or {}
    if metadata.get("kind") != "card_on_file":
        return None

    attempt: CardChargeAttempt | None = None
    key = metadata.get("idempotency_key")
    if key:
        attempt = await _find_attempt(db, str(key))
    intent_id = payment_intent.get("id")
    if attempt is None and intent_id:
        found = await db.execute(
            select(CardChargeAttempt).where(
                CardChargeAttempt.stripe_payment_intent_id == str(intent_id)
            )
        )
        attempt = found.scalar_one_or_none()

    error = payment_intent.get("last_payment_error") or {}
    decline_code = error.get("decline_code") or error.get("code") or "card_declined"
    message = error.get("message")

    if attempt is None:
        # The synchronous path never got to write anything. Rebuild the row from
        # the event so the failure is not invisible.
        attempt = await _attempt_from_event(db, payment_intent, metadata, decline_code, message)
        if attempt is None:
            logger.warning("card_charge_failed_webhook_no_match", payment_intent_id=intent_id)
            return None
        await notify_charge_declined(db, attempt)
        return attempt

    if attempt.status == CHARGE_STATUS_DECLINED:
        return attempt

    attempt.status = CHARGE_STATUS_DECLINED
    attempt.decline_code = str(decline_code)[:64]
    attempt.failure_message = message
    if intent_id and not attempt.stripe_payment_intent_id:
        attempt.stripe_payment_intent_id = str(intent_id)
    await db.commit()
    logger.info(
        "card_charge_reconciled_from_webhook",
        attempt_id=str(attempt.id),
        payment_intent_id=intent_id,
        decline_code=attempt.decline_code,
    )
    await notify_charge_declined(db, attempt)
    return attempt


async def _attempt_from_event(
    db: AsyncSession,
    payment_intent: dict[str, Any],
    metadata: dict[str, Any],
    decline_code: str,
    message: str | None,
) -> CardChargeAttempt | None:
    """Build a declined attempt row from a webhook the sync path never saw."""
    from app.services.payments.stripe_client import from_minor_units

    contact = await _resolve_contact(db, metadata)
    if contact is None:
        return None
    intent_id = str(payment_intent.get("id") or "")
    currency = str(payment_intent.get("currency") or "usd").upper()
    amount_minor = payment_intent.get("amount") or 0
    invoice_raw = metadata.get("invoice_id")
    invoice_id: uuid.UUID | None = None
    if invoice_raw:
        try:
            invoice_id = uuid.UUID(str(invoice_raw))
        except ValueError:
            invoice_id = None

    return await _record_attempt(
        db,
        status=CHARGE_STATUS_DECLINED,
        workspace_id=contact.workspace_id,
        contact_id=contact.id,
        payment_method_id=None,
        amount=from_minor_units(int(amount_minor), currency),
        currency=currency,
        # Prefer the original key so a late webhook and a late retry of the same
        # charge still collapse onto one row.
        idempotency_key=str(metadata.get("idempotency_key") or f"pi:{intent_id}"),
        trigger=str(metadata.get("trigger") or "manual"),
        invoice_id=invoice_id,
        stripe_payment_intent_id=intent_id or None,
        decline_code=str(decline_code)[:64],
        failure_message=message,
    )
