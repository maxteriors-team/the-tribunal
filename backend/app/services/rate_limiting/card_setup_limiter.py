"""Rate limits for the unauthenticated card-setup endpoints.

``/p/card-setup/{token}/intent`` is open to the internet and creates a real
Stripe object on every successful call. Two distinct abuses matter and they need
distinct buckets:

* **Per IP** — one host hammering many tokens, or the same token repeatedly, to
  burn Stripe API quota or probe for valid tokens.
* **Per token** — a customer (or something wearing their link) reloading the
  page in a loop. Tokens are single-use, so this should be ~1 in practice; the
  limit exists because "should be" is not an enforcement mechanism.

Follows :mod:`app.services.rate_limiting.embed_limiter` exactly, including its
fail-open-on-Redis-outage stance: a Redis blip must not stop a customer paying.
The single-use token is the hard cap; this is the cost guard in front of it.
"""

from app.services.rate_limiting.embed_limiter import ONE_HOUR_SECONDS, enforce_embed_rate_limit

# A customer normally does this once. Ten leaves room for a fumbled card entry,
# a page refresh, and a shared office IP without ever being a useful attack.
CARD_SETUP_PER_IP_LIMIT = 10
CARD_SETUP_PER_TOKEN_LIMIT = 5

# Reading the page is cheap (no Stripe call), so it gets a looser cap than the
# endpoint that mints SetupIntents — but it is still capped, because an
# uncapped public read keyed by token is a free enumeration oracle.
CARD_SETUP_VIEW_PER_IP_LIMIT = 60


async def enforce_card_setup_view_limits(client_ip: str) -> None:
    """Cap reads of the public card-setup page per IP."""
    await enforce_embed_rate_limit(
        scope="card_setup:view:ip",
        identifier=client_ip,
        limit=CARD_SETUP_VIEW_PER_IP_LIMIT,
        window_seconds=ONE_HOUR_SECONDS,
        detail="Too many requests. Please try again shortly.",
    )


async def enforce_card_setup_intent_limits(client_ip: str, token: str) -> None:
    """Cap SetupIntent creation per IP and per setup token."""
    await enforce_embed_rate_limit(
        scope="card_setup:intent:ip",
        identifier=client_ip,
        limit=CARD_SETUP_PER_IP_LIMIT,
        window_seconds=ONE_HOUR_SECONDS,
        detail="Too many attempts. Please try again later.",
    )
    await enforce_embed_rate_limit(
        scope="card_setup:intent:token",
        identifier=token,
        limit=CARD_SETUP_PER_TOKEN_LIMIT,
        window_seconds=ONE_HOUR_SECONDS,
        detail="Too many attempts on this link. Please ask for a new one.",
    )
