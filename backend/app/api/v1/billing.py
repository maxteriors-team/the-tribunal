"""Stripe subscription billing endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import stripe
import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.core.config import settings
from app.core.encryption import decrypt_json, encrypt_json
from app.models.workspace import WorkspaceIntegration, WorkspaceMembership

router = APIRouter()
logger = structlog.get_logger()

_STRIPE_INTEGRATION_TYPE = "stripe"


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class CheckoutRequest(BaseModel):
    price_id: str | None = None


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalResponse(BaseModel):
    portal_url: str


class BillingStatus(BaseModel):
    subscribed: bool
    plan: str | None = None
    status: str | None = None
    current_period_end: datetime | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stripe_client() -> stripe.StripeClient:
    """Return a configured Stripe client."""
    return stripe.StripeClient(settings.stripe_secret_key)


async def _get_user_workspace_id(current_user: CurrentUser, db: DB) -> uuid.UUID:
    """Resolve the user's default (or first) workspace ID."""
    result = await db.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == current_user.id,
            WorkspaceMembership.is_default.is_(True),
        )
    )
    membership = result.scalar_one_or_none()

    if membership is None:
        result = await db.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.user_id == current_user.id)
            .order_by(WorkspaceMembership.created_at.asc())
            .limit(1)
        )
        membership = result.scalar_one_or_none()

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No workspace found. Please create a workspace first.",
        )

    return membership.workspace_id


async def _get_stripe_integration(workspace_id: uuid.UUID, db: DB) -> WorkspaceIntegration | None:
    """Fetch the Stripe WorkspaceIntegration for this workspace, or None."""
    result = await db.execute(
        select(WorkspaceIntegration).where(
            WorkspaceIntegration.workspace_id == workspace_id,
            WorkspaceIntegration.integration_type == _STRIPE_INTEGRATION_TYPE,
        )
    )
    return result.scalar_one_or_none()


async def _upsert_stripe_integration(
    workspace_id: uuid.UUID,
    db: DB,
    credentials: dict[str, Any],
) -> None:
    """Create or update the Stripe WorkspaceIntegration with the given credentials."""
    existing = await _get_stripe_integration(workspace_id, db)
    if existing is not None:
        existing.encrypted_credentials = encrypt_json(credentials)
        existing.is_active = True
    else:
        db.add(
            WorkspaceIntegration(
                workspace_id=workspace_id,
                integration_type=_STRIPE_INTEGRATION_TYPE,
                encrypted_credentials=encrypt_json(credentials),
                is_active=True,
            )
        )
    await db.commit()


def _get_customer_id(integration: WorkspaceIntegration | None) -> str | None:
    """Return the stored Stripe customer ID, or None."""
    if integration is None:
        return None
    try:
        creds = decrypt_json(integration.encrypted_credentials)
        return creds.get("customer_id") or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    request: CheckoutRequest,
    current_user: CurrentUser,
    db: DB,
) -> CheckoutResponse:
    """Create a Stripe Checkout session for a new subscription."""
    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is not configured.",
        )

    workspace_id = await _get_user_workspace_id(current_user, db)
    price_id = request.price_id or settings.stripe_price_id

    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Stripe price ID provided.",
        )

    client = _stripe_client()

    # Re-use existing customer if we already have one
    existing = await _get_stripe_integration(workspace_id, db)
    customer_id = _get_customer_id(existing)

    # Build params as a plain dict so we can conditionally add keys.
    # The Stripe SDK accepts plain dicts wherever TypedDicts are expected.
    params: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": f"{settings.frontend_url}/realtor-dashboard?subscribed=true",
        "cancel_url": f"{settings.frontend_url}/onboarding",
        "metadata": {"workspace_id": str(workspace_id)},
    }
    if customer_id:
        params["customer"] = customer_id
    else:
        params["customer_email"] = current_user.email

    try:
        session = client.checkout.sessions.create(params=params)  # type: ignore[arg-type]
    except stripe.StripeError as exc:
        logger.error(
            "stripe_checkout_error",
            error=str(exc),
            workspace_id=str(workspace_id),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe error: {exc.user_message}",
        ) from exc

    logger.info(
        "stripe_checkout_created",
        workspace_id=str(workspace_id),
        session_id=session.id,
    )

    return CheckoutResponse(checkout_url=session.url or "")


@router.post("/portal", response_model=PortalResponse)
async def create_portal(
    current_user: CurrentUser,
    db: DB,
) -> PortalResponse:
    """Create a Stripe Customer Portal session for subscription management."""
    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is not configured.",
        )

    workspace_id = await _get_user_workspace_id(current_user, db)
    existing = await _get_stripe_integration(workspace_id, db)
    customer_id = _get_customer_id(existing)

    if not customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active subscription found. Please subscribe first.",
        )

    client = _stripe_client()

    try:
        return_url = f"{settings.frontend_url}/realtor-dashboard"
        session = client.billing_portal.sessions.create(
            params={"customer": customer_id, "return_url": return_url},
        )
    except stripe.StripeError as exc:
        logger.error(
            "stripe_portal_error",
            error=str(exc),
            workspace_id=str(workspace_id),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe error: {exc.user_message}",
        ) from exc

    logger.info(
        "stripe_portal_created",
        workspace_id=str(workspace_id),
        customer_id=customer_id,
    )

    return PortalResponse(portal_url=session.url)


@router.get("/status", response_model=BillingStatus)
async def get_billing_status(
    current_user: CurrentUser,
    db: DB,
) -> BillingStatus:
    """Return the subscription status for the current workspace."""
    if not settings.stripe_secret_key:
        return BillingStatus(subscribed=False)

    workspace_id = await _get_user_workspace_id(current_user, db)
    existing = await _get_stripe_integration(workspace_id, db)
    customer_id = _get_customer_id(existing)

    if not customer_id:
        return BillingStatus(subscribed=False)

    client = _stripe_client()

    try:
        subscriptions = client.subscriptions.list(
            params={"customer": customer_id, "status": "all", "limit": 1},
        )
    except stripe.StripeError as exc:
        logger.error(
            "stripe_status_error",
            error=str(exc),
            workspace_id=str(workspace_id),
        )
        return BillingStatus(subscribed=False)

    if not subscriptions.data:
        return BillingStatus(subscribed=False)

    sub = subscriptions.data[0]
    is_active = sub.status in ("active", "trialing")

    plan_name: str | None = None
    if sub.items.data:
        item = sub.items.data[0]
        price = item.price
        if price.nickname:
            plan_name = price.nickname
        elif price.product:
            plan_name = price.product if isinstance(price.product, str) else None

    # Stripe v15 removed current_period_end; use trial_end as a fallback
    period_end: datetime | None = None
    trial_end = getattr(sub, "trial_end", None)
    if trial_end is not None:
        period_end = datetime.fromtimestamp(int(trial_end), tz=UTC)

    return BillingStatus(
        subscribed=is_active,
        plan=plan_name,
        status=sub.status,
        current_period_end=period_end,
    )


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, db: DB) -> dict[str, str]:
    """Handle Stripe webhook events.

    Signature verification is performed using the raw request body and the
    ``Stripe-Signature`` header.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not settings.stripe_webhook_secret:
        logger.warning("stripe_webhook_secret_not_configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook secret not configured.",
        )

    try:
        event = stripe.Webhook.construct_event(  # type: ignore[no-untyped-call]
            payload, sig_header, settings.stripe_webhook_secret
        )
    except stripe.SignatureVerificationError as exc:
        logger.warning("stripe_webhook_invalid_signature", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe signature.",
        ) from exc
    except ValueError as exc:
        logger.warning("stripe_webhook_invalid_payload", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payload.",
        ) from exc

    event_type: str = event["type"]
    # ``event.data.object`` is a Stripe ``StripeObject``, not a plain dict, and in
    # stripe>=15 it has no ``.get`` — the downstream handlers index it with
    # ``.get(...)``, so flatten it before dispatching. ``to_dict`` returns a plain
    # dict whose nested ``metadata`` (the only nested field handlers read) is also
    # dict-typed, so ``metadata.get(...)`` keeps working.
    event_data: dict[str, Any] = event["data"]["object"].to_dict()

    logger.info("stripe_webhook_received", event_type=event_type)

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(event_data, db)
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(event_data, db)

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Webhook handlers
# ---------------------------------------------------------------------------


async def _handle_checkout_completed(session: dict[str, Any], db: DB) -> None:
    """Mark workspace as subscribed after a successful checkout.

    In-call payments (the ``collect_payment`` voice tool) reuse the same Stripe
    webhook but run in ``payment`` mode and carry a ``call_payment_id`` in
    metadata. Route those to the call-payment handler instead of the SaaS
    subscription path so they mark a :class:`CallPayment` paid + notify operators.
    """
    metadata = session.get("metadata") or {}
    # Customer-invoice payments also run in ``payment`` mode, so route them by
    # their ``invoice_id`` metadata *before* the in-call-payment check below.
    if metadata.get("invoice_id"):
        from app.services.invoices.invoice_service import (
            handle_invoice_checkout_session_completed,
        )

        await handle_invoice_checkout_session_completed(session, db)
        return
    if session.get("mode") == "payment" or metadata.get("call_payment_id"):
        from app.services.payments import call_payment_service

        await call_payment_service.handle_checkout_session_completed(session, db)
        return

    workspace_id_str: str | None = metadata.get("workspace_id")
    customer_id: str | None = session.get("customer")

    if not workspace_id_str or not customer_id:
        logger.warning(
            "checkout_completed_missing_metadata",
            workspace_id=workspace_id_str,
            customer_id=customer_id,
        )
        return

    try:
        workspace_id = uuid.UUID(workspace_id_str)
    except ValueError:
        logger.warning(
            "checkout_completed_invalid_workspace_id",
            value=workspace_id_str,
        )
        return

    await _upsert_stripe_integration(
        workspace_id,
        db,
        {"customer_id": customer_id, "subscribed": True},
    )

    logger.info(
        "workspace_subscribed",
        workspace_id=workspace_id_str,
        customer_id=customer_id,
    )


async def _handle_subscription_deleted(subscription: dict[str, Any], db: DB) -> None:
    """Mark workspace as unsubscribed when a subscription is cancelled."""
    customer_id: str | None = subscription.get("customer")
    if not customer_id:
        return

    # Find the workspace integration by scanning for the matching customer_id.
    result = await db.execute(
        select(WorkspaceIntegration).where(
            WorkspaceIntegration.integration_type == _STRIPE_INTEGRATION_TYPE,
        )
    )
    integrations = result.scalars().all()

    for integration in integrations:
        try:
            creds = decrypt_json(integration.encrypted_credentials)
        except Exception:
            continue
        if creds.get("customer_id") == customer_id:
            creds["subscribed"] = False
            integration.encrypted_credentials = encrypt_json(creds)
            await db.commit()
            logger.info(
                "workspace_unsubscribed",
                workspace_id=str(integration.workspace_id),
                customer_id=customer_id,
            )
            return

    logger.warning(
        "subscription_deleted_no_matching_workspace",
        customer_id=customer_id,
    )
