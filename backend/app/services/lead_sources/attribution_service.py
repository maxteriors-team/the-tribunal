"""Lead-source attribution cleanup: suggest and assign sources for leads.

Powers the "unknown attribution" queue. A contact is considered unattributed
when it has no ``first_touch_lead_source_id``. Assigning a source backfills the
contact's touch fields and any of its still-unattributed opportunities so the
correction flows through to canonical booked ROI.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.contact import Contact
from app.models.lead_source import LeadSource, LeadSourceCampaign, LeadSourceType
from app.models.opportunity import Opportunity
from app.models.phone_number import PhoneNumber

# Confidence assigned when an operator manually picks the source by hand.
MANUAL_ASSIGNMENT_CONFIDENCE = 1.0

# Confidence for a call received on a number explicitly mapped by an operator.
# This direct evidence must outrank heuristic UTM inference.
TRACKING_NUMBER_ATTRIBUTION_CONFIDENCE = 1.0

# Confidence for a lead captured through a known lead-source form. The owning
# source is certain; only the upstream channel detail can be fuzzy.
WEB_FORM_ATTRIBUTION_CONFIDENCE = 0.9

# Spoken answers are only promoted into structured ROI when the deterministic
# mapper finds exactly one recognizable channel. Ambiguous answers stay raw.
AI_ATTRIBUTION_MIN_CONFIDENCE = 0.8

# Tracking-metadata columns copied verbatim from a submission onto the contact.
_TRACKING_FIELDS = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "gclid",
    "fbclid",
    "landing_page",
    "referrer",
)


@dataclass(frozen=True)
class _AttributionSignals:
    """The subset of contact fields used to guess a likely channel."""

    gclid: str | None = None
    fbclid: str | None = None
    utm_source: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class ResolvedWebAttribution:
    """Validated source/campaign chosen from server-observed tracking signals."""

    lead_source: LeadSource
    campaign_id: uuid.UUID | None


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


async def resolve_web_attribution(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    capture_source: LeadSource,
    requested_campaign_id: uuid.UUID | None,
    utm_source: str | None,
    utm_campaign: str | None,
    fbclid: str | None,
    gclid: str | None,
) -> ResolvedWebAttribution:
    """Resolve browser tracking into a workspace-owned source and campaign.

    The form's owning source remains the fallback. A click id or recognizable
    ``utm_source`` can switch a generic website form to the one unambiguous paid
    channel, while ``utm_campaign`` maps to a configured campaign server-side.
    Client-supplied UUIDs never cross workspace/source boundaries.
    """
    inferred_type = suggest_source_type(
        _AttributionSignals(
            gclid=gclid,
            fbclid=fbclid,
            utm_source=utm_source,
            source="website",
        )
    )

    resolved_source = capture_source
    if inferred_type is not None and capture_source.source_type != inferred_type:
        candidates = (
            (
                await db.execute(
                    select(LeadSource)
                    .where(
                        LeadSource.workspace_id == workspace_id,
                        LeadSource.source_type == inferred_type,
                        LeadSource.enabled.is_(True),
                    )
                    .order_by(LeadSource.created_at.asc())
                    .limit(2)
                )
            )
            .scalars()
            .all()
        )
        if len(candidates) == 1:
            resolved_source = candidates[0]

    if requested_campaign_id is not None:
        requested = (
            await db.execute(
                select(LeadSourceCampaign, LeadSource)
                .join(LeadSource, LeadSource.id == LeadSourceCampaign.lead_source_id)
                .where(
                    LeadSourceCampaign.id == requested_campaign_id,
                    LeadSourceCampaign.workspace_id == workspace_id,
                    LeadSourceCampaign.lead_source_id == resolved_source.id,
                    LeadSource.id == resolved_source.id,
                    LeadSource.workspace_id == workspace_id,
                    LeadSourceCampaign.enabled.is_(True),
                    LeadSource.enabled.is_(True),
                )
            )
        ).one_or_none()
        if requested is not None:
            campaign, source = requested
            return ResolvedWebAttribution(source, campaign.id)

    normalized_campaign = (utm_campaign or "").strip().lower()
    if normalized_campaign:
        match_query = (
            select(LeadSourceCampaign, LeadSource)
            .join(LeadSource, LeadSource.id == LeadSourceCampaign.lead_source_id)
            .where(
                LeadSourceCampaign.workspace_id == workspace_id,
                LeadSourceCampaign.lead_source_id == resolved_source.id,
                LeadSource.id == resolved_source.id,
                LeadSource.workspace_id == workspace_id,
                LeadSourceCampaign.enabled.is_(True),
                LeadSource.enabled.is_(True),
                or_(
                    func.lower(LeadSourceCampaign.name) == normalized_campaign,
                    func.lower(LeadSourceCampaign.utm_campaign) == normalized_campaign,
                    LeadSourceCampaign.platform_campaign_id == (utm_campaign or "").strip(),
                ),
            )
        )
        matches = (await db.execute(match_query.limit(2))).all()
        if len(matches) == 1:
            campaign, source = matches[0]
            return ResolvedWebAttribution(source, campaign.id)

    return ResolvedWebAttribution(resolved_source, None)


@dataclass(frozen=True)
class AILeadSourceMatch:
    """One conservative channel match from a caller's verbatim answer."""

    source_type: LeadSourceType
    confidence: float


def _normalize_spoken_source(value: str) -> str:
    """Normalize speech text for deterministic phrase matching."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def map_ai_lead_source_answer(answer: str) -> AILeadSourceMatch | None:
    """Map an unambiguous spoken answer to one acquisition channel.

    This intentionally uses a small allowlist rather than an LLM guess. If an
    answer names multiple channels or uses vague wording, ``None`` preserves the
    raw answer without silently corrupting ROI.
    """
    normalized = _normalize_spoken_source(answer)
    if not normalized:
        return None
    words = set(normalized.split())
    matches: set[LeadSourceType] = set()

    if words.intersection({"facebook", "instagram"}) or "meta ad" in normalized:
        matches.add(LeadSourceType.FACEBOOK_ADS)
    if "google" in words:
        # A bare "Google" is a deliberate supported answer. Workspaces that
        # split multiple Google sources still require an exact source-name match.
        matches.add(LeadSourceType.GOOGLE_ADS)
    if (
        "online search" in normalized
        or "web search" in normalized
        or "search engine" in normalized
        or words.intersection({"website", "internet", "seo"})
    ):
        matches.add(LeadSourceType.ORGANIC)
    if words.intersection({"radio", "podcast"}):
        matches.add(LeadSourceType.PHONE_RADIO)
    if (
        words.intersection({"friend", "family", "referral", "referred", "recommended"})
        or "word of mouth" in normalized
        or "my neighbor" in normalized
        or "neighbor told" in normalized
        or "neighbor recommended" in normalized
    ):
        matches.add(LeadSourceType.REFERRAL_PARTNER)
    if (
        "repeat customer" in normalized
        or "past customer" in normalized
        or "existing customer" in normalized
        or "used you before" in normalized
        or "hired you before" in normalized
    ):
        matches.add(LeadSourceType.REPEAT_CUSTOMER)
    if words.intersection({"truck", "van"}) or "vehicle wrap" in normalized:
        matches.add(LeadSourceType.TRUCK_WRAP)
    if "yard sign" in normalized or "lawn sign" in normalized:
        matches.add(LeadSourceType.YARD_SIGN)
    if (
        "knocked on my door" in normalized
        or "door hanger" in normalized
        or "working next door" in normalized
        or "job next door" in normalized
        or "neighbor s house" in normalized
    ):
        matches.add(LeadSourceType.CANVASS_NEIGHBOR)

    if len(matches) != 1:
        return None

    source_type = next(iter(matches))
    confidence = 0.85 if normalized == "google" else 0.95
    if confidence < AI_ATTRIBUTION_MIN_CONFIDENCE:  # pragma: no cover - defensive constant guard
        return None
    return AILeadSourceMatch(source_type=source_type, confidence=confidence)


async def apply_ai_receptionist_attribution(
    db: AsyncSession,
    contact: Contact,
    raw_answer: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Store a caller answer and structure it only when source resolution is safe."""
    answer = raw_answer.strip()[:500]
    if not answer:
        return False
    contact.lead_source_raw_answer = answer

    # AI must never replace a source established by an operator, tracking
    # number, public form, or earlier high-confidence capture.
    if contact.first_touch_lead_source_id is not None:
        return False

    match = map_ai_lead_source_answer(answer)
    if match is None:
        return False

    result = await db.execute(
        select(LeadSource)
        .where(
            LeadSource.workspace_id == contact.workspace_id,
            LeadSource.source_type == match.source_type,
            LeadSource.enabled.is_(True),
        )
        .order_by(LeadSource.created_at.asc())
    )
    candidates = list(result.scalars().all())
    if not candidates:
        return False

    chosen: LeadSource | None = candidates[0] if len(candidates) == 1 else None
    if len(candidates) > 1:
        normalized_answer = _normalize_spoken_source(answer)
        named_matches = [
            source
            for source in candidates
            if (name := _normalize_spoken_source(source.name))
            and (normalized_answer == name or name in normalized_answer)
        ]
        if len(named_matches) == 1:
            chosen = named_matches[0]

    # A channel with several configured sources is not specific enough unless
    # the caller named exactly one; choosing the oldest row would fabricate ROI.
    if chosen is None:
        return False

    _apply_contact_touch(
        contact,
        lead_source_id=chosen.id,
        lead_source_campaign_id=None,
        confidence=match.confidence,
        now=now,
    )

    if contact.id is not None:
        opportunities = await db.execute(
            select(Opportunity).where(
                Opportunity.workspace_id == contact.workspace_id,
                Opportunity.primary_contact_id == contact.id,
                Opportunity.lead_source_id.is_(None),
            )
        )
        for opportunity in opportunities.scalars().all():
            apply_opportunity_attribution_snapshot(
                opportunity,
                lead_source_id=chosen.id,
                lead_source_campaign_id=None,
                confidence=match.confidence,
            )

    return True


@dataclass(frozen=True)
class WebAttributionInput:
    """Tracking signals captured from a public lead-form submission."""

    lead_source_campaign_id: uuid.UUID | None = None
    attribution_confidence: float | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None
    gclid: str | None = None
    fbclid: str | None = None
    landing_page: str | None = None
    referrer: str | None = None


def _apply_contact_touch(
    contact: Contact,
    *,
    lead_source_id: uuid.UUID,
    lead_source_campaign_id: uuid.UUID | None,
    confidence: float,
    now: datetime | None = None,
) -> None:
    """Preserve first touch while refreshing the contact's latest touch."""
    stamp = now or datetime.now(UTC)

    if contact.first_touch_lead_source_id is None:
        contact.first_touch_lead_source_id = lead_source_id
        contact.first_touch_lead_source_campaign_id = lead_source_campaign_id
        contact.first_touch_at = stamp

    contact.latest_touch_lead_source_id = lead_source_id
    contact.latest_touch_lead_source_campaign_id = lead_source_campaign_id
    contact.latest_touch_at = stamp
    contact.attribution_confidence = confidence


def apply_opportunity_attribution_snapshot(
    opportunity: Opportunity,
    *,
    lead_source_id: uuid.UUID | None,
    lead_source_campaign_id: uuid.UUID | None,
    confidence: float | None,
    referral_partner_id: uuid.UUID | None = None,
) -> bool:
    """Set an opportunity's immutable attribution snapshot when still empty.

    ``referral_partner_id`` rides along in the same snapshot as the lead source
    so per-partner booked revenue uses the same immutable snapshot as
    lead-source ROI. A snapshot that already names a source *or* a partner is
    treated as written and is never rewritten.
    """
    if opportunity.lead_source_id is not None or opportunity.referral_partner_id is not None:
        return False
    if lead_source_id is None and referral_partner_id is None:
        return False

    opportunity.lead_source_id = lead_source_id
    opportunity.lead_source_campaign_id = lead_source_campaign_id
    opportunity.attribution_confidence = confidence
    opportunity.referral_partner_id = referral_partner_id
    return True


def snapshot_contact_attribution_on_opportunity(opportunity: Opportunity, contact: Contact) -> bool:
    """Copy the contact's latest known touch onto a newly created opportunity.

    A referred lead whose partner is known but whose channel was never wired to a
    configured lead source still gets credited, so the partner scoreboard does not
    silently drop referrals from workspaces that skipped lead-source setup.
    """
    lead_source_id: uuid.UUID | None
    campaign_id: uuid.UUID | None
    if contact.latest_touch_lead_source_id is not None:
        lead_source_id = contact.latest_touch_lead_source_id
        campaign_id = contact.latest_touch_lead_source_campaign_id
    else:
        lead_source_id = contact.first_touch_lead_source_id
        campaign_id = contact.first_touch_lead_source_campaign_id

    referral_partner_id = contact.referral_partner_id
    if lead_source_id is None and referral_partner_id is None:
        return False

    return apply_opportunity_attribution_snapshot(
        opportunity,
        lead_source_id=lead_source_id,
        lead_source_campaign_id=campaign_id,
        confidence=contact.attribution_confidence,
        referral_partner_id=referral_partner_id,
    )


async def apply_tracking_number_attribution(
    db: AsyncSession,
    contact: Contact,
    phone_number: PhoneNumber,
    *,
    now: datetime | None = None,
) -> bool:
    """Attribute a mapped inbound number without rewriting historical snapshots.

    Tracking-number evidence always becomes the contact's latest touch and only
    becomes first touch when no prior touch exists. Opportunities are updated only
    while unattributed, preserving the immutable source on already-attributed jobs.
    """
    if phone_number.lead_source_id is None:
        return False

    _apply_contact_touch(
        contact,
        lead_source_id=phone_number.lead_source_id,
        lead_source_campaign_id=phone_number.lead_source_campaign_id,
        confidence=TRACKING_NUMBER_ATTRIBUTION_CONFIDENCE,
        now=now,
    )

    if contact.id is None:
        return True

    result = await db.execute(
        select(Opportunity).where(
            Opportunity.workspace_id == contact.workspace_id,
            Opportunity.primary_contact_id == contact.id,
            Opportunity.lead_source_id.is_(None),
        )
    )
    for opportunity in result.scalars().all():
        apply_opportunity_attribution_snapshot(
            opportunity,
            lead_source_id=phone_number.lead_source_id,
            lead_source_campaign_id=phone_number.lead_source_campaign_id,
            confidence=TRACKING_NUMBER_ATTRIBUTION_CONFIDENCE,
        )

    return True


def apply_web_attribution(
    contact: Contact,
    lead_source: LeadSource,
    data: WebAttributionInput,
    *,
    now: datetime | None = None,
) -> None:
    """Stamp first/latest-touch attribution and tracking metadata onto a contact.

    The submission arrived through a known lead-source form, so the owning
    source is reliable. First-touch is set only when missing — preserving the
    true first touch for a returning contact — while latest-touch is always
    refreshed. Tracking fields are overwritten only when the submission carries
    a value, so a later blank submission never erases earlier signal.
    """
    confidence = (
        data.attribution_confidence
        if data.attribution_confidence is not None
        else WEB_FORM_ATTRIBUTION_CONFIDENCE
    )
    _apply_contact_touch(
        contact,
        lead_source_id=lead_source.id,
        lead_source_campaign_id=data.lead_source_campaign_id,
        confidence=confidence,
        now=now,
    )

    for field in _TRACKING_FIELDS:
        value = getattr(data, field)
        if value:
            setattr(contact, field, value)


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
        correct_existing: bool = False,
    ) -> Contact:
        """Assign a lead source to a contact and backfill its open jobs.

        Sets the contact's latest touch (and first touch when unset) to the
        chosen source at full confidence, then attributes any of the contact's
        opportunities that are still missing a source so ROI reflects the fix.
        """
        lead_source = await self.db.get(LeadSource, lead_source_id)
        if (
            lead_source is None
            or lead_source.workspace_id != workspace_id
            or not lead_source.enabled
        ):
            raise AttributionCleanupError("Active lead source not found")

        contact = await self.db.get(Contact, contact_id)
        if contact is None or contact.workspace_id != workspace_id:
            raise AttributionCleanupError("Contact not found")

        previous_first_source_id = contact.first_touch_lead_source_id
        if correct_existing:
            stamp = datetime.now(UTC)
            contact.first_touch_lead_source_id = lead_source_id
            contact.first_touch_lead_source_campaign_id = lead_source_campaign_id
            contact.first_touch_at = contact.first_touch_at or stamp
            contact.latest_touch_lead_source_id = lead_source_id
            contact.latest_touch_lead_source_campaign_id = lead_source_campaign_id
            contact.latest_touch_at = stamp
            contact.attribution_confidence = MANUAL_ASSIGNMENT_CONFIDENCE
        else:
            _apply_contact_touch(
                contact,
                lead_source_id=lead_source_id,
                lead_source_campaign_id=lead_source_campaign_id,
                confidence=MANUAL_ASSIGNMENT_CONFIDENCE,
            )

        # Persist the chosen channel on the source itself when the operator
        # corrected it (e.g. confirming a guessed phone/radio lead).
        if source_type is not None and lead_source.source_type != source_type:
            lead_source.source_type = source_type

        await self._backfill_opportunities(
            workspace_id=workspace_id,
            contact_id=contact_id,
            lead_source_id=lead_source_id,
            lead_source_campaign_id=lead_source_campaign_id,
            replace_source_id=previous_first_source_id if correct_existing else None,
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
        replace_source_id: uuid.UUID | None = None,
    ) -> None:
        """Backfill gaps, or repair snapshots inherited from a corrected source.

        Normal cleanup touches only unattributed rows. Explicit correction also
        replaces the old contact source while preserving independently sourced
        opportunities.
        """
        source_filters: list[ColumnElement[bool]] = [Opportunity.lead_source_id.is_(None)]
        if replace_source_id is not None:
            # Explicit corrections may rewrite snapshots inherited from the old
            # contact source, but never opportunities attributed independently.
            source_filters.append(Opportunity.lead_source_id == replace_source_id)

        result = await self.db.execute(
            select(Opportunity).where(
                Opportunity.workspace_id == workspace_id,
                Opportunity.primary_contact_id == contact_id,
                or_(*source_filters),
            )
        )
        for opportunity in result.scalars().all():
            opportunity.lead_source_id = lead_source_id
            opportunity.lead_source_campaign_id = lead_source_campaign_id
            opportunity.attribution_confidence = MANUAL_ASSIGNMENT_CONFIDENCE
