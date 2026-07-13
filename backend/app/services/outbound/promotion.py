"""Promote enriched lead prospects into CRM contacts.

Closes the missing "prospect -> Contact" path. For a qualified/enriched
:class:`LeadProspect` it:

* Checks suppression/opt-out (phone on the global opt-out list) before creating
  anything.
* Creates (or reuses, by ``phone_hash``) a :class:`Contact`, copying the ad
  evidence — including the **specific ad to reference** — into
  ``business_intel`` so outreach is concrete.
* Applies tags (``ad-library``, ``stale-creative``, ``long-runner``,
  ``no-testing``) so these contacts are filterable.
* Links ``lead_prospects.contact_id`` + stamps ``promoted_at``.
* Optionally opens an :class:`Opportunity` in the workspace's default pipeline.

The CRM ``Contact`` model requires a phone number, so a prospect with no phone
after enrichment is skipped with a clear reason rather than forced.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_phone
from app.models.contact import Contact
from app.models.lead_prospect import LeadProspect, ProspectStatus
from app.models.opportunity import Opportunity
from app.services.opportunities import get_default_pipeline_first_stage
from app.services.rate_limiting.opt_out_manager import OptOutManager
from app.services.tags.tag_service import TagService

logger = structlog.get_logger()

_DEFAULT_TAGS = ("ad-library",)


@dataclass(slots=True)
class PromotionResult:
    """Outcome of promoting one prospect."""

    prospect_id: uuid.UUID
    promoted: bool
    contact_id: int | None = None
    opportunity_id: uuid.UUID | None = None
    skipped_reason: str | None = None


class ProspectPromotionService:
    """Promote enriched prospects into CRM contacts (+ optional opportunity)."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._opt_out = OptOutManager()
        self._tags = TagService(db)
        self._logger = logger.bind(component="prospect_promotion")

    async def promote(
        self,
        prospect: LeadProspect,
        *,
        create_opportunity: bool = False,
        extra_tags: list[str] | None = None,
    ) -> PromotionResult:
        """Promote one prospect into a Contact. Flushes; does not commit."""
        log = self._logger.bind(prospect_id=str(prospect.id))

        if prospect.contact_id is not None:
            return PromotionResult(
                prospect_id=prospect.id,
                promoted=False,
                contact_id=prospect.contact_id,
                skipped_reason="already_promoted",
            )

        if prospect.status == ProspectStatus.SUPPRESSED:
            return PromotionResult(
                prospect_id=prospect.id, promoted=False, skipped_reason="suppressed"
            )

        phone = prospect.phone_number
        if not phone:
            return PromotionResult(
                prospect_id=prospect.id, promoted=False, skipped_reason="no_phone"
            )

        # Suppression / opt-out gate.
        if await self._opt_out.check_opt_out(prospect.workspace_id, phone, self._db):
            prospect.status = ProspectStatus.SUPPRESSED
            prospect.suppression_reason = "global_opt_out"
            log.info("promotion_suppressed_opt_out")
            return PromotionResult(
                prospect_id=prospect.id, promoted=False, skipped_reason="opt_out"
            )

        contact = await self._find_or_create_contact(prospect, phone)
        await self._db.flush()

        tags = list(_DEFAULT_TAGS) + _signal_tags(prospect) + list(extra_tags or [])
        await self._tags.add_tags_to_contact(
            workspace_id=prospect.workspace_id,
            contact_id=contact.id,
            names=tags,
        )

        opportunity_id: uuid.UUID | None = None
        if create_opportunity:
            opportunity = await self._open_opportunity(prospect, contact)
            opportunity_id = opportunity.id if opportunity else None

        # Link + stamp the prospect.
        prospect.contact_id = contact.id
        prospect.promoted_at = datetime.now(UTC)
        prospect.status = ProspectStatus.CONVERTED
        await self._db.flush()

        log.info(
            "prospect_promoted",
            contact_id=contact.id,
            opportunity_id=str(opportunity_id) if opportunity_id else None,
        )
        return PromotionResult(
            prospect_id=prospect.id,
            promoted=True,
            contact_id=contact.id,
            opportunity_id=opportunity_id,
        )

    async def _find_or_create_contact(self, prospect: LeadProspect, phone: str) -> Contact:
        """Reuse an existing contact by phone_hash, else create one."""
        phone_hash = hash_phone(phone)
        existing = await self._db.execute(
            select(Contact).where(
                Contact.workspace_id == prospect.workspace_id,
                Contact.phone_hash == phone_hash,
            )
        )
        contact = existing.scalar_one_or_none()
        business_intel = _build_business_intel(prospect)

        if contact is not None:
            # Merge ad intel onto the existing contact without clobbering.
            merged = dict(contact.business_intel or {})
            merged.setdefault("ad_library", business_intel["ad_library"])
            contact.business_intel = merged
            if prospect.lead_score > (contact.lead_score or 0):
                contact.lead_score = prospect.lead_score
            # Contact.website_url is String(500); the prospect column is wider.
            contact.website_url = contact.website_url or (
                prospect.website_url[:500] if prospect.website_url else None
            )
            contact.linkedin_url = contact.linkedin_url or prospect.linkedin_url
            return contact

        contact = Contact(
            workspace_id=prospect.workspace_id,
            first_name=_first_name(prospect),
            last_name=prospect.last_name,
            email=prospect.email,
            phone_number=phone,
            company_name=prospect.company_name,
            website_url=prospect.website_url[:500] if prospect.website_url else None,
            linkedin_url=prospect.linkedin_url,
            status="new",
            source="ad_library",
            lead_score=prospect.lead_score,
            enrichment_status="enriched" if prospect.last_enriched_at else "pending",
            enriched_at=prospect.last_enriched_at,
            business_intel=business_intel,
        )
        self._db.add(contact)
        return contact

    async def _open_opportunity(
        self, prospect: LeadProspect, contact: Contact
    ) -> Opportunity | None:
        """Open an opportunity in the workspace's default pipeline / first stage."""
        pipeline, stage = await get_default_pipeline_first_stage(self._db, prospect.workspace_id)

        company = prospect.company_name or contact.company_name or "Ad-library lead"
        opportunity = Opportunity(
            workspace_id=prospect.workspace_id,
            pipeline_id=pipeline.id,
            stage_id=stage.id if stage else None,
            primary_contact_id=contact.id,
            name=f"Ad creative testing — {company}"[:255],
            description=_opportunity_description(prospect)[:2000],
            probability=stage.probability if stage else 0,
            source="ad_library",
            status="open",
        )
        self._db.add(opportunity)
        await self._db.flush()
        return opportunity


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _first_name(prospect: LeadProspect) -> str:
    """Resolve a non-null first name (Contact requires one)."""
    if prospect.first_name:
        return prospect.first_name[:100]
    if prospect.full_name:
        return prospect.full_name.split()[0][:100]
    if prospect.company_name:
        return prospect.company_name[:100]
    return "Lead"


def _ad_signal(prospect: LeadProspect) -> dict[str, Any]:
    """Return the ad-signal evidence blob from a prospect, if present."""
    for item in prospect.evidence or []:
        if isinstance(item, dict) and item.get("type") == "ad_signal":
            return item
    return {}


def _build_business_intel(prospect: LeadProspect) -> dict[str, Any]:
    """Carry the ad signal + the specific ad to reference into business_intel."""
    signal = _ad_signal(prospect)
    return {
        "ad_library": {
            "platform": signal.get("platform"),
            "opportunity_score": signal.get("opportunity_score"),
            "longest_running_active_days": signal.get("longest_running_active_days"),
            "distinct_creative_count": signal.get("distinct_creative_count"),
            "creative_refresh_rate": signal.get("creative_refresh_rate"),
            "continuity_score": signal.get("continuity_score"),
            "reasons": signal.get("reasons", []),
            # The exact ad outreach can reference.
            "example_creative": signal.get("example_creative"),
            "page_url": signal.get("page_url"),
        }
    }


def _signal_tags(prospect: LeadProspect) -> list[str]:
    """Derive descriptive tags from the ad signal."""
    signal = _ad_signal(prospect)
    if not signal:
        return []
    tags: list[str] = []
    if (signal.get("longest_running_active_days") or 0) >= 90:
        tags.append("long-runner")
    if (signal.get("distinct_creative_count") or 99) <= 3:
        tags.append("stale-creative")
    if (signal.get("creative_refresh_rate") or 99) < 1.0:
        tags.append("no-testing")
    return tags


def _opportunity_description(prospect: LeadProspect) -> str:
    """Human-readable opportunity description naming the specific ad."""
    signal = _ad_signal(prospect)
    reasons = signal.get("reasons") or []
    example = signal.get("example_creative") or {}
    parts: list[str] = []
    if reasons:
        parts.append(" ".join(reasons))
    running = example.get("running_days")
    snippet = example.get("body_snippet")
    if running and snippet:
        parts.append(f'Reference ad ({running}d running): "{snippet}"')
    elif running:
        parts.append(f"Reference ad running {running} days.")
    return " ".join(parts) or "Ad-library prospect: consistent spender, low creative iteration."
