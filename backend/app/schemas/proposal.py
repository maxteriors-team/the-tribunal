"""Client-facing proposal schemas.

Two concerns live here:

* **Proposal template settings** — the per-workspace branding + boilerplate
  (logo, colors, business identity, default intro/terms/footer) stored in
  ``workspace.settings["proposal_template"]``. This is the *extensibility layer*:
  the operator edits these anytime and every proposal re-renders from them, so
  adding a new field is a settings tweak, not a schema migration.
* **Public proposal payload** — the read-only, safe-fields-only view of a sent
  quote rendered on the no-auth client proposal page (``/p/quotes/{token}``). It
  deliberately excludes internal ids, costs, and margins.

Colors are validated as hex on write but read leniently so a hand-edited blob
never turns a settings read into a 500.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Accepts ``#rgb`` or ``#rrggbb`` (case-insensitive).
_HEX_COLOR = r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$"

# Sensible brand defaults so the proposal page looks intentional before the
# operator customizes anything (dark slate primary, blue accent).
DEFAULT_BRAND_COLOR = "#0F172A"
DEFAULT_ACCENT_COLOR = "#2563EB"


class ProposalTemplateSettings(BaseModel):
    """Branding + boilerplate for a workspace's client proposals (read view).

    Read leniently: values come from a JSON blob the operator can edit, so this
    schema never rejects a stored value. ``business_name`` falls back to the
    workspace name in the service when unset.
    """

    business_name: str | None = None
    logo_url: str | None = None
    brand_color: str = DEFAULT_BRAND_COLOR
    accent_color: str = DEFAULT_ACCENT_COLOR
    business_address: str | None = None
    business_phone: str | None = None
    business_email: str | None = None
    # Default intro blurb shown above the line items; per-quote notes can add to it.
    intro: str | None = None
    # Default terms applied when a quote has no terms of its own.
    default_terms: str | None = None
    # Small print at the bottom of every proposal (license #, thank-you, etc.).
    footer: str | None = None


class ProposalTemplateUpdate(BaseModel):
    """Partial update of the proposal template (merged into the settings blob).

    Every field is optional; only provided keys are written. Colors are
    validated as hex here so a bad value is rejected at the edge instead of
    breaking every proposal render.
    """

    business_name: str | None = Field(default=None, max_length=200)
    logo_url: str | None = Field(default=None, max_length=2000)
    brand_color: str | None = Field(default=None, pattern=_HEX_COLOR)
    accent_color: str | None = Field(default=None, pattern=_HEX_COLOR)
    business_address: str | None = Field(default=None, max_length=500)
    business_phone: str | None = Field(default=None, max_length=50)
    business_email: str | None = Field(default=None, max_length=320)
    intro: str | None = Field(default=None, max_length=4000)
    default_terms: str | None = Field(default=None, max_length=8000)
    footer: str | None = Field(default=None, max_length=2000)


# --------------------------------------------------------------------------- #
# Public proposal payload (no-auth client page)
# --------------------------------------------------------------------------- #
class PublicProposalLineItem(BaseModel):
    """A single proposal line as shown to the client (no internal ids)."""

    name: str
    description: str | None = None
    quantity: float
    unit_price: float
    discount: float
    total: float


class PublicProposalBranding(BaseModel):
    """The branding subset rendered on the public proposal page."""

    business_name: str
    logo_url: str | None = None
    brand_color: str = DEFAULT_BRAND_COLOR
    accent_color: str = DEFAULT_ACCENT_COLOR
    business_address: str | None = None
    business_phone: str | None = None
    business_email: str | None = None
    footer: str | None = None


class PublicProposal(BaseModel):
    """Read-only proposal payload for the client-facing page.

    Safe fields only — no workspace/contact/quote ids, costs, or margins. The
    ``token`` is echoed back so the page can call approve/decline.
    """

    token: str
    number: str
    title: str | None = None
    status: str
    currency: str
    subtotal: float
    tax_amount: float
    discount_amount: float
    total: float
    issue_date: date | None = None
    expiry_date: date | None = None
    is_expired: bool = False
    # A decided proposal can't be approved/declined again by the client.
    is_decided: bool = False
    intro: str | None = None
    notes: str | None = None
    terms: str | None = None
    client_name: str | None = None
    line_items: list[PublicProposalLineItem] = Field(default_factory=list)
    # Rich multi-tier presentation snapshot built by the sales wizard. When set,
    # the public page renders the Good/Better/Best tiers, financing, Care Plan,
    # and add-ons from it; when null it falls back to the flat ``line_items``.
    proposal_document: dict[str, Any] | None = None
    branding: PublicProposalBranding


class PublicProposalDecline(BaseModel):
    """Optional decline reason from the client."""

    reason: str | None = Field(default=None, max_length=2000)


class PublicProposalActionResult(BaseModel):
    """Result of a client approve/decline on the public proposal page."""

    token: str
    status: str
    message: str

    model_config = ConfigDict(from_attributes=True)
