"""Bounded, workspace-scoped enrollment for draft campaign audiences."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import Campaign, CampaignContact, CampaignStatus, CampaignType
from app.models.contact import Contact
from app.models.segment import Segment
from app.models.tag import Tag
from app.services.contacts.contact_filter_validation import (
    ContactFilterValidationError,
    validate_contact_filter_rules,
)
from app.services.contacts.contact_filters import apply_contact_filters

MAX_CAMPAIGN_AUDIENCE_SIZE = 5_000


class CampaignAudienceError(ValueError):
    """A safe, user-facing campaign audience enrollment failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AudienceEnrollmentResult:
    """Counts from one idempotent audience enrollment."""

    source_count: int
    eligible_count: int
    added_count: int
    duplicate_count: int
    ineligible_count: int


class CampaignAudienceService:
    """Resolve and enroll one bounded audience without sending outreach."""

    def __init__(self, db: AsyncSession, workspace_id: uuid.UUID) -> None:
        self.db = db
        self.workspace_id = workspace_id

    async def enroll(
        self,
        *,
        campaign_id: uuid.UUID,
        segment_id: uuid.UUID | None = None,
        contact_ids: list[int] | None = None,
    ) -> AudienceEnrollmentResult:
        """Enroll exactly one segment or explicit contact list into a draft campaign."""

        if (segment_id is None) == (contact_ids is None):
            raise CampaignAudienceError(
                "invalid_source",
                "Provide exactly one audience source: segment_id or contact_ids.",
            )

        campaign = await self._get_draft_campaign(campaign_id)
        if segment_id is not None:
            contacts, source_count = await self._resolve_segment_contacts(segment_id)
        else:
            contacts, source_count = await self._resolve_explicit_contacts(contact_ids or [])

        eligible_ids = {
            contact.id
            for contact in contacts
            if _is_channel_eligible(contact, campaign.campaign_type)
        }
        existing_ids = await self._existing_contact_ids(campaign.id, eligible_ids)
        new_ids = eligible_ids - existing_ids
        added_count = await self._insert_enrollments(campaign.id, new_ids)
        campaign.total_contacts += added_count

        return AudienceEnrollmentResult(
            source_count=source_count,
            eligible_count=len(eligible_ids),
            added_count=added_count,
            duplicate_count=len(eligible_ids) - added_count,
            ineligible_count=source_count - len(eligible_ids),
        )

    async def _get_draft_campaign(self, campaign_id: uuid.UUID) -> Campaign:
        result = await self.db.execute(
            select(Campaign)
            .where(Campaign.id == campaign_id, Campaign.workspace_id == self.workspace_id)
            .with_for_update()
        )
        campaign = result.scalar_one_or_none()
        if campaign is None:
            raise CampaignAudienceError("not_found", "Campaign not found.")
        if campaign.status != CampaignStatus.DRAFT:
            raise CampaignAudienceError(
                "campaign_not_draft",
                "Audience enrollment is only allowed for draft campaigns.",
            )
        return campaign

    async def _resolve_segment_contacts(self, segment_id: uuid.UUID) -> tuple[list[Contact], int]:
        result = await self.db.execute(
            select(Segment).where(
                Segment.id == segment_id,
                Segment.workspace_id == self.workspace_id,
            )
        )
        segment = result.scalar_one_or_none()
        if segment is None:
            raise CampaignAudienceError("not_found", "Segment not found.")

        definition = segment.definition if isinstance(segment.definition, dict) else {}
        try:
            rules, logic = validate_contact_filter_rules(
                definition.get("rules"),
                definition.get("logic", "and"),
            )
        except ContactFilterValidationError as exc:
            raise CampaignAudienceError(
                "invalid_segment",
                "The segment contains unsupported filters; edit it before enrollment.",
            ) from exc
        tag_ids = {
            uuid.UUID(value) for rule in rules if rule["field"] == "tags" for value in rule["value"]
        }
        if tag_ids:
            tag_result = await self.db.execute(
                select(Tag.id).where(
                    Tag.id.in_(tag_ids),
                    Tag.workspace_id == self.workspace_id,
                )
            )
            if set(tag_result.scalars().all()) != tag_ids:
                raise CampaignAudienceError(
                    "invalid_segment",
                    "The segment contains unavailable tags; edit it before enrollment.",
                )

        count_query = apply_contact_filters(
            select(func.count(Contact.id)).where(Contact.workspace_id == self.workspace_id),
            self.workspace_id,
            filter_rules=rules,
            filter_logic=logic,
        )
        count_result = await self.db.execute(count_query)
        source_count = int(count_result.scalar_one())
        self.check_batch_size(source_count)

        contacts_query = (
            apply_contact_filters(
                select(Contact).where(Contact.workspace_id == self.workspace_id),
                self.workspace_id,
                filter_rules=rules,
                filter_logic=logic,
            )
            .order_by(Contact.id)
            .limit(MAX_CAMPAIGN_AUDIENCE_SIZE + 1)
        )
        contacts_result = await self.db.execute(contacts_query)
        contacts = list(contacts_result.scalars().all())
        self.check_batch_size(len(contacts))
        return contacts, len(contacts)

    async def _resolve_explicit_contacts(self, contact_ids: list[int]) -> tuple[list[Contact], int]:
        if not isinstance(contact_ids, list) or not contact_ids:
            raise CampaignAudienceError("invalid_source", "contact_ids cannot be empty.")
        self.check_batch_size(len(contact_ids))
        if any(
            isinstance(contact_id, bool) or not isinstance(contact_id, int) or contact_id <= 0
            for contact_id in contact_ids
        ):
            raise CampaignAudienceError(
                "invalid_source",
                "contact_ids must contain positive integers.",
            )
        unique_ids = set(contact_ids)

        result = await self.db.execute(
            select(Contact).where(
                Contact.id.in_(unique_ids),
                Contact.workspace_id == self.workspace_id,
            )
        )
        contacts = list(result.scalars().all())
        if len(contacts) != len(unique_ids):
            raise CampaignAudienceError("not_found", "One or more contacts were not found.")
        return contacts, len(unique_ids)

    @staticmethod
    def check_batch_size(source_count: int) -> None:
        if source_count > MAX_CAMPAIGN_AUDIENCE_SIZE:
            raise CampaignAudienceError(
                "audience_too_large",
                (
                    f"Audience exceeds the {MAX_CAMPAIGN_AUDIENCE_SIZE:,}-contact limit; "
                    "narrow it first."
                ),
            )

    async def _existing_contact_ids(
        self, campaign_id: uuid.UUID, eligible_ids: set[int]
    ) -> set[int]:
        if not eligible_ids:
            return set()
        result = await self.db.execute(
            select(CampaignContact.contact_id).where(
                CampaignContact.campaign_id == campaign_id,
                CampaignContact.contact_id.in_(eligible_ids),
            )
        )
        return set(result.scalars().all())

    async def _insert_enrollments(self, campaign_id: uuid.UUID, contact_ids: set[int]) -> int:
        if not contact_ids:
            return 0
        statement = (
            pg_insert(CampaignContact)
            .values(
                [
                    {"campaign_id": campaign_id, "contact_id": contact_id}
                    for contact_id in sorted(contact_ids)
                ]
            )
            .on_conflict_do_nothing(constraint="uq_campaign_contact")
            .returning(CampaignContact.contact_id)
        )
        result = await self.db.execute(statement)
        return len(result.scalars().all())


def _is_channel_eligible(contact: Contact, campaign_type: CampaignType | str) -> bool:
    if campaign_type == CampaignType.EMAIL:
        return bool(contact.email and contact.email.strip()) and contact.email_opted_out_at is None
    return (
        bool(contact.phone_number and contact.phone_number.strip())
        and contact.sms_consent_status != "opted_out"
    )
