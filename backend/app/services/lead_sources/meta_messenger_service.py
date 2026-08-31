"""Inbound Messenger and Instagram Direct ingestion.

A DM carries no phone number, so it cannot become a ``Contact`` on arrival the
way an Instant Form lead does. It opens a contact-less conversation keyed on the
sender's Page-Scoped ID and rides the same inbound pipeline as SMS, so AI reply
scheduling, campaign sync, push and the SLA clock all behave identically.

The thread graduates to a real contact the moment the person shares a phone
number, which is also when Facebook Ads attribution is stamped and the lead
starts counting toward the Lead Source ROI card. That is deliberate rather than
incidental: Meta's standard messaging window closes 24 hours after the person's
last message and the 7-day human-agent tag does not cover bot replies, so
getting to SMS inside the window *is* the job of a DM conversation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import phonenumbers
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal
from app.db.tenancy import (
    mark_session_as_system,
    scope_session_to_workspace,
    session_system_reason,
    session_workspace_id,
)
from app.models.contact import Contact
from app.models.conversation import Conversation, MessageChannel
from app.models.lead_source import LeadSourceType
from app.models.workspace import WorkspaceIntegration
from app.services.lead_sources.attribution_service import (
    WebAttributionInput,
    apply_web_attribution,
)
from app.services.lead_sources.meta_lead_ads_service import (
    META_LEAD_ADS_INTEGRATION,
    MetaLeadAdsClient,
    MetaLeadAdsError,
    MetaLeadAdsValidationError,
    resolve_facebook_lead_source,
    validate_meta_credentials,
)
from app.services.telephony.inbound_text import (
    InboundTextEvent,
    persist_inbound_text_message,
    process_inbound_text_event,
)
from app.services.telephony.inbound_types import InboundMessageIngestResult
from app.utils.phone import normalize_phone_safe, validate_phone_number

logger = structlog.get_logger()

META_MESSENGER_EXTERNAL_SOURCE = "facebook_messenger"

#: Meta's standard messaging window. Outside it the Send API returns error 10.
MESSAGING_WINDOW = timedelta(hours=24)

#: Credential keys that may identify the account a DM was delivered to. Meta
#: sends the Page ID for Messenger and the Instagram account ID for IG Direct,
#: and the two are different numbers for the same connected business.
_ACCOUNT_CREDENTIAL_KEYS = ("page_id", "instagram_id")


class SenderProfileClient(Protocol):
    """The only Graph capability DM ingestion needs: resolve a sender's name.

    Narrower than :class:`MetaLeadAdsClient` on purpose. Ingestion never sends,
    never fetches a lead, and never touches insights, so depending on the whole
    client would overstate what this path can reach \u2014 and would force every test
    to fake methods it does not exercise.
    """

    async def fetch_sender_name(self, *, psid: str, access_token: str) -> str | None:
        """Return the DM sender's profile name, or ``None`` when unavailable."""


@dataclass(frozen=True, slots=True)
class MetaMessageEvent:
    """One inbound user DM, already stripped of echoes and receipts."""

    account_id: str
    psid: str
    message_id: str
    text: str
    channel: MessageChannel
    sent_at_ms: int | None = None

    @property
    def sent_at(self) -> datetime:
        """Return when the person sent this, defaulting to now on a bad value."""
        if self.sent_at_ms is None:
            return datetime.now(UTC)
        try:
            return datetime.fromtimestamp(self.sent_at_ms / 1000, tz=UTC)
        except (OSError, OverflowError, ValueError):
            return datetime.now(UTC)


async def process_meta_message(
    db: AsyncSession,
    *,
    event: MetaMessageEvent,
    client: SenderProfileClient | None = None,
) -> bool:
    """Ingest one inbound DM. Returns ``True`` when it persisted a new message.

    ``False`` means the delivery was a duplicate or was consumed without
    creating a message — Meta retries aggressively, and it replays the same
    ``mid`` rather than a new one.
    """
    integration, credentials = await _integration_for_account(db, event.account_id)
    _page_id, access_token = validate_meta_credentials(credentials)

    log = logger.bind(
        workspace_id=str(integration.workspace_id),
        channel=event.channel.value,
    )

    display_name = await _sender_name(
        client or MetaLeadAdsClient(),
        psid=event.psid,
        access_token=access_token,
        log=log,
    )

    inbound = InboundTextEvent(
        provider_message_id=event.message_id,
        # Meta object IDs, not phone numbers: the thread is keyed on the PSID.
        from_number=event.psid,
        to_number=event.account_id,
        body=event.text,
        workspace_id=integration.workspace_id,
        channel=event.channel,
        response_channel=event.channel.value,
        messenger_psid=event.psid,
        messenger_display_name=display_name,
        messenger_window_expires_at=event.sent_at + MESSAGING_WINDOW,
    )

    ingestor = _MessengerIngestor(log)
    message = await process_inbound_text_event(
        db=db,
        event=inbound,
        ingest_message=ingestor,
        log=log,
    )
    if message is None or not ingestor.created:
        return False

    await _link_contact_when_phone_shared(
        db,
        conversation_id=message.conversation_id,
        integration=integration,
        credentials=credentials,
        text=event.text,
        log=log,
    )
    return True


class _MessengerIngestor:
    """Bind the shared inbound persister to this DM's Messenger fields.

    Remembers whether the row was actually created, because the shared pipeline
    returns the same ``Message`` for a first delivery and for Meta's replay of
    it \u2014 and reporting a replay as newly processed would double-count the lead.
    """

    def __init__(self, log: Any) -> None:
        self._log = log
        self.created = False

    async def __call__(
        self, db: AsyncSession, event: InboundTextEvent
    ) -> InboundMessageIngestResult:
        result = await persist_inbound_text_message(
            db=db,
            provider_message_id=event.provider_message_id,
            from_number=event.from_number,
            to_number=event.to_number,
            body=event.body,
            workspace_id=event.workspace_id,
            channel=event.channel,
            log=self._log,
            messenger_psid=event.messenger_psid,
            messenger_display_name=event.messenger_display_name,
            messenger_window_expires_at=event.messenger_window_expires_at,
        )
        self.created = result.created
        return result


async def _integration_for_account(
    db: AsyncSession, account_id: str
) -> tuple[WorkspaceIntegration, dict[str, Any]]:
    """Resolve the single workspace that owns this Page/Instagram account.

    The lookup runs in its own explicitly system-labelled session: deciding
    *which* tenant a delivery belongs to cannot itself be tenant-scoped, and
    doing it on the request session would silently leave that session able to
    read every workspace for the rest of the request.

    Selecting never widens. An account matching no integration is rejected, and
    one matching two is an error rather than a coin flip \u2014 guessing would drop a
    stranger's DM into another tenant's inbox.
    """
    async with AsyncSessionLocal() as routing:
        mark_session_as_system(
            routing,
            reason="Meta webhook routing: the Page ID is what decides the workspace",
        )
        integrations = (
            (
                await routing.execute(
                    select(WorkspaceIntegration).where(
                        WorkspaceIntegration.integration_type == META_LEAD_ADS_INTEGRATION,
                        WorkspaceIntegration.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        matches = [
            (integration.id, integration.workspace_id, dict(integration.credentials))
            for integration in integrations
            if any(
                str(integration.credentials.get(key) or "").strip() == account_id
                for key in _ACCOUNT_CREDENTIAL_KEYS
            )
        ]

    if not matches:
        raise MetaLeadAdsValidationError("No active workspace integration matches the Meta account")
    if len(matches) > 1:
        logger.error("meta_message_account_ambiguous", security_event=True)
        raise MetaLeadAdsError("Multiple active workspace integrations match the Meta account")

    integration_id, workspace_id, credentials = matches[0]
    # Pin the request session to the workspace the Page resolved to, so every
    # later read and write in this delivery is filtered to that tenant.
    if session_workspace_id(db) is None and session_system_reason(db) is None:
        scope_session_to_workspace(db, workspace_id)
    integration = await db.get(WorkspaceIntegration, integration_id)
    if integration is None:  # pragma: no cover - deleted between the two reads
        raise MetaLeadAdsValidationError("Meta integration disappeared mid-delivery")
    return integration, credentials


async def _sender_name(
    client: SenderProfileClient,
    *,
    psid: str,
    access_token: str,
    log: Any,
) -> str | None:
    """Best-effort profile name; a Graph failure must not drop the message."""
    try:
        return await client.fetch_sender_name(psid=psid, access_token=access_token)
    except (MetaLeadAdsError, MetaLeadAdsValidationError) as exc:
        log.info("meta_message_profile_unavailable", error=str(exc))
        return None


def extract_phone(text: str) -> str | None:
    """Return the first valid US phone number in a DM, or ``None``.

    Uses ``PhoneNumberMatcher`` rather than a digit regex so "call me at 5pm on
    the 15th" does not become a phone number.
    """
    for match in phonenumbers.PhoneNumberMatcher(text, "US"):
        candidate = normalize_phone_safe(
            phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
        )
        if candidate and validate_phone_number(candidate):
            return candidate
    return None


async def _link_contact_when_phone_shared(
    db: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    integration: WorkspaceIntegration,
    credentials: dict[str, Any],
    text: str,
    log: Any,
) -> None:
    """Attach a contact once the person shares a phone, and attribute the lead.

    This is the point a DM becomes a lead the ROI card can see: before a phone
    exists there is no contact to hang first-touch attribution on, and after it
    exists the follow-up can move to SMS, which has no 24-hour ceiling.
    """
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.contact_id is not None:
        return

    phone = extract_phone(text)
    if phone is None:
        return

    phone_hash = hash_phone(phone)
    contact = (
        await db.execute(
            select(Contact).where(
                Contact.workspace_id == integration.workspace_id,
                Contact.phone_hash == phone_hash,
            )
        )
    ).scalar_one_or_none()

    is_new = contact is None
    if contact is None:
        first_name, _, last_name = (conversation.messenger_display_name or "").partition(" ")
        contact = Contact(
            workspace_id=integration.workspace_id,
            first_name=first_name or "Unknown",
            last_name=last_name or None,
            phone_number=phone,
            phone_hash=phone_hash,
            source=META_MESSENGER_EXTERNAL_SOURCE,
            status="new",
        )
        db.add(contact)
        await db.flush()

    source = await resolve_facebook_lead_source(
        db,
        integration=integration,
        credentials=credentials,
        campaign_id=None,
    )
    if source.source_type != LeadSourceType.FACEBOOK_ADS:
        # A workspace can point ``lead_source_id`` at a row it owns; refuse to
        # attribute a DM to a channel that did not produce it rather than
        # quietly inflating some other source's ROI.
        raise MetaLeadAdsValidationError("Meta lead source must be a Facebook Ads source")

    apply_web_attribution(
        contact,
        source,
        WebAttributionInput(
            attribution_confidence=1.0,
            utm_source="facebook",
            utm_medium="social",
            utm_campaign=conversation.channel,
        ),
    )
    conversation.contact_id = contact.id
    await db.flush()
    log.info(
        "messenger_contact_linked",
        conversation_id=str(conversation.id),
        contact_id=str(contact.id),
        created=is_new,
    )
