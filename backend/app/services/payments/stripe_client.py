"""The single Stripe boundary: client construction plus money-unit conversion.

Every module that talks to Stripe builds its client here. That is deliberate and
load-bearing rather than tidiness: it is the **Connect seam**.

Today one platform API key (``settings.stripe_secret_key``) serves every call,
which is correct while the product is its owner's own tool. When Stripe Connect
lands, each workspace gets its own connected account and every request has to
carry ``stripe_account=acct_...``. Because construction is funnelled through
:func:`stripe_client`, that becomes a single new parameter here instead of an
audit of every call site.

Money conversion lives here too because it is genuinely shared: Stripe takes
amounts in the currency's *minor* unit (cents), except for the zero-decimal
currencies it lists, where the amount is already the smallest unit. Getting that
wrong is a 100x billing error, so both directions have exactly one implementation.
"""

from __future__ import annotations

import stripe

from app.core.config import settings

__all__ = [
    "from_minor_units",
    "is_payment_configured",
    "stripe_client",
    "to_minor_units",
]

# Currencies Stripe treats as zero-decimal: the amount is already the smallest
# unit, so no *100 scaling. https://docs.stripe.com/currencies#zero-decimal
_ZERO_DECIMAL_CURRENCIES = frozenset(
    {
        "bif",
        "clp",
        "djf",
        "gnf",
        "jpy",
        "kmf",
        "krw",
        "mga",
        "pyg",
        "rwf",
        "ugx",
        "vnd",
        "vuv",
        "xaf",
        "xof",
        "xpf",
    }
)


def is_payment_configured() -> bool:
    """Return whether Stripe is configured for collecting payments."""
    return bool(settings.stripe_secret_key)


def to_minor_units(amount: float, currency: str) -> int:
    """Convert a major-unit amount (e.g. dollars) to Stripe's minor units."""
    if currency.lower() in _ZERO_DECIMAL_CURRENCIES:
        return int(round(amount))
    return int(round(amount * 100))


def from_minor_units(amount: int, currency: str) -> float:
    """Convert a Stripe minor-unit amount back to major units (e.g. dollars)."""
    if currency.lower() in _ZERO_DECIMAL_CURRENCIES:
        return float(amount)
    return round(amount / 100, 2)


def stripe_client() -> stripe.StripeClient:
    """Return a Stripe client bound to the platform secret key.

    **This is the Connect seam.** Under Connect this grows a
    ``stripe_account: str | None = None`` parameter that is threaded into the
    per-request ``RequestOptions``; nothing else in the codebase should ever
    construct a ``stripe.StripeClient`` directly.
    """
    return stripe.StripeClient(settings.stripe_secret_key)
