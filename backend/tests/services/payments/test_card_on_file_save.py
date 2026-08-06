"""Saving a card on file: consent, idempotency, and what must never be stored.

Real Postgres (the unique constraints and the partial default index are the point
of several of these), fake Stripe. Run with ``pytest -m integration``.

The load-bearing assertions here are the negative ones:

* no Stripe object is created for a request that did not carry consent;
* an expired or already-spent link is refused *before* any Stripe call;
* nothing resembling a card number reaches the database.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.contact_card_setup_token import ContactCardSetupToken
from app.models.contact_payment_method import ContactPaymentMethod
from app.services.exceptions import ConflictError, NotFoundError, ValidationError
from app.services.payments import card_on_file_service
from tests.services.payments.conftest import (
    FakeStripeClient,
    FakeStripeObject,
    make_contact,
    make_workspace,
    session,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# Any run of 13-19 digits, ignoring spaces and dashes — the shape of a PAN.
_PAN_SHAPED = re.compile(r"\d{13,19}")

# Surrogate keys, excluded from the PAN scan. A UUID stripped of its dashes can
# incidentally contain a 15-digit run, so scanning these would fail at random on
# some generated ids while never being able to catch a real card number.
_SURROGATE_KEY_COLUMNS = frozenset({"id", "workspace_id", "contact_id"})


def _pm_id(label: str) -> str:
    """A per-run Stripe payment-method id.

    ``stripe_payment_method_id`` is globally unique (one Stripe handle, one row)
    and the local database is not reset between runs, so a hard-coded id would
    make the second run collide with the first.
    """
    return f"pm_{label}_{uuid.uuid4().hex[:12]}"


def _setup_intent_response(intent_id: str = "seti_test_1") -> FakeStripeObject:
    return FakeStripeObject(
        id=intent_id,
        client_secret=f"{intent_id}_secret_abc123",
        status="requires_payment_method",
    )


def _payment_method_response(pm_id: str = "pm_test_1") -> FakeStripeObject:
    return FakeStripeObject(
        id=pm_id,
        card=FakeStripeObject(brand="visa", last4="4242", exp_month=12, exp_year=2032),
    )


async def test_setup_intent_reuses_one_stripe_customer_per_contact(
    fake_stripe: FakeStripeClient,
) -> None:
    """A second card-save must attach to the same Stripe Customer, not a new one.

    A duplicate Customer is invisible until the day you charge the card saved
    against the *other* one and Stripe says it does not exist.
    """
    fake_stripe.customers.responses["create"] = FakeStripeObject(id="cus_reuse_me")
    fake_stripe.setup_intents.responses["create"] = _setup_intent_response()

    async with session() as db:
        ws = await make_workspace(db)
        contact = await make_contact(db, ws.id, email="dana@example.com")
        await db.commit()

        first = await card_on_file_service.create_setup_intent(
            db, contact, consent_accepted=True, client_ip="203.0.113.9", user_agent="ua/1"
        )
        second = await card_on_file_service.create_setup_intent(
            db, contact, consent_accepted=True, client_ip="203.0.113.9", user_agent="ua/1"
        )

        assert first.client_secret.startswith("seti_")
        assert second.client_secret.startswith("seti_")
        assert fake_stripe.actions().count("customers.create") == 1
        assert contact.stripe_customer_id == "cus_reuse_me"


async def test_setup_intent_carries_the_mandate_record_to_stripe(
    fake_stripe: FakeStripeClient,
) -> None:
    """Consent details ride on the SetupIntent so the webhook can persist them."""
    fake_stripe.customers.responses["create"] = FakeStripeObject(id="cus_mandate")
    fake_stripe.setup_intents.responses["create"] = _setup_intent_response()

    async with session() as db:
        ws = await make_workspace(db)
        contact = await make_contact(db, ws.id)
        await db.commit()

        await card_on_file_service.create_setup_intent(
            db,
            contact,
            consent_accepted=True,
            client_ip="198.51.100.7",
            user_agent="Mozilla/5.0 (probe)",
        )

    created = [c for name, c in fake_stripe.calls if name == "setup_intents.create"][0]
    params = created["kwargs"]["params"]
    metadata = params["metadata"]
    # off_session usage is what makes a later merchant-initiated charge legitimate.
    assert params["usage"] == "off_session"
    assert metadata["kind"] == "card_on_file"
    assert metadata["mandate_version"] == card_on_file_service.CARD_ON_FILE_MANDATE_VERSION
    assert metadata["mandate_ip"] == "198.51.100.7"
    assert metadata["mandate_user_agent"] == "Mozilla/5.0 (probe)"
    assert metadata["contact_id"] == str(contact.id)


async def test_saving_without_consent_is_refused_and_calls_no_stripe(
    fake_stripe: FakeStripeClient,
) -> None:
    """No consent means no Stripe object — not even a Customer."""
    async with session() as db:
        ws = await make_workspace(db)
        contact = await make_contact(db, ws.id)
        await db.commit()

        with pytest.raises(ValidationError):
            await card_on_file_service.create_setup_intent(
                db, contact, consent_accepted=False, client_ip="203.0.113.1", user_agent="ua"
            )

    assert fake_stripe.calls == []
    assert contact.stripe_customer_id is None


async def test_expired_and_used_tokens_are_refused_before_any_stripe_call(
    fake_stripe: FakeStripeClient,
) -> None:
    """A lapsed or spent link never reaches Stripe, and says which it is."""
    async with session() as db:
        ws = await make_workspace(db)
        contact = await make_contact(db, ws.id)
        await db.commit()

        live = await card_on_file_service.mint_card_setup_token(
            db, workspace_id=ws.id, contact_id=contact.id
        )
        # Same token, pushed past its window.
        live.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()

        with pytest.raises(ConflictError):
            await card_on_file_service.resolve_card_setup_token(db, live.token)

        spent = await card_on_file_service.mint_card_setup_token(
            db, workspace_id=ws.id, contact_id=contact.id
        )
        await card_on_file_service.burn_card_setup_token(db, spent)
        with pytest.raises(ConflictError):
            await card_on_file_service.resolve_card_setup_token(db, spent.token)

        with pytest.raises(NotFoundError):
            await card_on_file_service.resolve_card_setup_token(db, "not-a-real-token")

    assert fake_stripe.calls == []


async def test_minting_a_new_link_burns_the_previous_one(fake_stripe: FakeStripeClient) -> None:
    """ "Send it again" must not leave two live card-entry URLs for one customer."""
    async with session() as db:
        ws = await make_workspace(db)
        contact = await make_contact(db, ws.id)
        await db.commit()

        first = await card_on_file_service.mint_card_setup_token(
            db, workspace_id=ws.id, contact_id=contact.id
        )
        second = await card_on_file_service.mint_card_setup_token(
            db, workspace_id=ws.id, contact_id=contact.id
        )

        with pytest.raises(ConflictError):
            await card_on_file_service.resolve_card_setup_token(db, first.token)
        resolved = await card_on_file_service.resolve_card_setup_token(db, second.token)
        assert resolved.id == second.id


async def test_webhook_persists_card_display_fields_and_mandate(
    fake_stripe: FakeStripeClient,
) -> None:
    """``setup_intent.succeeded`` stores brand/last4/expiry plus the consent record."""
    pm_id = _pm_id("saved")
    fake_stripe.payment_methods.responses["retrieve"] = _payment_method_response(pm_id)

    async with session() as db:
        ws = await make_workspace(db)
        contact = await make_contact(db, ws.id)
        await db.commit()

        accepted_at = datetime(2026, 8, 5, 12, 30, tzinfo=UTC)
        saved = await card_on_file_service.save_payment_method_from_setup_intent(
            db,
            {
                "id": "seti_hook",
                "customer": "cus_hook",
                "payment_method": pm_id,
                "metadata": {
                    "kind": "card_on_file",
                    "contact_id": str(contact.id),
                    "workspace_id": str(ws.id),
                    "mandate_version": card_on_file_service.CARD_ON_FILE_MANDATE_VERSION,
                    "mandate_accepted_at": accepted_at.isoformat(),
                    "mandate_ip": "198.51.100.4",
                    "mandate_user_agent": "Safari/probe",
                },
            },
        )

        assert saved is not None
        assert saved.brand == "visa"
        assert saved.last4 == "4242"
        assert saved.exp_month == 12
        assert saved.exp_year == 2032
        assert saved.stripe_customer_id == "cus_hook"
        # The written agreement: version, time, and where it came from.
        assert saved.mandate_text_version == card_on_file_service.CARD_ON_FILE_MANDATE_VERSION
        assert saved.mandate_accepted_at == accepted_at
        assert saved.mandate_ip == "198.51.100.4"
        assert saved.mandate_user_agent == "Safari/probe"
        # First card saved becomes the default with no operator action.
        assert saved.is_default is True
        assert saved.status == "active"


async def test_webhook_replay_does_not_create_a_second_row(
    fake_stripe: FakeStripeClient,
) -> None:
    """Stripe retries events; a replay must find the card already saved."""
    pm_id = _pm_id("replay")
    fake_stripe.payment_methods.responses["retrieve"] = _payment_method_response(pm_id)

    async with session() as db:
        ws = await make_workspace(db)
        contact = await make_contact(db, ws.id)
        await db.commit()

        event = {
            "id": "seti_replay",
            "customer": "cus_replay",
            "payment_method": pm_id,
            "metadata": {
                "kind": "card_on_file",
                "contact_id": str(contact.id),
                "workspace_id": str(ws.id),
                "mandate_version": card_on_file_service.CARD_ON_FILE_MANDATE_VERSION,
            },
        }
        first = await card_on_file_service.save_payment_method_from_setup_intent(db, event)
        second = await card_on_file_service.save_payment_method_from_setup_intent(db, event)

        assert first is not None and second is not None
        assert first.id == second.id

        rows = await db.execute(
            select(ContactPaymentMethod).where(ContactPaymentMethod.contact_id == contact.id)
        )
        assert len(rows.scalars().all()) == 1


async def test_setup_intent_for_another_flow_is_ignored(fake_stripe: FakeStripeClient) -> None:
    """A SetupIntent that is not ours (no ``kind``) stores nothing."""
    async with session() as db:
        ws = await make_workspace(db)
        contact = await make_contact(db, ws.id)
        await db.commit()

        saved = await card_on_file_service.save_payment_method_from_setup_intent(
            db,
            {
                "id": "seti_other",
                "customer": "cus_other",
                "payment_method": "pm_other",
                "metadata": {"contact_id": str(contact.id)},
            },
        )
        assert saved is None
        assert "payment_methods.retrieve" not in fake_stripe.actions()


async def test_no_stored_value_looks_like_a_card_number(fake_stripe: FakeStripeClient) -> None:
    """Structural guard: nothing persisted for a saved card can be a PAN.

    Checks the model has no PAN-ish column *and* that every value actually
    written contains no 13-19 digit run — even when Stripe hands back something
    it should not.
    """
    forbidden = ("number", "pan", "cvc", "cvv", "card_number", "security_code")
    column_names = {c.name.lower() for c in ContactPaymentMethod.__table__.columns}
    assert not [c for c in column_names if any(bad in c for bad in forbidden)]

    # A hostile/buggy Stripe response carrying a full PAN in the last4 slot.
    pm_id = _pm_id("pan_probe")
    fake_stripe.payment_methods.responses["retrieve"] = FakeStripeObject(
        id=pm_id,
        card=FakeStripeObject(
            brand="visa",
            last4="4242424242424242",
            exp_month=1,
            exp_year=2030,
        ),
    )

    async with session() as db:
        ws = await make_workspace(db)
        contact = await make_contact(db, ws.id)
        await db.commit()

        saved = await card_on_file_service.save_payment_method_from_setup_intent(
            db,
            {
                "id": "seti_pan",
                "customer": "cus_pan",
                "payment_method": pm_id,
                "metadata": {
                    "kind": "card_on_file",
                    "contact_id": str(contact.id),
                    "workspace_id": str(ws.id),
                },
            },
        )
        assert saved is not None
        assert saved.last4 == "4242"

        for column in ContactPaymentMethod.__table__.columns:
            # Surrogate keys are structurally incapable of holding a PAN, and a
            # UUID with its dashes stripped can incidentally contain a 15-digit
            # run — checking them would make this assertion randomly red without
            # ever catching a real leak.
            if column.name in _SURROGATE_KEY_COLUMNS:
                continue
            value = getattr(saved, column.name)
            if value is None:
                continue
            digits_only = re.sub(r"[\s-]", "", str(value))
            assert not _PAN_SHAPED.search(digits_only), f"{column.name} looks like a card number"


async def test_setup_token_is_scoped_to_its_workspace(fake_stripe: FakeStripeClient) -> None:
    """Workspace A cannot mint a card-setup link for workspace B's contact."""
    async with session() as db:
        ws_a = await make_workspace(db, "Alpha")
        ws_b = await make_workspace(db, "Beta")
        contact_b = await make_contact(db, ws_b.id)
        await db.commit()

        with pytest.raises(NotFoundError):
            await card_on_file_service.mint_card_setup_token(
                db, workspace_id=ws_a.id, contact_id=contact_b.id
            )

        minted = await db.execute(
            select(ContactCardSetupToken).where(ContactCardSetupToken.contact_id == contact_b.id)
        )
        assert minted.scalars().all() == []
