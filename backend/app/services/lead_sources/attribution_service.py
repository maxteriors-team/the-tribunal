"""Lead-source attribution cleanup: suggest and assign sources for leads.

Powers the "unknown attribution" queue. A contact is considered unattributed
when it has no ``first_touch_lead_source_id``. Assigning a source backfills the
contact's touch fields and any of its still-unattributed opportunities so the
correction flows through to closed-won ROI.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.lead_source import LeadSource, LeadSourceType
from app.models.opportunity import Opportunity

# Confidence assigned when an operator manually picks the source by hand.
MANUAL_ASSIGNMENT_CONFIDENCE = 1.0


@dataclass(frozen=True)
class _AttributionSignals:
    """The subset of contact fields used to guess a likely channel."""

    gclid: str | None = None
    fbclid: str | None = None
    utm_source: str | None = None
    source: str | None = None


def _suggest_from_utm(utm: str) -> LeadSourceType | None:
    """Map a normalized ``utm_source`` value to a channel, if recognizable."""
    if any(token in utm for token in ("facebook", "instagram", "meta", "fb", "ig")):
        return LeadSourceType.FACEBOOK_ADS
    if any(token in utm for token in ("google", "adwords", "gads")):
        return LeadSourceType.GOOGLE_ADS
    if utm in ("organic", "seo", "direct", "referral"):
        return LeadSourceType.ORGANIC
    return None


def suggest_source_type(signals: _AttributionSignals) -> LeadSourceType | None:
    """Guess a likely channel from tracking signals on a contact.

    Pure function so the heuristic is unit-testable. Click ids are the
    strongest signal, then ``utm_source``, then the legacy ``source`` string.
    Returns ``None`` when nothing is conclusive.
    """
    if signals.gclid:
        return LeadSourceType.GOOGLE_ADS
    if signals.fbclid:
        return LeadSourceType.FACEBOOK_ADS

    utm = (signals.utm_source or "").strip().lower()
    if utm and (from_utm := _suggest_from_utm(utm)) is not None:
        return from_utm

    source = (signals.source or "").strip().lower()
    if source in ("inbound_call", "phone", "call", "radio"):
        return LeadSourceType.PHONE_RADIO

    return None


def suggest_source_type_for_contact(contact: Contact) -> LeadSourceType | None:
    """Convenience wrapper that reads the signals off a contact row."""
    return suggest_source_type(
        _AttributionSignals(
            gclid=contact.gclid,
            fbclid=contact.fbclid,
            utm_source=contact.utm_source,
            source=contact.source,
        )
    )


class AttributionCleanupError(Exception):
    """Raised when a lead source/contact cannot be resolved for assignment."""


class AttributionCleanupService:
    """Read the unattributed-lead queue and assign sources by hand."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def default_source_by_type(
        self, workspace_id: uuid.UUID
    ) -> dict[LeadSourceType, uuid.UUID]:
        """Map each channel to one enabled lead source to seed suggestions."""
        result = await self.db.execute(
            select(LeadSource.source_type, LeadSource.id)
            .where(LeadSource.workspace_id == workspace_id, LeadSource.enabled.is_(True))
            .order_by(LeadSource.created_at.asc())
        )
        by_type: dict[LeadSourceType, uuid.UUID] = {}
        for source_type, source_id in result.all():
            by_type.setdefault(source_type, source_id)
        return by_type

    async def list_unattributed(self, workspace_id: uuid.UUID, limit: int = 100) -> list[Contact]:
        """Return contacts with no known first-touch lead source."""
        result = await self.db.execute(
            select(Contact)
            .where(
                Contact.workspace_id == workspace_id,
                Contact.first_touch_lead_source_id.is_(None),
            )
            .order_by(Contact.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def assign(
        self,
        *,
        workspace_id: uuid.UUID,
        contact_id: int,
        lead_source_id: uuid.UUID,
        lead_source_campaign_id: uuid.UUID | None = None,
        source_type: LeadSourceType | None = None,
    ) -> Contact:
        """Assign a lead source to a contact and backfill its open jobs.

        Sets the contact's latest touch (and first touch when unset) to the
        chosen source at full confidence, then attributes any of the contact's
        opportunities that are still missing a source so ROI reflects the fix.
        """
        lead_source = await self.db.get(LeadSource, lead_source_id)
        if lead_source is None or lead_source.workspace_id != workspace_id:
            raise AttributionCleanupError("Lead source not found")

        contact = await self.db.get(Contact, contact_id)
        if contact is None or contact.workspace_id != workspace_id:
            raise AttributionCleanupError("Contact not found")

        now = datetime.now(UTC)

        contact.latest_touch_lead_source_id = lead_source_id
        contact.latest_touch_lead_source_campaign_id = lead_source_campaign_id
        contact.latest_touch_at = now
        if contact.first_touch_lead_source_id is None:
            contact.first_touch_lead_source_id = lead_source_id
            contact.first_touch_lead_source_campaign_id = lead_source_campaign_id
            contact.first_touch_at = now
        contact.attribution_confidence = MANUAL_ASSIGNMENT_CONFIDENCE

        # Persist the chosen channel on the source itself when the operator
        # corrected it (e.g. confirming a guessed phone/radio lead).
        if source_type is not None and lead_source.source_type != source_type:
            lead_source.source_type = source_type

        await self._backfill_opportunities(
            workspace_id=workspace_id,
            contact_id=contact_id,
            lead_source_id=lead_source_id,
            lead_source_campaign_id=lead_source_campaign_id,
        )

        await self.db.commit()
        await self.db.refresh(contact)
        return contact

    async def _backfill_opportunities(
        self,
        *,
        workspace_id: uuid.UUID,
        contact_id: int,
        lead_source_id: uuid.UUID,
        lead_source_campaign_id: uuid.UUID | None,
    ) -> None:
        """Attribute the contact's still-unattributed opportunities.

        Only rows where ``lead_source_id IS NULL`` are touched so historical
        attribution snapshots are never rewritten.
        """
        result = await self.db.execute(
            select(Opportunity).where(
                Opportunity.workspace_id == workspace_id,
                Opportunity.primary_contact_id == contact_id,
                Opportunity.lead_source_id.is_(None),
            )
        )
        for opportunity in result.scalars().all():
            opportunity.lead_source_id = lead_source_id
            opportunity.lead_source_campaign_id = lead_source_campaign_id
            opportunity.attribution_confidence = MANUAL_ASSIGNMENT_CONFIDENCE
