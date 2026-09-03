"""Real-DB integration tests for the public permanent-vs-temporary comparison.

Exercises the share -> public-view flow end-to-end against Postgres and, most
importantly, proves the client-facing payload **never** carries the internal
linear-feet measurement (nor per-foot rate / zone count). Marked ``integration``
and deselected by default; run with ``pytest -m integration``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Literal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.roofline_comparison import RooflineComparison
from app.models.workspace import Workspace
from app.schemas.estimate import (
    ComparisonShareRequest,
    EstimateCustomLine,
    PublicComparison,
)
from app.services.exceptions import NotFoundError, ValidationError
from app.services.quotes import QuoteService

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# A distinctive footage so we can string-search the serialized payload for a leak.
LEAK_FEET = 137.0


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    await engine.dispose()
    yield
    await engine.dispose()


async def _make_workspace(db: AsyncSession) -> Workspace:
    ws = Workspace(
        id=uuid.uuid4(),
        name="Maxteriors Lighting",
        slug=f"cmp-{uuid.uuid4().hex[:8]}",
        settings={
            "proposal_template": {"business_name": "Maxteriors Lighting Co."},
            "pricing": {
                "financing": {"enabled": True, "fee_buffer": 0.0},
                "permanent": {
                    "enabled": True,
                    "per_ft": 30,
                    "controller_base": 300,
                    "per_channel": 0,
                    "included_channels": 1,
                    "minimum": 0,
                },
                "christmas": {
                    "enabled": True,
                    "roofline_per_ft": 6,
                    # Distinctive garland rate so a leak is string-searchable.
                    "items": [
                        {
                            "key": "garland",
                            "label": "Garland",
                            "unit": "per_ft",
                            "options": [
                                {"key": "standard", "name": "Garland", "price": 13},
                            ],
                        },
                    ],
                    "takedown_enabled": True,
                    "takedown_rate": 0.25,
                    "storage_price": 0,
                    "minimum": 0,
                },
                "comparison_years": 5,
            },
        },
    )
    db.add(ws)
    await db.flush()
    return ws


async def _use_non_monotonic_complexity_package(db: AsyncSession, workspace: Workspace) -> None:
    settings = dict(workspace.settings or {})
    pricing = dict(settings.get("pricing", {}))
    pricing["permanent"] = {
        "enabled": True,
        "packages": [{"feet": 100, "cost": 1000}],
        # Deliberately non-monotonic: each semantic tier must retain its configured
        # multiplier instead of being silently sorted by numeric value.
        "easy_markup": 4,
        "standard_markup": 3,
        "complex_markup": 2,
        "markup": 3,
        "minimum": 0,
    }
    settings["pricing"] = pricing
    workspace.settings = settings
    await db.flush()


async def test_share_then_public_view_hides_linear_feet() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)

        share = await svc.share_comparison(
            ws.id,
            ComparisonShareRequest(
                feet=LEAK_FEET,
                client_name="Dana Homeowner",
                permanent_complexity="easy",
            ),
        )
        assert share.token
        assert share.url.endswith(f"/p/compare/{share.token}")

        public = await svc.get_public_comparison(share.token)
        assert isinstance(public, PublicComparison)

        # Prices are recomputed and present; exact permanent package pricing is
        # covered by the pricing tests and may change with the workspace price book.
        assert public.business_name == "Maxteriors Lighting Co."
        assert public.client_name == "Dana Homeowner"
        assert public.permanent.total > 0
        assert public.christmas.total == 137 * 6  # 822
        assert public.years == 5
        assert public.temporary_multi_year == round(822 * 5, 2)
        assert public.permanent_perks and public.christmas_perks

        # The critical guarantee: the serialized client payload contains NO field
        # named feet/per_ft/channels AND the raw JSON never echoes the measurement.
        dumped = public.model_dump()
        assert "feet" not in dumped
        assert "per_ft" not in dumped
        assert "channels" not in dumped
        raw_json = public.model_dump_json()
        assert "137" not in raw_json  # the measured footage must not leak anywhere


async def test_permanent_proposal_link_hides_seasonal_price_and_persists_discount() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)

        share = await svc.share_comparison(
            ws.id,
            ComparisonShareRequest(
                feet=100,
                proposal_side="permanent",
                permanent_complexity="easy",
                discount_amount=500,
                custom_lines=[
                    {
                        "label": "Seasonal-only add-on",
                        "quantity": 1,
                        "unit_price": 50,
                        "side": "seasonal",
                    }
                ],
            ),
        )
        saved = await db.scalar(
            select(RooflineComparison).where(RooflineComparison.public_token == share.token)
        )
        assert saved is not None
        assert saved.proposal_side == "permanent"
        assert float(saved.discount_amount) == 500

        public = await svc.get_public_comparison(share.token)
        assert public.proposal_side == "permanent"
        assert public.discount_amount == 500
        assert public.permanent.enabled is True
        assert public.permanent.subtotal > 500
        assert public.permanent.total == pytest.approx(public.permanent.subtotal - 500)
        assert public.christmas.enabled is False
        assert public.christmas.total == 0
        assert public.christmas_packages == []
        assert public.christmas_perks == []
        assert public.custom_lines == []


async def test_percent_discount_survives_sharing_as_dollars() -> None:
    """A percentage must be resolved before the link is stored.

    Only ``discount_amount`` is persisted, so a rep who typed a percentage would
    otherwise share a link carrying no discount at all -- the customer would see
    full price with nothing to show that anything was lost.
    """
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)

        share = await svc.share_comparison(
            ws.id,
            ComparisonShareRequest(
                feet=100,
                proposal_side="permanent",
                permanent_complexity="easy",
                discount_percent=10,
            ),
        )

        saved = await db.scalar(
            select(RooflineComparison).where(RooflineComparison.public_token == share.token)
        )
        assert saved is not None
        public = await svc.get_public_comparison(share.token)

        # Stored as the dollars it came to, not as a rate: recomputing the
        # percentage on each view would let a later price change silently
        # re-scale a discount the customer was already quoted.
        expected = round(public.permanent.subtotal * 0.10, 2)
        assert float(saved.discount_amount) == pytest.approx(expected)
        assert public.discount_amount == pytest.approx(expected)
        assert public.permanent.total == pytest.approx(public.permanent.subtotal - expected)


@pytest.mark.parametrize(
    ("scalar_complexity", "measured_complexity", "expected_total"),
    [
        ("easy", "complex", 2000),
        ("easy", "standard", 3000),
        ("complex", "easy", 4000),
    ],
    ids=["complex-map", "standard-map", "easy-map"],
)
async def test_share_then_public_view_preserves_measured_complexity(
    scalar_complexity: Literal["easy", "standard", "complex"],
    measured_complexity: Literal["easy", "standard", "complex"],
    expected_total: float,
) -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        await _use_non_monotonic_complexity_package(db, ws)
        svc = QuoteService(db)

        # Opposing scalar and measured values catches either persistence bug: the
        # public view must restore the map rather than silently repricing the scalar.
        share = await svc.share_comparison(
            ws.id,
            ComparisonShareRequest(
                feet=100,
                permanent_complexity=scalar_complexity,
                permanent_complexity_feet={measured_complexity: 100},
            ),
        )
        comparison = await db.scalar(
            select(RooflineComparison).where(RooflineComparison.public_token == share.token)
        )
        assert comparison is not None
        assert comparison.permanent_complexity == scalar_complexity
        assert comparison.permanent_complexity_feet == {measured_complexity: 100}

        public = await svc.get_public_comparison(share.token)
        assert public.permanent.total == expected_total


async def test_legacy_shared_comparison_defaults_to_standard_complexity() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        await _use_non_monotonic_complexity_package(db, ws)

        # This is the post-migration shape of an old row: the NOT NULL default
        # supplies Standard and the nullable map remains NULL (no unbounded backfill).
        comparison = RooflineComparison(workspace_id=ws.id, feet=100, channels=0)
        db.add(comparison)
        await db.commit()
        await db.refresh(comparison)
        assert comparison.permanent_complexity == "standard"
        assert comparison.permanent_complexity_feet is None

        public = await QuoteService(db).get_public_comparison(comparison.public_token)
        assert public.permanent.total == 3000  # $1,000 COGS × Standard markup


async def test_disabled_permanent_shows_not_configured_side() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        # Turn permanent off after seeding.
        settings = dict(ws.settings)
        pricing = dict(settings["pricing"])
        pricing["permanent"] = {"enabled": False}
        settings["pricing"] = pricing
        ws.settings = settings
        await db.flush()

        svc = QuoteService(db)
        share = await svc.share_comparison(ws.id, ComparisonShareRequest(feet=100))
        public = await svc.get_public_comparison(share.token)

        assert public.permanent.enabled is False
        assert public.permanent.total == 0
        assert public.christmas.enabled is True
        assert public.christmas.total == 600
        # No apples-to-apples savings when only one side is offered.
        assert public.multi_year_savings == 0


async def test_deprecated_per_ft_override_does_not_change_package_or_leak_rate() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        baseline_share = await svc.share_comparison(ws.id, ComparisonShareRequest(feet=100))
        baseline = await svc.get_public_comparison(baseline_share.token)

        # Permanent pricing now comes from server-owned kits and complexity markups;
        # legacy per-foot overrides are accepted for old clients but deliberately ignored.
        share = await svc.share_comparison(
            ws.id, ComparisonShareRequest(feet=100, per_ft_override=45)
        )
        public = await svc.get_public_comparison(share.token)
        assert public.permanent.total == baseline.permanent.total

        # The legacy rate remains private: neither it nor any per-foot rate is a
        # field on the client payload.
        dumped = public.model_dump()
        assert "per_ft" not in dumped
        assert "per_ft_override" not in dumped


async def test_internal_christmas_per_ft_override_recomputes_public_total_without_leaking_rate() -> (  # noqa: E501
    None
):
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        baseline_share = await svc.share_comparison(ws.id, ComparisonShareRequest(feet=100))
        baseline = await svc.get_public_comparison(baseline_share.token)

        # Rep tunes the seasonal roofline rate up to $9/ft for this one job.
        share = await svc.share_comparison(
            ws.id, ComparisonShareRequest(feet=100, christmas_per_ft_override=9)
        )
        public = await svc.get_public_comparison(share.token)

        # Seasonal price reflects the internal rate ($9), not the $6 standard.
        assert public.christmas.total == 100 * 9
        # Permanent package pricing is untouched by the seasonal override.
        assert public.permanent.total == baseline.permanent.total
        # No per-foot rate or override field on the client payload.
        dumped = public.model_dump()
        assert "per_ft" not in dumped
        assert "christmas_per_ft_override" not in dumped


async def test_seasonal_decor_recomputes_public_total_without_leaking_rate() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)

        # Homeowner selects 40 ft of garland ($13/ft internal rate).
        share = await svc.share_comparison(
            ws.id,
            ComparisonShareRequest(feet=100, christmas_items={"garland": {"standard": 40}}),
        )
        public = await svc.get_public_comparison(share.token)

        # Seasonal total = roofline 100*6=600 + garland 40*13=520 = 1120.
        assert public.christmas.total == 1120

        # The client payload shows totals only: neither the per-foot garland rate
        # (13) nor the selected feet (40) nor any per_ft field may appear.
        dumped = public.model_dump()
        assert "per_ft" not in dumped
        assert "christmas_items" not in dumped
        raw_json = public.model_dump_json()
        assert "13" not in raw_json  # the internal $/ft rate must not leak
        assert "40" not in raw_json  # the selected garland feet must not leak


async def test_unknown_comparison_token_404() -> None:
    async with AsyncSessionLocal() as db:
        svc = QuoteService(db)
        with pytest.raises(NotFoundError):
            await svc.get_public_comparison("does-not-exist")


async def test_share_with_phone_saves_estimate_to_customer() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)

        share = await svc.share_comparison(
            ws.id,
            ComparisonShareRequest(
                feet=120,
                client_name="Dana Homeowner",
                client_email="dana@example.com",
                client_phone="+15551230000",
            ),
            created_by_id=None,
        )

        # The estimate is saved onto a resolved/created customer.
        assert share.saved_to_customer is True
        assert share.contact_id is not None

        # The contact was created from the loose name split into first/last, with
        # the estimator as its source.
        contact = (
            await db.execute(select(Contact).where(Contact.id == share.contact_id))
        ).scalar_one()
        assert contact.workspace_id == ws.id
        assert contact.first_name == "Dana"
        assert contact.last_name == "Homeowner"
        assert contact.source == "roofline_estimator"

        # The persisted comparison points at that customer.
        comparison = (
            await db.execute(
                select(RooflineComparison).where(RooflineComparison.public_token == share.token)
            )
        ).scalar_one()
        assert comparison.contact_id == share.contact_id


async def test_share_without_phone_stays_unlinked() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)

        # Name + email but no phone. Contacts are phone-keyed, so there's nothing
        # to create on; the estimate still shares, just unlinked.
        share = await svc.share_comparison(
            ws.id,
            ComparisonShareRequest(feet=90, client_name="No Phone", client_email="np@example.com"),
        )
        assert share.saved_to_customer is False
        assert share.contact_id is None

        count = (
            await db.execute(
                select(func.count()).select_from(Contact).where(Contact.workspace_id == ws.id)
            )
        ).scalar_one()
        assert count == 0


async def test_deliver_comparison_emails_linked_contact(monkeypatch) -> None:  # noqa: ANN001
    sent: list[dict] = []

    async def fake_send_estimate_email(**kwargs):  # noqa: ANN003
        sent.append(kwargs)
        return True

    from app.services import email as email_module

    monkeypatch.setattr(email_module, "send_estimate_email", fake_send_estimate_email)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)

        share = await svc.share_comparison(
            ws.id,
            ComparisonShareRequest(
                feet=120,
                client_name="Dana Homeowner",
                client_email="dana@example.com",
                client_phone="+15551230000",
            ),
        )

        # No explicit destination: falls back to the linked contact's email.
        result = await svc.deliver_comparison(ws.id, share.token, to=None)
        assert result.ok is True
        assert result.to == "dana@example.com"
        assert sent and sent[0]["to_email"] == "dana@example.com"
        assert f"/p/compare/{share.token}" in sent[0]["estimate_url"]


async def test_deliver_comparison_uses_explicit_destination(monkeypatch) -> None:  # noqa: ANN001
    sent: list[dict] = []

    async def fake_send_estimate_email(**kwargs):  # noqa: ANN003
        sent.append(kwargs)
        return True

    from app.services import email as email_module

    monkeypatch.setattr(email_module, "send_estimate_email", fake_send_estimate_email)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)

        # Shared without a phone -> no linked contact/email on file.
        share = await svc.share_comparison(
            ws.id, ComparisonShareRequest(feet=90, client_name="No Phone")
        )
        result = await svc.deliver_comparison(ws.id, share.token, to="buyer@example.com")
        assert result.ok is True
        assert result.to == "buyer@example.com"
        assert sent[0]["to_email"] == "buyer@example.com"


async def test_deliver_comparison_without_destination_raises() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        # No phone -> no contact -> no email anywhere.
        share = await svc.share_comparison(ws.id, ComparisonShareRequest(feet=80))
        with pytest.raises(ValidationError):
            await svc.deliver_comparison(ws.id, share.token, to=None)


async def test_deliver_comparison_unknown_token_404() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        with pytest.raises(NotFoundError):
            await svc.deliver_comparison(ws.id, "does-not-exist", to="x@example.com")


async def test_deliver_comparison_texts_the_linked_contacts_phone(monkeypatch) -> None:  # noqa: ANN001
    """The SMS rail reaches the customer with the same public link as email."""
    texted: list[dict] = []

    async def fake_text(self, workspace_id, **kwargs):  # noqa: ANN001, ANN003
        texted.append({"workspace_id": workspace_id, **kwargs})

    monkeypatch.setattr(QuoteService, "_text_client_link", fake_text)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)

        share = await svc.share_comparison(
            ws.id,
            ComparisonShareRequest(
                feet=120,
                client_name="Dana Homeowner",
                client_email="dana@example.com",
                client_phone="+15551230000",
            ),
        )

        result = await svc.deliver_comparison(ws.id, share.token, channel="sms", to=None)
        assert result.ok is True
        assert result.channel == "sms"
        # Falls back to the linked contact's phone, not their email.
        assert result.to == "+15551230000"
        assert texted and texted[0]["phone"] == "+15551230000"
        # The client link the text carries is the public estimate page.
        assert f"/p/compare/{share.token}" in texted[0]["body"]
        # Greets by first name only — the body is a text, not a letter.
        assert texted[0]["body"].startswith("Hi Dana, ")


async def test_deliver_comparison_sms_without_a_phone_raises() -> None:
    """No phone anywhere is a refusal, never a silent no-op."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        # Shared without a phone -> no linked contact -> nothing to text.
        share = await svc.share_comparison(
            ws.id, ComparisonShareRequest(feet=90, client_name="No Phone")
        )
        with pytest.raises(ValidationError, match="phone"):
            await svc.deliver_comparison(ws.id, share.token, channel="sms", to=None)


async def test_deliver_comparison_rejects_an_unknown_channel() -> None:
    """An unknown rail fails loudly instead of quietly falling back to email."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        share = await svc.share_comparison(
            ws.id,
            ComparisonShareRequest(feet=90, client_name="Dana", client_phone="+15551230000"),
        )
        with pytest.raises(ValidationError, match="channel"):
            await svc.deliver_comparison(ws.id, share.token, channel="carrier-pigeon")


async def test_deliver_comparison_defaults_to_email(monkeypatch) -> None:  # noqa: ANN001
    """Callers predating SMS delivery keep emailing without passing a channel."""
    sent: list[dict] = []

    async def fake_send_estimate_email(**kwargs):  # noqa: ANN003
        sent.append(kwargs)
        return True

    from app.services import email as email_module

    monkeypatch.setattr(email_module, "send_estimate_email", fake_send_estimate_email)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        share = await svc.share_comparison(
            ws.id, ComparisonShareRequest(feet=90, client_name="Dana")
        )
        result = await svc.deliver_comparison(ws.id, share.token, to="buyer@example.com")
        assert result.channel == "email"
        assert sent[0]["to_email"] == "buyer@example.com"


async def test_resharing_same_phone_reuses_one_customer() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)

        first = await svc.share_comparison(
            ws.id,
            ComparisonShareRequest(
                feet=100, client_name="Repeat Client", client_phone="+15551230000"
            ),
        )
        second = await svc.share_comparison(
            ws.id,
            ComparisonShareRequest(
                feet=140, client_name="Repeat Client", client_phone="+15551230000"
            ),
        )

        # Both estimates resolve to the same customer (dedupe on phone hash).
        assert first.contact_id is not None
        assert first.contact_id == second.contact_id

        count = (
            await db.execute(
                select(func.count()).select_from(Contact).where(Contact.workspace_id == ws.id)
            )
        ).scalar_one()
        assert count == 1


async def test_custom_lines_survive_the_share_and_reach_the_client_itemized() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        baseline_share = await svc.share_comparison(ws.id, ComparisonShareRequest(feet=100))
        baseline = await svc.get_public_comparison(baseline_share.token)

        share = await svc.share_comparison(
            ws.id,
            ComparisonShareRequest(
                feet=100,
                custom_lines=[
                    EstimateCustomLine(label="Bucket truck day", unit_price=150, quantity=2),
                    EstimateCustomLine(label="Remove old clips", unit_price=90, side="permanent"),
                ],
            ),
        )
        public = await svc.get_public_comparison(share.token)

        # Seasonal roofline plus 2 × $150; permanent package plus $90.
        assert public.christmas.total == baseline.christmas.total + 300
        assert public.permanent.total == baseline.permanent.total + 90
        # Itemized rather than folded silently into the headline: an unexplained
        # bump in the price is the fastest way to lose a signature.
        assert [(line.label, line.amount, line.side) for line in public.custom_lines] == [
            ("Remove old clips", 90, "permanent"),
            ("Bucket truck day", 300, "seasonal"),
        ]


async def test_custom_lines_ride_on_top_of_the_chosen_package() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        pricing = dict(ws.settings["pricing"])
        pricing["christmas"] = {**pricing["christmas"], "packages_enabled": True}
        ws.settings = {**ws.settings, "pricing": pricing}
        await db.flush()
        svc = QuoteService(db)

        share = await svc.share_comparison(
            ws.id,
            ComparisonShareRequest(
                feet=100,
                custom_lines=[EstimateCustomLine(label="Balcony hand-tie", unit_price=200)],
            ),
        )
        public = await svc.get_public_comparison(share.token)

        # The recommended package's own total, plus the standalone line — the
        # add-on can't be lost just because the workspace sells packages.
        recommended = next(p for p in public.christmas_packages if p.recommended)
        assert public.christmas.total == round(recommended.total + 200, 2)
        assert [line.amount for line in public.custom_lines] == [200]


async def _packages_workspace(db: AsyncSession) -> Workspace:
    """A workspace selling Christmas as Good/Better/Best tiers."""
    ws = await _make_workspace(db)
    pricing = dict(ws.settings["pricing"])
    pricing["christmas"] = {**pricing["christmas"], "packages_enabled": True}
    ws.settings = {**ws.settings, "pricing": pricing}
    await db.flush()
    return ws


async def _priced_packages(svc: QuoteService, ws: Workspace):
    """The client-facing tier ladder for this workspace, with no add-ons on it."""
    share = await svc.share_comparison(ws.id, ComparisonShareRequest(feet=100))
    return await svc.get_public_comparison(share.token)


async def test_a_line_scoped_to_the_recommended_tier_is_billed_exactly_once() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _packages_workspace(db)
        svc = QuoteService(db)
        baseline = next(
            p for p in (await _priced_packages(svc, ws)).christmas_packages if p.recommended
        )

        share = await svc.share_comparison(
            ws.id,
            ComparisonShareRequest(
                feet=100,
                custom_lines=[
                    EstimateCustomLine(
                        label="Bucket truck day",
                        unit_price=200,
                        package_key=baseline.key,
                    )
                ],
            ),
        )
        public = await svc.get_public_comparison(share.token)
        recommended = next(p for p in public.christmas_packages if p.recommended)

        # The card absorbed the line...
        assert recommended.total == round(baseline.total + 200, 2)
        # ...and the headline is that card's total, NOT the card plus the line a
        # second time. That double-count is the one real hazard of scoping.
        assert public.christmas.total == recommended.total
        # Still itemized, so the client can see what they're paying for.
        assert [(line.label, line.amount) for line in public.custom_lines] == [
            ("Bucket truck day", 200)
        ]


async def test_a_line_scoped_to_another_tier_stays_off_the_clients_price() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _packages_workspace(db)
        svc = QuoteService(db)
        cheapest = (await _priced_packages(svc, ws)).christmas_packages[0]
        assert not cheapest.recommended

        share = await svc.share_comparison(
            ws.id,
            ComparisonShareRequest(
                feet=100,
                custom_lines=[
                    EstimateCustomLine(
                        label="Bucket truck day",
                        unit_price=200,
                        package_key=cheapest.key,
                    )
                ],
            ),
        )
        public = await svc.get_public_comparison(share.token)
        recommended = next(p for p in public.christmas_packages if p.recommended)

        # It priced into the tier it was sold with, and nowhere else.
        assert public.christmas_packages[0].total == round(cheapest.total + 200, 2)
        assert public.christmas.total == recommended.total
        # Not itemized against a price it isn't part of.
        assert public.custom_lines == []


async def test_a_line_naming_no_priced_package_is_dropped_from_the_client_page() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _packages_workspace(db)
        svc = QuoteService(db)
        plain = await _priced_packages(svc, ws)

        share = await svc.share_comparison(
            ws.id,
            ComparisonShareRequest(
                feet=100,
                custom_lines=[
                    EstimateCustomLine(
                        label="Bucket truck day",
                        unit_price=200,
                        package_key="platinum",
                    )
                ],
            ),
        )
        public = await svc.get_public_comparison(share.token)

        # A quiet fallback to "global" would move money the rep never asked to.
        assert public.christmas.total == plain.christmas.total
        assert public.custom_lines == []
