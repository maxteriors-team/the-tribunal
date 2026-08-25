"""Assemble a computed :class:`ProposalDocument` from a raw wizard selection.

Pure given resolved catalog data (no DB), so it is unit-testable and the save +
preview paths share one code path. Every money figure is computed here from the
workspace pricing config via :mod:`app.services.quotes.proposal_pricing`; the
client's submitted quantities are the only untrusted input.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.schemas.pricing import (
    DEFAULT_FINANCING_DISCLAIMER,
    MAINTENANCE_THROUGH_TOKEN,
    BistroInstallation,
    BistroPricing,
    ChristmasPackage,
    ChristmasPricing,
    PermanentPricing,
    PricingSettings,
    TierPricing,
    ValueProp,
)
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
    service_for_categories,
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
    # The price-book row's real primary key, carried alongside the stable
    # ``item_id`` key (a ``sku``) so an emitted line can tell the quote service
    # which catalog item to snapshot its ``service_category`` from. Without it a
    # wizard quote saves entirely uncategorized and reports no primary service,
    # which makes both attach metrics and attach rules blind to it.
    catalog_item_id: uuid.UUID | None = None


def _d(value: float | int | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _price_book_tier(base: Decimal, additional: Decimal, config: PricingSettings) -> TierPricing:
    """Price one package directly from catalog rows, with no finance/cash fork."""
    total = base + additional if base > 0 else base
    commission = pp.commission_amount(total, config) if total > 0 else Decimal("0")
    return TierPricing(
        base=float(base),
        additional=float(additional),
        financed_total=float(total),
        cash_total=float(total),
        cash_savings=0,
        monthly_payment=0,
        monthly_by_term={},
        commission_financed=float(commission),
        commission_cash=float(commission),
    )


def _active_categories(payload: ProposalWizardPayload) -> list[str]:
    """Resolve the product lines this quote includes, in canonical order.

    Explicit ``payload.categories`` wins. When empty (legacy wizard payloads),
    infer landscape, plus bistro when a bistro selection has legacy footage or
    grouped measured runs, so pre-existing callers keep their exact behavior.
    """
    if payload.categories:
        selected = {c for c in payload.categories if c in CATEGORY_ORDER}
    else:
        selected = {"landscape"}
        if payload.bistro is not None and (payload.bistro.feet > 0 or payload.bistro.runs):
            selected.add("bistro")
    return [c for c in CATEGORY_ORDER if c in selected]


def _counts(items: list[WizardCategoryCount]) -> dict[str, float]:
    """Fold size-keyed count rows into a ``{key: qty}`` map (last write wins)."""
    return {i.key: float(i.quantity) for i in items}


def _christmas_value_props(config: PricingSettings) -> list[ValueProp]:
    """Seasonal selling points with the maintenance cutoff date resolved.

    Substituting here rather than in the client snapshots the promise onto the
    saved proposal: the customer keeps reading the date they were sold, even
    after the workspace moves its cutoff for a later season.
    """
    through = config.christmas.maintenance_through_label
    return [
        ValueProp(
            title=prop.title,
            body=prop.body.replace(MAINTENANCE_THROUGH_TOKEN, through),
        )
        for prop in config.christmas.value_props
    ]


def _category_section(
    key: str,
    label: str,
    pricing: PermanentPricing | ChristmasPricing,
    config: PricingSettings,
    *,
    takedown: bool | None = None,
    storage: bool | None = None,
    value_props: list[ValueProp] | None = None,
) -> ProposalCategorySection:
    """Wrap a category pricing result with financed/cash/monthly figures.

    ``takedown``/``storage`` are the seasonal services the client bought. Only
    the christmas section passes them (permanent leaves them ``None``) so
    dispatch can later read what was sold instead of inferring it from the
    wording of a display line. ``value_props`` is likewise seasonal-only today.
    """
    total = _d(pricing.total)
    return ProposalCategorySection(
        key=key,
        label=label,
        lines=list(pricing.lines),
        value_props=list(value_props or []),
        financed_total=float(total),
        cash_total=float(pp.cash_price(total, config)) if total > 0 else 0.0,
        cash_savings=float(pp.cash_savings(total, config)) if total > 0 else 0.0,
        monthly_payment=float(pp.monthly_payment(total, config)) if total > 0 else 0.0,
        min_applied=pricing.min_applied,
        takedown=takedown,
        storage=storage,
    )


def _resolve_christmas_package(
    config: PricingSettings,
    selected_key: str | None,
    *,
    roofline_feet: float,
    items: dict[str, dict[str, float]],
    takedown: bool,
    storage: bool,
) -> ChristmasPackage | None:
    """Pick which seasonal package to quote when Christmas packages are enabled.

    The client's ``selected_package`` wins when it names a configured package.
    Otherwise fall back to the most inclusive package — highest in the canonical
    low→high order (``package_order`` then declared order, mirroring
    :func:`pp.price_christmas_packages`) — whose priced total is > 0, so an unset
    or stale selection still quotes the fullest display the measurement supports.
    Returns ``None`` when no package is configured or none prices above zero.
    """
    packages = config.christmas.packages
    by_key = {p.key: p for p in packages}
    if selected_key and selected_key in by_key:
        return by_key[selected_key]
    order = [k for k in config.christmas.package_order if k in by_key]
    order += [p.key for p in packages if p.key not in order]
    for key in reversed(order):
        pricing = pp.price_christmas_package(
            config,
            by_key[key],
            roofline_feet=roofline_feet,
            items=items,
            takedown=takedown,
            storage=storage,
        )
        if pricing.total > 0:
            return by_key[key]
    return None


def build_proposal_document(  # noqa: PLR0912, PLR0915 - one cohesive document assembly
    config: PricingSettings,
    catalog: dict[str, CatalogEntry],
    payload: ProposalWizardPayload,
) -> tuple[ProposalDocument, list[QuoteLineItemCreate]]:
    """Build the snapshot + the canonical line items for the selected tier."""
    qty_map = {q.item_id: _d(q.quantity) for q in payload.quantities}

    use_price_book = payload.pricing_source == "price_book"

    # Add-on charges follow the same pricing source as catalog lines.
    charges: list[ProposalCharge] = []
    for c in payload.additional_charges:
        amount = _d(c.net_amount) if use_price_book else pp.gross_up_price(c.net_amount, config)
        if amount > 0:
            charges.append(
                ProposalCharge(
                    id=new_charge_id(),
                    description=(c.description or "").strip() or "Additional Services",
                    amount=float(amount),
                    catalog_item_id=c.catalog_item_id,
                    tier_key=c.tier_key,
                )
            )
    categories = _active_categories(payload)
    has_landscape = "landscape" in categories

    tier_order = (config.tier_order or [t.key for t in config.tiers]) if has_landscape else []
    tiers_by_key = {t.key: t for t in config.tiers}
    # The keys a charge may legitimately name. Resolved before the tier loop so
    # the card price and the quote's line items apply the same stale-key rule;
    # if they disagreed, a document's displayed total would drift from the
    # server-recomputed one.
    known_tier_keys = set(tier_order)

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
            unit_price = (
                entry.unit_price if use_price_book else pp.gross_up_price(entry.unit_price, config)
            )
            line_total = unit_price * quantity
            base += line_total
            lines.append(
                ProposalLine(
                    item_id=iid,
                    name=entry.name,
                    unit_price=float(unit_price),
                    quantity=float(quantity),
                    line_total=float(line_total),
                    transformer=entry.transformer,
                )
            )
        tier_base[key] = base
        tier_lines[key] = lines
        # Only the charges this tier actually carries: a charge pinned to the
        # Premier must not inflate the Starter's card price, which is the whole
        # point of pinning it.
        tier_additional = sum(
            (_d(c.amount) for c in _charges_for(charges, key, known_tier_keys)),
            Decimal("0"),
        )
        pricing = (
            _price_book_tier(base, tier_additional, config)
            if use_price_book
            else pp.price_tier(base, tier_additional, config)
        )
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

    # Bistro measured runs use installation rates; legacy product footage keeps
    # the pre-existing strand/classic algorithm unchanged.
    bistro = None
    if "bistro" in categories and payload.bistro is not None:
        if payload.bistro.runs:
            grouped_runs: dict[BistroInstallation, float] = {}
            for run in payload.bistro.runs:
                grouped_runs[run.installation] = grouped_runs.get(run.installation, 0) + run.feet
            bistro = pp.price_bistro_installations(config, grouped_runs)
        elif payload.bistro.feet > 0 and config.bistro.enabled:
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
        christmas_items = {key: _counts(rows) for key, rows in payload.christmas.items.items()}
        if config.christmas.packages_enabled:
            # Sell Christmas as a single Good/Better/Best package: resolve the
            # client's pick (or the most inclusive priced package) and quote it
            # via the shared engine restricted to that package's coverage.
            package = _resolve_christmas_package(
                config,
                payload.christmas.selected_package,
                roofline_feet=payload.christmas.roofline_feet,
                items=christmas_items,
                takedown=payload.christmas.takedown,
                storage=payload.christmas.storage,
            )
            if package is not None:
                christmas_pricing = pp.price_christmas_package(
                    config,
                    package,
                    roofline_feet=payload.christmas.roofline_feet,
                    items=christmas_items,
                    takedown=payload.christmas.takedown,
                    storage=payload.christmas.storage,
                )
        else:
            christmas_pricing = pp.price_christmas(
                config,
                roofline_feet=payload.christmas.roofline_feet,
                items=christmas_items,
                takedown=payload.christmas.takedown,
                storage=payload.christmas.storage,
            )
        if christmas_pricing is not None and christmas_pricing.total > 0:
            category_sections.append(
                _category_section(
                    "christmas",
                    config.christmas.label,
                    christmas_pricing,
                    config,
                    # What the client bought, not what the workspace offers:
                    # takedown only counts when the config allowed it too, so
                    # this matches the money the engine actually charged.
                    takedown=payload.christmas.takedown and config.christmas.takedown_enabled,
                    storage=payload.christmas.storage,
                    value_props=_christmas_value_props(config),
                )
            )

    selection = select_tier(
        tier_views=tier_views,
        selected=selected,
        charges=charges,
        bistro=bistro,
        category_sections=category_sections,
        config=config,
        catalog=catalog,
        pricing_source=payload.pricing_source,
    )

    # Financing eligibility is presentation-only. Keep the existing price buffer
    # global so category configuration can never remove the fee gross-up or alter
    # cash-price reversal. Each qualifying service contributes its own subtotal;
    # uncategorized add-on charges cannot make an otherwise ineligible quote qualify.
    #
    # Every product line the quote covers starts at 0 rather than being omitted:
    # a category with no priced work still *is* part of this quote, and lighting
    # categories carry a zero minimum, so a landscape package sold entirely on
    # add-on charges keeps the estimate it showed before financing became
    # category-aware. A category with a real floor still has to clear it.
    category_totals: dict[str, float] = dict.fromkeys(categories, 0.0)
    for section in category_sections:
        category_totals[section.key] = section.financed_total
    selected_view = next((view for view in tier_views if view.key == selected), None)
    if has_landscape and selected_view is not None:
        category_totals["landscape"] = selected_view.pricing.base
    if bistro is not None and bistro.total > 0:
        category_totals["bistro"] = bistro.total

    financing = ProposalFinancing(
        enabled=(
            not use_price_book
            and pp.financing_is_eligible(selection.grand_financed, category_totals, config)
        ),
        provider=config.financing.provider,
        terms=[] if use_price_book else pp.finance_terms(config),
        default_term=config.financing.default_term,
        max_amount=config.financing.max_amount,
        headline=config.financing.headline,
        body=config.financing.body,
        points=list(config.financing.points),
        disclaimer=(config.financing.disclaimer or DEFAULT_FINANCING_DISCLAIMER),
    )

    document = ProposalDocument(
        version=1,
        pricing_source=payload.pricing_source,
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
        service=service_for_categories(categories),
        selected_financed_total=selection.selected_financed,
        selected_cash_total=selection.selected_cash,
        selected_monthly_payment=selection.selected_monthly,
        grand_financed_total=selection.grand_financed,
        grand_cash_total=selection.grand_cash,
        grand_monthly_payment=selection.grand_monthly,
        fulfillment=selection.fulfillment,
        notes=payload.notes,
        terms=payload.terms,
    )
    return document, selection.line_items


# --------------------------------------------------------------------------- #
# Package selection (shared by the builder and the client's own pick)
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class TierSelection:
    """Everything that follows from *which package* a quote is sold at.

    Produced by :func:`select_tier` and consumed both when the rep builds the
    quote and when the client picks a different package on the public page, so
    the money a client is charged is derived exactly one way.
    """

    line_items: list[QuoteLineItemCreate]
    fulfillment: list[FulfillmentPart]
    selected_financed: float
    selected_cash: float
    selected_monthly: float
    grand_financed: float
    grand_cash: float
    grand_monthly: float


def _charges_for(
    charges: Sequence[ProposalCharge],
    selected: str | None,
    known_keys: set[str],
) -> list[ProposalCharge]:
    """Charges owed when ``selected`` is the tier being bought.

    Global charges (no ``tier_key``) always apply. A pinned charge applies only
    to its own tier — that is what makes it follow the package it was sold with.
    A key matching no known tier falls back to global rather than vanishing, so a
    stale key can never silently delete money from a quote.
    """
    return [
        charge
        for charge in charges
        if charge.tier_key is None
        or charge.tier_key not in known_keys
        or charge.tier_key == selected
    ]


def charges_for_tier(
    charges: Sequence[ProposalCharge],
    selected: str | None,
    tier_views: Sequence[ProposalTierView],
) -> list[ProposalCharge]:
    """:func:`_charges_for` against a document's own tiers."""
    return _charges_for(charges, selected, {view.key for view in tier_views})


def _bistro_quote_line(bistro: BistroPricing, config: PricingSettings) -> QuoteLineItemCreate:
    """Describe measured runs without falling back to a legacy product label."""
    if bistro.pricing_mode == "installation":
        name = "Bistro Lighting"
        description = " · ".join(f"{row.feet:g} ft {row.label}" for row in bistro.installations)
    else:
        product_cfg = config.bistro.color if bistro.product == "color" else config.bistro.classic
        name = product_cfg.name if product_cfg else "Bistro Lighting"
        description = f"{bistro.ordered_ft:g} ft · {bistro.product}"
    return QuoteLineItemCreate(
        name=name,
        description=description,
        quantity=1,
        unit_price=bistro.total,
        discount=0,
    )


def select_tier(
    *,
    tier_views: list[ProposalTierView],
    selected: str | None,
    charges: list[ProposalCharge],
    bistro: BistroPricing | None,
    category_sections: list[ProposalCategorySection],
    config: PricingSettings,
    catalog: dict[str, CatalogEntry] | None = None,
    pricing_source: str = "workspace_rules",
) -> TierSelection:
    """Derive the canonical line items + totals for one selected package.

    The tier contributes its own fixture lines. Bistro and the per-category
    sections are tier-independent and ride along with every package; a charge
    does too *unless* it names a ``tier_key``, in which case it is only charged
    when that tier is the one being bought — see :func:`charges_for_tier`.
    Grand totals are summed from the emitted line items so a document's display
    figures can never drift from the server-recomputed quote total.

    ``catalog`` supplies the staff fulfillment sheet and the price-book id each
    fixture line snapshots its service category from; pass ``None`` when pricing
    a package purely for display, and the sheet comes back empty and the lines
    uncategorized (neither affects a displayed total).
    """
    selected_view = next((v for v in tier_views if v.key == selected), None)

    line_items: list[QuoteLineItemCreate] = []
    fulfillment: dict[str, FulfillmentPart] = {}
    if selected_view is not None:
        for line in selected_view.lines:
            if line.quantity <= 0:
                continue
            entry = (catalog or {}).get(line.item_id)
            line_items.append(
                QuoteLineItemCreate(
                    name=line.name,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    discount=0,
                    catalog_item_id=entry.catalog_item_id if entry else None,
                )
            )
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
    for charge in charges_for_tier(charges, selected, tier_views):
        line_items.append(
            QuoteLineItemCreate(
                name=charge.description,
                quantity=1,
                unit_price=charge.amount,
                discount=0,
                catalog_item_id=charge.catalog_item_id,
            )
        )
    if bistro is not None and bistro.total > 0:
        line_items.append(_bistro_quote_line(bistro, config))
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

    grand_financed = sum(
        (_d(li.unit_price) * _d(li.quantity) - _d(li.discount) for li in line_items),
        Decimal("0"),
    )
    if pricing_source == "price_book":
        grand_cash = grand_financed
        grand_monthly = Decimal("0")
    else:
        grand_cash = pp.cash_price(grand_financed, config) if grand_financed > 0 else Decimal("0")
        grand_monthly = (
            pp.monthly_payment(grand_financed, config) if grand_financed > 0 else Decimal("0")
        )

    return TierSelection(
        line_items=line_items,
        fulfillment=list(fulfillment.values()),
        selected_financed=selected_view.pricing.financed_total if selected_view else 0.0,
        selected_cash=selected_view.pricing.cash_total if selected_view else 0.0,
        selected_monthly=selected_view.pricing.monthly_payment if selected_view else 0.0,
        grand_financed=float(grand_financed),
        grand_cash=float(grand_cash),
        grand_monthly=float(grand_monthly),
    )


def new_charge_id() -> str:
    """Mint a stable handle for one :class:`ProposalCharge` within a document."""
    return uuid.uuid4().hex


def add_charge(
    document: ProposalDocument,
    *,
    description: str,
    net_amount: float,
    config: PricingSettings,
    catalog_item_id: uuid.UUID | None = None,
) -> tuple[ProposalDocument, str]:
    """Append one add-on charge to a snapshot, returning it and the new charge id.

    ``net_amount`` is what the rep keeps; it is grossed up by the finance buffer
    exactly as :func:`build_proposal_document` does for a charge typed during the
    original build, so a service added afterwards prices identically to the same
    service added before saving.

    Does **not** reprice — the caller pairs this with :func:`reprice_document`,
    which is what turns the charge into quote lines and totals.
    """
    amount = (
        _d(net_amount)
        if document.pricing_source == "price_book"
        else pp.gross_up_price(net_amount, config)
    )
    if amount <= 0:
        raise ValueError("A service needs an amount above zero")
    charge = ProposalCharge(
        id=new_charge_id(),
        description=description.strip() or "Additional Services",
        amount=float(amount),
        catalog_item_id=catalog_item_id,
    )
    updated = document.model_copy(
        update={"additional_charges": [*document.additional_charges, charge]},
        deep=True,
    )
    return updated, str(charge.id)


def remove_charge(document: ProposalDocument, charge_id: str) -> ProposalDocument:
    """Drop one add-on charge by id. Raises :class:`ValueError` if it isn't there.

    Does not reprice; see :func:`add_charge`.
    """
    remaining = [c for c in document.additional_charges if c.id != charge_id]
    if len(remaining) == len(document.additional_charges):
        raise ValueError("That service is no longer on this quote")
    return document.model_copy(update={"additional_charges": remaining}, deep=True)


def sellable_tier_keys(document: ProposalDocument) -> list[str]:
    """Package keys a client may actually buy, in the document's own order.

    A tier with no priced fixtures is a "Custom Quote" placeholder on the client
    page — it has no total, so it can never be selected or charged for.
    """
    priced = {v.key for v in document.tiers if v.pricing.base > 0}
    order = [k for k in document.tier_order if k in priced]
    return order or [v.key for v in document.tiers if v.key in priced]


def reprice_document(
    document: ProposalDocument,
    *,
    config: PricingSettings,
    catalog: dict[str, CatalogEntry] | None = None,
) -> tuple[ProposalDocument, list[QuoteLineItemCreate]]:
    """Re-derive a saved snapshot's money from its own current contents.

    The single place a stored document's totals, fulfillment sheet and canonical
    line items are recomputed. Used whenever something *inside* the document
    changes after it was first built — today, a service added to or removed from
    ``additional_charges`` — and by :func:`reselect_tier` once it has pointed the
    document at a different package. Keeping both on one path is what stops a
    post-save edit from pricing differently than the rep's original build.

    ``deposit_amount`` is recomputed too: it is a function of the all-in total,
    so leaving it alone here would leave a stale money figure sitting in a
    snapshot whose total just moved.
    """
    selection = select_tier(
        tier_views=document.tiers,
        selected=document.selected_tier,
        charges=document.additional_charges,
        bistro=document.bistro,
        category_sections=document.category_sections,
        config=config,
        catalog=catalog,
        pricing_source=document.pricing_source,
    )
    update: dict[str, Any] = {
        "selected_financed_total": selection.selected_financed,
        "selected_cash_total": selection.selected_cash,
        "selected_monthly_payment": selection.selected_monthly,
        "grand_financed_total": selection.grand_financed,
        "grand_cash_total": selection.grand_cash,
        "grand_monthly_payment": selection.grand_monthly,
        "fulfillment": selection.fulfillment,
    }
    if document.deposit_mode and document.deposit_value > 0:
        # Imported here rather than at module scope: the payments package reads
        # quote models, and this module is deliberately DB-free.
        from app.services.payments.quote_deposit_service import resolve_deposit

        update["deposit_amount"] = resolve_deposit(
            document.deposit_mode, document.deposit_value, selection.grand_financed
        )
    updated = document.model_copy(update=update, deep=True)
    return updated, selection.line_items


def reselect_tier(
    document: ProposalDocument,
    tier_key: str,
    *,
    config: PricingSettings,
    catalog: dict[str, CatalogEntry] | None = None,
) -> tuple[ProposalDocument, list[QuoteLineItemCreate]]:
    """Re-point a saved snapshot at a different package, re-deriving its money.

    This is how a client's own package choice becomes the quote they're charged
    for: only the tier key crosses the wire, and every figure is recomputed here
    from the stored snapshot through the same :func:`select_tier` path the rep's
    build used. Raises :class:`ValueError` for a tier that isn't sellable.
    """
    if tier_key not in sellable_tier_keys(document):
        raise ValueError(f"Unknown package: {tier_key}")

    return reprice_document(
        document.model_copy(update={"selected_tier": tier_key}),
        config=config,
        catalog=catalog,
    )
