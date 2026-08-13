"""Public one-click email unsubscribe endpoints (no auth).

Two scopes, because the product sends two kinds of commercial mail:

* ``/unsubscribe`` silences **one campaign enrollment**, and
* ``/unsubscribe-contact`` silences **every commercial email** to a contact,
  which is what a workflow-sent email links to — those have no campaign
  enrollment behind them, so the narrower opt-out cannot express "stop".

Both verify an HMAC-signed token before honouring anything, so links cannot be
forged or enumerated, and both are idempotent: repeat clicks show the same
confirmation. Both always return 200 with an HTML page — a mail client
prefetching the link must never show the recipient an error.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.api.deps import DB
from app.models.campaign import (
    Campaign,
    CampaignContact,
    CampaignContactStatus,
)
from app.services.campaigns.email_unsubscribe import verify_unsubscribe_token
from app.services.email_opt_out import record_email_opt_out, verify_email_unsubscribe_token

logger = structlog.get_logger()

public_router = APIRouter()


def _page(message: str, *, ok: bool) -> HTMLResponse:
    color = "#16a34a" if ok else "#dc2626"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Unsubscribe</title>
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
             background:#0a0a0a;color:#e5e5e5;display:flex;align-items:center;
             justify-content:center;min-height:100vh;margin:0;">
    <div style="max-width:420px;text-align:center;padding:40px;">
        <div style="font-size:44px;margin-bottom:16px;color:{color};">{"✓" if ok else "⚠"}</div>
        <p style="font-size:18px;line-height:1.5;">{message}</p>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200)


@public_router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(db: DB, token: str = Query(...)) -> HTMLResponse:
    """Honor an email unsubscribe link. Always returns 200 with an HTML page."""
    campaign_contact_id = verify_unsubscribe_token(token)
    if campaign_contact_id is None:
        return _page("This unsubscribe link is invalid or has expired.", ok=False)

    result = await db.execute(
        select(CampaignContact).where(CampaignContact.id == campaign_contact_id)
    )
    campaign_contact = result.scalar_one_or_none()
    if campaign_contact is None:
        return _page("You have been unsubscribed.", ok=True)

    if not campaign_contact.opted_out:
        campaign_contact.opted_out = True
        campaign_contact.opted_out_at = datetime.now(UTC)
        campaign_contact.status = CampaignContactStatus.OPTED_OUT

        campaign = await db.get(Campaign, campaign_contact.campaign_id)
        if campaign is not None:
            campaign.contacts_opted_out += 1
            campaign.emails_unsubscribed += 1

        await db.commit()
        logger.info("campaign_email_unsubscribed", campaign_contact_id=str(campaign_contact_id))

    return _page("You've been unsubscribed and won't receive these emails again.", ok=True)


@public_router.get("/unsubscribe-contact", response_class=HTMLResponse)
async def unsubscribe_contact(db: DB, token: str = Query(...)) -> HTMLResponse:
    """Honor a contact-level email opt-out link (workflow/automation email).

    Suppresses commercial email to this person across every automation and
    workflow, not just the one that prompted the click. Always returns 200.
    """
    contact_id = verify_email_unsubscribe_token(token)
    if contact_id is None:
        return _page("This unsubscribe link is invalid or has expired.", ok=False)

    # A deleted contact receives nothing anyway, so the honest answer to the
    # person clicking is still "you're unsubscribed".
    await record_email_opt_out(db, contact_id, source="unsubscribe_link")
    await db.commit()

    return _page("You've been unsubscribed and won't receive these emails again.", ok=True)
