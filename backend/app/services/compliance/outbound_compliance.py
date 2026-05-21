"""Outbound compliance checks for SMS and campaign sends."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from sqlalchemy import and_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import Campaign, CampaignContact, CampaignContactStatus
from app.models.contact import Contact
from app.services.rate_limiting.opt_out_manager import OptOutManager

logger = structlog.get_logger()


@dataclass(slots=True, frozen=True)
class OutboundComplianceRequest:
    """Input for outbound compliance evaluation."""

    workspace_id: uuid.UUID
    campaign: Campaign
    campaign_contact: CampaignContact | None
    contact: Contact
    channel: str
    action_type: str
    now: datetime
    require_sms_consent: bool = True


@dataclass(slots=True, frozen=True)
class OutboundComplianceResult:
    """Result of outbound compliance evaluation."""

    allowed: bool
    reason: str | None = None
    details: dict[str, object] = field(default_factory=dict)
    next_allowed_at: datetime | None = None

    def as_dict(self) -> dict[str, object]:
        """Serialize the result for storage."""
        payload: dict[str, object] = {
            "allowed": self.allowed,
            "reason": self.reason,
            "details": self.details,
        }
        if self.next_allowed_at is not None:
            payload["next_allowed_at"] = self.next_allowed_at.isoformat()
        return payload


class OutboundComplianceService:
    """Evaluate outbound campaign and SMS compliance controls."""

    OPTED_IN = "opted_in"

    def __init__(self, opt_out_manager: OptOutManager | None = None) -> None:
        self.opt_out_manager = opt_out_manager or OptOutManager()
        self.logger = logger.bind(component="outbound_compliance")

    async def evaluate(  # noqa: PLR0911
        self,
        request: OutboundComplianceRequest,
        db: AsyncSession,
    ) -> OutboundComplianceResult:
        """Evaluate all compliance gates for a proposed outbound send."""
        if await self.opt_out_manager.check_opt_out(
            request.workspace_id, request.contact.phone_number, db
        ):
            return self._blocked("global_opt_out", request)

        if request.channel == "sms" and request.require_sms_consent:
            consent_status = request.contact.sms_consent_status or "unknown"
            if consent_status != self.OPTED_IN:
                return self._blocked(
                    "missing_sms_consent",
                    request,
                    {"sms_consent_status": consent_status},
                )

        quiet_hours_result = self._evaluate_quiet_hours(request)
        if not quiet_hours_result.allowed:
            return quiet_hours_result

        if (
            request.campaign.max_messages_per_campaign is not None
            and request.campaign.messages_sent >= request.campaign.max_messages_per_campaign
        ):
            return self._blocked(
                "campaign_send_cap_reached",
                request,
                {
                    "messages_sent": request.campaign.messages_sent,
                    "max_messages_per_campaign": request.campaign.max_messages_per_campaign,
                },
            )

        if request.campaign_contact is not None:
            if request.campaign_contact.messages_sent >= request.campaign.max_messages_per_contact:
                return self._blocked(
                    "contact_send_cap_reached",
                    request,
                    {
                        "messages_sent": request.campaign_contact.messages_sent,
                        "max_messages_per_contact": request.campaign.max_messages_per_contact,
                    },
                )

            if request.action_type == "campaign_initial_sms":
                duplicate_exists = await self._has_initial_duplicate(request, db)
                if duplicate_exists:
                    return self._blocked("duplicate_campaign_contact", request)

        return OutboundComplianceResult(
            allowed=True,
            details={
                "action_type": request.action_type,
                "channel": request.channel,
                "campaign_id": str(request.campaign.id),
                "contact_id": request.contact.id,
            },
        )

    def apply_suppression(
        self,
        campaign_contact: CampaignContact,
        result: OutboundComplianceResult,
        now: datetime | None = None,
    ) -> None:
        """Persist suppression metadata on a campaign contact."""
        checked_at = now or datetime.now(UTC)
        campaign_contact.compliance_checked_at = checked_at
        campaign_contact.last_compliance_result = result.as_dict()

        if result.allowed:
            return

        campaign_contact.suppressed_reason = result.reason
        campaign_contact.suppressed_at = checked_at
        if result.reason == "global_opt_out":
            campaign_contact.status = CampaignContactStatus.OPTED_OUT
            campaign_contact.opted_out = True
            campaign_contact.opted_out_at = checked_at

    async def _has_initial_duplicate(
        self,
        request: OutboundComplianceRequest,
        db: AsyncSession,
    ) -> bool:
        if request.campaign_contact is None:
            return False

        duplicate_query = select(
            exists().where(
                and_(
                    CampaignContact.campaign_id == request.campaign.id,
                    CampaignContact.contact_id == request.contact.id,
                    CampaignContact.id != request.campaign_contact.id,
                    CampaignContact.status.in_(
                        [
                            CampaignContactStatus.SENT,
                            CampaignContactStatus.DELIVERED,
                            CampaignContactStatus.REPLIED,
                            CampaignContactStatus.QUALIFIED,
                            CampaignContactStatus.COMPLETED,
                        ]
                    )
                    | (CampaignContact.conversation_id.is_not(None))
                    | (CampaignContact.first_sent_at.is_not(None)),
                )
            )
        )
        duplicate_result = await db.execute(duplicate_query)
        return bool(duplicate_result.scalar())

    def _evaluate_quiet_hours(self, request: OutboundComplianceRequest) -> OutboundComplianceResult:
        start = request.campaign.quiet_hours_start
        end = request.campaign.quiet_hours_end
        if start is None or end is None:
            return OutboundComplianceResult(allowed=True)

        timezone_name = request.campaign.quiet_hours_timezone or request.campaign.timezone or "UTC"
        try:
            local_now = request.now.astimezone(ZoneInfo(timezone_name))
        except ZoneInfoNotFoundError:
            self.logger.warning(
                "invalid_quiet_hours_timezone",
                timezone=timezone_name,
                campaign_id=str(request.campaign.id),
            )
            local_now = request.now.astimezone(ZoneInfo("UTC"))
            timezone_name = "UTC"

        local_time = local_now.time()
        if start <= end:
            in_quiet_hours = start <= local_time < end
        else:
            in_quiet_hours = local_time >= start or local_time < end

        if not in_quiet_hours:
            return OutboundComplianceResult(allowed=True)

        return self._blocked(
            "quiet_hours",
            request,
            {
                "quiet_hours_start": start.isoformat(),
                "quiet_hours_end": end.isoformat(),
                "timezone": timezone_name,
                "local_time": local_time.isoformat(),
            },
        )

    def _blocked(
        self,
        reason: str,
        request: OutboundComplianceRequest,
        details: dict[str, object] | None = None,
    ) -> OutboundComplianceResult:
        result_details: dict[str, object] = {
            "action_type": request.action_type,
            "channel": request.channel,
            "campaign_id": str(request.campaign.id),
            "contact_id": request.contact.id,
        }
        if details:
            result_details.update(details)
        return OutboundComplianceResult(allowed=False, reason=reason, details=result_details)
