"""On-site upsell schemas.

Deliberately narrow projections. These are the *only* shapes the ``field`` tier
can pull customer or pricing data through, so each one is hand-listed rather than
reusing the full ``ContactResponse`` / ``CatalogItemResponse`` models — inheriting
those would silently widen a technician's view every time an unrelated field is
added to the CRM.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pricing import CarePlanPricing


class UpsellJob(BaseModel):
    """A job the caller may sell an add-on on."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    status: str
    scheduled_start: datetime | None = None
    contact_id: int


class UpsellJobListResponse(BaseModel):
    """The caller's upsellable jobs."""

    items: list[UpsellJob]
    total: int


class UpsellCustomer(BaseModel):
    """The customer on a job — greeting and address detail only.

    No pipeline, notes, tags, lifecycle, or message history: a technician needs
    to know who answers the door and where to put the work, nothing more.
    """

    contact_id: int
    full_name: str
    phone_number: str
    email: str | None = None
    address_line1: str | None = None
    address_city: str | None = None
    address_state: str | None = None
    address_zip: str | None = None


class UpsellCatalogItem(BaseModel):
    """One add-on on the on-site menu."""

    id: uuid.UUID
    name: str
    description: str | None = None
    unit_price: float
    taxable: bool
    service_category: str | None = None
    attach_targets: list[str] = Field(default_factory=list)
    # How ``unit_price`` is measured, when it is not a flat per-item price (e.g.
    # ``"per linear foot"`` for string lighting). Derived server-side from the
    # catalog item's ``attributes`` rather than exposing that raw dict, which
    # also carries internal flags the field tier has no business seeing.
    #
    # Not cosmetic: without it a rate renders identically to a total, and a
    # technician reading "$18.50" aloud for a patio that prices out at $900 has
    # quoted the customer a number the business cannot honour.
    #
    # Deliberately NOT accompanied by the item's job minimum. Minimums apply to
    # whole-system quotes, not to the upgrades sold here, so showing one would
    # make a technician talk a customer out of a $640 add-on over a $2,307 floor
    # that does not apply to it.
    price_unit: str | None = None


class UpsellCatalogResponse(BaseModel):
    """The attachable add-on menu, and what the caller is allowed to sell off it."""

    items: list[UpsellCatalogItem]
    total: int
    # The most this caller may put on one proposal, or ``None`` for no limit
    # (a lead technician, anyone above them, or a workspace that configured no
    # cap). Sent so the UI can warn *before* the technician builds a proposal
    # they are not allowed to send — the server still enforces it either way.
    proposal_limit: float | None = None


class UpsellCarePlanResponse(BaseModel):
    """The Care Plan tiers available at a given fixture count.

    Reuses :class:`~app.schemas.pricing.CarePlanPricing` rather than projecting a
    field subset: this is the *same* priced option the sales wizard and the public
    proposal page render, and a technician's tier must never drift from the one
    the customer sees on the page they approve.
    """

    fixture_count: int
    free_fixtures: int
    options: list[CarePlanPricing] = Field(default_factory=list)
    # False when the workspace has not configured any Care Plan tiers, which is a
    # normal state (not every trade sells maintenance) and renders as guidance
    # rather than an error.
    configured: bool


class UpsellCarePlanSelection(BaseModel):
    """The Care Plan a technician signed the customer up for.

    Carries the tier *key* and the fixture count, never a price: the plan is
    priced server-side from the workspace's pricing config, exactly like the
    wizard prices it.

    ``fixture_count`` is what the technician counted in the yard. It drives
    ``base + per_fixture × (count - free_fixtures)``, so it is a real pricing
    input rather than a note — hence the explicit bound instead of an open int.
    """

    tier_key: str = Field(min_length=1, max_length=64)
    fixture_count: int = Field(ge=0, le=1000)


class UpsellQuoteLine(BaseModel):
    """A requested add-on line.

    Carries **no price**. The server resolves ``unit_price`` and ``name`` from the
    catalog item, so the pricing on an upsell proposal can never be set by the
    device in the driveway.
    """

    catalog_item_id: uuid.UUID
    quantity: float = Field(default=1.0, gt=0)


class UpsellQuoteRequest(BaseModel):
    """Build an add-on proposal for the customer on a job.

    A proposal may carry hardware add-ons, a Care Plan, or both. A Care Plan on
    its own is a complete sale — signing an existing system onto maintenance adds
    no hardware — so ``line_items`` may be empty when ``care_plan`` is set.
    """

    line_items: list[UpsellQuoteLine] = Field(default_factory=list)
    care_plan: UpsellCarePlanSelection | None = None
    title: str | None = Field(default=None, max_length=200)
    notes: str | None = None


class UpsellDeliverRequest(BaseModel):
    """Deliver the add-on proposal to the customer.

    ``to`` is intentionally absent: delivery always goes to the destination
    already on the contact record. Letting a technician type an arbitrary
    recipient would turn the scoped upsell surface into a general-purpose send
    rail for the one tier that does not hold ``comms:send``.
    """

    channel: str = Field(default="sms", pattern="^(sms|email)$")
