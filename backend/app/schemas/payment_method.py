"""Card-on-file schemas.

Every response here is display metadata plus opaque Stripe handles. No schema in
this module has a field that could carry a card number, and none ever should —
the customer's PAN is typed into a Stripe-owned iframe and never crosses this
API boundary.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PaymentMethodStatus = Literal["active", "removed", "expired"]
ChargeTrigger = Literal["invoice", "deposit", "recurring_job", "no_show_fee", "manual"]
ChargeOutcome = Literal[
    "succeeded",
    "declined",
    "requires_action",
    "error",
    "no_card_on_file",
    "skipped_no_automation",
]


class PaymentMethodResponse(BaseModel):
    """A saved card as the operator dashboard sees it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contact_id: int
    brand: str | None = None
    last4: str | None = None
    exp_month: int | None = None
    exp_year: int | None = None
    is_default: bool
    status: PaymentMethodStatus
    # Which version of the consent wording this customer agreed to, and when.
    # Surfaced so an operator can answer "what did they actually authorize?"
    # without a database query.
    mandate_text_version: str
    mandate_accepted_at: datetime
    created_at: datetime


class CardSetupLinkResponse(BaseModel):
    """A freshly minted, single-use card-setup link for a customer."""

    url: str
    token: str
    expires_at: datetime


class ChargeCardRequest(BaseModel):
    """Charge a contact's saved card for a specific amount."""

    amount: float = Field(gt=0, description="Amount in major units (e.g. dollars).")
    currency: str = Field(default="USD", min_length=3, max_length=3)
    description: str = Field(min_length=1, max_length=255)
    trigger: ChargeTrigger = "manual"
    invoice_id: uuid.UUID | None = None
    # Which saved card to use. Omitted means the contact's default card.
    payment_method_id: uuid.UUID | None = None


class ChargeCardResponse(BaseModel):
    """Outcome of an off-session charge.

    ``status`` is the whole point: ``succeeded``, ``requires_action`` (the
    customer must authenticate — recoverable), and ``declined`` (hard no, not
    retried) are three different things and the UI must not blur them.
    """

    status: ChargeOutcome
    amount: float
    currency: str
    attempt_id: uuid.UUID | None = None
    payment_intent_id: str | None = None
    decline_code: str | None = None
    message: str | None = None
    # Present only for ``requires_action``: where to send the customer so they
    # can authenticate and complete this same payment. Deliberately a page URL,
    # never a client secret — secrets do not belong in links.
    recovery_url: str | None = None


class PublicCardSetup(BaseModel):
    """What the customer's card-setup page needs before it can render a form."""

    contact_name: str
    business_name: str
    publishable_key: str
    mandate_text_version: str
    mandate_text: str
    expires_at: datetime


class PublicCardSetupIntentRequest(BaseModel):
    """The customer's explicit opt-in, sent with the request that starts setup.

    ``accept_terms`` is ``Literal[True]``, so a request that omits it or sends
    ``false`` is rejected by FastAPI's own validation with a 422 **before the
    handler runs** — no Stripe object is created for an unconsented save. The
    service re-checks it anyway; this is the boundary, not the only guard.
    """

    accept_terms: Literal[True]
    mandate_text_version: str = Field(min_length=1, max_length=50)


class PublicCardSetupIntent(BaseModel):
    """The SetupIntent client secret for one customer's card entry.

    Scoped to a single customer and a single card entry. It is returned once, to
    the browser that holds the setup token, and is never logged or persisted.
    """

    client_secret: str
    publishable_key: str
