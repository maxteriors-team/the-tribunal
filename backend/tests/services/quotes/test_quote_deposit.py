"""Real-DB integration tests for proposal deposit collection and recording.

Covers the Stripe-backed public flow plus authenticated-service semantics for
offline cash/check/other deposits: durable provenance, workspace scoping,
checkout expiry before manual recording, and a single atomic paid transition.
Marked ``integration`` and deselected by default; run with ``pytest -m integration``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_phone, hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.quote import Quote
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.quote import QuoteCreate, QuoteLineItemCreate
from app.services.exceptions import ConflictError, NotFoundError
from app.services.payments import quote_deposit_service as deposit
from app.services.payments.call_payment_service import (
    CheckoutSessionResult,
    SessionStatus,
)
from app.services.quotes import QuoteService

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    await engine.dispose()
    yield
    await engine.dispose()


async def _make_workspace(db: AsyncSession) -> Workspace:
    ws = Workspace(
        id=uuid.uuid4(),
        name="Maxteriors Lighting",
        slug=f"dep-{uuid.uuid4().hex[:8]}",
        settings={},
    )
    db.add(ws)
    await db.flush()
    return ws


async def _make_contact(db: AsyncSession, workspace_id: uuid.UUID) -> Contact:
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    email = f"client-{uuid.uuid4().hex[:8]}@example.com"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Dana",
        last_name="Homeowner",
        phone_number=phone,
        phone_hash=hash_phone(phone),
        email=email,
        email_hash=hash_value(email),
    )
    db.add(contact)
    await db.flush()
    return contact


async def _make_user(db: AsyncSession) -> User:
    email = f"operator-{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email=email,
        email_hash=hash_value(email),
        hashed_password="x",
        full_name="Deposit Recorder",
    )
    db.add(user)
    await db.flush()
    return user


async def _sent_quote_with_deposit(
    svc: QuoteService,
    workspace_id: uuid.UUID,
    contact_id: int,
    *,
    deposit_percentage: float | None = 30.0,
    expiry: date | None = None,
) -> tuple[str, uuid.UUID]:
    created = await svc.create_quote(
        workspace_id,
        QuoteCreate(
            contact_id=contact_id,
            title="Backyard lighting install",
            deposit_percentage=deposit_percentage,
            expiry_date=expiry,
            line_items=[
                QuoteLineItemCreate(name="Fixtures", quantity=6, unit_price=120.0),
                QuoteLineItemCreate(name="Labor", quantity=1, unit_price=400.0, discount=50.0),
            ],
        ),
    )
    sent = await svc.mark_sent(workspace_id, created.id)
    assert sent.public_token is not None
    return sent.public_token, created.id


async def test_public_payload_derives_deposit_amount() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        token, _ = await _sent_quote_with_deposit(svc, ws.id, contact.id)

        proposal = await svc.get_public_proposal(token)
        # total = 6*120 + (400-50) = 1070; 30% => 321.00
        assert proposal.total == 1070.0
        assert proposal.deposit_percentage == 30.0
        assert proposal.deposit_amount == 321.0
        assert proposal.deposit_paid is False


async def test_no_deposit_yields_null_amount() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        token, _ = await _sent_quote_with_deposit(svc, ws.id, contact.id, deposit_percentage=None)

        proposal = await svc.get_public_proposal(token)
        assert proposal.deposit_percentage is None
        assert proposal.deposit_amount is None
        assert proposal.deposit_paid is False


async def test_checkout_persists_session_and_returns_url(monkeypatch) -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        token, quote_id = await _sent_quote_with_deposit(svc, ws.id, contact.id)

        monkeypatch.setattr(deposit.call_payment_service, "is_payment_configured", lambda: True)

        async def _fake_session(**kwargs):
            # The amount handed to Stripe is the derived deposit (major units).
            assert kwargs["amount"] == 321.0
            assert kwargs["metadata"]["quote_id"] == str(quote_id)
            assert kwargs["metadata"]["kind"] == deposit.DEPOSIT_KIND
            return CheckoutSessionResult(
                session_id="cs_test_123",
                url="https://checkout.stripe.test/pay/cs_test_123",
                payment_intent_id="pi_test_123",
            )

        monkeypatch.setattr(
            deposit.call_payment_service, "create_payment_checkout_session", _fake_session
        )

        result = await deposit.create_deposit_checkout_session(db, token)
        assert result.url == "https://checkout.stripe.test/pay/cs_test_123"
        assert result.amount == 321.0

        refreshed = await db.get(Quote, quote_id)
        assert refreshed is not None
        assert refreshed.deposit_checkout_session_id == "cs_test_123"
        assert refreshed.deposit_payment_intent_id == "pi_test_123"
        assert refreshed.deposit_paid_at is None


async def test_webhook_marks_deposit_paid_idempotently(monkeypatch) -> None:
    notifications: list[dict[str, object]] = []

    async def _capture_notification(_db, **kwargs):
        notifications.append(kwargs)
        return 1

    monkeypatch.setattr(
        "app.services.payments.customer_payment_notifications.notify_customer_payment",
        _capture_notification,
    )

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        token, quote_id = await _sent_quote_with_deposit(svc, ws.id, contact.id)

        session = {
            "id": "cs_test_abc",
            "metadata": {"quote_id": str(quote_id), "kind": deposit.DEPOSIT_KIND},
            "payment_intent": "pi_test_abc",
        }
        await deposit.handle_deposit_checkout_session_completed(session, db)

        proposal = await svc.get_public_proposal(token)
        assert proposal.deposit_paid is True
        refreshed = await db.get(Quote, quote_id)
        assert refreshed is not None
        assert refreshed.deposit_payment_method == "card"
        assert refreshed.deposit_recorded_by_id is None
        assert notifications == [
            {
                "workspace_id": ws.id,
                "amount": 321.0,
                "currency": "USD",
                "description": f"Deposit on {proposal.number}",
                "idempotency_scope": "quote_deposit_operator_email",
                "idempotency_id": quote_id,
                "deep_link": "/(tabs)/quotes",
                "client_name": "Dana Homeowner",
                "client_email": contact.email,
                "client_phone": contact.phone_number,
                "quote_number": proposal.number,
            }
        ]

        # Idempotent: replaying the webhook keeps a single paid transition/email.
        first_paid_at = refreshed.deposit_paid_at
        await deposit.handle_deposit_checkout_session_completed(session, db)
        again = await db.get(Quote, quote_id)
        assert again.deposit_paid_at == first_paid_at
        assert len(notifications) == 1


async def test_manual_cash_deposit_records_operator_provenance(monkeypatch) -> None:
    notifications: list[dict[str, object]] = []

    async def _capture_notification(_db, **kwargs):
        notifications.append(kwargs)

    monkeypatch.setattr(
        "app.services.payments.customer_payment_notifications.notify_customer_payment",
        _capture_notification,
    )

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        operator = await _make_user(db)
        _, quote_id = await _sent_quote_with_deposit(QuoteService(db), ws.id, contact.id)

        recorded = await deposit.record_manual_deposit(
            db,
            ws.id,
            quote_id,
            payment_method="cash",
            recorded_by_id=operator.id,
        )

        assert recorded.deposit_paid_at is not None
        assert recorded.deposit_payment_method == "cash"
        assert recorded.deposit_recorded_by_id == operator.id
        assert recorded.deposit_payment_intent_id is None
        # The operator already knows they recorded it; customer-payment alerts are
        # reserved for unattended card transitions.
        assert notifications == []


async def test_manual_deposit_expires_open_card_checkout(monkeypatch) -> None:
    expired_sessions: list[str] = []

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        operator = await _make_user(db)
        _, quote_id = await _sent_quote_with_deposit(QuoteService(db), ws.id, contact.id)
        quote = await db.get(Quote, quote_id)
        assert quote is not None
        quote.deposit_checkout_session_id = "cs_open_manual"
        await db.commit()

        monkeypatch.setattr(deposit.call_payment_service, "is_payment_configured", lambda: True)

        async def _open_status(session_id: str) -> SessionStatus:
            assert session_id == "cs_open_manual"
            return SessionStatus(payment_status="unpaid", status="open", payment_intent_id=None)

        async def _expire(session_id: str) -> bool:
            expired_sessions.append(session_id)
            return True

        monkeypatch.setattr(deposit.call_payment_service, "retrieve_session_status", _open_status)
        monkeypatch.setattr(
            deposit.call_payment_service, "expire_checkout_session_if_open", _expire
        )

        recorded = await deposit.record_manual_deposit(
            db,
            ws.id,
            quote_id,
            payment_method="check",
            recorded_by_id=operator.id,
        )

        assert expired_sessions == ["cs_open_manual"]
        assert recorded.deposit_payment_method == "check"
        assert recorded.deposit_recorded_by_id == operator.id


async def test_paid_card_checkout_wins_over_manual_recording(monkeypatch) -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        operator = await _make_user(db)
        _, quote_id = await _sent_quote_with_deposit(QuoteService(db), ws.id, contact.id)
        quote = await db.get(Quote, quote_id)
        assert quote is not None
        quote.deposit_checkout_session_id = "cs_paid_before_cash"
        await db.commit()

        monkeypatch.setattr(deposit.call_payment_service, "is_payment_configured", lambda: True)

        async def _paid_status(_session_id: str) -> SessionStatus:
            return SessionStatus(
                payment_status="paid",
                status="complete",
                payment_intent_id="pi_wins",
            )

        monkeypatch.setattr(deposit.call_payment_service, "retrieve_session_status", _paid_status)

        recorded = await deposit.record_manual_deposit(
            db,
            ws.id,
            quote_id,
            payment_method="cash",
            recorded_by_id=operator.id,
        )

        assert recorded.deposit_payment_method == "card"
        assert recorded.deposit_payment_intent_id == "pi_wins"
        assert recorded.deposit_recorded_by_id is None


async def test_manual_deposit_is_workspace_scoped_and_single_transition() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        other_ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        operator = await _make_user(db)
        _, quote_id = await _sent_quote_with_deposit(QuoteService(db), ws.id, contact.id)

        with pytest.raises(NotFoundError):
            await deposit.record_manual_deposit(
                db,
                other_ws.id,
                quote_id,
                payment_method="other",
                recorded_by_id=operator.id,
            )

        await deposit.record_manual_deposit(
            db,
            ws.id,
            quote_id,
            payment_method="other",
            recorded_by_id=operator.id,
        )
        with pytest.raises(ConflictError):
            await deposit.record_manual_deposit(
                db,
                ws.id,
                quote_id,
                payment_method="cash",
                recorded_by_id=operator.id,
            )


async def test_checkout_rejects_bad_states(monkeypatch) -> None:
    monkeypatch.setattr(deposit.call_payment_service, "is_payment_configured", lambda: True)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)

        # No deposit requested.
        no_dep_token, _ = await _sent_quote_with_deposit(
            svc, ws.id, contact.id, deposit_percentage=None
        )
        with pytest.raises(deposit.DepositError):
            await deposit.create_deposit_checkout_session(db, no_dep_token)

        # Already paid.
        paid_token, paid_id = await _sent_quote_with_deposit(svc, ws.id, contact.id)
        paid = await db.get(Quote, paid_id)
        await deposit.mark_deposit_paid(db, paid)
        with pytest.raises(deposit.DepositError):
            await deposit.create_deposit_checkout_session(db, paid_token)

        # Expired proposal.
        exp_token, _ = await _sent_quote_with_deposit(
            svc, ws.id, contact.id, expiry=date.today() - timedelta(days=1)
        )
        await svc.get_public_proposal(exp_token)  # lazily flips to expired
        with pytest.raises(deposit.DepositError):
            await deposit.create_deposit_checkout_session(db, exp_token)


async def test_checkout_requires_stripe_configured(monkeypatch) -> None:
    monkeypatch.setattr(deposit.call_payment_service, "is_payment_configured", lambda: False)
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        token, _ = await _sent_quote_with_deposit(svc, ws.id, contact.id)
        with pytest.raises(deposit.DepositError):
            await deposit.create_deposit_checkout_session(db, token)


async def test_fixed_deposit_amount_clamps_to_total() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        # Fixed $500 deposit on a $1070 total resolves to exactly $500.
        created = await svc.create_quote(
            ws.id,
            QuoteCreate(
                contact_id=contact.id,
                title="Fixed deposit",
                deposit_amount_fixed=500.0,
                line_items=[
                    QuoteLineItemCreate(name="Fixtures", quantity=6, unit_price=120.0),
                    QuoteLineItemCreate(name="Labor", quantity=1, unit_price=400.0, discount=50.0),
                ],
            ),
        )
        sent = await svc.mark_sent(ws.id, created.id)
        proposal = await svc.get_public_proposal(sent.public_token)
        assert proposal.total == 1070.0
        assert proposal.deposit_percentage is None
        assert proposal.deposit_amount == 500.0
        assert proposal.deposit_required is True

        # A fixed deposit larger than the total is clamped down to the total.
        big = await svc.create_quote(
            ws.id,
            QuoteCreate(
                contact_id=contact.id,
                title="Oversized deposit",
                deposit_amount_fixed=99999.0,
                line_items=[QuoteLineItemCreate(name="Job", unit_price=200.0)],
            ),
        )
        big_sent = await svc.mark_sent(ws.id, big.id)
        big_proposal = await svc.get_public_proposal(big_sent.public_token)
        assert big_proposal.deposit_amount == 200.0


async def test_workspace_default_deposit_is_inherited() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        ws.settings = {"pricing": {"deposit": {"enabled": True, "mode": "percentage", "value": 50}}}
        await db.flush()
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        # Operator sets no deposit -> inherits the 50% workspace default.
        created = await svc.create_quote(
            ws.id,
            QuoteCreate(
                contact_id=contact.id,
                title="Inherited deposit",
                line_items=[QuoteLineItemCreate(name="Job", unit_price=1000.0)],
            ),
        )
        sent = await svc.mark_sent(ws.id, created.id)
        proposal = await svc.get_public_proposal(sent.public_token)
        assert proposal.deposit_percentage == 50.0
        assert proposal.deposit_amount == 500.0


async def test_reconcile_marks_paid_when_stripe_reports_paid(monkeypatch) -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        token, quote_id = await _sent_quote_with_deposit(svc, ws.id, contact.id)

        # Simulate a checkout having been started (session id persisted).
        quote = await db.get(Quote, quote_id)
        quote.deposit_checkout_session_id = "cs_reconcile_1"
        await db.flush()

        monkeypatch.setattr(deposit.call_payment_service, "is_payment_configured", lambda: True)

        async def _paid_status(session_id: str) -> SessionStatus:
            assert session_id == "cs_reconcile_1"
            return SessionStatus(
                payment_status="paid", status="complete", payment_intent_id="pi_rec_1"
            )

        monkeypatch.setattr(deposit.call_payment_service, "retrieve_session_status", _paid_status)

        status = await deposit.reconcile_deposit(db, token)
        assert status.deposit_paid is True
        assert status.deposit_amount == 321.0

        refreshed = await db.get(Quote, quote_id)
        assert refreshed.deposit_paid_at is not None
        assert refreshed.deposit_payment_intent_id == "pi_rec_1"
        assert refreshed.deposit_payment_method == "card"
        assert refreshed.deposit_recorded_by_id is None
        # Idempotent: a second reconcile keeps the same paid timestamp.
        first = refreshed.deposit_paid_at
        again = await deposit.reconcile_deposit(db, token)
        assert again.deposit_paid is True
        after = await db.get(Quote, quote_id)
        assert after.deposit_paid_at == first


async def test_reconcile_reports_unpaid_when_stripe_not_paid(monkeypatch) -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        token, quote_id = await _sent_quote_with_deposit(svc, ws.id, contact.id)
        quote = await db.get(Quote, quote_id)
        quote.deposit_checkout_session_id = "cs_unpaid_1"
        await db.flush()

        monkeypatch.setattr(deposit.call_payment_service, "is_payment_configured", lambda: True)

        async def _unpaid_status(session_id: str) -> SessionStatus:
            return SessionStatus(payment_status="unpaid", status="open", payment_intent_id=None)

        monkeypatch.setattr(deposit.call_payment_service, "retrieve_session_status", _unpaid_status)

        status = await deposit.reconcile_deposit(db, token)
        assert status.deposit_paid is False
        refreshed = await db.get(Quote, quote_id)
        assert refreshed.deposit_paid_at is None


async def test_accepting_a_quote_produces_a_deposit_payment_intent(monkeypatch) -> None:
    """Accept must hand off to Stripe, not just flip the quote to approved.

    The client page rolls straight from "Approve & Pay Deposit" into checkout on
    the strength of ``deposit_required``. If accept reported no deposit, or the
    checkout it triggers did not persist a payment intent, the operator would
    see an approved quote with no money attached and no way to reconcile it.
    """
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        token, quote_id = await _sent_quote_with_deposit(svc, ws.id, contact.id)

        approved = await svc.approve_public(token, proposal_version=None)

        # Accept alone collects nothing; it tells the page money is owed.
        assert approved.status == "approved"
        assert approved.deposit_required is True
        assert approved.deposit_amount == 321.0

        monkeypatch.setattr(deposit.call_payment_service, "is_payment_configured", lambda: True)

        async def _fake_session(**kwargs):
            # An approved quote is still chargeable, and for the accepted total.
            assert kwargs["amount"] == 321.0
            assert kwargs["metadata"]["quote_id"] == str(quote_id)
            return CheckoutSessionResult(
                session_id="cs_accept_1",
                url="https://checkout.stripe.test/pay/cs_accept_1",
                payment_intent_id="pi_accept_1",
            )

        monkeypatch.setattr(
            deposit.call_payment_service, "create_payment_checkout_session", _fake_session
        )

        checkout = await deposit.create_deposit_checkout_session(db, token)

        assert checkout.url == "https://checkout.stripe.test/pay/cs_accept_1"
        assert checkout.amount == 321.0

        refreshed = await db.get(Quote, quote_id)
        assert refreshed is not None
        # The payment intent is what reconciles the money back to this quote.
        assert refreshed.deposit_payment_intent_id == "pi_accept_1"
        assert refreshed.deposit_checkout_session_id == "cs_accept_1"
        # Still unpaid until Stripe confirms; accept must not fake a payment.
        assert refreshed.deposit_paid_at is None
