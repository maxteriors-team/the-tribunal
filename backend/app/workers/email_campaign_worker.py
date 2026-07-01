"""Email campaign worker.

Processes ``campaign_type = 'email'`` campaigns: for each RUNNING email campaign
it grabs PENDING enrollments, renders the per-contact subject and body, and sends
via Resend with a compliant unsubscribe footer. Mirrors the SMS campaign worker's
enrollment/status model but has no phone sender, number pool, or Telnyx dependency.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import QueryableAttribute, selectinload

from app.models.campaign import (
    Campaign,
    CampaignContact,
    CampaignContactStatus,
    CampaignType,
)
from app.models.contact import Contact
from app.services.campaigns.email_unsubscribe import build_unsubscribe_url
from app.services.email import send_campaign_email
from app.workers.base import WorkerRegistry
from app.workers.base_campaign_worker import BaseCampaignWorker

# Per tick, cap the fan-out so one campaign can't monopolize a cycle and to keep
# well under Resend's rate limits. Multiple ticks drain a large list over time.
MAX_EMAILS_PER_TICK = 50


def _render_template(template: str, contact: Contact) -> str:
    """Substitute {first_name}/{last_name}/{full_name}/{company_name} placeholders."""
    full_name = " ".join(filter(None, [contact.first_name, contact.last_name])) or ""
    replacements = {
        "first_name": contact.first_name or "",
        "last_name": contact.last_name or "",
        "full_name": full_name,
        "company_name": contact.company_name or "",
    }
    rendered = template
    for key, value in replacements.items():
        for token in (f"{{{key}}}", f"{{{key.upper()}}}"):
            rendered = rendered.replace(token, value)
    return rendered


class EmailCampaignWorker(BaseCampaignWorker):
    """Background worker that sends email campaigns via Resend."""

    POLL_INTERVAL_SECONDS = 30
    COMPONENT_NAME = "email_campaign_worker"
    MAX_CONCURRENCY = 1
    # Email campaigns use Resend, not Telnyx — override the SMS/voice dependency.
    requires_telnyx_api_key = False

    @property
    def campaign_type(self) -> CampaignType:
        return CampaignType.EMAIL

    @property
    def eager_loads(self) -> list[QueryableAttribute[Any]]:
        return [Campaign.offer]

    def _get_remaining_filter(self, campaign: Campaign) -> Any:
        return and_(
            CampaignContact.campaign_id == campaign.id,
            CampaignContact.status == CampaignContactStatus.PENDING,
        )

    async def _process_campaign_contacts(
        self,
        campaign: Campaign,
        db: AsyncSession,
        log: Any,
    ) -> None:
        """Send the campaign email to each pending enrollment."""
        if not campaign.initial_message or not campaign.email_subject:
            log.warning("Email campaign missing subject or body, skipping")
            return

        result = await db.execute(
            select(CampaignContact)
            .options(selectinload(CampaignContact.contact))
            .where(
                CampaignContact.campaign_id == campaign.id,
                CampaignContact.status == CampaignContactStatus.PENDING,
            )
            .order_by(CampaignContact.priority.desc(), CampaignContact.created_at)
            .limit(MAX_EMAILS_PER_TICK)
        )
        pending = result.scalars().all()
        if not pending:
            await self._check_completion(campaign, db, log)
            await db.commit()
            return

        for campaign_contact in pending:
            contact = campaign_contact.contact
            to_email = (contact.email or "").strip() if contact else ""

            if not to_email:
                # No address to send to — a send failure, not a provider bounce
                # (emails_bounced is driven by Resend bounce webhooks).
                campaign_contact.status = CampaignContactStatus.FAILED
                campaign.messages_failed += 1
                continue

            subject = _render_template(campaign.email_subject, contact)
            body = _render_template(campaign.initial_message, contact)
            unsubscribe_url = build_unsubscribe_url(campaign_contact.id)

            try:
                email_id = await send_campaign_email(
                    to_email=to_email,
                    subject=subject,
                    body=body,
                    unsubscribe_url=unsubscribe_url,
                    idempotency_key=campaign_contact.id,
                )
            except Exception:
                log.warning("Email send raised", contact_id=contact.id, exc_info=True)
                email_id = None

            now = datetime.now(UTC)
            if email_id:
                campaign_contact.status = CampaignContactStatus.SENT
                campaign_contact.messages_sent += 1
                campaign_contact.first_sent_at = campaign_contact.first_sent_at or now
                campaign_contact.last_sent_at = now
                campaign.emails_sent += 1
                campaign.messages_sent += 1
                self.record_items_processed()
            else:
                campaign_contact.status = CampaignContactStatus.FAILED
                campaign.messages_failed += 1

        # Persist completion status in the same commit as the sent/failed updates,
        # matching the voice worker: _check_completion sets status but never commits.
        await self._check_completion(campaign, db, log)
        await db.commit()


# Singleton registry
_registry = WorkerRegistry(EmailCampaignWorker)
start_email_campaign_worker = _registry.start
stop_email_campaign_worker = _registry.stop
get_email_campaign_worker = _registry.get
