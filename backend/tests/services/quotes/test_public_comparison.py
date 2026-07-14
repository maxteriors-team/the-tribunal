"""Real-DB integration tests for the public permanent-vs-temporary comparison.

Exercises the share -> public-view flow end-to-end against Postgres and, most
importantly, proves the client-facing payload **never** carries the internal
linear-feet measurement (nor per-foot rate / zone count). Marked ``integration``
and deselected by default; run with ``pytest -m integration``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal, engine
from app.models.workspace import Workspace
from app.schemas.estimate import ComparisonShareRequest, PublicComparison
from app.services.exceptions import NotFoundError
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


async def test_share_then_public_view_hides_linear_feet() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)

        share = await svc.share_comparison(
            ws.id,
            ComparisonShareRequest(feet=LEAK_FEET, client_name="Dana Homeowner"),
            created_by_id=None,
        )
        assert share.token
        assert share.url.endswith(f"/p/compare/{share.token}")

        public = await svc.get_public_comparison(share.token)
        assert isinstance(public, PublicComparison)

        # Prices are recomputed and present.
        assert public.business_name == "Maxteriors Lighting Co."
        assert public.client_name == "Dana Homeowner"
        assert public.permanent.total == 137 * 30 + 300  # 4410
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


async def test_internal_per_ft_override_recomputes_public_total_without_leaking_rate() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)

        # Rep tunes the permanent rate up to $45/ft for this one job (internal).
        share = await svc.share_comparison(
            ws.id, ComparisonShareRequest(feet=100, per_ft_override=45)
        )
        public = await svc.get_public_comparison(share.token)

        # The homeowner's price reflects the internal rate ($45), not the $30
        # standard configured rate: 100ft * $45 + $300 controller = $4,800.
        assert public.permanent.total == 100 * 45 + 300

        # The rate itself is a private input: neither the per-foot rate nor the
        # override is a field on the client payload.
        dumped = public.model_dump()
        assert "per_ft" not in dumped
        assert "per_ft_override" not in dumped


async def test_internal_christmas_per_ft_override_recomputes_public_total_without_leaking_rate() -> (  # noqa: E501
    None
):
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)

        # Rep tunes the seasonal roofline rate up to $9/ft for this one job.
        share = await svc.share_comparison(
            ws.id, ComparisonShareRequest(feet=100, christmas_per_ft_override=9)
        )
        public = await svc.get_public_comparison(share.token)

        # Seasonal price reflects the internal rate ($9), not the $6 standard.
        assert public.christmas.total == 100 * 9
        # Permanent side untouched by the seasonal override.
        assert public.permanent.total == 100 * 30 + 300
        # No per-foot rate or override field on the client payload.
        dumped = public.model_dump()
        assert "per_ft" not in dumped
        assert "christmas_per_ft_override" not in dumped


async def test_unknown_comparison_token_404() -> None:
    async with AsyncSessionLocal() as db:
        svc = QuoteService(db)
        with pytest.raises(NotFoundError):
            await svc.get_public_comparison("does-not-exist")
