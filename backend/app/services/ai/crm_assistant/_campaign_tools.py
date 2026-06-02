"""Campaign CRM assistant tools."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.db.scope import get_workspace_owned, select_workspace_owned
from app.models.campaign import Campaign, CampaignContact
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
    parse_uuid,
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


class CampaignAssistantTools:
    """Read, send, and lifecycle tools for campaigns."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_campaigns": self.list_campaigns,
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
        limit = min(args.get("limit", 10), 50)
        stmt = (
            select_workspace_owned(Campaign, self.context.workspace_id)
            .order_by(Campaign.created_at.desc())
            .limit(limit)
        )
        if args.get("status"):
            stmt = stmt.where(Campaign.status == args["status"])

        result = await self.context.db.execute(stmt)
        campaigns = result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "id": str(campaign.id),
                    "name": campaign.name,
                    "status": campaign.status,
                    "type": campaign.campaign_type,
                }
                for campaign in campaigns
            ],
            "count": len(campaigns),
        }

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
            return {"success": False, "error": "Contact not found"}

        phone_result = await self.context.db.execute(
            select_workspace_owned(PhoneNumber, self.context.workspace_id).limit(1)
        )
        phone = phone_result.scalar_one_or_none()
        if not phone:
            return {"success": False, "error": "No phone number available in workspace"}

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
            return {"success": False, "error": "Invalid campaign_id"}
        contact_id = args.get("contact_id")
        if contact_id is None:
            return {"success": False, "error": "contact_id is required"}

        campaign = await self.get_campaign_for_workspace(campaign_id)
        if campaign is None:
            return {"success": False, "error": "Campaign not found"}
        if not campaign.initial_message:
            return {"success": False, "error": "Campaign has no initial message"}

        return await self.send_sms(
            {"contact_id": contact_id, "body": campaign.initial_message, "confirmed": True}
        )

    async def start_campaign(self, args: ToolArguments) -> dict[str, object]:
        campaign_id = parse_uuid(args.get("campaign_id"))
        if campaign_id is None:
            return {"success": False, "error": "Invalid campaign_id"}

        campaign = await self.get_campaign_for_workspace(campaign_id)
        if campaign is None:
            return {"success": False, "error": "Campaign not found"}

        try:
            lifecycle_result = await start_campaign(self.context.db, campaign)
        except CampaignLifecycleError as exc:
            return {"success": False, "error": str(exc)}

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
            return {"success": False, "error": "Invalid campaign_id"}

        campaign = await self.get_campaign_for_workspace(campaign_id)
        if campaign is None:
            return {"success": False, "error": "Campaign not found"}

        try:
            lifecycle_result = await pause_campaign(campaign)
        except CampaignLifecycleError as exc:
            return {"success": False, "error": str(exc)}

        await self.context.db.flush()
        return {
            "success": True,
            "message": lifecycle_result.message,
            "data": {"campaign_id": str(campaign.id), "status": lifecycle_result.status.value},
        }

    async def resume_campaign(self, args: ToolArguments) -> dict[str, object]:
        campaign_id = parse_uuid(args.get("campaign_id"))
        if campaign_id is None:
            return {"success": False, "error": "Invalid campaign_id"}

        campaign = await self.get_campaign_for_workspace(campaign_id)
        if campaign is None:
            return {"success": False, "error": "Campaign not found"}

        try:
            lifecycle_result = await resume_campaign(self.context.db, campaign)
        except CampaignLifecycleError as exc:
            return {"success": False, "error": str(exc)}

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
            return {"success": False, "error": "Invalid campaign_id"}

        campaign = await self.get_campaign_for_workspace(campaign_id)
        if campaign is None:
            return {"success": False, "error": "Campaign not found"}

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
