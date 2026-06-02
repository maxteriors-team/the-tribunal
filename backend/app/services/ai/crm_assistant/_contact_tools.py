"""Contact and dashboard CRM assistant tools."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func

from app.db.scope import select_workspace_owned
from app.models.appointment import Appointment
from app.models.campaign import Campaign
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.services.ai.crm_assistant._tool_context import CRMToolContext, ToolArguments, ToolHandler


class ContactAssistantTools:
    """Read and mutate contacts for CRM assistant tool calls."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "search_contacts": self.search_contacts,
            "create_contact": self.create_contact,
            "get_dashboard_stats": self.get_dashboard_stats,
        }

    async def search_contacts(self, args: ToolArguments) -> dict[str, object]:
        query = args["query"]
        limit = min(args.get("limit", 10), 50)
        pattern = f"%{query}%"

        stmt = (
            select_workspace_owned(Contact, self.context.workspace_id)
            .where(
                (Contact.first_name.ilike(pattern))
                | (Contact.last_name.ilike(pattern))
                | (Contact.email.ilike(pattern))
                | (Contact.phone_number.ilike(pattern))
                | (Contact.company_name.ilike(pattern))
            )
            .order_by(Contact.created_at.desc())
            .limit(limit)
        )
        result = await self.context.db.execute(stmt)
        contacts = result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "id": contact.id,
                    "first_name": contact.first_name,
                    "last_name": contact.last_name,
                    "phone": contact.phone_number,
                    "email": contact.email,
                    "status": contact.status,
                    "company": contact.company_name,
                }
                for contact in contacts
            ],
            "count": len(contacts),
        }

    async def create_contact(self, args: ToolArguments) -> dict[str, object]:
        phone = args["phone"]
        existing = await self.context.db.execute(
            select_workspace_owned(
                Contact,
                self.context.workspace_id,
                Contact.phone_number == phone,
            )
        )
        if existing.scalar_one_or_none():
            return {"success": False, "error": "Contact with this phone already exists"}

        contact = Contact(
            workspace_id=self.context.workspace_id,
            first_name=args["first_name"],
            last_name=args.get("last_name"),
            phone_number=phone,
            email=args.get("email"),
            notes=args.get("notes"),
        )
        self.context.db.add(contact)
        await self.context.db.flush()

        return {
            "success": True,
            "data": {
                "id": contact.id,
                "first_name": contact.first_name,
                "last_name": contact.last_name,
                "phone": contact.phone_number,
            },
        }

    async def get_dashboard_stats(self, _args: ToolArguments) -> dict[str, object]:
        contacts_count = await self.context.db.scalar(
            select_workspace_owned(Contact, self.context.workspace_id)
            .with_only_columns(func.count())
            .select_from(Contact)
        )
        campaigns_count = await self.context.db.scalar(
            select_workspace_owned(Campaign, self.context.workspace_id)
            .with_only_columns(func.count())
            .select_from(Campaign)
        )
        conversations_count = await self.context.db.scalar(
            select_workspace_owned(Conversation, self.context.workspace_id)
            .with_only_columns(func.count())
            .select_from(Conversation)
        )
        appointments_count = await self.context.db.scalar(
            select_workspace_owned(
                Appointment,
                self.context.workspace_id,
                Appointment.scheduled_at >= datetime.now(UTC),
            )
            .with_only_columns(func.count())
            .select_from(Appointment)
        )

        return {
            "success": True,
            "data": {
                "contacts": contacts_count or 0,
                "campaigns": campaigns_count or 0,
                "conversations": conversations_count or 0,
                "upcoming_appointments": appointments_count or 0,
            },
        }
