"""Campaign CRM assistant tools."""

from __future__ import annotations

import uuid
from datetime import datetime, time
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, or_, select

from app.db.scope import get_workspace_owned, select_workspace_owned
from app.models.agent import Agent
from app.models.campaign import (
    Campaign,
    CampaignContact,
    CampaignStatus,
    CampaignType,
)
from app.models.contact import Contact
from app.models.offer import Offer
from app.models.phone_number import PhoneNumber
from app.schemas.campaign import CampaignCreate, CampaignUpdate
from app.services.ai.crm_assistant._pagination import count_matching, listing
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
    parse_uuid,
)
from app.services.ai.crm_assistant._tool_errors import (
    conflict,
    invalid_argument,
    invalid_id,
    missing_argument,
    not_found,
    unavailable,
    validation_failed,
)
from app.services.campaigns.campaign_lifecycle import (
    CampaignLifecycleError,
    count_campaign_contacts,
    get_campaign_for_workspace,
    pause_campaign,
    resume_campaign,
    start_campaign,
    summarize_campaign,
)
from app.utils.datetime import parse_time_string


def _enum_value(value: object) -> object:
    return value.value if hasattr(value, "value") else value


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _clock(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value else None


def serialize_campaign(campaign: Campaign, *, contact_count: int) -> dict[str, Any]:
    """Return the fields an operator needs to inspect before launch."""

    return {
        "id": str(campaign.id),
        "name": campaign.name,
        "description": campaign.description,
        "status": _enum_value(campaign.status),
        "type": _enum_value(campaign.campaign_type),
        "agent_id": str(campaign.agent_id) if campaign.agent_id else None,
        "offer_id": str(campaign.offer_id) if campaign.offer_id else None,
        "from_phone_number": campaign.from_phone_number,
        "initial_message": campaign.initial_message,
        "email_subject": campaign.email_subject,
        "ai_enabled": campaign.ai_enabled,
        "qualification_criteria": campaign.qualification_criteria,
        "schedule": {
            "start": _iso(campaign.scheduled_start),
            "end": _iso(campaign.scheduled_end),
            "sending_hours_start": _clock(campaign.sending_hours_start),
            "sending_hours_end": _clock(campaign.sending_hours_end),
            "sending_days": campaign.sending_days,
            "timezone": campaign.timezone,
        },
        "messages_per_minute": campaign.messages_per_minute,
        "follow_up": {
            "enabled": campaign.follow_up_enabled,
            "delay_hours": campaign.follow_up_delay_hours,
            "message": campaign.follow_up_message,
            "max_follow_ups": campaign.max_follow_ups,
        },
        "contact_count": contact_count,
        "performance": {
            "messages_sent": campaign.messages_sent,
            "messages_delivered": campaign.messages_delivered,
            "messages_failed": campaign.messages_failed,
            "replies_received": campaign.replies_received,
            "contacts_qualified": campaign.contacts_qualified,
            "contacts_opted_out": campaign.contacts_opted_out,
            "appointments_booked": campaign.appointments_booked,
        },
        "created_at": _iso(campaign.created_at),
        "updated_at": _iso(campaign.updated_at),
    }


def _parse_campaign_times(data: dict[str, Any]) -> dict[str, Any] | None:
    """Convert HH:MM strings in a validated campaign payload.

    ``None`` means a supplied value was malformed. The public campaign route
    uses the same parser but silently converts bad values to ``None``; tool
    calls must fail loudly so the model can self-correct instead of erasing a
    sending window.
    """

    for field in ("sending_hours_start", "sending_hours_end"):
        if field not in data:
            continue
        raw = data[field]
        parsed = parse_time_string(raw)
        if raw is not None and parsed is None:
            return None
        data[field] = parsed
    return data


class CampaignAssistantTools:
    """Read, send, and lifecycle tools for campaigns."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_campaigns": self.list_campaigns,
            "create_campaign": self.create_campaign,
            "update_campaign": self.update_campaign,
            "list_campaign_contacts": self.list_campaign_contacts,
            "send_sms": self.send_sms,
            "send_initial_message": self.send_initial_message,
            "start_campaign": self.start_campaign,
            "pause_campaign": self.pause_campaign,
            "resume_campaign": self.resume_campaign,
            "summarize_campaign": self.summarize_campaign,
        }

    async def get_campaign_for_workspace(self, campaign_id: uuid.UUID) -> Campaign | None:
        return await get_campaign_for_workspace(
            self.context.db,
            campaign_id,
            self.context.workspace_id,
        )

    async def list_campaigns(self, args: ToolArguments) -> dict[str, object]:
        limit = min(max(int(args.get("limit", 10)), 1), 50)
        stmt = select_workspace_owned(Campaign, self.context.workspace_id)
        if args.get("status"):
            stmt = stmt.where(Campaign.status == args["status"])

        total = await count_matching(self.context.db, Campaign, stmt)
        result = await self.context.db.execute(
            stmt.order_by(Campaign.created_at.desc()).limit(limit)
        )
        campaigns = result.scalars().all()
        contact_counts = await self._campaign_contact_counts(
            [campaign.id for campaign in campaigns]
        )

        return listing(
            [
                serialize_campaign(
                    campaign,
                    contact_count=contact_counts.get(campaign.id, 0),
                )
                for campaign in campaigns
            ],
            total=total,
        )

    async def _campaign_contact_counts(self, campaign_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not campaign_ids:
            return {}
        result = await self.context.db.execute(
            select(CampaignContact.campaign_id, func.count(CampaignContact.id))
            .join(Campaign, Campaign.id == CampaignContact.campaign_id)
            .where(
                Campaign.workspace_id == self.context.workspace_id,
                CampaignContact.campaign_id.in_(campaign_ids),
            )
            .group_by(CampaignContact.campaign_id)
        )
        return {campaign_id: int(total) for campaign_id, total in result.all()}

    async def _validate_reference(
        self,
        model: type[Agent] | type[Offer],
        raw_id: object,
        label: str,
    ) -> uuid.UUID | dict[str, object] | None:
        """Validate an optional workspace-owned foreign-key reference."""

        if raw_id in (None, ""):
            return None
        parsed = parse_uuid(raw_id)
        if parsed is None:
            return invalid_id(label, f"Call list_{label.removesuffix('_id')}s to get a valid id.")
        entity = await get_workspace_owned(
            self.context.db,
            model,
            parsed,
            self.context.workspace_id,
        )
        if entity is None:
            return not_found(
                label.removesuffix("_id").replace("_", " ").title(),
                f"Choose a {label} from this workspace.",
            )
        return parsed

    async def _resolve_sender(
        self,
        campaign_type: str,
        requested_number: object,
    ) -> str | dict[str, object] | None:
        """Resolve a usable, workspace-owned sender for SMS/voice campaigns."""

        if campaign_type == CampaignType.EMAIL.value:
            return None
        stmt = select_workspace_owned(
            PhoneNumber,
            self.context.workspace_id,
            PhoneNumber.is_active.is_(True),
            or_(
                PhoneNumber.sms_enabled.is_(True),
                PhoneNumber.imessage_enabled.is_(True),
            ),
        )
        if requested_number not in (None, ""):
            stmt = stmt.where(PhoneNumber.phone_number == str(requested_number))
        result = await self.context.db.execute(stmt.order_by(PhoneNumber.created_at).limit(1))
        sender = result.scalar_one_or_none()
        if sender is None:
            return unavailable(
                "No active SMS or iMessage sender is available in this workspace.",
                "Add or activate a sending phone number in Settings, then retry.",
            )
        return str(sender.phone_number)

    async def create_campaign(  # noqa: PLR0911 - explicit validation exits
        self, args: ToolArguments
    ) -> dict[str, object]:
        """Create a validated draft campaign; this does not enroll or message anyone."""

        try:
            payload = CampaignCreate.model_validate(args).model_dump()
        except ValidationError as exc:
            return validation_failed("Campaign", str(exc))

        campaign_type = str(payload["campaign_type"])
        if campaign_type not in {item.value for item in CampaignType}:
            return invalid_argument(
                "campaign_type is not supported.",
                "Use sms, voice_sms_fallback, or email.",
            )
        if not str(payload["name"]).strip():
            return invalid_argument("Campaign name cannot be blank.", "Provide a short name.")
        if not str(payload["initial_message"]).strip():
            return invalid_argument(
                "initial_message cannot be blank.",
                "Provide the SMS text or email body before creating the draft.",
            )
        if (
            campaign_type == CampaignType.EMAIL.value
            and not str(payload.get("email_subject") or "").strip()
        ):
            return invalid_argument(
                "Email campaigns require an email_subject.",
                "Add the email subject and retry.",
            )

        for field, model in (("agent_id", Agent), ("offer_id", Offer)):
            reference = await self._validate_reference(model, payload.get(field), field)
            if isinstance(reference, dict):
                return reference
            payload[field] = reference

        sender = await self._resolve_sender(campaign_type, payload.get("from_phone_number"))
        if isinstance(sender, dict):
            return sender
        payload["from_phone_number"] = sender

        parsed_payload = _parse_campaign_times(payload)
        if parsed_payload is None:
            return invalid_argument(
                "Sending hours must use 24-hour HH:MM format.",
                "Use values such as 09:00 and 17:30.",
            )

        campaign = Campaign(
            workspace_id=self.context.workspace_id,
            status=CampaignStatus.DRAFT,
            **parsed_payload,
        )
        self.context.db.add(campaign)
        await self.context.db.flush()
        return {
            "success": True,
            "data": serialize_campaign(campaign, contact_count=0),
            "hint": (
                "The campaign is a draft with no contacts; review it and enroll "
                "contacts before starting."
            ),
        }

    async def update_campaign(  # noqa: PLR0911, PLR0912 - validation branches
        self, args: ToolArguments
    ) -> dict[str, object]:
        """Update an existing draft/paused campaign without launching it."""

        campaign_id = parse_uuid(args.get("campaign_id"))
        if campaign_id is None:
            return invalid_id("campaign_id", "Call list_campaigns to get a valid campaign id.")
        campaign = await self.get_campaign_for_workspace(campaign_id)
        if campaign is None:
            return not_found("Campaign", "Call list_campaigns to get a valid campaign id.")
        if campaign.status not in {CampaignStatus.DRAFT, CampaignStatus.PAUSED}:
            return conflict(
                "Only draft or paused campaigns can be edited.",
                "Pause a running campaign first; completed/canceled campaigns are immutable.",
            )

        raw_updates = {key: value for key, value in args.items() if key != "campaign_id"}
        if not raw_updates:
            return invalid_argument(
                "No campaign fields were provided to update.",
                "Include at least one field to change alongside campaign_id.",
            )
        try:
            updates = CampaignUpdate.model_validate(raw_updates).model_dump(exclude_unset=True)
        except ValidationError as exc:
            return validation_failed("Campaign", str(exc))

        for field, model in (("agent_id", Agent), ("offer_id", Offer)):
            if field not in updates:
                continue
            reference = await self._validate_reference(model, updates[field], field)
            if isinstance(reference, dict):
                return reference
            updates[field] = reference

        if "from_phone_number" in updates:
            sender = await self._resolve_sender(
                str(_enum_value(campaign.campaign_type)),
                updates["from_phone_number"],
            )
            if isinstance(sender, dict):
                return sender
            updates["from_phone_number"] = sender

        parsed_updates = _parse_campaign_times(updates)
        if parsed_updates is None:
            return invalid_argument(
                "Sending hours must use 24-hour HH:MM format.",
                "Use values such as 09:00 and 17:30.",
            )
        if "name" in parsed_updates and not str(parsed_updates["name"]).strip():
            return invalid_argument("Campaign name cannot be blank.", "Provide a short name.")
        if (
            "initial_message" in parsed_updates
            and not str(parsed_updates["initial_message"] or "").strip()
        ):
            return invalid_argument(
                "initial_message cannot be blank.",
                "Provide the message body or omit this field.",
            )

        for field, value in parsed_updates.items():
            setattr(campaign, field, value)
        await self.context.db.flush()
        count = await count_campaign_contacts(self.context.db, campaign_id)
        return {
            "success": True,
            "data": serialize_campaign(campaign, contact_count=count),
        }

    async def list_campaign_contacts(self, args: ToolArguments) -> dict[str, object]:
        """List campaign enrollments joined to the corresponding contact records."""

        campaign_id = parse_uuid(args.get("campaign_id"))
        if campaign_id is None:
            return invalid_id("campaign_id", "Call list_campaigns to get a valid campaign id.")
        campaign = await self.get_campaign_for_workspace(campaign_id)
        if campaign is None:
            return not_found("Campaign", "Call list_campaigns to get a valid campaign id.")

        limit = min(max(int(args.get("limit", 20)), 1), 50)
        status_filter = args.get("status")
        conditions = [
            CampaignContact.campaign_id == campaign_id,
            Campaign.workspace_id == self.context.workspace_id,
        ]
        if status_filter:
            conditions.append(CampaignContact.status == status_filter)

        total = await self.context.db.scalar(
            select(func.count(CampaignContact.id))
            .join(Campaign, Campaign.id == CampaignContact.campaign_id)
            .where(*conditions)
        )
        result = await self.context.db.execute(
            select(CampaignContact, Contact)
            .join(Campaign, Campaign.id == CampaignContact.campaign_id)
            .join(Contact, Contact.id == CampaignContact.contact_id)
            .where(*conditions, Contact.workspace_id == self.context.workspace_id)
            .order_by(CampaignContact.created_at.desc())
            .limit(limit)
        )
        rows = result.all()
        return listing(
            [
                {
                    "campaign_contact_id": str(enrollment.id),
                    "contact_id": contact.id,
                    "first_name": contact.first_name,
                    "last_name": contact.last_name,
                    "phone": contact.phone_number,
                    "email": contact.email,
                    "status": _enum_value(enrollment.status),
                    "messages_sent": enrollment.messages_sent,
                    "messages_received": enrollment.messages_received,
                    "follow_ups_sent": enrollment.follow_ups_sent,
                    "is_qualified": enrollment.is_qualified,
                    "opted_out": enrollment.opted_out,
                    "first_sent_at": _iso(enrollment.first_sent_at),
                    "last_reply_at": _iso(enrollment.last_reply_at),
                    "last_error": enrollment.last_error,
                }
                for enrollment, contact in rows
            ],
            total=int(total or 0),
        )

    async def send_sms(self, args: ToolArguments) -> dict[str, object]:
        from app.models.phone_number import PhoneNumber
        from app.services.telephony.text_provider import get_text_message_provider

        contact_id = args["contact_id"]
        body = args["body"]

        from app.models.contact import Contact

        contact = await get_workspace_owned(
            self.context.db,
            Contact,
            contact_id,
            self.context.workspace_id,
        )
        if not contact:
            return not_found("Contact", "Call search_contacts to get a valid contact_id.")

        phone_result = await self.context.db.execute(
            select_workspace_owned(PhoneNumber, self.context.workspace_id).limit(1)
        )
        phone = phone_result.scalar_one_or_none()
        if not phone:
            return unavailable(
                "This workspace has no sending phone number.",
                "Tell the operator to add a phone number in Settings before sending.",
            )

        sms_service = get_text_message_provider()
        try:
            await sms_service.send_message(
                to_number=contact.phone_number,
                from_number=phone.phone_number,
                body=body,
                db=self.context.db,
                workspace_id=self.context.workspace_id,
                phone_number_id=phone.id,
            )
        finally:
            await sms_service.close()

        return {"success": True, "message": f"SMS sent to {contact.first_name}"}

    async def send_initial_message(self, args: ToolArguments) -> dict[str, object]:
        campaign_id = parse_uuid(args.get("campaign_id"))
        if campaign_id is None:
            return invalid_id("campaign_id", "Call list_campaigns to get a valid campaign id.")
        contact_id = args.get("contact_id")
        if contact_id is None:
            return missing_argument("contact_id", "Call search_contacts to find the contact.")

        campaign = await self.get_campaign_for_workspace(campaign_id)
        if campaign is None:
            return not_found("Campaign", "Call list_campaigns to get a valid campaign id.")
        if not campaign.initial_message:
            return conflict(
                "That campaign has no initial message to send.",
                "Set initial_message with update_campaign first.",
            )

        return await self.send_sms(
            {"contact_id": contact_id, "body": campaign.initial_message, "confirmed": True}
        )

    async def start_campaign(self, args: ToolArguments) -> dict[str, object]:
        campaign_id = parse_uuid(args.get("campaign_id"))
        if campaign_id is None:
            return invalid_id("campaign_id", "Call list_campaigns to get a valid campaign id.")

        campaign = await self.get_campaign_for_workspace(campaign_id)
        if campaign is None:
            return not_found("Campaign", "Call list_campaigns to get a valid campaign id.")

        try:
            lifecycle_result = await start_campaign(self.context.db, campaign)
        except CampaignLifecycleError as exc:
            return conflict(str(exc), "Check the campaign status before retrying.")

        await self.context.db.flush()
        return {
            "success": True,
            "message": lifecycle_result.message,
            "data": {
                "campaign_id": str(campaign.id),
                "status": lifecycle_result.status.value,
                "contact_count": lifecycle_result.contact_count,
            },
        }

    async def pause_campaign(self, args: ToolArguments) -> dict[str, object]:
        campaign_id = parse_uuid(args.get("campaign_id"))
        if campaign_id is None:
            return invalid_id("campaign_id", "Call list_campaigns to get a valid campaign id.")

        campaign = await self.get_campaign_for_workspace(campaign_id)
        if campaign is None:
            return not_found("Campaign", "Call list_campaigns to get a valid campaign id.")

        try:
            lifecycle_result = await pause_campaign(campaign)
        except CampaignLifecycleError as exc:
            return conflict(str(exc), "Check the campaign status before retrying.")

        await self.context.db.flush()
        return {
            "success": True,
            "message": lifecycle_result.message,
            "data": {"campaign_id": str(campaign.id), "status": lifecycle_result.status.value},
        }

    async def resume_campaign(self, args: ToolArguments) -> dict[str, object]:
        campaign_id = parse_uuid(args.get("campaign_id"))
        if campaign_id is None:
            return invalid_id("campaign_id", "Call list_campaigns to get a valid campaign id.")

        campaign = await self.get_campaign_for_workspace(campaign_id)
        if campaign is None:
            return not_found("Campaign", "Call list_campaigns to get a valid campaign id.")

        try:
            lifecycle_result = await resume_campaign(self.context.db, campaign)
        except CampaignLifecycleError as exc:
            return conflict(str(exc), "Check the campaign status before retrying.")

        await self.context.db.flush()
        return {
            "success": True,
            "message": lifecycle_result.message,
            "data": {
                "campaign_id": str(campaign.id),
                "status": lifecycle_result.status.value,
                "contact_count": lifecycle_result.contact_count,
            },
        }

    async def summarize_campaign(self, args: ToolArguments) -> dict[str, object]:
        campaign_id = parse_uuid(args.get("campaign_id"))
        if campaign_id is None:
            return invalid_id("campaign_id", "Call list_campaigns to get a valid campaign id.")

        campaign = await self.get_campaign_for_workspace(campaign_id)
        if campaign is None:
            return not_found("Campaign", "Call list_campaigns to get a valid campaign id.")

        summary = summarize_campaign(campaign)
        total_contacts = await count_campaign_contacts(self.context.db, campaign_id)
        status_result = await self.context.db.execute(
            select(CampaignContact.status, func.count(CampaignContact.id))
            .where(CampaignContact.campaign_id == campaign_id)
            .group_by(CampaignContact.status)
        )
        status_counts = {
            (status.value if hasattr(status, "value") else str(status)): count
            for status, count in status_result.all()
        }
        summary["enrolled_contacts"] = total_contacts
        summary["contact_status_counts"] = status_counts
        return {"success": True, "data": summary}
