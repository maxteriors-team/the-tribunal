"""Assemble a computed :class:`ProposalDocument` from a raw wizard selection.

Pure given resolved catalog data (no DB), so it is unit-testable and the save +
preview paths share one code path. Every money figure is computed here from the
workspace pricing config via :mod:`app.services.quotes.proposal_pricing`; the
client's submitted quantities are the only untrusted input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.schemas.pricing import ChristmasPricing, PermanentPricing, PricingSettings
from app.schemas.proposal_wizard import (
    CATEGORY_ORDER,
    FulfillmentPart,
    ProposalCarePlan,
    ProposalCategorySection,
    ProposalCharge,
    ProposalDocument,
    ProposalFinancing,
    ProposalLine,
    ProposalTierView,
    ProposalWizardPayload,
    WizardCategoryCount,
)
from app.schemas.quote import QuoteLineItemCreate
from app.services.quotes import proposal_pricing as pp


@dataclass
class CatalogEntry:
    """Resolved catalog item the builder needs (net price + fulfillment parts)."""

    item_id: str
    name: str
    unit_price: Decimal  # net (pre-gross-up)
    transformer: bool = False
    components: list[dict[str, Any]] = field(default_factory=list)


def _d(value: float | int | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _active_categories(payload: ProposalWizardPayload) -> list[str]:
    """Resolve the product lines this quote includes, in canonical order.

    Explicit ``payload.categories`` wins. When empty (legacy wizard payloads),
    infer landscape, plus bistro when a bistro selection with footage is present,
    so pre-existing quotes and callers keep their exact behavior.
    """
    if payload.categories:
        selected = {c for c in payload.categories if c in CATEGORY_ORDER}
    else:
        selected = {"landscape"}
        if payload.bistro is not None and payload.bistro.feet > 0:
            selected.add("bistro")
    return [c for c in CATEGORY_ORDER if c in selected]


def _counts(items: list[WizardCategoryCount]) -> dict[str, float]:
    """Fold size-keyed count rows into a ``{key: qty}`` map (last write wins)."""
    return {i.key: float(i.quantity) for i in items}


def _category_section(
    key: str,
    label: str,
    pricing: PermanentPricing | ChristmasPricing,
    config: PricingSettings,
) -> ProposalCategorySection:
    """Wrap a category pricing result with financed/cash/monthly figures."""
    total = _d(pricing.total)
    return ProposalCategorySection(
        key=key,
        label=label,
        lines=list(pricing.lines),
        financed_total=float(total),
        cash_total=float(pp.cash_price(total, config)) if total > 0 else 0.0,
        cash_savings=float(pp.cash_savings(total, config)) if total > 0 else 0.0,
        monthly_payment=float(pp.monthly_payment(total, config)) if total > 0 else 0.0,
        min_applied=pricing.min_applied,
    )


def build_proposal_document(  # noqa: PLR0912, PLR0915 - one cohesive document assembly
    config: PricingSettings,
    catalog: dict[str, CatalogEntry],
    payload: ProposalWizardPayload,
) -> tuple[ProposalDocument, list[QuoteLineItemCreate]]:
    """Build the snapshot + the canonical line items for the selected tier."""
    qty_map = {q.item_id: _d(q.quantity) for q in payload.quantities}

    # Add-on charges: rep enters net, we gross up (matches every other price).
    charges: list[ProposalCharge] = []
    for c in payload.additional_charges:
        amount = pp.gross_up_price(c.net_amount, config)
        if amount > 0:
            charges.append(
                ProposalCharge(
                    description=(c.description or "").strip() or "Additional Services",
                    amount=float(amount),
                )
            )
    additional_total = sum((_d(c.amount) for c in charges), Decimal("0"))

    categories = _active_categories(payload)
    has_landscape = "landscape" in categories

    tier_order = (config.tier_order or [t.key for t in config.tiers]) if has_landscape else []
    tiers_by_key = {t.key: t for t in config.tiers}

    tier_views: list[ProposalTierView] = []
    tier_base: dict[str, Decimal] = {}
    tier_lines: dict[str, list[ProposalLine]] = {}

    for key in tier_order:
        tcfg = tiers_by_key.get(key)
        if tcfg is None:
            continue
        item_ids = [iid for section in tcfg.sections for iid in section.item_ids]
        lines: list[ProposalLine] = []
        base = Decimal("0")
        for iid in item_ids:
            entry = catalog.get(iid)
            if entry is None:
                continue
            quantity = qty_map.get(iid, Decimal("0"))
            gross = pp.gross_up_price(entry.unit_price, config)
            line_total = gross * quantity
            base += line_total
            lines.append(
                ProposalLine(
                    item_id=iid,
                    name=entry.name,
                    unit_price=float(gross),
                    quantity=float(quantity),
                    line_total=float(line_total),
                    transformer=entry.transformer,
                )
            )
        tier_base[key] = base
        tier_lines[key] = lines
        pricing = pp.price_tier(base, additional_total, config)
        tier_views.append(
            ProposalTierView(
                key=key,
                label=tcfg.label,
                name=tcfg.name,
                experience=tcfg.experience,
                warranty=tcfg.warranty,
                marker=tcfg.marker,
                value_tag=tcfg.value_tag,
                popular=tcfg.popular,
                points=list(tcfg.points),
                lines=lines,
                pricing=pricing,
            )
        )

    # Headline tier = highest base (matches the wizard's headlineTier()).
    headline = None
    if tier_base:
        headline = max(tier_base, key=lambda k: tier_base[k])
    selected = payload.selected_tier if payload.selected_tier in tiers_by_key else headline

    # Care Plan: count non-transformer fixtures in the headline tier unless the
    # rep overrode the count.
    if payload.care_count_manual is not None:
        care_count = payload.care_count_manual
    else:
        care_count = int(
            sum(
                int(line.quantity)
                for line in tier_lines.get(headline or "", [])
                if not line.transformer
            )
        )
    care_plan = None
    if has_landscape and config.care_plan.tiers:
        care_plan = ProposalCarePlan(
            fixture_count=care_count,
            free_fixtures=config.care_plan.free_fixtures,
            options=pp.price_care_plan(care_count, config),
            selected=payload.care_plan_tier,
        )

    # Bistro string lighting (its own bespoke block, kept as-is).
    bistro = None
    if (
        "bistro" in categories
        and payload.bistro is not None
        and payload.bistro.feet > 0
        and config.bistro.enabled
    ):
        bistro = pp.price_bistro(
            config,
            product=payload.bistro.product,
            tier_key=payload.bistro.tier,
            feet=payload.bistro.feet,
        )

    # New per-linear-ft / decor product lines rendered as uniform sections.
    category_sections: list[ProposalCategorySection] = []
    permanent_pricing = None
    if "permanent" in categories and payload.permanent is not None:
        permanent_pricing = pp.price_permanent(
            config,
            feet=payload.permanent.feet,
            channels=payload.permanent.channels,
        )
        if permanent_pricing.total > 0:
            category_sections.append(
                _category_section("permanent", config.permanent.label, permanent_pricing, config)
            )
    christmas_pricing = None
    if "christmas" in categories and payload.christmas is not None:
        christmas_pricing = pp.price_christmas(
            config,
            roofline_feet=payload.christmas.roofline_feet,
            trees=_counts(payload.christmas.trees),
            bushes=_counts(payload.christmas.bushes),
            wreaths=_counts(payload.christmas.wreaths),
            takedown=payload.christmas.takedown,
            storage=payload.christmas.storage,
        )
        if christmas_pricing.total > 0:
            category_sections.append(
                _category_section("christmas", config.christmas.label, christmas_pricing, config)
            )

    financing = ProposalFinancing(
        enabled=config.financing.enabled,
        provider=config.financing.provider,
        terms=pp.finance_terms(config),
        default_term=config.financing.default_term,
        max_amount=config.financing.max_amount,
        headline=config.financing.headline,
        body=config.financing.body,
        points=list(config.financing.points),
        disclaimer=config.financing.disclaimer,
    )

    selected_view = next((v for v in tier_views if v.key == selected), None)
    selected_financed = selected_view.pricing.financed_total if selected_view else 0.0
    selected_cash = selected_view.pricing.cash_total if selected_view else 0.0
    selected_monthly = selected_view.pricing.monthly_payment if selected_view else 0.0

    # Canonical line items (selected tier fixtures with qty>0 + charges + bistro).
    line_items: list[QuoteLineItemCreate] = []
    fulfillment: dict[str, FulfillmentPart] = {}
    if selected_view is not None:
        for line in selected_view.lines:
            if line.quantity <= 0:
                continue
            line_items.append(
                QuoteLineItemCreate(
                    name=line.name,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    discount=0,
                )
            )
            entry = catalog.get(line.item_id)
            for comp in entry.components if entry else []:
                sku = str(comp.get("sku") or "").strip()
                if not sku:
                    continue
                qty = _d(comp.get("qty", 1)) * _d(line.quantity)
                if sku in fulfillment:
                    fulfillment[sku].qty = float(_d(fulfillment[sku].qty) + qty)
                else:
                    fulfillment[sku] = FulfillmentPart(
                        sku=sku, description=comp.get("description"), qty=float(qty)
                    )
    for charge in charges:
        line_items.append(
            QuoteLineItemCreate(
                name=charge.description, quantity=1, unit_price=charge.amount, discount=0
            )
        )
    if bistro is not None and bistro.total > 0:
        product_cfg = config.bistro.color if bistro.product == "color" else config.bistro.classic
        line_items.append(
            QuoteLineItemCreate(
                name=(product_cfg.name if product_cfg else "Bistro Lighting"),
                description=f"{bistro.ordered_ft:g} ft · {bistro.product}",
                quantity=1,
                unit_price=bistro.total,
                discount=0,
            )
        )
    # One canonical line per new category section (permanent / christmas).
    for section in category_sections:
        detail_bits = [line.label for line in section.lines]
        line_items.append(
            QuoteLineItemCreate(
                name=section.label,
                description=" · ".join(detail_bits) if detail_bits else None,
                quantity=1,
                unit_price=section.financed_total,
                discount=0,
            )
        )

    # Grand totals are derived from the emitted line items so the document's
    # display figures can never drift from the server-recomputed quote total.
    grand_financed = sum(
        (_d(li.unit_price) * _d(li.quantity) - _d(li.discount) for li in line_items),
        Decimal("0"),
    )
    grand_cash = pp.cash_price(grand_financed, config) if grand_financed > 0 else Decimal("0")
    grand_monthly = (
        pp.monthly_payment(grand_financed, config) if grand_financed > 0 else Decimal("0")
    )

    document = ProposalDocument(
        version=1,
        client=payload.client,
        tier_order=[v.key for v in tier_views],
        tiers=tier_views,
        selected_tier=selected,
        headline_tier=headline,
        additional_charges=charges,
        care_plan=care_plan,
        bistro=bistro,
        financing=financing,
        night_preview=payload.night_preview,
        mockups=payload.mockups,
        categories=categories,
        category_sections=category_sections,
        selected_financed_total=selected_financed,
        selected_cash_total=selected_cash,
        selected_monthly_payment=selected_monthly,
        grand_financed_total=float(grand_financed),
        grand_cash_total=float(grand_cash),
        grand_monthly_payment=float(grand_monthly),
        fulfillment=list(fulfillment.values()),
        notes=payload.notes,
        terms=payload.terms,
    )
    return document, line_items
