"""Public card-setup page: the customer types their own card.

No auth. Addressed only by an unguessable token that expires in 72 hours and
burns on first use — see :class:`app.models.contact_card_setup_token`.

Two endpoints, deliberately asymmetric:

``GET /p/card-setup/{token}``
    Renders the page: who this is for, which business is asking, the publishable
    key, and the exact consent wording. Creates nothing.

``POST /p/card-setup/{token}/intent``
    Creates a SetupIntent and returns its client secret. This is the expensive,
    abusable one — it is rate limited per IP *and* per token, requires explicit
    consent (a ``Literal[True]`` field, so FastAPI rejects an unconsented body
    with 422 before the handler runs), and spends the token.

The client secret is returned in the response body and **never** logged, put in
a URL, or persisted. The publishable key is served from here rather than a
``NEXT_PUBLIC_`` build variable so there is one source of truth — and because
under Connect the publishable key becomes per-connected-account, at which point
this endpoint's shape is already right.
"""

import structlog
from fastapi import APIRouter, Request

from app.api.deps import DB
from app.api.service_errors import ServiceErrorRoute
from app.core.config import settings
from app.core.utils import get_client_ip
from app.models.workspace import Workspace
from app.schemas.payment_method import (
    PublicCardSetup,
    PublicCardSetupIntent,
    PublicCardSetupIntentRequest,
)
from app.services.exceptions import ValidationError
from app.services.payments import card_on_file_service
from app.services.rate_limiting.card_setup_limiter import (
    enforce_card_setup_intent_limits,
    enforce_card_setup_view_limits,
)

public_router = APIRouter(route_class=ServiceErrorRoute)
logger = structlog.get_logger()


def _client_ip(request: Request) -> str:
    """Return the validated caller IP used for rate limits and the consent record."""
    return get_client_ip(request, settings.trusted_proxies)


@public_router.get("/{token}", response_model=PublicCardSetup)
async def get_card_setup_page(token: str, request: Request, db: DB) -> PublicCardSetup:
    """Render the customer's card-setup page. Expired or spent links are refused."""
    await enforce_card_setup_view_limits(_client_ip(request))

    record = await card_on_file_service.resolve_card_setup_token(db, token)
    contact = record.contact if record.contact is not None else None
    if contact is None:  # pragma: no cover - FK guarantees a contact
        raise ValidationError("This card setup link is no longer valid.")

    workspace = await db.get(Workspace, record.workspace_id)
    business_name = ""
    if workspace is not None:
        from app.services.quotes.proposal_template import get_proposal_template

        template = get_proposal_template(workspace)
        business_name = template.business_name or workspace.name

    return PublicCardSetup(
        # First name only: the page is public, so it confirms "this is for you"
        # without publishing a full customer record to whoever holds the link.
        contact_name=contact.first_name,
        business_name=business_name,
        publishable_key=settings.stripe_publishable_key,
        mandate_text_version=card_on_file_service.CARD_ON_FILE_MANDATE_VERSION,
        mandate_text=card_on_file_service.CARD_ON_FILE_MANDATE_TEXT,
        expires_at=record.expires_at,
    )


@public_router.post("/{token}/intent", response_model=PublicCardSetupIntent)
async def create_card_setup_intent(
    token: str,
    payload: PublicCardSetupIntentRequest,
    request: Request,
    db: DB,
) -> PublicCardSetupIntent:
    """Create the SetupIntent the browser confirms the card against.

    The token is spent here rather than on success, because a SetupIntent is a
    billable Stripe object and one link must not be able to mint several. The
    customer's IP and user agent are read from *this* request — that is the
    written-agreement record, so it has to be observed rather than reported.
    """
    client_ip = _client_ip(request)
    await enforce_card_setup_intent_limits(client_ip, token)

    record = await card_on_file_service.resolve_card_setup_token(db, token)
    if payload.mandate_text_version != card_on_file_service.CARD_ON_FILE_MANDATE_VERSION:
        # The wording changed while this page was open. Refusing is the only safe
        # answer: consent is to a specific text, not to "the terms" in general.
        raise ValidationError(
            "These terms have been updated. Please reload the page and read them again."
        )

    contact = record.contact
    result = await card_on_file_service.create_setup_intent(
        db,
        contact,
        consent_accepted=bool(payload.accept_terms),
        client_ip=client_ip,
        user_agent=request.headers.get("user-agent"),
    )
    await card_on_file_service.burn_card_setup_token(db, record)

    # Logs the SetupIntent id, never the client secret.
    logger.info(
        "card_setup_intent_issued",
        contact_id=contact.id,
        workspace_id=str(record.workspace_id),
        setup_intent_id=result.setup_intent_id,
    )
    return PublicCardSetupIntent(
        client_secret=result.client_secret,
        publishable_key=result.publishable_key,
    )
