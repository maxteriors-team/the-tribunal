"""Public short-link redirect endpoints."""

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.campaign import Campaign
from app.models.link_click import LinkClick
from app.models.short_link import ShortLink

logger = structlog.get_logger()

router = APIRouter(tags=["redirects"])


@router.get("/r/{short_code}")
async def redirect_short_link(
    short_code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Resolve a short code, log the click, and 302 to the target URL."""
    result = await db.execute(select(ShortLink).where(ShortLink.short_code == short_code))
    short_link = result.scalar_one_or_none()
    if short_link is None:
        raise HTTPException(status_code=404, detail="Short link not found")

    now = datetime.now(UTC)
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    referer = request.headers.get("referer")

    click = LinkClick(
        short_link_id=short_link.id,
        clicked_at=now,
        ip_address=ip_address,
        user_agent=user_agent,
        referer=referer,
    )
    db.add(click)

    await db.execute(
        update(ShortLink)
        .where(ShortLink.id == short_link.id)
        .values(
            click_count=ShortLink.click_count + 1,
            last_clicked_at=now,
        )
    )

    if short_link.campaign_id is not None:
        await db.execute(
            update(Campaign)
            .where(Campaign.id == short_link.campaign_id)
            .values(links_clicked=Campaign.links_clicked + 1)
        )

    await db.commit()

    logger.info(
        "short_link_clicked",
        short_code=short_code,
        target_url=short_link.target_url,
        ip=ip_address,
    )

    return RedirectResponse(url=short_link.target_url, status_code=302)
